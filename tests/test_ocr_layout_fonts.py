from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MAIN_DIR = ROOT / "comic-translate-ai" / "main"
if str(MAIN_DIR) not in sys.path:
    sys.path.insert(0, str(MAIN_DIR))

from onnx_baberu_ocr import OnnxBaberuOcr, Vocab, preprocess
from text_style import choose_font_style, choose_layout_direction
from vertical_typesetter import VerticalTypesetter


class BaberuWrapperTests(unittest.TestCase):
    def test_preprocess_matches_published_input_shape(self):
        output = preprocess(Image.new("RGB", (48, 96), "white"))
        self.assertEqual(output.shape, (1, 3, 224, 224))
        self.assertEqual(output.dtype, np.float32)

    def test_model_completeness_accepts_int4_or_fp16_vision(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            for relative in (
                "onnx/vision_int4.onnx",
                "onnx/decoder_prefill_int8.onnx",
                "onnx/decoder_step_int8.onnx",
                "tokenizer/vocab.json",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertTrue(OnnxBaberuOcr.is_complete(root))

    def test_character_vocab_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            vocab_path = Path(temporary_dir) / "vocab.json"
            vocab_path.write_text(json.dumps(["日", "本", "語"]), encoding="utf-8")
            vocab = Vocab(vocab_path)
            self.assertEqual(vocab.decode([1, 4, 5, 6, 2]), "日本語")


class LayoutSelectionTests(unittest.TestCase):
    def test_direction_preserves_detector_and_corrects_strong_geometry(self):
        self.assertEqual(choose_layout_direction(True, 80, 200, "日本語"), 1)
        self.assertEqual(choose_layout_direction(True, 300, 80, "旁白"), 0)
        self.assertEqual(choose_layout_direction(False, 55, 180, "日本語です"), 1)
        self.assertEqual(choose_layout_direction(False, 300, 55, "日本語です"), 0)

    def test_style_rules_keep_normal_dialogue_unaccented(self):
        common = dict(direction=1, width=100, height=220, non_bubble=False)
        self.assertEqual(choose_font_style("普通の会話", emphasis=0.2, **common), "dialogue")
        self.assertEqual(choose_font_style("本当！？", emphasis=0.2, **common), "radiating")
        self.assertEqual(choose_font_style("ドン", emphasis=0.5, **(common | {"non_bubble": True})), "sfx")
        self.assertEqual(choose_font_style("大事な話", emphasis=0.55, **common), "bold_dialogue")
        self.assertEqual(choose_font_style("うれしい〜〜♪", emphasis=0.2, **common), "cute")


class FontFallbackAndDirectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cn = ROOT / "comic-translate-ai" / "font_file" / "CN"
        cls.dialogue = cn / "SourceHanSansSC-Medium-2.otf"
        cls.klee = cn / "special" / "KleeOne-Regular.ttf"
        cls.typesetter = VerticalTypesetter(
            {
                "dialogue": str(cls.dialogue),
                "cute": str(cls.klee),
            },
            18,
        )

    def test_explicit_horizontal_is_not_overridden_by_box_shape(self):
        image = Image.new("RGB", (240, 240), "white")
        self.typesetter.draw_text(
            image,
            [80, 30, 145, 205],
            "明确横排",
            "dialogue",
            direction=0,
        )
        self.assertEqual(self.typesetter.last_direction, "horizontal")

    def test_missing_glyph_falls_back_to_source_han(self):
        fallback_char = next(
            char
            for char in "龘齉鬱爨灶炉饭馒饺鲜艳"
            if not self.typesetter._font_supports(str(self.klee), char)
            and self.typesetter._font_supports(str(self.dialogue), char)
        )
        self.assertEqual(
            self.typesetter._font_path_for_char("cute", fallback_char),
            str(self.dialogue),
        )
        self.assertEqual(self.typesetter._style_for_text("cute", fallback_char), "dialogue")


if __name__ == "__main__":
    unittest.main()
