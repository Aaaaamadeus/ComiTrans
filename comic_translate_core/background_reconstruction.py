"""Conservative native-pixel reconstruction of verifiable local backgrounds."""
import cv2
import numpy as np


MAX_RECONSTRUCTION_PIXELS = 1_000_000


def reconstruct_background(image, mask):
    """Return (image, strategy), or None when context cannot validate a fill.

    No resampling: smooth backgrounds use a fitted colour plane; stationary
    patterns copy agreeing, unmasked pixels at verified integer periods.
    Arbitrary artwork is left to the inpainting backend.
    """
    selected = mask > 0
    height, width = selected.shape
    if not np.any(selected) or height * width > MAX_RECONSTRUCTION_PIXELS:
        return None
    x, y, w, h = cv2.boundingRect(mask)
    if x < 2 or y < 2 or x + w > width - 2 or y + h > height - 2:
        return None
    known = ~selected
    if np.count_nonzero(known) < max(64, height * width * .3):
        return None
    yy, xx = np.mgrid[:height, :width]
    coordinates = np.stack((xx / max(1, width - 1), yy / max(1, height - 1), np.ones_like(xx)), axis=2)
    samples, colours = coordinates[known], image[known]
    step = max(1, len(samples) // 20000)
    coefficients = np.linalg.lstsq(samples[::step], colours[::step], rcond=None)[0]
    plane = coordinates @ coefficients
    error = np.max(np.abs(plane[known] - colours), axis=1)
    # Check every known pixel, not just the fit samples. A line or texture in
    # otherwise smooth margins must veto the smooth fill.
    if np.max(error) <= 3:
        result = image.copy()
        result[selected] = np.clip(np.rint(plane[selected]), 0, 255).astype(np.uint8)
        return result, 'colour-plane'

    periods = []
    rng = np.random.default_rng(0)
    sample_y = rng.integers(0, height, 4096)
    sample_x = rng.integers(0, width, 4096)
    for axis, length in ((1, width), (0, height)):
        for shift in range(2, min(64, length // 3) + 1):
            source_y = sample_y - shift if axis == 0 else sample_y
            source_x = sample_x - shift if axis == 1 else sample_x
            valid_samples = (source_y >= 0) & (source_x >= 0)
            ay, ax = sample_y[valid_samples], sample_x[valid_samples]
            by, bx = source_y[valid_samples], source_x[valid_samples]
            valid_samples = known[ay, ax] & known[by, bx]
            if np.count_nonzero(valid_samples) < 64:
                continue
            differences = image[ay[valid_samples], ax[valid_samples]].astype(np.int16) - image[by[valid_samples], bx[valid_samples]]
            if np.max(np.abs(differences)) > 3:
                continue
            a = [slice(None), slice(None)]
            b = [slice(None), slice(None)]
            a[axis], b[axis] = slice(shift, None), slice(None, -shift)
            a, b = tuple(a), tuple(b)
            valid = known[a] & known[b]
            if np.count_nonzero(valid) < max(64, np.count_nonzero(known) * .25):
                continue
            differences = np.max(np.abs(image[a].astype(np.int16) - image[b]), axis=2)[valid]
            if np.max(differences) <= 3:
                periods.append((axis, shift))
                break
    if not periods:
        return None

    target_y, target_x = np.where(selected)
    low = np.full((len(target_y), 3), 255, np.uint8)
    high = np.zeros_like(low)
    count = np.zeros(len(target_y), np.uint16)
    # Exponentially spaced offsets reach beyond wide text without repeatedly
    # scanning the entire crop for every multiple of a short period.
    for axis, period in periods:
        offset = period
        while offset < image.shape[axis]:
            for sign in (-1, 1):
                source_y = target_y + offset * sign if axis == 0 else target_y
                source_x = target_x + offset * sign if axis == 1 else target_x
                valid = (source_y >= 0) & (source_y < height) & (source_x >= 0) & (source_x < width)
                indexes = np.flatnonzero(valid)
                indexes = indexes[known[source_y[indexes], source_x[indexes]]]
                values = image[source_y[indexes], source_x[indexes]]
                low[indexes] = np.minimum(low[indexes], values)
                high[indexes] = np.maximum(high[indexes], values)
                count[indexes] += 1
            offset *= 2
    if np.any(count < 2) or np.any(high.astype(np.int16) - low > 3):
        return None
    result = image.copy()
    result[selected] = ((high.astype(np.uint16) + low) // 2).astype(np.uint8)
    return result, 'periodic-texture'
