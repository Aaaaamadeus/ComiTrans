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
    if args.reference_mask:
        with Image.open(args.reference_mask) as source:
            report['metrics'] = evaluate_masks(result.erase_mask, np.array(source.convert('L')))
    args.output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(result.erase_mask).save(args.output / 'erase.png')
    Image.fromarray(result.layout_mask).save(args.output / 'layout.png')
    overlay = rgb.copy()
    selected = result.erase_mask > 0
    overlay[selected] = ((rgb[selected].astype(np.uint16) + [255, 0, 80]) // 2).astype(np.uint8)
    Image.fromarray(overlay).save(args.output / 'overlay.png')
    (args.output / 'diagnostics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
