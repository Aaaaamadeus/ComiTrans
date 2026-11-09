"""python -m comic_translate_core.mask_debug --help; no model/API required."""
import argparse
import importlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .text_mask import AdaptiveTextMask, MaskRequest, validate_result


def evaluate_masks(prediction, reference):
    if prediction.shape != reference.shape:
        raise ValueError('reference mask dimensions must match the image')
    predicted, expected = prediction > 0, reference > 0
    intersection = int(np.count_nonzero(predicted & expected))
    union = int(np.count_nonzero(predicted | expected))
    return {'iou': intersection / union if union else 1.,
            'precision': intersection / max(1, int(predicted.sum())),
            'recall': intersection / max(1, int(expected.sum()))}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Test a text-mask component without OCR, translation or LaMa.')
    parser.add_argument('image', type=Path)
    parser.add_argument('--box', nargs=4, type=int, required=True, metavar=('X1', 'Y1', 'X2', 'Y2'))
    parser.add_argument('--font-size', type=int, default=16)
    parser.add_argument('--detector', type=Path)
    parser.add_argument('--reference-mask', type=Path)
    parser.add_argument('--provider', help='Trusted installed module:factory implementing generate(MaskRequest)')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    with Image.open(args.image) as source:
        rgb = np.array(source.convert('RGB'))
    detector = None
    if args.detector:
        with Image.open(args.detector) as source:
            detector = np.array(source.convert('L'))
    generator = AdaptiveTextMask()
    if args.provider:
        module, factory = args.provider.split(':', 1)
        generator = getattr(importlib.import_module(module), factory)()
    result = validate_result(generator.generate(MaskRequest(
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), tuple(args.box), detector, args.font_size)), rgb.shape[:2])
    report = dict(result.diagnostics)
    report['source_outline_ratio'] = result.source_outline_ratio
    erase = result.erase_mask
    fallback = getattr(result, 'box_fill_mask', None)
    final = erase if fallback is None else np.maximum(erase, fallback)
    report['box_fill_pixels'] = int(np.count_nonzero(fallback)) if fallback is not None else 0
    report['final_pixels'] = int(np.count_nonzero(final))
    if args.reference_mask:
        with Image.open(args.reference_mask) as source:
            reference = np.array(source.convert('L'))
            # The reference annotates text pixels, so it grades the detector mask.
            # The whole-box fallback is a repair scope, not a text mask; report it
            # separately instead of inflating the same score.
            report['metrics'] = evaluate_masks(erase, reference)
            report['metrics_final_scope'] = evaluate_masks(final, reference)
    args.output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(erase).save(args.output / 'erase.png')
    if fallback is not None:
        Image.fromarray(fallback).save(args.output / 'box_fill.png')
    Image.fromarray(final).save(args.output / 'final_mask.png')
    Image.fromarray(result.layout_mask).save(args.output / 'layout.png')
    # Three-colour overlay: detector mask red, fallback-only blue, overlap magenta.
    red = erase > 0
    blue = (fallback > 0) if fallback is not None else np.zeros_like(red)
    overlay = rgb.copy()
    for selection, tint in ((red & blue, [255, 0, 255]),
                            (red & ~blue, [255, 0, 80]),
                            (~red & blue, [40, 160, 255])):
        if np.any(selection):
            overlay[selection] = ((rgb[selection].astype(np.uint16) + tint) // 2).astype(np.uint8)
    Image.fromarray(overlay).save(args.output / 'overlay.png')
    (args.output / 'diagnostics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
