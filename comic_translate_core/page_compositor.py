"""Compose changed native-pixel regions without copying an entire page per edit."""
from PIL import Image
from .watermark import watermark_overlay
from .restoration import protected_region


def intersection(a, b):
    box = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return box if box[2] > box[0] and box[3] > box[1] else None


def layer_bounds(layer):
    surface, left, top = layer
    return left, top, left + surface.width, top + surface.height


def compose_page(base, previous, layers, dirty, *, watermark=False, original=None, items=(), copy_previous=False):
    bounds = (0, 0, base.width, base.height)
    full = previous is None or dirty is None
    rectangles = [bounds] if full else [box for raw in dirty if (box := intersection(raw, bounds))]
    # Merge overlapping regions so alpha never accumulates on the same pixels.
    merged = []
    for box in rectangles:
        changed = True
        while changed:
            changed = False
            for other in list(merged):
                if intersection(box, other):
                    merged.remove(other)
                    box = min(box[0], other[0]), min(box[1], other[1]), max(box[2], other[2]), max(box[3], other[3])
                    changed = True
        merged.append(box)
    mark = watermark_overlay(base.size) if watermark and min(base.size) >= 8 else None
    restorations = [(bounds, mask) for item in items if item.get('restore_original')
                    for bounds, mask in [protected_region(item, items, base.size)]]
    patches = []
    for box in merged:
        patch = base.crop(box)
        for surface, left, top in layers:
            overlap = intersection(box, (left, top, left + surface.width, top + surface.height))
            if overlap:
                crop = surface.crop((overlap[0]-left, overlap[1]-top, overlap[2]-left, overlap[3]-top))
                patch.paste(crop, (overlap[0]-box[0], overlap[1]-box[1]), crop)
        if mark:
            surface, left, top = mark
            overlap = intersection(box, (left, top, left + surface.width, top + surface.height))
            if overlap:
                relative = (overlap[0]-box[0], overlap[1]-box[1], overlap[2]-box[0], overlap[3]-box[1])
                layer = surface.crop((overlap[0]-left, overlap[1]-top, overlap[2]-left, overlap[3]-top))
                composed = Image.alpha_composite(patch.crop(relative).convert('RGBA'), layer)
                patch.paste(composed.convert(patch.mode), relative[:2])
        for region, mask in restorations:
            overlap = intersection(box, region)
            if overlap:
                crop_mask = mask.crop((overlap[0]-region[0], overlap[1]-region[1], overlap[2]-region[0], overlap[3]-region[1]))
                patch.paste(original.crop(overlap), (overlap[0]-box[0], overlap[1]-box[1]), crop_mask)
        patches.append((box, patch))
    # Generate all patches before mutating the live canvas so failures retain its pixels.
    if full:
        canvas = patches[0][1]
    else:
        canvas = previous.copy() if copy_previous else previous
        for box, patch in patches:
            canvas.paste(patch, box[:2])
    return canvas, merged
