"""Lossless original-page snapshots and per-bubble restoration regions."""
import base64
import io
import os
from pathlib import Path
import tempfile

from PIL import Image, ImageChops


def original_snapshot_path(output_path):
    output = Path(output_path)
    return output.parent.parent / f'{output.parent.name}_original' / f'{output.stem}_original.png'


def pdf_original_path(output_path):
    output = Path(output_path)
    if output.parent.name == 'translated' and (output.parent.parent / 'project.json').is_file():
        return output.parent.parent / 'source' / output.name
    return None


def find_original(output_path):
    for candidate in (original_snapshot_path(output_path), pdf_original_path(output_path)):
        if candidate is not None and candidate.is_file():
            return candidate
    return None


def save_original(output_path, image, input_path=None):
    """Accept an image or a factory so reusing a PDF page needs no decoded copy."""
    # PDF projects already own an immutable source PNG at the exact pixel size.
    pdf_source = pdf_original_path(output_path)
    destination = original_snapshot_path(output_path)
    if (pdf_source is not None and input_path is not None and pdf_source.is_file()
            and Path(input_path).resolve() == pdf_source.resolve() and not destination.exists()):
        return pdf_source
    # Refresh a previous manual override when processing this page again.
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.original-', suffix='.png', dir=destination.parent)
    os.close(descriptor)
    staged = Path(name)
    try:
        if callable(image):
            image = image()
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(staged, format='PNG')
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)
    return destination


def clipped_box(box, size):
    x1, y1, x2, y2 = map(int, box[:4])
    width, height = size
    region = (max(0, x1), max(0, y1), min(width, x2), min(height, y2))
    if region[2] <= region[0] or region[3] <= region[1]:
        raise ValueError('原气泡框不在图片范围内')
    return region


def encode_region(bounds, mask):
    stream = io.BytesIO()
    mask.convert('L').save(stream, format='PNG')
    return {'version': 1, 'box': list(bounds), 'mask_png': base64.b64encode(stream.getvalue()).decode('ascii')}


def make_region(box, size, repair_bounds=None, repair_mask=None):
    """Restore the original detection box plus its exact padded erase pixels."""
    region = clipped_box(box, size)
    if repair_bounds is None:
        bounds = region
    else:
        repair_bounds = clipped_box(repair_bounds, size)
        bounds = (min(region[0], repair_bounds[0]), min(region[1], repair_bounds[1]),
                  max(region[2], repair_bounds[2]), max(region[3], repair_bounds[3]))
    mask = Image.new('L', (bounds[2]-bounds[0], bounds[3]-bounds[1]))
    if repair_bounds is not None and repair_mask is not None:
        if repair_mask.size != (repair_bounds[2]-repair_bounds[0], repair_bounds[3]-repair_bounds[1]):
            raise ValueError('气泡擦除掩膜尺寸不一致')
        mask.paste(repair_mask, (repair_bounds[0]-bounds[0], repair_bounds[1]-bounds[1]))
    mask.paste(255, (region[0]-bounds[0], region[1]-bounds[1], region[2]-bounds[0], region[3]-bounds[1]))
    return encode_region(bounds, mask)


def legacy_region(item, original, cleaned):
    """Recover old padded repair pixels from original/cleaned differences."""
    x1, y1, x2, y2 = clipped_box(item['box'], original.size)
    bounds = clipped_box((x1-15, y1-15, x2+15, y2+15), original.size)
    channels = ImageChops.difference(original.crop(bounds), cleaned.crop(bounds)).split()
    difference = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    mask = difference.point(lambda value: 255 if value else 0)
    return make_region(item['box'], original.size, bounds, mask)


def decode_region(item, size):
    data = item.get('original_region')
    if data is None:
        region = clipped_box(item['box'], size)
        return region, Image.new('L', (region[2]-region[0], region[3]-region[1]), 255)
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('气泡原图区域格式无效')
    bounds = tuple(data['box'])
    if len(bounds) != 4 or any(type(value) is not int for value in bounds) or clipped_box(bounds, size) != bounds:
        raise ValueError('气泡原图区域超出图片范围')
    region = clipped_box(item['box'], size)
    if not (bounds[0] <= region[0] < region[2] <= bounds[2]
            and bounds[1] <= region[1] < region[3] <= bounds[3]):
        raise ValueError('气泡原图区域没有包含原气泡框')
    with Image.open(io.BytesIO(base64.b64decode(data['mask_png'], validate=True))) as source:
        if source.size != (bounds[2]-bounds[0], bounds[3]-bounds[1]):
            raise ValueError('气泡原图掩膜尺寸不一致')
        mask = source.convert('L').point(lambda value: 255 if value else 0)
    return bounds, mask


def protected_region(item, items, size):
    bounds, mask = decode_region(item, size)
    # A padded edge must not undo the adjacent bubble's own detection box.
    for other in items:
        if other is item:
            continue
        try:
            x1, y1, x2, y2 = clipped_box(other['box'], size)
        except (ValueError, TypeError, KeyError):
            continue
        overlap = (max(x1, bounds[0]), max(y1, bounds[1]), min(x2, bounds[2]), min(y2, bounds[3]))
        if overlap[2] > overlap[0] and overlap[3] > overlap[1]:
            mask.paste(0, (overlap[0]-bounds[0], overlap[1]-bounds[1], overlap[2]-bounds[0], overlap[3]-bounds[1]))
    # In overlapping detection boxes, the explicitly restored box takes priority.
    region = clipped_box(item['box'], size)
    mask.paste(255, (region[0]-bounds[0], region[1]-bounds[1], region[2]-bounds[0], region[3]-bounds[1]))
    return bounds, mask


def apply_restorations(image, original, items):
    if image.size != original.size:
        raise ValueError('原图与当前页面尺寸不一致，无法无损还原')
    for item in items:
        if item.get('restore_original'):
            bounds, mask = protected_region(item, items, image.size)
            image.paste(original.crop(bounds), bounds[:2], mask)
    return image


def intersects_restored_region(box, items, size):
    for item in items:
        if not item.get('restore_original'):
            continue
        bounds, mask = protected_region(item, items, size)
        x1, y1, x2, y2 = max(box[0], bounds[0]), max(box[1], bounds[1]), min(box[2], bounds[2]), min(box[3], bounds[3])
        if x2 > x1 and y2 > y1 and mask.crop((x1-bounds[0], y1-bounds[1], x2-bounds[0], y2-bounds[1])).getbbox():
            return True
    return False
