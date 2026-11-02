"""Native-resolution filters used only to estimate text-mask backgrounds."""
import cv2
import numpy as np


def gaussian_background(image, sigma):
    """Accelerate large uint8 Gaussian kernels without changing their footprint.

    Preserve OpenCV's 8-bit coefficient quantization and half-up output rounding.
    Two filter2D passes use its DFT implementation for long kernels. Rounding the
    result to the 1/65536 grid removes DFT noise before converting back to uint8.
    No input/output image is resized, and no floating-point kernel approximation
    replaces the original fixed-point coefficients.
    """
    if sigma < 12 or image.dtype != np.uint8:
        return cv2.GaussianBlur(image, (0, 0), sigma)
    length = round(sigma * 6 + 1) | 1
    coefficients = cv2.getGaussianKernel(length, sigma).ravel()
    weights = np.zeros(length, np.float64)
    residual = 0.
    for index in range(length // 2):
        adjusted = coefficients[index] * 256 + residual
        quantized = round(adjusted)
        residual = adjusted - quantized
        weights[index] = weights[-index - 1] = quantized
    weights[length // 2] = 256 - 2 * weights[:length // 2].sum()
    weights /= 256
    filtered = cv2.filter2D(image, cv2.CV_64F, weights.reshape(1, -1))
    cv2.filter2D(filtered, -1, weights.reshape(-1, 1), dst=filtered)
    filtered *= 65536
    np.rint(filtered, out=filtered)
    filtered += 32768
    np.floor_divide(filtered, 65536, out=filtered)
    return filtered.astype(np.uint8)
