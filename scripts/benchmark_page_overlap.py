"""Offline batch-barrier vs streaming comparison using real local models.

No API is called. Each nonblank page uses a configurable simulated API delay.
Inputs are existing native PNG pages; PDF rasterization is not measured.
"""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'comic-translate-ai/main')]

from PIL import Image
from PySide6.QtWidgets import QApplication
from comic_translator_pipeline import ComicTranslatorPipeline
from comic_translate_desktop import config as app_config
from comic_translate_desktop.worker import BatchWorker


@contextmanager
def batch_barrier(pages, prepare, translate, *, capacity, cancelled, close_preparation):
    """Reproduce the preceding scheduler with the same stage callbacks."""
    with ThreadPoolExecutor(max_workers=capacity) as pool:
        def batches():
            for offset in range(0, len(pages), capacity):
                batch = deque()
                for page in pages[offset:offset + capacity]:
                    prepared = prepare(page)
                    if prepared is not None:
                        batch.append((page, prepared))
                    prepared = None
                translated = deque((page, prepared, pool.submit(translate, page, prepared))
                                   for page, prepared in batch)
                batch.clear()
                for _page, _prepared, future in translated:
                    future.result()
                _prepared = future = None
                while translated:
                    yield translated.popleft()
        iterator = batches()
        try:
            yield iterator
        finally:
            iterator.close()
            close_preparation()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--pages', nargs='+', type=int, default=[1, 2, 3])
    parser.add_argument('--api-delay', type=float, default=2.)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    inputs, known_texts = [], {}
    for number in args.pages:
        stem = f'page_{number:04d}'
        source = args.project / 'source' / f'{stem}.png'
        layout = args.project / 'translated_layout' / f'{stem}_layout.json'
        if not source.exists():
            source, layout = args.project / f'{stem}.png', args.project / f'{stem}_layout.json'
        inputs.append(source)
        known_texts.update({b.get('source_text', ''): b.get('text', '')
                           for b in json.loads(layout.read_text(encoding='utf-8'))})
    fonts = {style: str(app_config.AI_ROOT / path) for style, path in app_config.FONT_DEFAULTS.items()}
    pipeline = ComicTranslatorPipeline(
        det_model_path=str(app_config.MODELS_ROOT / 'text_detector/comic-text-detector.onnx'),
        lama_path=str(app_config.MODELS_ROOT / 'manga-lama/lama-manga-dynamic.onnx'),
        font_map=fonts, font_size=16, use_gpu=True, watermark_enabled=False,
        translation_model='offline-benchmark', multimodal=False, multimodal_font_probe=False)
    if 'CUDAExecutionProvider' not in pipeline.inpainter.onnx_session.get_providers():
        raise RuntimeError('CUDA must be active for this GPU comparison')
    def offline_translation(texts, _image):
        if any(text.strip() for text in texts):
            time.sleep(max(0., args.api_delay))
        return [known_texts.get(text) or '示例译文' if text.strip() else '' for text in texts]
    pipeline.translate_page_batch = offline_translation
    (ROOT / 'tmp').mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='overlap-benchmark-', dir=ROOT / 'tmp'))
    # Warm native inference shapes and fonts before either timed mode.
    warm = pipeline.prepare_comic_page(str(inputs[0]))
    pipeline.finish_comic_page(output / 'warmup.png', warm,
                              [known_texts.get(text) or '示例译文' if text.strip() else '' for text in warm['ocr_texts']])
    del warm
    report = dict(scope='native_image_decode_ocr_simulated_api_repair_typeset_save',
                  simulated_api_seconds=args.api_delay, capacity=4, results=[])
    hashes = []
    for mode in ('batch_barrier', 'streaming'):
        worker = BatchWorker(inputs, output / mode,
                             dict(max_workers=4, resume_enabled=False, watermark_enabled=False,
                                  font_size=16, font_map=fonts, multimodal=False,
                                  multimodal_font_probe=False, translation_model='offline-benchmark'),
                             pipeline=pipeline)
        completions, summaries = [], []
        started = time.perf_counter()
        worker.page_progress.connect(lambda done, total: completions.append(time.perf_counter() - started) if done else None)
        worker.finished.connect(lambda *values: summaries.append(values))
        with patch('comic_translate_desktop.worker.PagePrefetch', batch_barrier) if mode == 'batch_barrier' else nullcontext():
            worker.run()
        elapsed = time.perf_counter() - started
        if summaries != [(len(inputs), 0)]:
            raise RuntimeError(f'Benchmark failed: {mode}: {summaries}')
        digest = []
        for path in inputs:
            with Image.open(output / mode / f'{path.stem}_translated.png') as image:
                digest.append((image.size, hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()))
        hashes.append(digest)
        record = dict(mode=mode, seconds=elapsed, first_page_seconds=completions[0], page_completions=completions)
        report['results'].append(record)
        print(json.dumps(record), flush=True)
    report['identical_output_pixels'] = hashes[0] == hashes[1]
    if not report['identical_output_pixels']:
        raise AssertionError('Scheduling changed output pixels')
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding='utf-8')
    app.processEvents()


if __name__ == '__main__':
    main()
