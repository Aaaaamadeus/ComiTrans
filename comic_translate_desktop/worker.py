from __future__ import annotations

from comic_translate_core.pipeline_settings import apply_runtime_settings
from comic_translate_core.errors import TaskCancelledError, TranslationError
from .i18n import tr

import contextlib
import io
import sys
import traceback
import threading
import uuid
from time import perf_counter
from copy import copy
from comic_translate_core.page_prefetch import PagePrefetch
from comic_translate_core.inference_control import inference_cancellation
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import config as app_config
from .pdf_utils import PdfPageRenderer, plan_pdf_pages, RenderedPdfPage
from .pdf_project import create_pdf_project, publish_pdf_project, write_project_metadata
from .checkpoints import DocumentCheckpoint
from comic_translate_core.languages import OCR_CONFIG_KEYS
from comic_translate_core.chinese import normalize_target_language
from comic_translate_core.layout_options import normalize_text_color, normalize_vertical_alignment


@dataclass
class _PageJob:
    document: "_DocumentJob"
    input_path: Path
    output_path: Path
    page_number: int = 1
    page_size_points: tuple[float, float] | None = None
    resumed: bool = False
    completed: bool = False


@dataclass
class _DocumentJob:
    index: int
    source_path: Path
    output_path: Path
    is_pdf: bool
    pages: list[_PageJob] = field(default_factory=list)
    error: str = ""
    error_stack: str = ""
    project_dir: Path | None = None
    checkpoint: DocumentCheckpoint | None = None
    error_lock: object = field(default_factory=threading.Lock, repr=False, compare=False)


class QtTextStream(io.TextIOBase):
    """把 worker 里的 print 输出转发成 Qt 日志信号。"""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self._buffers = {}
        self._lock = threading.RLock()

    def write(self, text: str) -> int:
        with self._lock:
            thread_id = threading.get_ident()
            buffer = self._buffers.get(thread_id, "") + text
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip()
                if line:
                    self._callback(line)
            self._buffers[thread_id] = buffer
        return len(text)

    def flush(self) -> None:
        with self._lock:
            for buffer in self._buffers.values():
                if buffer.strip():
                    self._callback(buffer.rstrip())
            self._buffers.clear()


