"""CJK 标点规范化、纵排形式与禁则处理。

本模块只负责文本和字格规划，不依赖 Pillow，便于单元测试。实际字形绘制由
``vertical_typesetter.py`` 完成。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


VERTICAL_FORMS = {
    "，": "︐",
    "、": "︑",
    "。": "︒",
    "：": "︓",
    "；": "︔",
    "！": "︕",
    "？": "︖",
    "…": "︙",
    "—": "︱",
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
CENTERED_PUNCTUATION = frozenset("！？：；…—～")
OPENING_PUNCTUATION = frozenset("（《「『【〔〈〖〘〚［｛‘“")
CLOSING_PUNCTUATION = frozenset("）》】」』〕〉〗〙〛］｝’”")
FORBIDDEN_COLUMN_START = frozenset(
    "、。，．！？：；）》】」』〕〉〗〙〛］｝’”ゝゞ々ー～"
)
FORBIDDEN_COLUMN_END = OPENING_PUNCTUATION

_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_DOT_RUN_RE = re.compile(r"(?<!\d)(?:\.{3,}|．{3,})(?!\d)")
_GROUPS = ("……", "——", "！？", "？！", "!?", "?!")
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
        group = next((value for value in _GROUPS if text.startswith(value, index)), None)
        if group:
            tokens.append(GlyphToken(group, punctuation_kind(group)))
            index += len(group)
            continue
        char = text[index]
        tokens.append(GlyphToken(char, punctuation_kind(char)))
        index += 1
    return tokens


def token_starts_forbidden(token: GlyphToken) -> bool:
    return bool(token.text and token.text[0] in FORBIDDEN_COLUMN_START)


def token_ends_forbidden(token: GlyphToken) -> bool:
    return bool(token.text and token.text[-1] in FORBIDDEN_COLUMN_END)


def wrap_vertical_tokens(tokens: list[GlyphToken], max_cells: int) -> list[list[GlyphToken]]:
    """按固定字格分列，并执行基础中文/日文避头尾规则。"""
    if not tokens:
        return []
    max_cells = max(1, int(max_cells))
    columns: list[list[GlyphToken]] = []
    current: list[GlyphToken] = []

    def used(items: list[GlyphToken]) -> int:
        return sum(token.cells for token in items)

    for token in tokens:
        if not current or used(current) + token.cells <= max_cells:
            current.append(token)
            continue

        carry: list[GlyphToken] = []
        # 左括号等不能留在旧列末尾，应和下一个字符一起移到新列。
        while len(current) > 1 and token_ends_forbidden(current[-1]):
            carry.insert(0, current.pop())

        # 结束标点不能独占新列：从旧列带一个正文字符过去。若旧列只有一个
        # 字符，则允许标点在旧列溢出一个字格，避免产生标点孤列。
        if token_starts_forbidden(token) and not carry:
            if len(current) > 1:
                carry.insert(0, current.pop())
                while current and token_ends_forbidden(current[-1]):
                    carry.insert(0, current.pop())
                if not current:
                    current = carry + [token]
                    continue
            else:
                current.append(token)
                continue

        if current:
            columns.append(current)
        current = carry + [token]

    if current:
        columns.append(current)
    return [column for column in columns if column]


def wrap_vertical_text(text: str, max_cells: int) -> list[str]:
    tokens = tokenize_punctuation(text)
    return ["".join(token.text for token in column) for column in wrap_vertical_tokens(tokens, max_cells)]


def vertical_form(char: str) -> str | None:
    return VERTICAL_FORMS.get(char)
