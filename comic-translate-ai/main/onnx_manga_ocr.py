from __future__ import annotations

import json
import re
from pathlib import Path

import jaconv
import numpy as np
import onnxruntime as ort
from PIL import Image
from tokenizers import Tokenizer


class OnnxMangaOcr:
    def __init__(self, model_dir: str, device: str = "cpu", max_length: int = 300):
        model_dir = Path(model_dir)
        self.encoder_path = model_dir / "encoder_model.onnx"
        self.decoder_path = model_dir / "decoder_model.onnx"
        self.tokenizer_path = model_dir / "tokenizer.json"
        self.config_path = model_dir / "config.json"
        if not (self.encoder_path.exists() and self.decoder_path.exists() and self.tokenizer_path.exists()):
            raise FileNotFoundError(f"OCR ONNX 模型不完整: {model_dir}")

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
        try:
            self.encoder = ort.InferenceSession(str(self.encoder_path), providers=providers)
            self.decoder = ort.InferenceSession(str(self.decoder_path), providers=providers)
        except Exception:
            self.encoder = ort.InferenceSession(str(self.encoder_path), providers=["CPUExecutionProvider"])
            self.decoder = ort.InferenceSession(str(self.decoder_path), providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(self.tokenizer_path))

        config = json.loads(self.config_path.read_text(encoding="utf-8")) if self.config_path.exists() else {}
        self.decoder_start_token_id = int(config.get("decoder_start_token_id", 2))
        self.eos_token_id = int(config.get("eos_token_id", 3))
        self.pad_token_id = int(config.get("pad_token_id", 0))
        self.max_length = max_length

    def __call__(self, img_or_path):
        if isinstance(img_or_path, (str, Path)):
            img = Image.open(img_or_path)
        elif isinstance(img_or_path, Image.Image):
            img = img_or_path
        else:
            raise ValueError("img_or_path must be a path or PIL.Image")

        pixel_values = self._preprocess(img)
        encoder_hidden_states = self.encoder.run(None, {"pixel_values": pixel_values})[0]

        ids = [self.decoder_start_token_id]
        for _ in range(self.max_length):
            logits = self.decoder.run(
                None,
                {
                    "input_ids": np.asarray([ids], dtype=np.int64),
                    "encoder_hidden_states": encoder_hidden_states,
                },
            )[0]
            next_id = int(logits[0, -1].argmax())
            ids.append(next_id)
            if next_id == self.eos_token_id:
                break

        text = self.tokenizer.decode(ids, skip_special_tokens=True)
        return post_process(text)

    def _preprocess(self, img: Image.Image) -> np.ndarray:
        img = img.convert("L").convert("RGB")
        img = img.resize((224, 224), Image.BICUBIC)
        arr = np.asarray(img, dtype=np.float32) / 255.0
        arr = (arr - 0.5) / 0.5
        arr = arr.transpose((2, 0, 1))
        return np.expand_dims(arr, 0).astype(np.float32)


def post_process(text: str) -> str:
    text = "".join(text.split())
    text = text.replace("…", "...")
    text = re.sub("[・.]{2,}", lambda x: (x.end() - x.start()) * ".", text)
    text = jaconv.h2z(text, ascii=True, digit=True)
    return text