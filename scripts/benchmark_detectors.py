"""Offline detector comparison. Private annotation file and overlays remain local."""
import argparse, json, time, sys, statistics, hashlib
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'comic-translate-ai/main')]
from scripts.benchmark_local_ocr import memory
from comic_translate_core.onnx_session import create_onnx_session
from onnx_text_detector import OnnxTextDetector

def overlap(a, b):
    a = np.asarray(a)
    b = np.asarray(b)
    area = np.prod(np.maximum(0, np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2])))
    aa = np.prod(a[2:] - a[:2])
    bb = np.prod(b[2:] - b[:2])
    return (area / max(aa + bb - area, 1), area / max(aa, 1), bb / max(aa, 1))

def match(gold, pred):
    matrix = np.array([[overlap(a, b)[0] for b in pred] for a in gold])
    if not len(pred):
        return {'tp': 0, 'fp': 0, 'fn': len(gold), 'coverage80': 0, 'pairs': []}
    assigned = {}

    def assign(i, seen):
        for j in np.argsort(-matrix[i]):
            j = int(j)
            if matrix[i, j] < 0.5 or j in seen:
                continue
            seen.add(j)
            if j not in assigned or assign(assigned[j], seen):
                assigned[j] = i
                return True
        return False
    for i in range(len(gold)):
        assign(i, set())
    pairs = [(i, j) for j, i in assigned.items()]
    cover = sum((any((c >= 0.8 and ratio <= 4 for _, c, ratio in (overlap(a, b) for b in pred))) for a in gold))
    return {'tp': len(pairs), 'fp': len(pred) - len(pairs), 'fn': len(gold) - len(pairs), 'coverage80': cover, 'pairs': pairs}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--device', default='cpu')
    p.add_argument('--annotations', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--overlays', type=Path)
    args = p.parse_args()
    data = json.loads(args.annotations.read_text(encoding='utf8'))
    assert data['rights']
    pages = []
    for page in data['pages']:
        path = ROOT / page['source']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == page['sha256']
        pages.append(Image.open(path).convert('RGB'))
    t = time.perf_counter()
    legacy = args.model == 'legacy'
    if legacy:
        engine = OnnxTextDetector(ROOT / 'comic-translate-ai/models/text_detector/comic-text-detector.onnx', device=args.device)
        session = engine.session
    else:
        session = create_onnx_session(args.model, args.device)
    load = time.perf_counter() - t
    original_run = session.run
    network_times = []

    def timed_run(*inputs, **kwargs):
        start = time.perf_counter()
        result = original_run(*inputs, **kwargs)
        network_times.append(time.perf_counter() - start)
        return result
    session.run = timed_run

    def infer(im):
        if legacy:
            _, mask, blocks = engine(np.asarray(im)[:, :, ::-1].copy())
            return [{'box': list(map(float, b.xyxy)), 'label': 1, 'score': 1.0} for b in blocks]
        x = np.asarray(im.resize((640, 640), Image.Resampling.BILINEAR), dtype=np.float32).transpose(2, 0, 1)[None] / 255
        labels, boxes, scores = session.run(None, {'images': x, 'orig_target_sizes': np.array([[im.width, im.height]], np.int64)})
        return [{'box': b.tolist(), 'label': int(l), 'score': float(s)} for l, b, s in zip(labels[0], boxes[0], scores[0])]
    t = time.perf_counter()
    infer(pages[0])
    cold = time.perf_counter() - t
    rows = []
    for n, (im, page) in enumerate(zip(pages, data['pages'])):
        times = []
        for _ in range(3):
            t = time.perf_counter()
            detections = infer(im)
            times.append(time.perf_counter() - t)
        network_median = statistics.median(network_times[-3:])
        gold = [r['box'] for r in page['regions']]
        thresholds = {}
        for thr in (0.3, 0.5, 0.7):
            text = [d['box'] for d in detections if d['label'] in (1, 2) and d['score'] >= thr]
            thresholds[str(thr)] = match(gold, text)
        if args.overlays:
            canvas = im.copy()
            draw = ImageDraw.Draw(canvas)
            for i, r in enumerate(gold):
                draw.rectangle(r, outline='#0088ff', width=2)
                draw.text((r[0], r[1]), str(i), fill='#0088ff')
            for d in detections:
                if d['score'] >= 0.5:
                    draw.rectangle(d['box'], outline='#ee2222' if d['label'] else '#00aa00', width=2)
            args.overlays.mkdir(exist_ok=True, parents=True)
            canvas.save(args.overlays / f'{n}.png')
        rows.append({'network_median_s': network_median, 'dimensions': im.size, 'warm_s': times, 'warm_median_s': statistics.median(times), 'thresholds': thresholds, 'detections': detections, 'source': page['source']})
    out = {'model': args.model, 'requested_device': args.device, 'providers': session.get_providers(), 'load_s': load, 'first_inference_s': cold, 'memory': memory(), 'torch_imported': 'torch' in sys.modules, 'pages': rows}
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print({k: v for k, v in out.items() if k != 'pages'}, flush=True)
if __name__ == '__main__':
    main()
