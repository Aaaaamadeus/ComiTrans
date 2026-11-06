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
from comic_translate_core.inference_control import run_inference
import onnxruntime as ort
from comic_translate_core.onnx_session import create_onnx_session
from PIL import Image


_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_PAST_NAMES = [f"past_k{i}" for i in range(6)] + [f"past_v{i}" for i in range(6)]


def generation_profile(root: Path) -> dict:
    """Unmarked legacy packages keep v2.5.0 decoding exactly as before."""
    path = root / "comitrans-model.json"
    if not path.is_file():
        return {"max_new_tokens": 128, "max_symbol_run": 0}
    profile = json.loads(path.read_text(encoding="utf-8"))
    expected = {"format": 1, "model": "baberu", "revision": "v1.2",
                "max_new_tokens": 256, "max_symbol_run": 16}
    if profile != expected:
        raise ValueError(f"不支持的 Baberu 模型配置: {path}")
    return profile


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
        max_new_tokens: int | None = None,
    ):
        root = Path(model_dir)
        if not self.is_complete(root):
            raise FileNotFoundError(f"Baberu OCR ONNX 模型不完整: {root}")
        profile = generation_profile(root)

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
        session_device = device if vision_name == "vision_fp16.onnx" else "cpu"

        def make_session(path: Path):
            return create_onnx_session(path, session_device, sess_options=options)

        self.vision = make_session(onnx_dir / vision_name)
        self.decoder_prefill = make_session(onnx_dir / "decoder_prefill_int8.onnx")
        self.decoder_step = make_session(onnx_dir / "decoder_step_int8.onnx")
        expected_outputs = ["logits"] + [name.replace("past_", "present_") for name in _PAST_NAMES]
        for session, inputs, outputs in (
            (self.vision, {"pixel_values"}, ["vision_embeds"]),
            (self.decoder_prefill, {"vision_embeds", "input_ids"}, expected_outputs),
            (self.decoder_step, {"input_ids", "position_ids", *_PAST_NAMES}, expected_outputs),
        ):
            if ({item.name for item in session.get_inputs()} != inputs
                    or [item.name for item in session.get_outputs()] != outputs):
                raise ValueError("Baberu ONNX 输入、输出或 KV cache 顺序不兼容，请使用完整的同版本模型包")
        expected_outputs = ["logits"] + [name.replace("past_", "present_") for name in _PAST_NAMES]
        for session, inputs, outputs in (
            (self.vision, {"pixel_values"}, ["vision_embeds"]),
            (self.decoder_prefill, {"vision_embeds", "input_ids"}, expected_outputs),
            (self.decoder_step, {"input_ids", "position_ids", *_PAST_NAMES}, expected_outputs),
        ):
            if ({item.name for item in session.get_inputs()} != inputs
                    or [item.name for item in session.get_outputs()] != outputs):
                raise ValueError("Baberu ONNX 输入、输出或 KV cache 顺序不兼容，请使用完整的同版本模型包")
        self.vocab = Vocab(root / "tokenizer/vocab.json")
        self.max_new_tokens = max(16, int(profile["max_new_tokens"] if max_new_tokens is None else max_new_tokens))
        self.max_symbol_run = profile["max_symbol_run"]
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
        vision_embeds = run_inference(self.vision,
            ["vision_embeds"], {"pixel_values": preprocess(image)}
        )[0]
        outputs = run_inference(self.decoder_prefill,
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
            last = tokens[-1] if tokens else 0
            cap = max_content_run if last in vocab.content_ids else self.max_symbol_run if last > 3 else 0
            if cap:
                last_token = tokens[-1]
                run_length = 0
                for token_id in reversed(tokens):
                    if token_id != last_token:
                        break
                    run_length += 1
                if run_length >= cap:
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
            outputs = run_inference(self.decoder_step, None, feed)
            logits = outputs[0][0, -1].astype(np.float64)
            present = outputs[1:]
            position += 1

        return vocab.decode(tokens).strip()
