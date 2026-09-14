from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml


if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    AI_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "comic-translate-ai"
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    AI_ROOT = PROJECT_ROOT / "comic-translate-ai"
MAIN_DIR = AI_ROOT / "main"
MODELS_ROOT = PROJECT_ROOT / "comic-translate-ai" / "models"
PAGE_BASE = PROJECT_ROOT if getattr(sys, "frozen", False) else AI_ROOT
ICON_PATH = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "assets" / "ComiTrans.ico" if getattr(sys, "frozen", False) else PROJECT_ROOT / "assets" / "ComiTrans.ico"
if getattr(sys, "frozen", False):
    CONFIG_PATH = PROJECT_ROOT / "config.yaml"
    DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "page" / "output_page_output"
else:
    CONFIG_PATH = MAIN_DIR / "config.yaml"
    DEFAULT_OUTPUT_DIR = AI_ROOT / "page" / "output_page_output"

FONT_KEYS = {
    "dialogue": "font_dialogue",
    "bold_dialogue": "font_bold_dialogue",
    "radiating": "font_radiating",
    "handwriting": "font_handwriting",
    "thought": "font_thought",
    "whisper": "font_whisper",
    "serious": "font_serious",
    "narration": "font_narration",
    "sfx": "font_sfx",
    "cute": "font_cute",
    "next_preview": "font_next_preview",
    "title": "font_title",
}
FONT_DEFAULTS = {
    "dialogue": "font_file/CN/special/LXGWWenKai-Regular.ttf",
    "bold_dialogue": "font_file/CN/SourceHanSansSC-Heavy-2.otf",
    "radiating": "font_file/CN/special/SmileySans-Oblique.ttf",
    "handwriting": "font_file/CN/setofont.ttf",
    "thought": "font_file/CN/SourceHanSerifCN-Regular-1.otf",
    "whisper": "font_file/CN/special/KleeOne-Regular.ttf",
    "serious": "font_file/CN/SourceHanSerifCN-Regular-1.otf",
    "narration": "font_file/CN/special/LXGWWenKai-Regular.ttf",
    "sfx": "font_file/CN/special/SmileySans-Oblique.ttf",
    "cute": "font_file/CN/special/KleeOne-Regular.ttf",
    "next_preview": "font_file/CN/special/KleeOne-Regular.ttf",
    "title": "font_file/CN/SourceHanSansSC-Heavy-2.otf",
}


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _clean_text(value: Any) -> str:
    if value in (None, "", "none", "None"):
        return ""
    return str(value).strip()


def _resolve_path(value: Any, default: str, base: Path | None = None) -> Path:
    base = base or AI_ROOT
    raw = str(value).strip() if value else ""
    if not raw or raw in ("none", "None"):
        return base / default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        if base.name == "models" and path.parts and path.parts[0] == "models":
            path = Path(*path.parts[1:])
        path = base / path
    return path


def load_ai_config() -> dict[str, Any]:
    raw = load_yaml(CONFIG_PATH)
    font_map = {}
    for style, key in FONT_KEYS.items():
        font_map[style] = str(_resolve_path(raw.get(key), FONT_DEFAULTS[style]))
    ocr_backend = str(raw.get("ocr_backend") or "auto").strip().lower()
    if ocr_backend not in ("auto", "baberu", "manga", "manga-ocr"):
        ocr_backend = "auto"

    return {
        "api_key": _clean_text(raw.get("api_key")),
        "api_base_url": _clean_text(raw.get("api_base_url")),
        "translation_model": _clean_text(raw.get("translation_model")) or "gemini-2.5-flash",
        "translation_prompt": str(raw.get("translation_prompt") or ""),
        "chinese_names": str(raw.get("chinese_names") or ""),
        "font_size": int(raw.get("font_size") or 16),
        "multimodal": bool(raw.get("multimodal", False)),
        "max_workers": int(raw.get("max_workers") or 4),
        "pdf_dpi": int(raw.get("pdf_dpi") or 200),
        "issue_url": str(raw.get("issue_url") or ""),
        "use_gpu": bool(raw.get("use_gpu", False)),
        "font_map": font_map,
        "detector_model": str(_resolve_path(raw.get("detector_model"), "text_detector/comic-text-detector.onnx", base=MODELS_ROOT)),
        "lama_model": str(_resolve_path(raw.get("lama_model"), "manga-lama/lama-manga-dynamic.onnx", base=MODELS_ROOT)),
        "ocr_backend": ocr_backend,
        "ocr_model": str(_resolve_path(raw.get("ocr_model"), "manga-ocr-onnx", base=MODELS_ROOT)),
        "baberu_ocr_model": str(_resolve_path(raw.get("baberu_ocr_model"), "baberu-ocr", base=MODELS_ROOT)),
        "page_input_dir": str(_resolve_path(raw.get("page_input_dir"), "page/test", base=PAGE_BASE)),
        "page_output_dir": str(_resolve_path(raw.get("page_output_dir"), "page/output_page_output", base=PAGE_BASE)),
        "page_test_output_dir": str(_resolve_path(raw.get("page_test_output_dir"), "page/test_output", base=PAGE_BASE)),
        "raw": raw,
    }


def save_ai_config(updates: dict[str, Any]) -> dict[str, Any]:
    raw = load_yaml(CONFIG_PATH)
    for key, value in updates.items():
        if value is not None:
            raw[key] = value
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return load_ai_config()


def mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}{'*' * (len(api_key) - 8)}{api_key[-4:]}"


def config_fingerprint(config: dict[str, Any]) -> tuple:
    return (
        config["use_gpu"],
        config["detector_model"],
        config["lama_model"],
        config["ocr_backend"],
        config["ocr_model"],
        config["baberu_ocr_model"],
        tuple(sorted(config["font_map"].items())),
    )


def _manga_ocr_complete(path: Path) -> bool:
    return path.is_dir() and all(
        (path / name).exists()
        for name in ("encoder_model.onnx", "decoder_model.onnx", "tokenizer.json")
    )


def _baberu_ocr_complete(path: Path) -> bool:
    onnx_dir = path / "onnx"
    return path.is_dir() and (
        (onnx_dir / "vision_fp16.onnx").exists()
        or (onnx_dir / "vision_int4.onnx").exists()
    ) and all(
        (path / name).exists()
        for name in (
            "onnx/decoder_prefill_int8.onnx",
            "onnx/decoder_step_int8.onnx",
            "tokenizer/vocab.json",
        )
    )


def missing_models(config: dict[str, Any]) -> list[str]:
    missing = []
    for key in ("detector_model", "lama_model"):
        path = Path(config[key])
        if not path.exists():
            missing.append(f"{key}: {path}")
    backend = str(config.get("ocr_backend") or "auto").lower()
    manga_path = Path(config["ocr_model"])
    baberu_path = Path(config["baberu_ocr_model"])
    manga_ok = _manga_ocr_complete(manga_path)
    baberu_ok = _baberu_ocr_complete(baberu_path)
    if backend == "baberu" and not baberu_ok:
        missing.append(f"baberu_ocr_model: {baberu_path} (模型文件不完整)")
    elif backend in ("manga", "manga-ocr") and not manga_ok:
        missing.append(f"ocr_model: {manga_path} (manga-ocr 模型文件不完整)")
    elif backend == "auto" and not (baberu_ok or manga_ok):
        missing.append(
            f"OCR: Baberu ({baberu_path}) 与 manga-ocr ({manga_path}) 均不完整"
        )
    return missing
