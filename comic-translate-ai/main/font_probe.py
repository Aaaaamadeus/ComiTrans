"""多模态字体候选判别：本地生成候选，模型只做 1-of-3 选择。

设计依据见 docs/FONT_STYLE_STRATEGY.md §4.12（全部为实测数字）：

- 开放式「属于哪个字体族」提问：单块 57%、整页 39%；
- 同一批块改成「三候选比对」：5/5 全中（连开放式提问判错的濑户手写也选对）；
- 候选扩到 8 个：2/5，且出现一次 8000 token 全被 reasoning 吃光、没有产出；
- 同一提示词重复 3 次：自一致率 100%（误差是系统性的，投票无收益）；
- 模型自报 confidence 错答也是 0.8~0.95，不能用于门控。

因此本模块把模型的决策面压到最小：
    本地决定角色、候选集与候选字体 → 模型只回答「原块更像哪个候选」
    模型结果还要过「精确率门控 + 本地许可」，不通过就保留本地判定。

纯函数，无网络、无全局状态，可单测。
"""
from __future__ import annotations

import os
from typing import Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


# 角色分工（见 §4.5）：只让模型参与正文类与手写类角色，
# 装饰/情绪类角色（拟声、标题、下回预告、可爱、低语、独白）由本地保留。
ROUTED_ROLES = ("dialogue", "narration", "bold_dialogue", "serious", "handwriting")
DECORATIVE_ROLES = ("title", "next_preview", "sfx", "radiating", "cute", "whisper", "thought")

# 三个候选：字母 → 字体族 → 依次尝试的风格键（实际字体由 font_map 决定）
CANDIDATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("A", "gothic", ("bold_dialogue", "title", "dialogue")),
    ("B", "mincho", ("serious", "thought")),
    ("C", "handwriting", ("tegaki_851", "handwriting", "whisper")),
)

# (角色, 字体族) → 风格。未命中则保留本地角色（模型无权换角色）。
FAMILY_STYLE: dict[str, dict[str, str]] = {
    "gothic": {
        "dialogue": "lxgw_marker",
        "narration": "lxgw_marker",
        "serious": "lxgw_marker",
        "handwriting": "lxgw_marker",
        "bold_dialogue": "bold_dialogue",
    },
    "mincho": {
        "dialogue": "serious",
        "narration": "serious",
        "serious": "serious",
        "handwriting": "serious",
        "bold_dialogue": "serious",
    },
    "handwriting": {
        "dialogue": "handwriting",
        "narration": "handwriting",
        "serious": "handwriting",
        "handwriting": "handwriting",
        "bold_dialogue": "handwriting",
    },
}

# 选择性采纳：只有历史精确率达标（合成集校准）的字体族才允许替换本地判定。
# 当前取值为三候选比对实测（5/5）；样本量小，接入真实评测后按族更新。
PRECISION_GATE: dict[str, float] = {"gothic": 1.0, "mincho": 1.0, "handwriting": 1.0}
PRECISION_THRESHOLD = 0.75

PANEL_GAP = 6
LABEL_FONT_SIZE = 22
MAX_HORIZONTAL_CHARS = 12
MAX_VERTICAL_CHARS = 7
# 原图字号小于该值时，整张对比图等比放大（保持各格相对比例），让模型看得清笔画端点
SMALL_GLYPH_PX = 30
MAX_UPSCALE = 3


def should_probe(role: str | None, text: str | None) -> bool:
    """该文本块是否值得外发模型：正文/手写类角色且原文非空。"""
    if not (text or "").strip():
        return False
    return str(role or "") in ROUTED_ROLES


def candidate_specs(font_map: Mapping[str, str]) -> list[tuple[str, str, str]]:
    """按候选顺序取实际字体文件路径；缺任一候选则返回空（宁可不用，也不错配）。"""
    specs: list[tuple[str, str, str]] = []
    for letter, family, style_keys in CANDIDATES:
        for style in style_keys:
            path = str(font_map.get(style) or "")
            if path and os.path.isfile(path):
                specs.append((letter, family, path))
                break
        else:
            return []
    return specs


def resolve_style(role: str | None, family: str | None) -> str:
    """本地许可表：字体族 → 本角色下允许的风格；未命中保留本地角色。"""
    role = str(role or "dialogue")
    mapped = FAMILY_STYLE.get(str(family or ""), {}).get(role)
    return mapped or role


def accept_family(family: str | None) -> bool:
    """精确率门控：未达阈值的字体族一律不采纳（保留本地判定）。"""
    if not family:
        return False
    return PRECISION_GATE.get(str(family), 0.0) >= PRECISION_THRESHOLD


def parse_pick(content: str | None) -> tuple[str | None, str | None]:
    """从模型回答里取出候选字母与字体族；无法解析或 none 时返回 (None, None)。"""
    import json

    text = (content or "").strip()
    if not text:
        return None, None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None, None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None, None
    pick = str(data.get("pick") or "").strip().upper()
    for letter, family, _ in CANDIDATES:
        if pick == letter:
            return letter, family
    return None, None


