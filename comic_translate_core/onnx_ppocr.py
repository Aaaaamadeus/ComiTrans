from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image


class OnnxPPOcr:
    """PP-OCRv5 line recognition with RapidOCR's embedded character dictionary.

    Input: BGR, NCHW, height 48, [-1, 1], zero padding; output: NTC CTC.
    Models and the reference format are linked in docs/MULTILINGUAL_OCR.md.
    """

    def __init__(self, model_path: str, device: str = "cpu"):
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"PP-OCR 模型不存在: {model_path}，请运行 scripts/download_ocr_models.py")
        providers = ["CPUExecutionProvider"]
        if device == "cuda" and "CUDAExecutionProvider" in ort.get_available_providers():
            providers.insert(0, "CUDAExecutionProvider")
        try:
            self.session = ort.InferenceSession(str(model_path), providers=providers)
        except Exception:
            if len(providers) == 1:
                raise
            self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0]
        if len(self.input.shape) != 4:
            raise ValueError("PP-OCR 模型输入必须为 NCHW。")
        metadata = self.session.get_modelmeta().custom_metadata_map
        characters = metadata.get("character", "").splitlines()
        if not characters:
            raise ValueError("PP-OCR 模型缺少内置 character 字典，请使用文档指定的 RapidOCR 模型。")
        self.characters = [""] + characters + [" "]
        self.height = self.input.shape[2] if isinstance(self.input.shape[2], int) else 48

    def preprocess(self, image: Image.Image) -> np.ndarray:
        bgr = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        width = max(1, math.ceil(self.height * bgr.shape[1] / bgr.shape[0]))
        fixed_width = self.input.shape[3]
        padded_width = fixed_width if isinstance(fixed_width, int) else max(320, min(4096, width))
        width = min(width, padded_width)
        pixels = cv2.resize(bgr, (width, self.height)).astype(np.float32) / 127.5 - 1.0
        batch = np.zeros((1, 3, self.height, padded_width), dtype=np.float32)
        batch[0, :, :, :width] = pixels.transpose(2, 0, 1)
        return batch

    def recognize(self, image: Image.Image) -> tuple[str, float]:
        scores = self.session.run(None, {self.input.name: self.preprocess(image)})[0]
        if scores.ndim != 3 or scores.shape[2] != len(self.characters):
            raise ValueError("PP-OCR 输出与字符字典不匹配。")
        ids = scores[0].argmax(axis=1)
        keep = np.r_[True, ids[1:] != ids[:-1]] & (ids != 0)
        text = "".join(self.characters[i] for i in ids[keep])
        confidence = float(scores[0].max(axis=1)[keep].mean()) if keep.any() else 0.0
        return text.strip(), confidence
