from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml


if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = PROJECT_ROOT / "comic-translate-ai"
MAIN_DIR = AI_ROOT / "main"
CONFIG_PATH = MAIN_DIR / "config.yaml"
DEFAULT_OUTPUT_DIR = AI_ROOT / "page" / "test_page_output"

FONT_KEYS = {
    "dialogue": "font_dialogue",
    "radiating": "font_radiating",
    "handwriting": "font_handwriting",
    "serious": "font_serious",
}
FONT_DEFAULTS = {
    "dialogue": "font_file/CN/SourceHanSerifCN-Regular-1.otf",
    "radiating": "font_file/CN/SourceHanSansSC-Heavy-2.otf",
    "handwriting": "font_file/CN/setofont.ttf",
    "serious": "font_file/CN/SourceHanSansSC-Medium-2.otf",
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


def _resolve_path(value: Any, default: str) -> Path:
    raw = str(value).strip() if value else ""
    if not raw or raw in ("none", "None"):
        return AI_ROOT / default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = AI_ROOT / path
    return path


def load_ai_config() -> dict[str, Any]:
    raw = load_yaml(CONFIG_PATH)
    font_map = {}
    for style, key in FONT_KEYS.items():
        font_map[style] = str(_resolve_path(raw.get(key), FONT_DEFAULTS[style]))

    return {
        "api_key": _clean_text(raw.get("api_key")),
        "api_base_url": _clean_text(raw.get("api_base_url")),
        "translation_model": _clean_text(raw.get("translation_model")) or "gemini-2.5-flash",
        "translation_prompt": str(raw.get("translation_prompt") or ""),
        "chinese_names": str(raw.get("chinese_names") or ""),
        "font_size": int(raw.get("font_size") or 16),
        "multimodal": bool(raw.get("multimodal", False)),
        "issue_url": str(raw.get("issue_url") or ""),
        "use_gpu": bool(raw.get("use_gpu", False)),
        "font_map": font_map,
        "detector_model": str(_resolve_path(raw.get("detector_model"), "models/text_detector/comictextdetector.pt")),
        "lama_model": str(_resolve_path(raw.get("lama_model"), "models/manga-lama/lama-manga-dynamic.onnx")),
        "ocr_model": str(_resolve_path(raw.get("ocr_model"), "models/manga-ocr-base")),
        "page_input_dir": str(_resolve_path(raw.get("page_input_dir"), "page/test_page")),
        "page_output_dir": str(_resolve_path(raw.get("page_output_dir"), "page/test_page_output")),
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
        config["ocr_model"],
        tuple(sorted(config["font_map"].items())),
    )


def missing_models(config: dict[str, Any]) -> list[str]:
    missing = []
    for key in ("detector_model", "lama_model", "ocr_model"):
        path = Path(config[key])
        if not path.exists():
            missing.append(f"{key}: {path}")
        elif key == "ocr_model" and path.is_dir() and not (path / "pytorch_model.bin").exists():
            missing.append(f"{key}: {path} (缺少 pytorch_model.bin)")
    return missing