def pick_majority(families: Iterable[str | None], *, strict: bool = True) -> str | None:
    """多数表决：把单次判定的抖动收敛成稳定结论，票不够就弃权。

    规则：① 有效票（模型给出了可解析的族）必须达到样本数的一半，否则弃权；
    ② 在有效票中拿到过半（默认严格过半）才通过。

    实测动机（文档 §4.15）：关掉思考后单块只要 ~5 个 completion token，
    但同一块三次仍可能给出 handwriting/mincho/mincho 这样的组合，
    因此用「多采样 + 过半才采纳」代替「单次说了算」。
    """
    from collections import Counter

    samples = list(families or [])
    if not samples:
        return None
    valid = [family for family in samples if family]
    if not valid or len(valid) * 2 < len(samples):
        return None
    family, count = Counter(valid).most_common(1)[0]
    threshold = len(valid) / 2 if strict else 0
    return family if count > threshold else None


def estimate_glyph_px(crop: Image.Image, text: str, direction: int) -> int:
    """估算原图单字像素：优先用检测器给出的字号，这里只做兜底估算。"""
    chars = max(1, len([char for char in (text or "") if not char.isspace()]))
    if direction == 1:
        # 竖排：一列约 char 个字，取列宽与列内字高的较小者
        return int(max(12, min(crop.width, crop.height / chars)))
    # 横排：按可用宽度均分，行数按需要折行
    lines = max(1, (chars + MAX_HORIZONTAL_CHARS - 1) // MAX_HORIZONTAL_CHARS)
    return int(max(12, min(crop.height / lines, crop.width / min(chars, MAX_HORIZONTAL_CHARS))))


def _candidate_panel(
    text: str,
    font_path: str,
    label: str,
    *,
    glyph_px: int,
    direction: int,
) -> Image.Image:
    """候选面板：字形尺寸与原图块一致，才谈得上公平比较。"""
    body = text.strip()
    if direction == 1:
        body = "".join(char for char in body if not char.isspace())[:MAX_VERTICAL_CHARS]
    else:
        body = body[:MAX_HORIZONTAL_CHARS]
    font = ImageFont.truetype(font_path, max(12, min(glyph_px, 96)))
    label_font = ImageFont.truetype(font_path, LABEL_FONT_SIZE)
    if direction == 1:
        text_width = font.size
        text_height = font.size * max(1, len(body))
    else:
        text_width = int(font.getlength(body))
        text_height = font.size
    width = max(70, text_width + 24)
    height = max(52, text_height + 42, min(label_font.size * 2, 48) + text_height)
    panel = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(panel)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(190, 190, 190))
    draw.text((6, 2), label, font=label_font, fill=(110, 110, 110))
    if direction == 1:
        y = height - text_height - 6
        for char in body:
            draw.text((width - font.size - 10, y), char, font=font, fill="black")
            y += font.size
    else:
        draw.text((12, height - font.size - 8), body, font=font, fill="black")
    return panel


def build_probe_sheet(
    crop: Image.Image,
    text: str,
    specs: Sequence[tuple[str, str, str]],
    *,
    direction: int = 1,
    reference_font: str | None = None,
    glyph_px: int | None = None,
) -> Image.Image:
    """拼出「原图 + A/B/C 候选」的竖排对比图。

    - 候选标签只写字母，**不写字体族名称**，避免模型读标签而不是看字形；
    - 原图块与候选用**同一个字形像素尺寸**渲染，避免"候选字更大"造成的偏差；
    - 原图字号过小时整张图等比放大（保持相对比例），上限 MAX_UPSCALE。
    """
    original = crop.convert("RGB")
    glyph = int(glyph_px or 0) or estimate_glyph_px(original, text, direction)
    glyph = max(12, min(glyph, 96))

    panels = [original]
    for letter, _family, path in specs:
        panels.append(
            _candidate_panel(text, path, letter, glyph_px=glyph, direction=direction)
        )

    common_height = max(panel.height for panel in panels)
    common_width = max(panel.width for panel in panels)
    sheet = Image.new(
        "RGB",
        (common_width, common_height * len(panels) + PANEL_GAP * (len(panels) - 1)),
        "white",
    )
    y = 0
    for panel in panels:
        sheet.paste(panel, (0, y))
        y += common_height + PANEL_GAP

    if glyph < SMALL_GLYPH_PX:
        factor = min(MAX_UPSCALE, max(2, SMALL_GLYPH_PX // max(1, glyph)))
        sheet = sheet.resize((sheet.width * factor, sheet.height * factor), Image.LANCZOS)
    return sheet


def probe_prompt() -> str:
    """A′ 契约：只有 1-of-3（或 none），没有字体名、没有字号、没有方向。"""
    letters = "、".join(letter for letter, _, _ in CANDIDATES)
    return (
        "图中最上面一格的「原图」是漫画原图的文字块，下面 "
        f"{letters} 三格是同一句话用三种不同字体渲染出来的候选。\n"
        "请只做一件事：判断原块的字体最接近哪一个候选。\n"
        f'只输出 JSON，不要解释：{{"pick":"{CANDIDATES[0][0]}"}}；'
        '若三个都不像，输出 {"pick":"none"}。\n'
        "不要输出字体名称，不要输出字体文件名，不要输出字号。"
    )
