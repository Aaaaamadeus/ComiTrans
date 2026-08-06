from __future__ import annotations

import contextlib
import io
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import config as app_config


class QtTextStream(io.TextIOBase):
    """把 worker 里的 print 输出转发成 Qt 日志信号。"""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                self._callback(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._callback(self._buffer.rstrip())
            self._buffer = ""


class BatchWorker(QThread):
    progress = Signal(int, int, str)
    log = Signal(str)
    pipeline_ready = Signal(object)
    image_done = Signal(str, str)
    image_failed = Signal(str, str)
    stage_changed = Signal(int, str, str)
    finished = Signal(int, int)

    def __init__(self, files, output_dir, config, pipeline=None, parent=None):
        super().__init__(parent)
        self._files = [Path(f) for f in files]
        self._output_dir = Path(output_dir)
        self._config = config
        self._pipeline = pipeline
        self._stop = False
        self._current_index = 0

    def stop(self) -> None:
        self._stop = True

    def _is_stopped(self) -> bool:
        return self._stop

    def _emit_stage(self, stage: str, message: str) -> None:
        if stage == "start" and self._current_index > 0:
            message = f"{self._files[self._current_index - 1].name}: 开始处理"
        self.stage_changed.emit(self._current_index, stage, message)
        self.log.emit(message)

    def _configure_pipeline(self, pipeline) -> None:
        pipeline.cancel_callback = self._is_stopped
        pipeline.progress_callback = self._emit_stage

    @contextlib.contextmanager
    def _capture_pipeline_output(self):
        stream = QtTextStream(self.log.emit)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = stream
        sys.stderr = stream
        try:
            yield
        finally:
            stream.flush()
            sys.stdout = old_out
            sys.stderr = old_err

    def _build_pipeline(self):
        main_dir = str(app_config.MAIN_DIR)
        if main_dir not in sys.path:
            sys.path.insert(0, main_dir)
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

        self.log.emit("[预热] 开始导入 comic_translator_pipeline")
        from comic_translator_pipeline import ComicTranslatorPipeline
        self.log.emit("[预热] pipeline 导入完成")

        self.log.emit("[预热] 开始实例化 AI 管线")
        with self._capture_pipeline_output():
            pipeline = ComicTranslatorPipeline(
                det_model_path=self._config["detector_model"],
                font_map=self._config["font_map"],
                font_size=self._config["font_size"],
                use_gpu=self._config["use_gpu"],
                lama_path=self._config["lama_model"],
                ocr_model_path=self._config.get("ocr_model"),
                translation_model=self._config["translation_model"],
                api_key=self._config["api_key"],
                api_base_url=self._config["api_base_url"],
                translation_prompt=self._config.get("translation_prompt", ""),
                chinese_names=self._config.get("chinese_names", ""),
                multimodal=self._config.get("multimodal", False),
                progress_callback=self._emit_stage,
                cancel_callback=self._is_stopped,
            )
        self.log.emit("[预热] 实例化完成")
        return pipeline

    @staticmethod
    def _apply_api_config(pipeline, config) -> None:
        pipeline.api_key = config["api_key"]
        pipeline.api_base_url = config["api_base_url"]
        pipeline.translation_model = config["translation_model"]
        pipeline.translation_prompt = config.get("translation_prompt", "")
        pipeline.chinese_names = config.get("chinese_names", "")
        pipeline.multimodal = bool(config.get("multimodal", False))

    def run(self) -> None:
        main_dir = str(app_config.MAIN_DIR)
        if main_dir not in sys.path:
            sys.path.insert(0, main_dir)
        try:
            from comic_translator_pipeline import TaskCancelledError
        except Exception as exc:
            stack = traceback.format_exc().strip()
            self.log.emit(f"[严重错误] 无法加载翻译管线: {exc}\n{stack}")
            self.finished.emit(0, len(self._files))
            return

        success_count = 0
        failed_count = 0
        total = len(self._files)

        try:
            if self._pipeline is None:
                self._pipeline = self._build_pipeline()
                self.pipeline_ready.emit(self._pipeline)
            else:
                self._apply_api_config(self._pipeline, self._config)
            self._configure_pipeline(self._pipeline)

            self._output_dir.mkdir(parents=True, exist_ok=True)

            for index, input_path in enumerate(self._files, start=1):
                if self._stop:
                    self.log.emit("用户请求停止，跳过剩余图片。")
                    break

                self._current_index = index
                self.progress.emit(index - 1, total, f"{input_path.name}: 开始处理")
                self.stage_changed.emit(index, "start", f"{input_path.name}: 开始处理")
                if not input_path.exists():
                    raise FileNotFoundError(f"文件不存在: {input_path}")
                suffix = input_path.suffix.lower() or ".png"
                output_path = self._output_dir / f"{input_path.stem}_translated{suffix}"

                try:
                    with self._capture_pipeline_output():
                        self._pipeline.process_comic_page(str(input_path), str(output_path))
                    success_count += 1
                    self.image_done.emit(str(input_path), str(output_path))
                    self.progress.emit(index, total, f"{input_path.name}: 完成")
                except TaskCancelledError:
                    self._stop = True
                    self.stage_changed.emit(index, "cancelled", f"{input_path.name}: 已取消")
                    self.log.emit(f"已取消: {input_path.name}")
                    break
                except Exception as exc:
                    failed_count += 1
                    self.image_failed.emit(input_path.name, str(exc))
                    self.log.emit(f"[失败] {input_path.name}: {exc}")
                    stack = traceback.format_exc().strip()
                    if stack:
                        self.log.emit(f"[失败堆栈]\n{stack}")
                    self.progress.emit(index, total, f"{input_path.name}: 失败")
        except Exception as exc:
            failed_count = total
            stack = traceback.format_exc().strip()
            self.log.emit(f"[严重错误] {exc}\n{stack}")

        self.finished.emit(success_count, failed_count)
