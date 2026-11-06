"""Text-only CPU adapter for muscgab/manga-ocr-charspot-small.

Preprocessing and vocabulary mapping adapted from the Apache-2.0 reference
implementation, revision 72ca29202673880ca9c67b1c02c107535be4472b.
See docs/licenses/charspot/LICENSE. Model weights have a separate license.
"""
import json
import math
import os
from itertools import product
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from .inference_control import run_inference
from .onnx_session import create_onnx_session


def preprocess(image):
    image = image.convert("RGB")
    width, height = image.size
    # Same grid search and rounding as the released small model.
    low, high = 1e-4, 1000.0
    for _ in range(60):
        scale = (low + high) / 2
        if math.ceil(width * scale / 14) * math.ceil(height * scale / 14) <= 256:
            low = scale
        else:
            high = scale
    cols, rows = math.ceil(width * low / 14), math.ceil(height * low / 14)
    scale = low * 16 / 14
    size = (max(1, min(cols * 16, round(width * scale))),
            max(1, min(rows * 16, round(height * scale))))
    pixels = np.asarray(image.resize(size, Image.Resampling.BICUBIC))
    border = np.concatenate((pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]))
    canvas = np.empty((rows * 16, cols * 16, 3), dtype=np.uint8)
    canvas[:] = np.median(border, axis=0)
    canvas[:size[1], :size[0]] = pixels
    return np.ascontiguousarray(canvas.transpose(2, 0, 1)[None], dtype=np.float32)


class OnnxCharSpot:
    def __init__(self, directory):
        root = Path(directory)
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        if (config["model"], config["version"], config["onnx"], config["vocab"]) != (
                "manga-ocr-charspot-small", "1.0.0", "model.onnx", "vocab.json"):
            raise ValueError(f"Unsupported CharSpot package: {root}")
        chars = json.loads((root / "vocab.json").read_text(encoding="utf-8"))["characters"]
        combos = ["".join(p) for length in (2, 3) for p in product("!?", repeat=length)]
        if len(chars) > config["n_cls"] or config["n_cls"] + len(combos) != config["n_out"]:
            raise ValueError("Incompatible CharSpot vocabulary")
        self.vocab = chars + [""] * (config["n_cls"] - len(chars)) + combos
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(8, os.cpu_count() or 1)
        options.inter_op_num_threads = 1
        self.session = create_onnx_session(root / "model.onnx", "cpu", sess_options=options)
        if ([v.name for v in self.session.get_inputs()] != ["img"] or
                [v.name for v in self.session.get_outputs()] != ["boxes", "scores", "ids", "order"]):
            raise ValueError("Incompatible CharSpot ONNX interface")

    def __call__(self, image):
        ids, order = run_inference(self.session, ["ids", "order"], {"img": preprocess(image)})
        return "".join(self.vocab[i] for i in ids[order])
