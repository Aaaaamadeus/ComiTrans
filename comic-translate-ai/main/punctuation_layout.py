"""CJK 标点规范化、纵排形式与禁则处理。

本模块只负责文本和字格规划，不依赖 Pillow，便于单元测试。实际字形绘制由
``vertical_typesetter.py`` 完成。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import accumulate


from comic_translate_core.chinese import convert_chinese


VERTICAL_FORMS = {
    "，": "︐",
    "、": "︑",
    "。": "︒",
    "：": "︓",
    "；": "︔",
    "！": "︕",
    "？": "︖",
    "…": "︙",
    "⋯": "︙",
    "‥": "︰",
    "—": "︱",
    "―": "︱",
    "（": "︵",
    "）": "︶",
    "【": "︻",
    "】": "︼",
    "《": "︽",
    "》": "︾",
    "「": "﹁",
    "」": "﹂",
    "『": "﹃",
    "』": "﹄",
    "〔": "︹",
    "〕": "︺",
    "［": "﹇",
    "］": "﹈",
    "｛": "︷",
    "｝": "︸",
}

UPPER_RIGHT_PUNCTUATION = frozenset("，。、．“”‘’")
ELLIPSIS_DOT_COUNTS = {"…": 3, "⋯": 3, "︙": 3, "‥": 2, "︰": 2}
VERTICAL_DASH_CHARS = frozenset("—―︱")
CENTERED_PUNCTUATION = frozenset("！？：；～") | frozenset(ELLIPSIS_DOT_COUNTS) | VERTICAL_DASH_CHARS
OPENING_PUNCTUATION = frozenset("（《「『【〔〈〖〘〚［｛‘“")
CLOSING_PUNCTUATION = frozenset("）》】」』〕〉〗〙〛］｝’”")
FORBIDDEN_COLUMN_START = frozenset(
    "、。，．！？：；）》】」』〕〉〗〙〛］｝’”ゝゞ々ー～"
)
FORBIDDEN_COLUMN_END = OPENING_PUNCTUATION

_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_DOT_RUN_RE = re.compile(r"(?<!\d)(?:\.{3,}|．{3,})(?!\d)")
_GROUPS = ("！？", "？！", "!?", "?!")
_ASCII_TO_CJK = {
    ",": "，",
    ".": "。",
    ":": "：",
    ";": "；",
    "!": "！",
    "?": "？",
    "(": "（",
    ")": "）",
    "[": "［",
    "]": "］",
    "{": "｛",
    "}": "｝",
    "~": "～",
}
_CONTEXT_PUNCTUATION = frozenset(
    ".,:;!?()[]{}~，。：；！？（）［］｛｝～…—、"
)
_ASCII_BRACKET_PAIRS = {"(": ")", "[": "]", "{": "}"}
_ASCII_CLOSING_TO_OPENING = {value: key for key, value in _ASCII_BRACKET_PAIRS.items()}


@dataclass(frozen=True)
class GlyphToken:
    text: str
    kind: str = "text"

    @property
    def cells(self) -> int:
        return max(1, len(self.text))


def _nearest_visible(text: str, index: int, step: int) -> str:
    cursor = index + step
    while 0 <= cursor < len(text):
        if not text[cursor].isspace():
            return text[cursor]
        cursor += step
    return ""


def _nearest_context_char(text: str, index: int, step: int) -> str:
    cursor = index + step
    while 0 <= cursor < len(text):
        char = text[cursor]
        if char.isspace() or char in _CONTEXT_PUNCTUATION:
            cursor += step
            continue
        return char
    return ""


def _is_cjk(char: str) -> bool:
    return bool(char and _CJK_RE.fullmatch(char))


def normalize_cjk_punctuation(text: str) -> str:
    """只在 CJK 上下文规范标点，保留时间、小数、URL 和英文内容。"""
    if not text:
        return ""

    def replace_dot_run(match: re.Match) -> str:
        previous = _nearest_visible(text, match.start(), -1)
        following = _nearest_visible(text, match.end() - 1, 1)
        if not (_is_cjk(previous) or _is_cjk(following)):
            return match.group(0)
        # 三点省略号占一格；六点及以上按中文习惯保留两个省略号字格。
        return "……" if len(match.group(0)) >= 6 else "…"

    text = _DOT_RUN_RE.sub(replace_dot_run, text)
    cjk_bracket_indices: set[int] = set()
    bracket_stack: list[tuple[str, int]] = []
    for index, char in enumerate(text):
        if char in _ASCII_BRACKET_PAIRS:
            bracket_stack.append((char, index))
        elif char in _ASCII_CLOSING_TO_OPENING:
            expected = _ASCII_CLOSING_TO_OPENING[char]
            match_position = next(
                (
                    stack_index
                    for stack_index in range(len(bracket_stack) - 1, -1, -1)
                    if bracket_stack[stack_index][0] == expected
                ),
                None,
            )
            if match_position is not None:
                _opening, opening_index = bracket_stack.pop(match_position)
                if _CJK_RE.search(text[opening_index + 1:index]):
                    cjk_bracket_indices.update((opening_index, index))

    output = []
    for index, char in enumerate(text):
        replacement = _ASCII_TO_CJK.get(char)
        if replacement is None:
            output.append(char)
            continue
        previous = _nearest_visible(text, index, -1)
        following = _nearest_visible(text, index, 1)
        # 数字内部的时间、小数、比例保持 ASCII；英文两侧也不转换。
        if char in "()[]{}":
            output.append(replacement if index in cjk_bracket_indices else char)
        elif char in ".:" and previous.isdigit() and following.isdigit():
            output.append(char)
        elif _is_cjk(_nearest_context_char(text, index, -1)) or _is_cjk(
            _nearest_context_char(text, index, 1)
        ):
            output.append(replacement)
        else:
            output.append(char)
    return "".join(output)


def punctuation_kind(text: str) -> str:
    first = text[0]
    if first in OPENING_PUNCTUATION:
        return "opening"
    if first in CLOSING_PUNCTUATION:
        return "closing"
    if first in UPPER_RIGHT_PUNCTUATION:
        return "upper_right"
    if first in CENTERED_PUNCTUATION or text in ("！？", "？！", "!?", "?!"):
        return "centered"
    return "text"


def tokenize_punctuation(text: str, *, normalize: bool = True) -> list[GlyphToken]:
    text = normalize_cjk_punctuation(text) if normalize else text
    tokens = []
    index = 0
    while index < len(text):
        # A continuous ellipsis/dash is one unit, including alternate glyphs.
        # Pairwise grouping still allows longer runs to split between columns.
        char = text[index]
        run_chars = (ELLIPSIS_DOT_COUNTS if char in ELLIPSIS_DOT_COUNTS
                     else VERTICAL_DASH_CHARS if char in VERTICAL_DASH_CHARS else ())
        if run_chars:
            end = index + 1
            while end < len(text) and text[end] in run_chars:
                end += 1
            tokens.append(GlyphToken(text[index:end], "centered"))
            index = end
            continue
        group = next((value for value in _GROUPS if text.startswith(value, index)), None)
        if group:
            tokens.append(GlyphToken(group, punctuation_kind(group)))
            index += len(group)
            continue
        char = text[index]
        tokens.append(GlyphToken(char, punctuation_kind(char)))
        index += 1
    return tokens


@lru_cache(maxsize=512)
def _paragraph_breaks(text: str):
    """Reusable offsets for all font sizes tried while fitting this paragraph."""
    import jieba
    # Use the main dictionary for both scripts, but always slice the original.
    analysis = convert_chinese(text, 'zh-Hans')
    if len(analysis) != len(text):
        analysis = text
    word_ends = {end for _, _, end in jieba.tokenize(analysis)}
    tokens = tokenize_punctuation(text, normalize=False)
    ends = accumulate(len(token.text) for token in tokens)
    legal = tuple(end for end in ends if end == len(text) or (
        text[end - 1] not in FORBIDDEN_COLUMN_END and text[end] not in FORBIDDEN_COLUMN_START
    ))
    return legal, word_ends


def wrap_paragraph(text, limit, measure, final_tolerance=0):
    """Fit one normalized paragraph in pixels or cells, preferring word boundaries."""
    if not text or measure(text) <= limit + final_tolerance:
        return [text]
    breaks, word_ends = _paragraph_breaks(text)
    lines = []
    start = first = 0
    while first < len(breaks):
        # Even the narrowest box gets one legal unit (e.g. a whole dash run).
        chosen = first
        for index in range(first, len(breaks)):
            end = breaks[index]
            tolerance = final_tolerance if end == len(text) else 0
            if measure(text[start:end]) > limit + tolerance:
                break
            if end == len(text) or end in word_ends:
                chosen = index
            elif breaks[chosen] not in word_ends:
                chosen = index  # A long word alone can split at a legal glyph.
        end = breaks[chosen]
        lines.append(text[start:end])
        start = end
        first = chosen + 1
    return lines


def normalize_line_breaks(text: str) -> str:
    return text.replace('\r\n', '\n').replace('\r', '\n').replace('\u2028', '\n').replace('\u2029', '\n')


def wrap_vertical_text(text: str, max_cells: int) -> list[str]:
    if not text:
        return []
    columns = []
    for paragraph in normalize_line_breaks(text).split('\n'):
        columns.extend(wrap_paragraph(normalize_cjk_punctuation(paragraph), max(1, int(max_cells)), len))
    return columns


def vertical_form(char: str) -> str | None:
    return VERTICAL_FORMS.get(char)
