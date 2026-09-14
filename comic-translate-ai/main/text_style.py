"""漫画文本块的排版方向与字体风格选择规则。"""
from __future__ import annotations

import re

import cv2
import numpy as np


FONT_STYLES = (
    "dialogue",
    "bold_dialogue",
    "radiating",
    "handwriting",
    "thought",
    "whisper",
    "serious",
    "narration",
    "sfx",
    "cute",
    "next_preview",
    "title",
)

_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_PREVIEW_RE = re.compile(
    r"次回|つづく|続く|待续|下回|TO\s+BE\s+CONTINUED|次号|"
    r"第\s*\d+\s*话|后篇|後篇|预告|最终话|最終話|最终回|最終回",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"^(?:第\s*)?[0-9一二三四五六七八九十百]+\s*(?:話|话|章|幕|回|巻|卷)$")


def choose_layout_direction(
    detected_vertical: bool,
    width: int,
    height: int,
    text: str = "",
) -> int:
    """返回 1=竖排、0=横排；保留检测结果，只纠正明显矛盾的长宽比。"""
    width = max(1, int(width))
    height = max(1, int(height))
    has_cjk = bool(_CJK_RE.search(text or ""))
    if detected_vertical:
        # 很宽的旁白框、章节标题不应因为单条竖线误判为竖排。
        return 0 if width >= height * 1.75 else 1
    # 日文瘦长文本块偶尔会被检测器判成横排；英文/数字保持横排。
    if has_cjk and height >= width * 1.65:
        return 1
    return 0


def estimate_text_emphasis(crop, target_font_size: int | None = None) -> float:
    """估算原字笔画强度，返回约 0..1；用于区分普通、粗体和音效字。"""
    if crop is None or getattr(crop, "size", 0) == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    _threshold, ink = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    dark_ratio = float(np.mean(ink > 0))
    if dark_ratio <= 0.002:
        return 0.0
    distance = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    positive = distance[distance > 0]
    stroke_radius = float(np.percentile(positive, 80)) if positive.size else 0.0
    reference = max(8.0, float(target_font_size or min(gray.shape[:2]) * 0.18))
    stroke_score = min(1.0, (stroke_radius * 2.0) / reference)
    density_score = min(1.0, dark_ratio / 0.22)
    return stroke_score * 0.7 + density_score * 0.3


def choose_font_style(
    text: str,
    *,
    direction: int,
    width: int,
    height: int,
    non_bubble: bool = False,
    emphasis: float = 0.0,
) -> str:
    """用 OCR 文本、位置属性和字重特征选择有限且稳定的字体风格。"""
    text = (text or "").strip()
    compact = re.sub(r"\s+", "", text)
    if _PREVIEW_RE.search(compact):
        return "next_preview"
    if _TITLE_RE.search(compact):
        return "title"
    if re.search(r"[♥♡❤♪♫☆★]+|[～〜~]{2,}", compact):
        return "cute"
    if non_bubble:
        if len(compact) <= 18 or emphasis >= 0.34:
            return "sfx"
        return "narration"
    if direction == 0 and width >= height * 2.0:
        return "narration"
    if re.search(r"[!！?？]{2,}|[!！][?？]|[?？][!！]", compact):
        return "radiating"
    if emphasis >= 0.43 and len(compact) <= 24:
        return "bold_dialogue"
    if re.search(r"^(?:\(|（).*(?:\)|）)$", compact):
        return "thought"
    if compact.startswith(("…", "...")) or re.search(r"小声|ひそひそ|こそこそ", compact):
        return "whisper"
    if re.search(r"手書き|メモ|注[:：]", compact):
        return "handwriting"
    return "dialogue"
