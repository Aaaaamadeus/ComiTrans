"""Offline split-detector experiment. All page outputs stay in the private work directory."""

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "comic-translate-ai/main")]
from comic_translate_core.onnx_session import create_onnx_session
from comic_translator_pipeline import ComicTranslatorPipeline
from onnx_text_detector import OnnxTextDetector
from onnx_text_detector import (
    _preprocess_img_np,
    _postprocess_mask_np,
    SegDetectorRepresenter,
    group_output,
    refine_mask,
    REFINEMASK_INPAINT,
)
from onnx_split_detector import line_polygons, text_regions
from manga_lama import MangaLama
from scripts.benchmark_detectors import match
from scripts.benchmark_local_ocr import memory

MODELS = ROOT / "comic-translate-ai/models"
CANDIDATES = {
    "fp32": "detector.onnx",
    "int8": "detector_int8.onnx",
    "small": "detector-v4-s_int8.onnx",
}


def control():
    # Four Japanese lettering panels with exact before/after pixels.
    clean = np.full((768, 640, 3), 246, np.uint8)
    ink = Image.new("L", (640, 768))
    draw = ImageDraw.Draw(ink)
    font = ImageFont.truetype("C:/Windows/Fonts/YuGothM.ttc", 27)
    for i, bg in enumerate([255, 14, 218, 205]):
        y = 14 + 188 * i
        clean[y : y + 166, 26:614] = bg
        if i == 2:
            for yy in range(y, y + 166, 6):
                clean[yy : yy + 2, 26:614:4] = 72
        if i == 3:
            for x in range(60, 400, 12):
                cv2.line(clean, (x, y), (x + 110, y + 163), (68, 68, 68), 2)
        for j, line in enumerate(("明日はきっと晴れる", "ここで待っている")):
            draw.text((130, y + 35 + j * 45), line, 255, font=font)
    alpha = np.asarray(ink, dtype=np.float32) / 255
    fg = np.zeros_like(clean)
    fg[202:368] = 255
    pixels = np.rint(clean * (1 - alpha[..., None]) + fg * alpha[..., None]).astype(np.uint8)
    return pixels, clean, alpha > 0.15


def region_boxes(session, bgr):
    return [box for box, _ in text_regions(session, bgr)]


def split_regions(session, lines, bgr, fixed_boxes=None):
    boxes = region_boxes(session, bgr) if fixed_boxes is None else fixed_boxes
    polygons = line_polygons(lines, bgr) if lines else []
    seed = np.zeros(bgr.shape[:2], np.uint8) if lines else None
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    records = []
    assigned = set()
    for x1, y1, x2, y2 in boxes:
        thickness = []
        for idx, poly in enumerate(polygons):
            cx, cy = poly.mean(axis=0)
            if not (x1 <= cx < x2 and y1 <= cy < y2):
                continue
            assigned.add(idx)
            local = np.zeros((y2 - y1, x2 - x1), np.uint8)
            cv2.fillPoly(local, [(poly - [x1, y1]).astype(np.int32)], 1)
            inside = local.astype(bool)
            if not inside.any():
                continue
            region = gray[y1:y2, x1:x2]
            # Restrict possible ink to contrasting pixels in an assigned line.
            paper = np.median(region[inside])
            seed[y1:y2, x1:x2][inside & (np.abs(region.astype(float) - paper) > 36)] = 255
            thickness.append(min(cv2.minAreaRect(poly)[1]))
        size = max(6, round(np.median(thickness))) if thickness else 16
        records.append((x1, y1, x2, y2, int(y2 - y1 > x2 - x1), "dialogue", size, 0, "unknown"))
    return records, seed, len(polygons), len(assigned)


