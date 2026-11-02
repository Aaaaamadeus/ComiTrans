"""Native-resolution text masks, independent of OCR, LaMa and desktop UI."""
from dataclasses import dataclass, field
from typing import Protocol

import cv2
import numpy as np
from .image_filters import gaussian_background


@dataclass(frozen=True)
class MaskRequest:
    image: np.ndarray  # uint8 BGR crop; never modified
    text_box: tuple[int, int, int, int]  # crop-local, exclusive right/bottom
    detector_mask: np.ndarray | None = None  # uint8, same height/width
    font_size: int = 16


@dataclass(frozen=True)
class MaskResult:
    erase_mask: np.ndarray  # binary uint8, 255 = replace
    layout_mask: np.ndarray  # independent, wider placement footprint
    fill_color: tuple[int, int, int] | None = None  # BGR; None = textured repair
    diagnostics: dict = field(default_factory=dict)
    source_outline_ratio: float | None = None  # white stroke width / original font size


class TextMaskGenerator(Protocol):
    def generate(self, request: MaskRequest) -> MaskResult: ...


def validate_result(result: MaskResult, shape) -> MaskResult:
    for name in ('erase_mask', 'layout_mask'):
        value = getattr(result, name)
        if (not isinstance(value, np.ndarray) or value.shape != tuple(shape)
                or value.dtype != np.uint8 or np.any((value != 0) & (value != 255))):
            raise ValueError(f'{name} must be a binary uint8 mask of shape {tuple(shape)}')
    if result.fill_color is not None:
        if len(result.fill_color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in result.fill_color):
            raise ValueError('fill_color must contain three BGR integers in [0, 255]')
    ratio = result.source_outline_ratio
    if ratio is not None and (type(ratio) not in (float, int) or not 0 < ratio <= .3):
        raise ValueError('source_outline_ratio must be in (0, 0.3]')
    return result


def _ellipse(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1,) * 2)


def _dilate(mask, radius):
    return cv2.dilate(mask.astype(np.uint8), _ellipse(radius)) > 0


def _white_outline(image, seeds, size):
    """Find bounded white contours wrapping detector-supported dark strokes."""
    dark = seeds & (cv2.inRange(image, (0, 0, 0), (159, 159, 159)) > 0)
    if not dark.any():
        return None
    white = cv2.inRange(image, (237, 237, 237), (255, 255, 255)) > 0
    rim = _dilate(dark, 2) & ~dark
    if not np.any(rim & white):
        return None
    count, labels = cv2.connectedComponents(white.astype(np.uint8), connectivity=8)
    supported = np.zeros(count, bool)
    supported[np.unique(labels[rim & white])] = True
    # The white paper or a highlight that continues into the art is not a
    # lettering outline. Never clip such a component to the search radius.
    bounded = _dilate(dark, max(3, min(14, round(size * .27))))
    bounded[[0, -1], :] = bounded[:, [0, -1]] = False
    supported[np.unique(labels[~bounded])] = False
    supported[0] = False
    candidate = supported[labels]
    if not candidate.any():
        return None
    # Require the white component to surround a stroke, not just run along
    # one side of it. Measure support separately for each dark component.
    ink_count, ink_labels = cv2.connectedComponents(dark.astype(np.uint8), connectivity=8)
    rim_labels = cv2.dilate(ink_labels.astype(np.float32), _ellipse(2))[rim].astype(np.int32)
    perimeter = np.bincount(rim_labels, minlength=ink_count)
    hits = np.bincount(rim_labels[candidate[rim]], minlength=ink_count)
    wrapped = (perimeter >= 6) & (hits >= perimeter * .65)
    if not wrapped.any():
        return None
    supported[:] = False
    supported[np.unique(labels[_dilate(wrapped[ink_labels], 2) & candidate])] = True
    supported[0] = False
    outline = supported[labels]
    ratio = None
    # A small outlined mark can be erased independently. Transfer its style
    # to the whole text block only if most of the ink boundary supports it.
    if perimeter[wrapped].sum() >= perimeter.sum() * .6:
        distance = cv2.distanceTransform((~dark).astype(np.uint8), cv2.DIST_L2, 5)
        thickness = float(np.percentile(distance[outline], 90))
        ratio = min(.3, thickness / size)
    return outline, ratio


