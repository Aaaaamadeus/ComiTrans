"""Shared lettering options for translation and editing."""

import re

VERTICAL_ALIGNMENTS = (('top', '上对齐'), ('center', '居中对齐'), ('bottom', '下对齐'))


def normalize_vertical_alignment(value) -> str:
    return value if value in ('top', 'center', 'bottom') else 'center'


def normalize_text_color(value) -> str | None:
    """Persist opaque RGB colors as #rrggbb; missing/invalid values keep legacy colors."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if re.fullmatch(r'#[0-9a-f]{3}', value):
        return '#' + ''.join(char * 2 for char in value[1:])
    return value if re.fullmatch(r'#[0-9a-f]{6}', value) else None
