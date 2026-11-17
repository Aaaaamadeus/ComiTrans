"""Editor-only transforms of transparent lettering layers at native resolution."""
import math

from PIL import Image
from .i18n import tr


def bounded_number(value, default, minimum, maximum):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, value)) if math.isfinite(value) else default


def text_transform(item):
    return (bounded_number(item.get('text_scale_x'), 1., .1, 4.),
            bounded_number(item.get('text_scale_y'), 1., .1, 4.),
            bounded_number(item.get('text_rotation'), 0., -180., 180.))


def outline_width(item):
    value = item.get('outline_width')
    return None if value is None else bounded_number(value, None, 0., 30.)


def transform_layer(layer, transform):
    """Stretch then rotate clockwise about the ink's center, keeping all its edges."""
    if layer is None or transform == (1., 1., 0.):
        return layer
    surface, left, top = layer
    bounds = surface.getchannel('A').getbbox()
    if bounds is None:
        return layer
    scale_x, scale_y, angle = transform
    center_x = left + (bounds[0] + bounds[2]) / 2
    center_y = top + (bounds[1] + bounds[3]) / 2
    width = max(1, round((bounds[2] - bounds[0]) * scale_x))
    height = max(1, round((bounds[3] - bounds[1]) * scale_y))
    radians = math.radians(angle)
    rotated_width = math.ceil(abs(width * math.cos(radians)) + abs(height * math.sin(radians))) + 2
    rotated_height = math.ceil(abs(width * math.sin(radians)) + abs(height * math.cos(radians))) + 2
    # Match the editor's 64 MB layer budget before allocating either intermediate.
    if max(width * height, rotated_width * rotated_height) > 16_000_000:
        raise ValueError(tr('文字变形尺寸过大，请减小字号或拉伸比例。'))
    surface = surface.crop(bounds)
    if surface.size != (width, height):
        surface = surface.resize((width, height), Image.Resampling.LANCZOS)
    if angle:
        surface = surface.rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True)
    return surface, round(center_x - surface.width / 2), round(center_y - surface.height / 2)
