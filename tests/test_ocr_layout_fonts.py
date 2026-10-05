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
from text_style import FONT_STYLES, choose_font_style, choose_layout_direction
from vertical_typesetter import VerticalTypesetter

NEW_FONT_STYLES = ("seto", "tegaki_851", "lxgw_marker")



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

    def test_new_optional_styles_are_not_auto_selected_yet(self):
        """新增字体风格当前只供手动/多模态指定，自动启发式不得选中它们。"""
        common = dict(direction=1, width=100, height=220)
        for text in ("手書きメモ 注: 重要", "普通の会話", "ドン", "次回につづく", "うれしい〜〜♪", "本当！？"):
            for emphasis in (0.1, 0.3, 0.5, 0.9):
                for non_bubble in (False, True):
                    style = choose_font_style(
                        text,
                        emphasis=emphasis,
                        **(common | {"non_bubble": non_bubble}),
                    )
                    self.assertNotIn(style, NEW_FONT_STYLES, f"{text!r} emphasis={emphasis}")


class OptionalFontRegistrationTests(unittest.TestCase):
    """可选字体新增后：风格表、配置键与字体文件必须一致且可渲染。"""

    @classmethod
    def setUpClass(cls):
        from comic_translate_desktop.config import FONT_DEFAULTS, FONT_KEYS

        cls.defaults = FONT_DEFAULTS
        cls.keys = FONT_KEYS
        cls.ai_root = ROOT / "comic-translate-ai"
        cls.font_map = {style: str(cls.ai_root / path) for style, path in FONT_DEFAULTS.items()}

    def test_new_styles_are_registered_in_every_catalog(self):
        for style in NEW_FONT_STYLES:
            self.assertIn(style, FONT_STYLES)
            self.assertIn(style, self.keys)
            self.assertIn(style, self.defaults)

    def test_every_style_has_a_config_key_and_bundled_font(self):
        self.assertEqual(set(self.keys), set(self.defaults))
        self.assertEqual(set(self.keys), set(FONT_STYLES))
        for style, path in self.defaults.items():
            self.assertTrue((self.ai_root / path).is_file(), f"{style} 缺少字体文件: {path}")

    def test_new_styles_use_distinct_font_files(self):
        self.assertEqual(
            Path(self.defaults["tegaki_851"]).name, "851tegaki_zatsu_normal_0883.ttf"
        )
        self.assertEqual(
            Path(self.defaults["lxgw_marker"]).name, "LXGWMarkerGothic-Regular.ttf"
        )
        self.assertEqual(Path(self.defaults["seto"]).name, "setofont.ttf")

    def test_new_styles_actually_draw_ink(self):
        typesetter = VerticalTypesetter(self.font_map, 18)
        for style in NEW_FONT_STYLES:
            with self.subTest(style=style):
                # 字体必须真的加载成功，而不是被静默换成 ImageFont.load_default()。
                self.assertEqual(
                    Path(getattr(typesetter.fonts[style], "path", "")),
                    Path(self.font_map[style]),
                )
                image = Image.new("RGB", (320, 320), "white")
                typesetter.draw_text(
                    image, [90, 40, 230, 280], "译文手写测试！", style, direction=1
                )
                self.assertIsNotNone(typesetter.last_font_size)
                self.assertLess(
                    image.convert("L").getextrema()[0], 200, f"{style} 未绘制出任何笔画"
                )

    def test_new_styles_fall_back_to_their_family(self):
        """新风格缺字时按登记的家族回退链换字体，而不是画出豆腐块。"""
        cn = ROOT / "comic-translate-ai" / "font_file" / "CN"
        klee = cn / "special" / "KleeOne-Regular.ttf"
        han = cn / "SourceHanSansSC-Medium-2.otf"
        for style, expected in (
            ("seto", "handwriting"),
            ("tegaki_851", "handwriting"),
            ("lxgw_marker", "bold_dialogue"),
        ):
            with self.subTest(style=style):
                # 用缺字更多的 Klee One 代替新字体本身，验证的是登记的回退链。
                typesetter = VerticalTypesetter(
                    {style: str(klee), expected: str(han), "dialogue": str(han)}, 18
                )
                rare = next(
                    char
                    for char in "龘齉鬱爨灶炉饭馒饺鲜艳"
                    if not typesetter._font_supports(str(klee), char)
                    and typesetter._font_supports(str(han), char)
                )
                self.assertEqual(typesetter._style_for_text(style, rare), expected)
                self.assertEqual(
                    typesetter._font_path_for_char(style, rare), str(han)
                )


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
