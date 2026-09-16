from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx
from PIL import Image

from .languages import effective_ocr_backend, source_language, validate_ocr_config


class OcrError(RuntimeError):
    """An OCR failure must stop the page before erasing any original text."""


@dataclass(frozen=True)
class OcrResult:
    text: str
    language: str
    backend: str
    confidence: float | None = None


class OcrEngine(Protocol):
    name: str
    uses_lines: bool

    def recognize(self, image: Image.Image, language: str) -> OcrResult: ...


class LocalOcr:
    def __init__(self, name, recognizer, uses_lines=False):
        self.name, self.recognizer, self.uses_lines = name, recognizer, uses_lines

    def recognize(self, image, language):
        if self.uses_lines:
            text, confidence = self.recognizer.recognize(image)
        else:
            text, confidence = self.recognizer(image), None
        return OcrResult(text, language, self.name, confidence)


class CustomOcr:
    name = "自定义 OCR"
    uses_lines = False

    def __init__(self, config):
        self.url = config["custom_ocr_url"].strip()
        self.key = str(config.get("custom_ocr_api_key") or "").strip()
        self.model = str(config.get("custom_ocr_model") or "").strip()
        self.protocol = config.get("custom_ocr_protocol", "http")
        self.timeout = float(config.get("custom_ocr_timeout", 60))

    def recognize(self, image, language):
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        try:
            if self.protocol == "openai":
                from openai import OpenAI

                # The SDK needs a nonempty key even for an unauthenticated local server.
                with OpenAI(base_url=self.url, api_key=self.key or "local", timeout=self.timeout, max_retries=0) as client:
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": "你是 OCR 引擎。只逐字输出图片中的原文，保留空格和换行。不得翻译、解释或补写。无文字时输出空字符串。"},
                            {"role": "user", "content": [
                                {"type": "text", "text": f"识别源语言 {language} 的原文。"},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                            ]},
                        ],
                    )
                    text = response.choices[0].message.content
                    if not isinstance(text, str):
                        raise OcrError("自定义 OCR 未返回文本。")
                    return OcrResult(text.strip(), language, self.name)
            headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
            payload = {"image_base64": encoded, "mime_type": "image/png", "language": language}
            if self.model:
                payload["model"] = self.model
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.post(self.url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("text"), str):
                raise OcrError('自定义 OCR 响应格式错误：应返回 {"text": "原文"}。')
            confidence = data.get("confidence")
            if confidence is not None and (
                isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not 0 <= confidence <= 1
            ):
                raise OcrError("自定义 OCR confidence 应为 0–1 的数值。")
            return OcrResult(data["text"].strip(), language, self.name, confidence)
        except OcrError:
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
            # Never include response bodies, URLs or exception text that may contain credentials/images.
            detail = f"HTTP {status}" if status else type(exc).__name__
            raise OcrError(f"自定义 OCR 请求失败（{detail}），请检查地址、密钥、模型和超时配置。") from None


def create_ocr(config: dict, device: str = "cpu") -> OcrEngine:
    errors = validate_ocr_config(config)
    if errors:
        raise OcrError("；".join(errors))
    backend = effective_ocr_backend(config)
    if backend == "custom":
        return CustomOcr(config)
    if backend == "ppocr":
        from .onnx_ppocr import OnnxPPOcr
        key = "korean_ocr_model" if source_language(config) == "ko" else "english_ocr_model"
        return LocalOcr("ppocr", OnnxPPOcr(config[key], device), uses_lines=True)
    from onnx_baberu_ocr import OnnxBaberuOcr
    from onnx_manga_ocr import OnnxMangaOcr
    if backend in ("auto", "baberu"):
        try:
            return LocalOcr("baberu", OnnxBaberuOcr(config["baberu_ocr_model"], device))
        except Exception:
            if backend == "baberu":
                raise
            print("[INFO] Baberu 不可用，自动回退 manga-ocr。")
    return LocalOcr("manga-ocr", OnnxMangaOcr(config["ocr_model"], device))


def recognize_regions(engine: OcrEngine, image: Image.Image, language: str,
                      lines: list[Image.Image] | None = None,
                      check_cancelled: Callable[[], None] = lambda: None) -> OcrResult:
    """Keep one result per bubble, even when its OCR runs on several text lines."""
    results = []
    for crop in (lines if engine.uses_lines and lines else [image]):
        check_cancelled()
        results.append(engine.recognize(crop, language))
        check_cancelled()
    scores = [r.confidence for r in results if r.confidence is not None]
    return OcrResult("\n".join(r.text for r in results if r.text), language, engine.name,
                     sum(scores) / len(scores) if scores else None)
