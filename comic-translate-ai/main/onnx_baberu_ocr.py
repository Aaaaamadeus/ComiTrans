"""Baberu OCR 的轻量 ONNX Runtime 封装。

推理流程改编自模型作者发布的 ``onnx_infer.py``：
https://huggingface.co/genshiai-daichi/baberu-ocr/blob/main/onnx_infer.py
Baberu OCR 以 Apache-2.0 许可证发布。本文件只依赖 numpy、Pillow 与
onnxruntime，不引入 PyTorch/transformers。
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image


_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_PAST_NAMES = [f"past_k{i}" for i in range(6)] + [f"past_v{i}" for i in range(6)]


def preprocess(image: Image.Image) -> np.ndarray:
    image = image.convert("RGB").resize((224, 224), Image.Resampling.BICUBIC)
    pixels = (np.asarray(image, dtype=np.float32) / 255.0 - _MEAN) / _STD
    return pixels.transpose(2, 0, 1)[None].astype(np.float32)


class Vocab:
    """Baberu 的字符级词表。0..3 为特殊 token，字符从 4 开始。"""

    def __init__(self, vocab_path: str | Path):
        charset = json.loads(Path(vocab_path).read_text(encoding="utf-8"))
        self.id_to_char = {0: "", 1: "", 2: "", 3: ""}
        self.id_to_char.update({index + 4: char for index, char in enumerate(charset)})
        self.bos = 1
        self.eos = 2
        self.content_ids = {
            index + 4
            for index, char in enumerate(charset)
            if len(char) == 1
            and char not in "ーｰ〜~"
            and unicodedata.category(char)[0] in "LN"
        }

    def decode(self, token_ids) -> str:
        return "".join(self.id_to_char.get(int(token_id), "") for token_id in token_ids if token_id >= 4)


class OnnxBaberuOcr:
    REQUIRED_FILES = (
        "onnx/decoder_prefill_int8.onnx",
        "onnx/decoder_step_int8.onnx",
        "tokenizer/vocab.json",
    )

    @classmethod
    def is_complete(cls, model_dir: str | Path) -> bool:
        root = Path(model_dir)
        has_vision = (root / "onnx/vision_fp16.onnx").exists() or (
            root / "onnx/vision_int4.onnx"
        ).exists()
        return has_vision and all((root / relative).exists() for relative in cls.REQUIRED_FILES)

    def __init__(
        self,
        model_dir: str | Path,
        device: str = "cpu",
        max_new_tokens: int = 128,
    ):
        root = Path(model_dir)
        if not self.is_complete(root):
            raise FileNotFoundError(f"Baberu OCR ONNX 模型不完整: {root}")

        onnx_dir = root / "onnx"
        vision_name = (
            "vision_fp16.onnx"
            if (onnx_dir / "vision_fp16.onnx").exists()
            else "vision_int4.onnx"
        )
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # 当前发布的 int4 视觉模型在 CPU EP 上兼容性最好。若使用 fp16 版本且
        # CUDA EP 可用，则优先让 ORT 尝试 GPU，失败时自动回退 CPU。
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if device == "cuda" and vision_name == "vision_fp16.onnx"
            else ["CPUExecutionProvider"]
        )

        def make_session(path: Path):
            try:
                return ort.InferenceSession(str(path), options, providers=providers)
            except Exception:
                return ort.InferenceSession(
                    str(path), options, providers=["CPUExecutionProvider"]
                )

        self.vision = make_session(onnx_dir / vision_name)
        self.decoder_prefill = make_session(onnx_dir / "decoder_prefill_int8.onnx")
        self.decoder_step = make_session(onnx_dir / "decoder_step_int8.onnx")
        self.vocab = Vocab(root / "tokenizer/vocab.json")
        self.max_new_tokens = max(16, int(max_new_tokens))
        self.vision_name = vision_name

    def __call__(
        self,
        image_or_path,
        repetition_penalty: float = 1.2,
        max_content_run: int = 12,
    ) -> str:
        if isinstance(image_or_path, (str, Path)):
            with Image.open(image_or_path) as opened:
                image = opened.convert("RGB")
        elif isinstance(image_or_path, Image.Image):
            image = image_or_path
        else:
            raise ValueError("image_or_path 必须是路径或 PIL.Image")

        vocab = self.vocab
        vision_embeds = self.vision.run(
            ["vision_embeds"], {"pixel_values": preprocess(image)}
        )[0]
        outputs = self.decoder_prefill.run(
            None,
            {
                "vision_embeds": vision_embeds,
                "input_ids": np.array([[vocab.bos]], dtype=np.int64),
            },
        )
        logits = outputs[0][0, -1].astype(np.float64)
        present = outputs[1:]
        sequence = [vocab.bos]
        tokens = []
        position = vision_embeds.shape[1] + 1

        for _ in range(self.max_new_tokens):
            if repetition_penalty != 1.0:
                for token_id in set(sequence):
                    score = logits[token_id]
                    logits[token_id] = (
                        score * repetition_penalty
                        if score < 0
                        else score / repetition_penalty
                    )
            if max_content_run and tokens and tokens[-1] in vocab.content_ids:
                last_token = tokens[-1]
                run_length = 0
                for token_id in reversed(tokens):
                    if token_id != last_token:
                        break
                    run_length += 1
                if run_length >= max_content_run:
                    logits[last_token] = -np.inf

            next_token = int(np.argmax(logits))
            if next_token == vocab.eos:
                break
            tokens.append(next_token)
            sequence.append(next_token)
            if len(tokens) >= self.max_new_tokens:
                break

            feed = {
                "input_ids": np.array([[next_token]], dtype=np.int64),
                "position_ids": np.array([[position]], dtype=np.int64),
            }
            feed.update(
                {name: value for name, value in zip(_PAST_NAMES, present)}
            )
            outputs = self.decoder_step.run(None, feed)
            logits = outputs[0][0, -1].astype(np.float64)
            present = outputs[1:]
            position += 1

        return vocab.decode(tokens).strip()
