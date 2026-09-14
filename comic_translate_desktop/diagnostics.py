from __future__ import annotations

import datetime
import platform
import sys

from . import config as app_config


class Diagnostics:
    def __init__(self):
        self.entries: list[str] = []
        self.errors: list[str] = []
        self.log_path = app_config.PROJECT_ROOT / "Log" / "app.log"
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def append(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        self.entries.append(line)
        if len(self.entries) > 2000:
            self.entries = self.entries[-2000:]
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def add_error(self, message: str, stack: str | None = None) -> None:
        self.errors.append(message)
        if len(self.errors) > 50:
            self.errors = self.errors[-50:]
        self.append(message, "ERROR")
        if stack:
            self.append(stack, "ERROR")

    def raw_text(self, limit: int = 400) -> str:
        return "\n".join(self.entries[-limit:]) or "（无）"

    def build_prompt(self) -> str:
        config = app_config.load_ai_config()
        try:
            import torch

            torch_version = torch.__version__
            cuda_available = torch.cuda.is_available()
        except Exception:
            torch_version = "未知"
            cuda_available = False
        try:
            import PySide6

            pyside_version = PySide6.__version__
        except Exception:
            pyside_version = "未知"

        api_key = config.get("api_key", "")
        key_display = app_config.mask_api_key(api_key) if api_key else "未设置"
        missing_models = app_config.missing_models(config)

        environment = "\n".join(
            [
                f"- 时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"- 操作系统: {platform.platform()}",
                f"- Python: {sys.version.split()[0]}",
                f"- PySide6: {pyside_version}",
                f"- Torch: {torch_version}",
                f"- CUDA 可用: {cuda_available}",
                f"- 翻译模型: {config.get('translation_model', '')}",
                f"- API Base URL: {config.get('api_base_url', '')}",
                f"- API Key: {key_display}",
                f"- 字体大小: {config.get('font_size', 16)}",
                f"- 使用 GPU: {config.get('use_gpu', False)}",
                f"- 检测模型: {config.get('detector_model', '')}",
                f"- OCR 后端: {config.get('ocr_backend', 'auto')}",
                f"- Baberu OCR: {config.get('baberu_ocr_model', '')}",
                f"- manga-ocr: {config.get('ocr_model', '')}",
                f"- 修复模型: {config.get('lama_model', '')}",
                f"- 输出目录: {config.get('page_output_dir', '')}",
            ]
        )

        if missing_models:
            missing_text = "\n".join(f"- {item}" for item in missing_models)
        else:
            missing_text = "无"

        errors = "\n".join(self.errors[-20:]) if self.errors else "（无）"
        recent_logs = self.raw_text(300)

        return (
            "请帮我分析以下 ComiTrans 本地客户端报错，并给出具体修复步骤。\n\n"
            "## 环境信息\n"
            f"{environment}\n"
            f"- 缺失模型: \n{missing_text}\n\n"
            "## 报错信息\n"
            f"{errors}\n\n"
            "## 最近日志\n"
            f"{recent_logs}\n"
        )

    def clear(self) -> None:
        self.entries.clear()
        self.errors.clear()
