"""Shared vertical column alignment choices for translation and editing."""

VERTICAL_ALIGNMENTS = (('top', '上对齐'), ('center', '居中对齐'), ('bottom', '下对齐'))


def normalize_vertical_alignment(value) -> str:
    return value if value in ('top', 'center', 'bottom') else 'center'
