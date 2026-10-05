"""Render the optional ComiTrans signature on a finished page, never its clean base."""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WATERMARK_TEXT = "@ComiTrans"
FONT_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets/ui/fonts/Skribble.ttf"


@lru_cache(maxsize=32)
def _wordmark(width: int) -> Image.Image:
    # Render above the output resolution to keep the small handwritten strokes smooth.
    scale = 4
    stroke = 3
    reference = ImageFont.truetype(str(FONT_PATH), 128)
    box = reference.getbbox(WATERMARK_TEXT)
    font_size = max(1, round(128 * max(1, width * scale - stroke * 2) / (box[2] - box[0])))
    font = ImageFont.truetype(str(FONT_PATH), font_size)
    left, top, right, bottom = font.getbbox(WATERMARK_TEXT, stroke_width=stroke)
    layer = Image.new("RGBA", (right - left, bottom - top))
    ImageDraw.Draw(layer).text(
        (-left, -top), WATERMARK_TEXT, font=font, fill=(40, 40, 40, 90),
        stroke_width=stroke, stroke_fill=(255, 255, 255, 120),
    )
    height = max(1, round(layer.height * width / layer.width))
    return layer.resize((width, height), Image.Resampling.LANCZOS)


def apply_watermark(image: Image.Image, *, enabled: bool = False) -> Image.Image:
    """Return a marked copy; disabled output is the original image without any I/O.

    The signature spans 14% of the page width, inset from the lower-right edge.
    Always call with a freshly typeset image so repeated saves cannot accumulate it.
    """
    if not enabled or min(image.size) < 8:
        return image
    short_edge = min(image.size)
    right_margin = max(1, round(short_edge * .020))
    bottom_margin = max(1, round(short_edge * .016))
    width = max(1, min(round(image.width * .14), image.width - right_margin * 2))
    layer = _wordmark(width)
    # Very wide pages must still leave the artwork visible and keep the mark in bounds.
    max_height = max(1, min(round(image.height * .05), image.height - bottom_margin * 2))
    if layer.height > max_height:
        layer = layer.resize(
            (max(1, round(layer.width * max_height / layer.height)), max_height),
            Image.Resampling.LANCZOS,
        )
    x = image.width - right_margin - layer.width
    y = image.height - bottom_margin - layer.height
    result = image.copy() if image.mode in ("RGB", "RGBA", "L", "LA") else image.convert("RGBA")
    region = (x, y, x + layer.width, y + layer.height)
    composed = Image.alpha_composite(result.crop(region).convert("RGBA"), layer)
    result.paste(composed.convert(result.mode), (x, y))
    return result