class AdaptiveTextMask:
    """Colour-aware flat fills and bounded, detector-guided texture masks.

    Detector seeds are essential on ambiguous artwork: a dark hair strand and
    a connected dark glyph cannot be separated reliably by intensity alone.
    Growth is therefore bounded on textured regions, even for huge components.
    """
    version = 'adaptive-v3'

    def generate(self, request: MaskRequest) -> MaskResult:
        image = request.image
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError('image must be uint8 BGR')
        height, width = image.shape[:2]
        x1, y1, x2, y2 = map(int, request.text_box)
        x1, x2 = max(0, x1), min(width, x2)
        y1, y2 = max(0, y1), min(height, y2)
        if x2 <= x1 or y2 <= y1:
            raise ValueError('text_box must intersect the image')
        size = max(4, int(request.font_size))
        inside = np.zeros((height, width), np.uint8)
        inside[y1:y2, x1:x2] = 1
        domain = _dilate(inside, max(3, min(8, round(size * .25))))
        seeds = np.zeros((height, width), bool)
        if request.detector_mask is not None:
            if request.detector_mask.shape != (height, width) or request.detector_mask.dtype != np.uint8:
                raise ValueError('detector_mask must be uint8 with the image dimensions')
            seeds = (request.detector_mask > 0) & domain

        # Sample a ring outside the text box; quantized mode avoids a few glyphs
        # shifting the estimated colour. Require tight colour consensus, not
        # brightness alone, before permitting a constant-colour fill.
        ring = _dilate(inside, max(3, min(12, size // 2))) & ~inside.astype(bool)
        ring &= ~_dilate(seeds, 2)
        samples = image[ring]
        if len(samples) < 16:
            border = np.zeros((height, width), bool)
            border[[0, -1], :] = True
            border[:, [0, -1]] = True
            samples = image[border & ~seeds]
        if len(samples):
            bins = samples.astype(np.int32) // 16
            keys = bins[:, 0] * 256 + bins[:, 1] * 16 + bins[:, 2]
            mode = np.bincount(keys, minlength=4096).argmax()
            background = np.median(samples[keys == mode], axis=0).astype(np.uint8)
            consensus = float(np.mean(np.max(np.abs(samples.astype(np.int16) - background), axis=1) <= 10))
        else:
            background = np.array([255, 255, 255], np.uint8)
            consensus = 0.0
        has_seeds = bool(np.any(seeds))
        flat_hint = consensus >= .97
        local_reference = False
        if flat_hint and has_seeds:
            # A coloured caption can sit entirely inside a white detection
            # margin. Its paper and dark ink then form one foreground blob.
            nearby = image[_dilate(seeds, 4) & ~_dilate(seeds, 2)]
            if len(nearby) >= 8:
                paper = np.median(nearby, axis=0).astype(np.int16)
                if (np.max(np.abs(paper - background)) > 12
                        and np.mean(np.max(np.abs(image[seeds] - paper), axis=1) > 12) > .5):
                    # Bright paper around dark letters can be their printed
                    # white keyline. Leave that case to the contour check.
                    local_reference = (np.min(background) >= 235 and np.min(paper) < 235
                                       and np.max(np.abs(nearby - paper)) <= 1)
                    flat_hint = local_reference
                    if local_reference:
                        background = paper
        colour_distance = np.max(np.abs(image.astype(np.int16) - background), axis=2)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if flat_hint:
            candidates = colour_distance > 12
        else:
            # Both white-on-black and black-on-white strokes; colour residuals
            # also retain chromatic letters with similar luminance to the art.
            kernel = _ellipse(max(2, min(15, size // 3)))
            light = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
            dark = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
            local = gaussian_background(image, max(1., size / 6))
            chromatic = np.max(np.abs(image.astype(np.int16) - local.astype(np.int16)), axis=2)
            contrast = gray.astype(np.int16) - cv2.cvtColor(local, cv2.COLOR_BGR2GRAY)
            dark_pixels, light_pixels = contrast < -6, contrast > 6
            colour_pixels = np.zeros(gray.shape, bool)
            if np.any(seeds):
                # Do not mistake the opposite-colour halo around a stroke for
                # another stroke. Keep both polarities when seeds support both.
                if np.mean(dark_pixels[seeds]) > .75:
                    light_pixels[:] = False
                elif np.mean(light_pixels[seeds]) > .75:
                    dark_pixels[:] = False
                foreground = np.median(image[seeds], axis=0)
                foreground_distance = np.max(np.abs(image.astype(np.float32) - foreground), axis=2)
                local_distance = np.max(np.abs(local.astype(np.float32) - foreground), axis=2)
                colour_pixels = (chromatic >= 24) & (foreground_distance < local_distance * .7)
            candidates = ((light >= 18) & light_pixels) | ((dark >= 18) & dark_pixels) | colour_pixels
            if np.any(seeds):
                candidates &= _dilate(seeds, max(3, min(8, round(size * .3))))
            else:
                candidates &= inside.astype(bool)

        count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), connectivity=8)
        selected = seeds.copy()
        near = _dilate(seeds, 1)
        seeded_labels = set(np.unique(labels[near])) if has_seeds else set()
        inside_labels = set(np.unique(labels[inside > 0]))
        accepted, bounded = np.zeros(count, bool), np.zeros(count, bool)
        small_components = 0
        for number in range(1, count):
            x, y, w, h, area = stats[number]
            touching = x == 0 or y == 0 or x + w == width or y + h == height
            supported = number in seeded_labels
            if flat_hint:
                # Never follow a border-connected hair/balloon outline. Keep
                # bounded detector support even if a glyph touches that outline.
                if not supported and area < max(3, size * .3):
                    small_components += int(number in inside_labels)
                    continue
                if touching or area > width * height * .5 or (has_seeds and area > size * size * 2):
                    bounded[number] = True
                elif supported or (not local_reference and number in inside_labels):
                    accepted[number] = True
            elif has_seeds:
                if supported:
                    accepted[number] = True
            elif not touching and area >= max(4, size * .3) and area < width * height * .3:
                accepted[number] = True
        selected |= accepted[labels]
        selected |= bounded[labels] & _dilate(seeds, 3)

        radius = max(1, min(3, round(size * .075)))
        erase = _dilate(selected, radius)
        # Flat-fill only if the unmasked inner area also agrees. White margins
        # around screentones or coloured artwork must not cause white paint.
        remaining = _dilate(inside, radius + 2) & ~erase
        inner_consensus = float(np.mean(colour_distance[remaining] <= 10)) if np.any(remaining) else 0.
        fill = None
        if flat_hint and (local_reference or inner_consensus >= .98) and small_components < 8:
            # White margins can agree with pale paper within the coarse colour
            # threshold. Sample immediately outside the strokes before painting.
            collar = _dilate(erase, radius + 1) & ~erase
            local = image[collar]
            if (len(local) >= 8 and np.max(np.ptp(local, axis=0)) <= 1
                    and np.max(np.abs(local[0].astype(np.int16) - background)) <= 10):
                fill = tuple(int(v) for v in np.median(local, axis=0))
        if fill is None and flat_hint and np.any(seeds):
            # Ring looked flat, but inner artwork did not: retract unseeded
            # candidates before inpainting (e.g. black hair inside a white box).
            selected &= _dilate(seeds, max(3, min(8, round(size * .3))))
            erase = _dilate(selected, radius)
        layout = _dilate(selected, 4)
        outline_pixels = 0
        outline_ratio = None
        if has_seeds and (fill is None or min(fill) < 237):
            detected = _white_outline(image, seeds, size)
            if detected is not None:
                outline, outline_ratio = detected
                # Include the antialiased outside edge in the repair only.
                edge = _dilate(outline, 1)
                outline_pixels = int(np.count_nonzero(edge & ~erase))
                erase |= edge
                if outline_pixels:
                    fill = None  # the old flat-colour collar no longer bounds this mask
                if outline_pixels:
                    fill = None  # the old flat-colour collar no longer bounds this mask
        return validate_result(MaskResult(
            erase.astype(np.uint8) * 255, layout.astype(np.uint8) * 255, fill,
            {'algorithm': self.version, 'detector_guided': bool(np.any(seeds)),
             'background': list(map(int, background)), 'ring_consensus': consensus,
             'inner_consensus': inner_consensus, 'strategy': 'flat' if fill is not None else 'texture',
             'erase_pixels': int(np.count_nonzero(erase)), 'edge_radius': radius,
             'extra_outline_pixels': outline_pixels}, source_outline_ratio=outline_ratio,
        ), (height, width))
