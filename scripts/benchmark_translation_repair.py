"""Benchmark native page repair from saved layouts, without OCR/API requests.

Usage: python scripts/benchmark_translation_repair.py PROJECT --pages 1 2 3
PROJECT contains source/ and translated_layout/; a flat copied fixture also works.
"""
import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'comic-translate-ai/main')]

import cv2
import numpy as np
from comic_translator_pipeline import ComicTranslatorPipeline
from manga_lama import MangaLama
from onnx_text_detector import OnnxTextDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--pages', type=int, nargs='+', default=[1, 2, 3])
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cuda')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
    started = perf_counter()
    pipeline.detector = OnnxTextDetector(str(ROOT / 'comic-translate-ai/models/text_detector/comic-text-detector.onnx'),
                                        device=args.device)
    pipeline.inpainter = MangaLama(ROOT / 'comic-translate-ai/models/manga-lama/lama-manga-dynamic.onnx', args.device)
    providers = pipeline.inpainter.onnx_session.get_providers()
    if args.device == 'cuda' and 'CUDAExecutionProvider' not in providers:
        raise RuntimeError('CUDA 未能启用；不能将 CPU 回退结果作为 GPU 基准。')
    report = dict(scope='background_repair_only', providers=providers,
                  model_load_seconds=perf_counter() - started, torch_imported='torch' in sys.modules, pages=[])
    infer = pipeline.inpainter._infer
    for number in args.pages:
        stem = f'page_{number:04d}'
        image_path = args.project / 'source' / f'{stem}.png'
        layout_path = args.project / 'translated_layout' / f'{stem}_layout.json'
        if not image_path.exists():
            image_path = args.project / f'{stem}.png'
            layout_path = args.project / f'{stem}_layout.json'
        pixels = cv2.imdecode(np.fromfile(image_path, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            raise ValueError(f'无法读取页图: {image_path}')
        started = perf_counter()
        _, pipeline.last_detector_mask, _ = pipeline.detector(pixels)
        detection_seconds = perf_counter() - started
        layout = json.loads(layout_path.read_text(encoding='utf-8'))
        boxes = [tuple(b['box']) + (b['direction'], b['style'], b['font_size'], 0)
                 for b in layout if b.get('text')]
        calls = []
        def timed_infer(image, mask):
            started = perf_counter()
            result = infer(image, mask)
            calls.append(perf_counter() - started)
            return result
        pipeline.inpainter._infer = timed_infer
        started = perf_counter()
        result = pipeline.inpaint_bubbles(pixels, boxes)
        elapsed = perf_counter() - started
        unmasked = np.asarray(pipeline.current_erase_mask) == 0
        unchanged = np.array_equal(np.asarray(result)[unmasked], pixels[..., ::-1][unmasked])
        if not unchanged or result.size != (pixels.shape[1], pixels.shape[0]):
            raise AssertionError('修补改变了未遮罩像素或页面尺寸')
        record = dict(page=number, size=result.size, detection_seconds=detection_seconds,
                      repair_seconds=elapsed, tiles=len(calls), inference_seconds=sum(calls),
                      unmasked_pixels_unchanged=unchanged)
        report['pages'].append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
        del result, pixels, unmasked
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
