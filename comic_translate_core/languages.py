from __future__ import annotations

import re
from urllib.parse import urlsplit

SOURCE_LANGUAGES = (("ja", "日语"), ("ko", "韩语"), ("en", "英语"), ("custom", "自定义 OCR"))
LANGUAGE_NAMES = dict(SOURCE_LANGUAGES)
OCR_DEFAULTS = {
    "source_language": "ja",
    "ocr_backend": "auto",
    "custom_source_language": "",
    "custom_source_language_name": "",
    "custom_ocr_protocol": "http",
    "custom_ocr_url": "",
    "custom_ocr_api_key": "",
    "custom_ocr_model": "",
    "custom_ocr_timeout": 60,
}
OCR_CONFIG_KEYS = tuple(OCR_DEFAULTS) + ("korean_ocr_model", "english_ocr_model")


def source_language(config: dict) -> str:
    value = str(config.get("source_language") or "ja").strip().lower()
    return str(config.get("custom_source_language") or "").strip() if value == "custom" else value


def source_language_name(config: dict) -> str:
    code = source_language(config)
    return LANGUAGE_NAMES.get(code) or str(config.get("custom_source_language_name") or code)


def effective_ocr_backend(config: dict) -> str:
    backend = str(config.get("ocr_backend") or "auto").strip().lower()
    if backend == "manga":
        backend = "manga-ocr"
    if config.get("source_language") == "custom":
        return "custom"
    if backend == "auto" and source_language(config) in ("en", "ko"):
        return "ppocr"
    return backend


def validate_ocr_config(config: dict) -> list[str]:
    errors = []
    code = source_language(config)
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", code):
        errors.append("请填写有效的源语言代码，例如 fr、de、zh-TW。")
    backend = effective_ocr_backend(config)
    if backend not in ("auto", "baberu", "manga-ocr", "ppocr", "custom"):
        errors.append("不支持的 OCR 后端。")
    elif backend in ("auto", "baberu", "manga-ocr") and code != "ja":
        errors.append("Baberu / manga-ocr 仅用于日语，请选择自动或自定义 OCR。")
    elif backend == "ppocr" and code not in ("en", "ko"):
        errors.append("内置 PP-OCR 支持韩语、英语，其它语言请接入自定义 OCR。")
    elif backend == "custom":
        protocol = config.get("custom_ocr_protocol", "http")
        if protocol not in ("http", "openai"):
            errors.append("自定义 OCR 协议应为 http 或 openai。")
        try:
            url = urlsplit(str(config.get("custom_ocr_url") or ""))
            valid_url = url.scheme in ("http", "https") and url.hostname and not url.username and not url.password
        except ValueError:
            valid_url = False
        if not valid_url:
            errors.append("请填写自定义 OCR 的 HTTP(S) 地址，密钥请填入独立密钥栏。")
        if protocol == "openai" and not str(config.get("custom_ocr_model") or "").strip():
            errors.append("请填写自定义 OCR 使用的视觉模型名。")
        try:
            timeout = float(config.get("custom_ocr_timeout", 60))
            if not 1 <= timeout <= 300:
                raise ValueError
        except (ValueError, TypeError):
            errors.append("自定义 OCR 超时须为 1–300 秒。")
    return errors