class PrunedDetector:
    """ogkalu proposes regions; the original seg and det heads retain line and ink evidence."""

    def __init__(self, regions, path, device):
        self.regions = regions
        self.session = create_onnx_session(path, device)
        self.represent = SegDetectorRepresenter(thresh=0.3)

    def __call__(self, bgr):
        h, w = bgr.shape[:2]
        feed, _, dw, dh = _preprocess_img_np(bgr)
        ink, lines = self.session.run(["seg", "det"], {"images": feed})
        mask = cv2.resize(_postprocess_mask_np(ink)[: 1024 - dh, : 1024 - dw], (w, h))
        polys, scores = self.represent((1024, 1024), lines)
        polys = (polys[0][scores[0] > 0.6] * [w / (1024 - dw), h / (1024 - dh)]).astype(np.int32)
        boxes = np.asarray(region_boxes(self.regions, bgr), dtype=np.int32).reshape(-1, 4)
        # ogkalu has no English/Japanese class. Keep region language unknown.
        proposals = (boxes, np.full(len(boxes), 2), np.ones(len(boxes)))
        blocks = group_output(proposals, polys, w, h, mask)
        return mask, refine_mask(bgr, mask, blocks, refine_mode=REFINEMASK_INPAINT), blocks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--backend", choices=["legacy", *CANDIDATES], required=True)
    parser.add_argument("--lines", action="store_true")
    parser.add_argument("--pruned", action="store_true")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    args.work = ROOT / args.work
    if (args.lines and args.pruned) or (args.backend == "legacy" and (args.lines or args.pruned)):
        parser.error("Choose one auxiliary graph and pair it with an ogkalu backend.")
    ref = json.loads((args.work / "annotations.json").read_text(encoding="utf8"))
    assert ref["rights"]
    pages = []
    for page in ref["pages"]:
        path = ROOT / page["source"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == page["sha256"]
        pages.append(cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR))
    sample, clean, truth = control()
    pages.append(sample)
    p = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
    p.cancel_callback = None
    p.source_language = "ja"

    def device_memory():
        if args.device == "cuda":
            usage = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--id=0",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
            )
            return int(usage.strip())

    initial_vram = device_memory()
    p.inpainter = MangaLama(str(MODELS / "manga-lama/lama-manga-dynamic.onnx"), args.device)
    t = time.perf_counter()
    if args.backend == "legacy":
        p.detector = OnnxTextDetector(
            MODELS / "text_detector/comic-text-detector.onnx", device=args.device
        )
        session = p.detector.session
    else:
        session = create_onnx_session(args.work / CANDIDATES[args.backend], args.device)
    lines = (
        create_onnx_session(args.work / "manga_det_v0.2.onnx", args.device) if args.lines else None
    )
    if args.pruned:
        p.detector = PrunedDetector(session, args.work / "old-seg-det.onnx", args.device)
    tag = (
        args.backend + ("-lines" if lines else "-pruned" if args.pruned else "") + "-" + args.device
    )
    result = {
        "backend": tag,
        "providers": session.get_providers(),
        "line_providers": lines.get_providers() if lines else [],
        "pages": [],
    }
    result["detector_load_s"] = time.perf_counter() - t

    def detect(bgr):
        if args.backend == "legacy" or args.pruned:
            boxes = p.detect_bubbles(bgr)
            return [(*b[:8], "unknown") for b in boxes], p.last_detector_mask, None, None
        return split_regions(session, lines, bgr)

    t = time.perf_counter()
    detect(pages[0])
    result["first_detection_s"] = time.perf_counter() - t
    for idx, bgr in enumerate(pages):
        times = []
        for _ in range(3):
            t = time.perf_counter()
            boxes, seed, nlines, assigned = detect(bgr)
            times.append(time.perf_counter() - t)
        p.last_detector_mask = seed
        t = time.perf_counter()
        repaired = p.inpaint_bubbles(bgr, boxes)
        repair_time = time.perf_counter() - t
        repaired.save(args.work / f"split-{tag}-{idx}.png")
        mask = np.asarray(p.current_erase_mask) > 0
        row = {
            "boxes": len(boxes),
            "lines": nlines,
            "assigned_lines": assigned,
            "detect_s": statistics.median(times),
            "repair_s_one_pass": repair_time,
            "masked_pixels": int(mask.sum()),
        }
        if idx < len(ref["pages"]) and "regions" in ref["pages"][idx]:
            labels = [r["box"] for r in ref["pages"][idx]["regions"]]
            metrics = match(labels, [b[:4] for b in boxes])
            row["matches"] = metrics["tp"]
            row["coverage80"] = int(metrics["coverage80"])
            row["matched_region_indices"] = [int(i) for i, _ in metrics["pairs"]]
        if idx == len(ref["pages"]):
            row["controls"] = []
            fixed = []
            for i in range(4):
                y, x = np.where(truth[i * 188 : (i + 1) * 188])
                fixed.append(
                    [
                        int(x.min() - 4),
                        int(y.min() + i * 188 - 4),
                        int(x.max() + 5),
                        int(y.max() + i * 188 + 5),
                    ]
                )
            if args.backend != "legacy" and not args.pruned:
                _, p.last_detector_mask, _, _ = split_regions(session, lines, bgr, fixed)
            records = [(*box, 0, "dialogue", 27, 0, "unknown") for box in fixed]
            rgb = np.asarray(p.inpaint_bubbles(bgr, records))
            mask = np.asarray(p.current_erase_mask) > 0
            for i in range(4):
                sl = slice(i * 188, (i + 1) * 188)
                m, g = mask[sl], truth[sl]
                err = np.abs(rgb[sl].astype(float) - clean[sl, :, ::-1])
                unprinted = (sample[sl] == clean[sl]).all(axis=2)
                row["controls"].append(
                    {
                        "stroke_coverage": float(m[g].mean()),
                        "extra_pixels_per_ink": float((m & ~g).sum() / g.sum()),
                        "ink_mae": float(err[g].mean()),
                        "changed_background_pixels": int(((err.max(axis=2) > 5) & unprinted).sum()),
                    }
                )
        result["pages"].append(row)
    result["process_memory"] = memory()
    result["vram_device_mib_before_after"] = [initial_vram, device_memory()]
    (args.work / f"split-{tag}.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(tag, [(r["boxes"], round(r["detect_s"], 3)) for r in result["pages"]], flush=True)


if __name__ == "__main__":
    main()
