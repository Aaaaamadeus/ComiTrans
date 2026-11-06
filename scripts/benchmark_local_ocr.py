"""Offline OCR evaluation. Each invocation is a fresh process; never calls translation.

Manifest: {"rights": "...", "samples": [{"image": "relative.png", "text": "gold",
"language": "ja", "kind": "real", "tags": ["vertical"], "sha256": "..."}]}.
Keep private images, labels and per-crop outputs outside the repository.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "comic-translate-ai/main")]


def normalize(text):
    return "".join(unicodedata.normalize("NFKC", text).split())


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def memory():
    if os.name != "nt":
        return {"peak_working_set_bytes": None}
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"working_set_bytes": counters.WorkingSetSize,
            "peak_working_set_bytes": counters.PeakWorkingSetSize,
            "peak_commit_bytes": counters.PeakPagefileUsage}


def summarize(rows):
    chars = sum(r["reference_chars"] for r in rows)
    return {"samples": len(rows), "reference_chars": chars,
            "errors": sum(r["errors"] for r in rows),
            "cer": sum(r["errors"] for r in rows) / max(1, chars),
            "exact": sum(r["exact"] for r in rows) / max(1, len(rows)),
            "warm_median_ms": statistics.median(r["warm_median_ms"] for r in rows),
            "warm_total_ms": sum(r["warm_median_ms"] for r in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--backend", choices=["baberu", "manga", "ppocr", "reference", "charspot-reference", "charspot"], required=True)
    parser.add_argument("--reference-script", type=Path)
    parser.add_argument("--language", default="ja")
    parser.add_argument("--threads", type=int, default=0, help="0 = existing ORT defaults; benchmark override only")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from PIL import Image
    import onnxruntime as ort
    data = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not data.get("rights"):
        raise ValueError("Document sample usage permission first")
    samples = [r for r in data["samples"] if r["language"] == args.language]
    images = []
    for sample in samples:
        path = args.manifest.parent / sample["image"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample["sha256"]:
            raise ValueError(f"Changed sample: {path}")
        with Image.open(path) as image:
            images.append(image.convert("RGB"))
    if not images or args.runs < 1:
        raise ValueError("Need samples and at least one warm pass")
    # Independent experiment only: preserve production session policy unless requested.
    original_session = ort.InferenceSession
    if args.threads:
        def session(path, sess_options=None, **kwargs):
            options = sess_options or ort.SessionOptions()
            options.intra_op_num_threads = args.threads
            return original_session(path, sess_options=options, **kwargs)
        ort.InferenceSession = session
    started = time.perf_counter()
    if args.backend == "reference":
        spec = importlib.util.spec_from_file_location("baberu_reference", args.reference_script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        model = module.BaberuOnnxOCR(args.model / "onnx", args.model / "tokenizer", "vision_int4.onnx")
        recognize = model
    elif args.backend == "charspot-reference":
        # Use the reviewed official checkout. Its auto / CUDA path requires Torch.
        sys.path.insert(0, str(args.model.resolve()))
        from manga_ocr_charspot_small import MangaOcrCharspotSmall
        reader = MangaOcrCharspotSmall(model_dir=args.model, backend="onnx")
        model, recognize = reader._b, reader
    elif args.backend == "charspot":
        from comic_translate_core.ocr import create_ocr
        engine = create_ocr({"source_language": "ja", "ocr_backend": "auto", "charspot_ocr_model": args.model})
        assert engine.name == "charspot"
        model = engine.recognizer
        recognize = lambda image: engine.recognize(image, "ja").text
    elif args.backend == "baberu":
        from onnx_baberu_ocr import OnnxBaberuOcr
        model = OnnxBaberuOcr(args.model, "cpu")
        recognize = model
    elif args.backend == "manga":
        from onnx_manga_ocr import OnnxMangaOcr
        model = OnnxMangaOcr(args.model, "cpu")
        recognize = model
    else:
        from comic_translate_core.onnx_ppocr import OnnxPPOcr
        model = OnnxPPOcr(str(args.model), "cpu")
        recognize = lambda image: model.recognize(image)[0]
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    cold_text = recognize(images[0])
    first_seconds = time.perf_counter() - started
    outputs = [[] for _ in samples]
    timings = [[] for _ in samples]
    for _ in range(args.runs):
        for i, image in enumerate(images):
            started = time.perf_counter()
            outputs[i].append(recognize(image))
            timings[i].append((time.perf_counter() - started) * 1000)
    rows = []
    for sample, texts, durations in zip(samples, outputs, timings):
        reference, prediction = normalize(sample["text"]), normalize(texts[0])
        rows.append({**sample, "prediction": texts[0], "stable": len(set(texts)) == 1,
                     "errors": distance(reference, prediction), "reference_chars": len(reference),
                     "exact": reference == prediction, "warm_ms": durations,
                     "warm_median_ms": statistics.median(durations)})
    sessions = {k: v for k, v in vars(model).items() if hasattr(v, "get_providers")}
    result = {"backend": args.backend, "model": str(args.model), "threads": args.threads,
              "ort": ort.__version__, "platform": platform.platform(), "processor": platform.processor(),
              "cold_session_load_s": load_seconds, "first_inference_s": first_seconds,
              "first_prediction": cold_text, "memory": memory(), "vram_bytes": 0,
              "vram_note": "OCR sessions explicitly use CPU; GPU is not requested.",
              "torch_imported": "torch" in sys.modules,
              "providers": {k: v.get_providers() for k, v in sessions.items()},
              "aggregate": summarize(rows),
              "groups": {kind: summarize([r for r in rows if r["kind"] == kind])
                         for kind in sorted(set(r["kind"] for r in rows))},
              "samples": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("samples", "first_prediction")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