class BatchWorker(QThread):
    progress = Signal(int, int, str)
    log = Signal(str)
    pipeline_ready = Signal(object)
    image_done = Signal(str, str)
    image_failed = Signal(str, str)
    stage_changed = Signal(int, str, str)
    stage_event = Signal(object)
    page_progress = Signal(int, int)
    finished = Signal(int, int)

    def __init__(self, files, output_dir, config, pipeline=None, parent=None):
        super().__init__(parent)
        self._files = [Path(f) for f in files]
        self._output_dir = Path(output_dir)
        self._config = dict(config)
        self._pipeline = pipeline
        self._stop = False
        self._fatal_error = ""
        self._fatal_lock = threading.Lock()
        self._current_index = 0
        self.task_id = uuid.uuid4().hex
        self._stage_context = threading.local()
        self._pdf_renderer = None
        self._pdf_document = None

    def stop(self) -> None:
        self._stop = True

    def _is_stopped(self) -> bool:
        return self._stop or bool(self._fatal_error)

    def _emit_stage(self, stage: str, message: str) -> None:
        # Compatibility adapter: the existing pipeline reports completions for
        # these callbacks. Translation also reports requests and continuations.
        state = "done" if stage in {"detect", "ocr", "inpaint", "typeset", "save"} or (stage == "translate" and message == "翻译完成") else "running"
        page = getattr(self._stage_context, "page", None)
        if page is not None:
            if stage == "translate" and getattr(self._stage_context, "blank", False):
                state, message = "skipped", "无可翻译文本，跳过 API 请求"
            self._page_event(stage, state, message)
        index = page.document.index if page is not None else self._current_index
        if stage == "start" and index > 0:
            message = f"{self._files[index - 1].name}: 开始处理"
        display_message = (tr('{_0}: 开始处理', _0=self._files[index - 1].name)
                           if stage == 'start' and index > 0 else tr(message))
        self.stage_changed.emit(index, stage, display_message)
        self._log_pipeline_output(message)

    def _page_event(self, stage, state, message):
        page = getattr(self._stage_context, "page", None)
        if page is not None:
            self.stage_event.emit({
                "task_id": self.task_id,
                "page_id": f"{page.document.index}:{page.page_number}",
                "document_index": page.document.index,
                "page_label": self._page_label(page),
                "stage": stage, "state": state, "message": message,
            })

    def _translate_page(self, page, prepared):
        self._stage_context.page = page
        self._stage_context.blank = not any(text.strip() for text in prepared["ocr_texts"])
        try:
            result = self._pipeline.translate_page_batch(prepared["ocr_texts"], prepared["img_cv"])
            self._page_event("translate", "skipped" if self._stage_context.blank else "done", "无可翻译文本，跳过 API 请求" if self._stage_context.blank else "翻译完成")
            return result
        except TaskCancelledError:
            self._page_event('translate', 'cancelled', '已取消')
            raise
        except Exception as exc:
            self._page_event("translate", "failed", str(exc))
            raise

    def _configure_pipeline(self, pipeline) -> None:
        pipeline.cancel_callback = self._is_stopped
        pipeline.progress_callback = self._emit_stage
        pipeline.watermark_enabled = bool(self._config.get("watermark_enabled", True))
        fonts = self._config.get('font_map')
        typesetter = getattr(pipeline, 'typesetter', None)
        fallbacks = tuple(self._config.get('font_fallbacks') or ())
        size = int(self._config.get('font_size') or 16)
        if fonts and typesetter is not None and (
            typesetter.font_map != fonts or typesetter.base_font_size != size
            or getattr(typesetter, 'fallback_fonts', ()) != fallbacks
        ):
            from vertical_typesetter import VerticalTypesetter
            pipeline.typesetter = VerticalTypesetter(fonts, size, fallback_fonts=fallbacks)

    def _log_pipeline_output(self, message):
        page = getattr(self._stage_context, 'page', None)
        self.log.emit(f'[{self._page_label(page)}] {message}' if page is not None else message)

    @contextlib.contextmanager
    def _capture_pipeline_output(self):
        stream = QtTextStream(self._log_pipeline_output)
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

        self.log.emit("[预热] 开始导入 comic_translator_pipeline")
        from comic_translator_pipeline import ComicTranslatorPipeline
        self.log.emit("[预热] pipeline 导入完成")

        self.log.emit("[预热] 开始实例化 AI 管线")
        with self._capture_pipeline_output():
            pipeline = ComicTranslatorPipeline(
                det_model_path=self._config["detector_model"],
                font_map=self._config["font_map"],
                font_size=self._config["font_size"],
                fallback_fonts=self._config.get('font_fallbacks'),
                use_gpu=self._config["use_gpu"],
                lama_path=self._config["lama_model"],
                ocr_model_path=self._config.get("ocr_model"),
                baberu_ocr_model_path=self._config.get("baberu_ocr_model"),
                ocr_backend=self._config.get("ocr_backend", "auto"),
                ocr_config={key: self._config[key] for key in OCR_CONFIG_KEYS if key in self._config},
                translation_model=self._config["translation_model"],
                api_key=self._config["api_key"],
                api_base_url=self._config["api_base_url"],
                translation_prompt=self._config.get("translation_prompt", ""),
                target_language=self._config.get("target_language", "zh-Hans"),
                vertical_alignment=self._config.get("vertical_alignment", "center"),
                text_color=self._config.get("text_color"),
                chinese_names=self._config.get("chinese_names", ""),
                multimodal=self._config.get("multimodal", False),
                multimodal_font_probe=(self._config.get("multimodal_font_probe", False)
                                       and not self._config.get('translation_font_active', False)),
                disable_thinking=self._config.get("disable_thinking", True),
                font_probe_samples=self._config.get("font_probe_samples", 3),
                progress_callback=self._emit_stage,
                cancel_callback=self._is_stopped,
            )
        self.log.emit("[预热] 实例化完成")
        return pipeline

    def _make_document_jobs(self) -> list[_DocumentJob]:
        documents: list[_DocumentJob] = []
        pdf_dpi = max(96, min(400, int(self._config.get("pdf_dpi") or 200)))
        for index, input_path in enumerate(self._files, start=1):
            is_pdf = input_path.suffix.lower() == ".pdf"
            suffix = ".pdf" if is_pdf else (input_path.suffix.lower() or ".png")
            document = _DocumentJob(
                index=index,
                source_path=input_path,
                output_path=self._output_dir / f"{input_path.stem}_translated{suffix}",
                is_pdf=is_pdf,
            )
            documents.append(document)
            self._current_index = index

            if self._stop:
                break
            try:
                if not input_path.exists():
                    raise FileNotFoundError(f"文件不存在: {input_path}")
                document.checkpoint = DocumentCheckpoint(input_path, document.output_path, self._config)
                if is_pdf:
                    source_dir = document.checkpoint.project_directory()
                    if source_dir is None:
                        source_dir = create_pdf_project(document.output_path)
                        document.checkpoint.set_project_directory(source_dir)
                    document.project_dir = source_dir
                    self.log.emit(f"[PDF] {input_path.name}: 精修资料保存在 {source_dir}")
                    rendered = plan_pdf_pages(input_path, source_dir / "source", dpi=pdf_dpi,
                                              cancel_callback=self._check_cancelled)
                    write_project_metadata(source_dir, input_path.name,
                                           [(page.width_points, page.height_points) for page in rendered])
                    for page in rendered:
                        document.pages.append(
                            _PageJob(
                                document=document,
                                input_path=page.image_path,
                                output_path=source_dir
                                / "translated"
                                / f"page_{page.page_index + 1:04d}.png",
                                page_number=page.page_index + 1,
                                page_size_points=(page.width_points, page.height_points),
                            )
                        )
                    self.log.emit(f"[PDF] {input_path.name}: 共 {len(document.pages)} 页，将按批次以原分辨率渲染")
                else:
                    document.pages.append(
                        _PageJob(
                            document=document,
                            input_path=input_path,
                            output_path=document.output_path,
                        )
                    )
                for page in document.pages:
                    page.resumed = document.checkpoint.completed(page.page_number, page.output_path)
                resumed = sum(page.resumed for page in document.pages)
                if resumed:
                    self.log.emit(f"[续传] {input_path.name}: 跳过 {resumed}/{len(document.pages)} 页已完成结果")
            except Exception as exc:
                document.error = str(exc)
                document.error_stack = traceback.format_exc().strip()
        return documents

    def _check_cancelled(self):
        if self._is_stopped():
            raise TaskCancelledError("任务已取消")

    def _close_pdf_renderer(self):
        if self._pdf_renderer is not None:
            self._pdf_renderer.close()
            self._pdf_renderer = None
            self._pdf_document = None

    def _ensure_pdf_page(self, page):
        if not page.document.is_pdf:
            return
        self._check_cancelled()
        if self._pdf_document is not page.document:
            self._close_pdf_renderer()
            dpi = max(96, min(400, int(self._config.get('pdf_dpi') or 200)))
            self._pdf_renderer = PdfPageRenderer(page.document.source_path, dpi)
            self._pdf_document = page.document
        started = perf_counter()
        self._page_event('detect', 'running', '正在准备原分辨率 PDF 页图')
        self._pdf_renderer.render(
            RenderedPdfPage(page.page_number - 1, page.input_path, *page.page_size_points),
            reuse_cached=True, cancel_callback=self._check_cancelled)
        self.log.emit(f'[耗时] {self._page_label(page)}: PDF 页图准备 {perf_counter() - started:.2f} 秒')

    @staticmethod
    def _page_label(page: _PageJob) -> str:
        if page.document.is_pdf:
            return tr('{_0} 第 {_1}/{_2} 页', _0=page.document.source_path.name,
                      _1=page.page_number, _2=len(page.document.pages))
        return page.document.source_path.name

    @staticmethod
    def _set_document_error(
        document: _DocumentJob, exc: Exception, *, include_stack: bool = True
    ) -> None:
        with document.error_lock:
            if document.error:
                return
            document.error = str(exc) or exc.__class__.__name__
            if include_stack:
                document.error_stack = traceback.format_exc().strip()

    @staticmethod
    def _apply_api_config(pipeline, config) -> None:
        apply_runtime_settings(pipeline, config)

    def _cancel_page(self, page):
        self._page_event('cancelled', 'cancelled', '已取消')
        self.stage_changed.emit(page.document.index, 'cancelled',
                                tr('{_0}: 已取消', _0=self._page_label(page)))

    def _prepare_page(self, page):
        if self._is_stopped() or page.document.error:
            return None
        self._stage_context.page = page
        self._stage_context.blank = False
        label = self._page_label(page)
        self.stage_changed.emit(page.document.index, 'start', tr('{_0}: 准备中', _0=label))
        try:
            self._ensure_pdf_page(page)
            started = perf_counter()
            with inference_cancellation(self._check_cancelled):
                prepared = self._preparation_pipeline.prepare_comic_page(str(page.input_path))
            self.log.emit(f'[耗时] {label}: 检测与 OCR {perf_counter() - started:.2f} 秒')
            return prepared
        except TaskCancelledError:
            if not self._fatal_error:
                self._stop = True
            self._cancel_page(page)
        except Exception as exc:
            self._set_document_error(page.document, exc)
            self._page_event('failure', 'failed', str(exc))
        return None

    def _translate_and_cache(self, page, prepared):
        self._stage_context.page = page
        self._stage_context.blank = not any(text.strip() for text in prepared['ocr_texts'])
        try:
            self._check_cancelled()
            cached = page.document.checkpoint.translation(page.page_number, prepared['ocr_texts'])
            if cached is not None:
                self.log.emit(f'[续传] {self._page_label(page)}: 复用已保存译文')
                self._page_event('translate', 'done', '复用已保存译文')
                return cached
            started = perf_counter()
            result = self._translate_page(page, prepared)
            # Persist a valid paid response even if stop arrived during HTTP.
            page.document.checkpoint.save_translation(page.page_number, prepared['ocr_texts'], result)
            self.log.emit(f'[耗时] {self._page_label(page)}: API 翻译 {perf_counter() - started:.2f} 秒')
            return result
        except TaskCancelledError:
            if not self._fatal_error:
                self._stop = True
            self._cancel_page(page)
        except Exception as exc:
            self._set_document_error(page.document, exc, include_stack=not isinstance(exc, TranslationError))
            self._page_event('failure', 'failed', str(exc))
            self.log.emit(f'[失败] {self._page_label(page)}: {exc}')
            if isinstance(exc, TranslationError) and getattr(exc, 'fatal', False):
                with self._fatal_lock:
                    if not self._fatal_error:
                        self._fatal_error = str(exc)
                        self.log.emit('[失败] 翻译服务返回全局配置/账户错误，已停止预取和后续请求。')
        return None

    def _finish_page(self, page, prepared, translations):
        self._stage_context.page = page
        self._stage_context.blank = not any(text.strip() for text in prepared['ocr_texts'])
        label = self._page_label(page)
        try:
            self._check_cancelled()
            page.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._page_event('inpaint', 'running', '正在准备背景修复与排版')
            started = perf_counter()
            with inference_cancellation(self._check_cancelled):
                self._pipeline.finish_comic_page(str(page.output_path), prepared, translations)
            self.log.emit(f'[耗时] {label}: 修补、嵌字与保存 {perf_counter() - started:.2f} 秒')
            page.document.checkpoint.mark_completed(page.page_number)
            page.completed = True
            return True
        except TaskCancelledError:
            if not self._fatal_error:
                self._stop = True
            self._cancel_page(page)
        except Exception as exc:
            self._set_document_error(page.document, exc)
            self._page_event('failure', 'failed', str(exc))
        return False

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
            if not self._files:
                self.finished.emit(0, 0)
                return
            _mask = app_config.mask_api_key(str(self._config.get("api_key") or "")) or "空"
            self.log.emit(
                f"[INFO] 翻译模型: {self._config.get('translation_model', '')}，API Key: {_mask}"
            )
            self._output_dir.mkdir(parents=True, exist_ok=True)
            documents = self._make_document_jobs()
            page_jobs = [page for document in documents for page in document.pages]
            completed_pages = sum(page.resumed for page in page_jobs)
            self.page_progress.emit(completed_pages, len(page_jobs))
            pending_pages = [page for page in page_jobs if not page.resumed]
            max_workers = max(1, int(self._config.get("max_workers") or 4))

            fork = getattr(self._pipeline, 'fork_preparation', None)
            self._preparation_pipeline = fork() if callable(fork) else copy(self._pipeline)
            self.log.emit(f'[流水线] 在途最多 {max_workers} 页；' +
                          ('准备/翻译与修补重叠，GPU 推理分块交错。' if max_workers > 1 else '单页顺序处理。'))
            # One output capture owns all cooperating threads. Nesting global
            # stdout redirects across producer/API/consumer threads is unsafe.
            with self._capture_pipeline_output(), PagePrefetch(
                pending_pages, self._prepare_page, self._translate_and_cache,
                capacity=max_workers, cancelled=self._is_stopped,
                close_preparation=self._close_pdf_renderer,
            ) as pages:
                for page, prepared, future in pages:
                    try:
                        if self._is_stopped():
                            break
                        translations = future.result()
                        if translations is not None and not self._is_stopped():
                            if self._finish_page(page, prepared, translations):
                                completed_pages += 1
                                self.page_progress.emit(completed_pages, len(page_jobs))
                    finally:
                        prepared = future = translations = None
            self._preparation_pipeline = None
            self._stage_context.page = None
            if self._fatal_error:
                for document in documents:
                    if not document.error and not all(p.resumed or p.completed for p in document.pages):
                        document.error = self._fatal_error

            completed = 0
            for document in documents:
                if self._stop:
                    break
                self._current_index = document.index
                if not document.error and document.is_pdf:
                    try:
                        publish_pdf_project(document.output_path, document.project_dir)
                        self.log.emit(
                            f"[PDF] {document.source_path.name}: 已生成 {len(document.pages)} 页译文 PDF"
                        )
                    except Exception as exc:
                        self._set_document_error(document, exc)

                completed += 1
                if document.error:
                    failed_count += 1
                    self.image_failed.emit(document.source_path.name, document.error)
                    self.log.emit(f"[失败] {document.source_path.name}: {document.error}")
                    if document.error_stack:
                        self.log.emit(f"[失败堆栈]\n{document.error_stack}")
                    self.progress.emit(completed, total, tr('{_0}: 失败', _0=document.source_path.name))
                else:
                    success_count += 1
                    self.image_done.emit(str(document.source_path), str(document.output_path))
                    self.progress.emit(completed, total, tr('{_0}: 完成', _0=document.source_path.name))
        except Exception as exc:
            failed_count = max(failed_count, total - success_count)
            stack = traceback.format_exc().strip()
            self.log.emit(f"[严重错误] {exc}\n{stack}")

        finally:
            self._preparation_pipeline = None
            self._close_pdf_renderer()

        self.finished.emit(success_count, failed_count)
