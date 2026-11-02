from __future__ import annotations

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MAIN_DIR = ROOT / "comic-translate-ai" / "main"
if str(MAIN_DIR) not in sys.path:
    sys.path.insert(0, str(MAIN_DIR))

from comic_translator_pipeline import ComicTranslatorPipeline
from vertical_typesetter import VerticalTypesetter
from comic_translate_core.text_mask import AdaptiveTextMask, MaskRequest, MaskResult


class _UnexpectedInpainter:
    def __call__(self, _image, _mask):
        raise AssertionError("纯白气泡不应调用 LaMa")


def _pipeline(detector_mask: np.ndarray) -> ComicTranslatorPipeline:
    pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
    pipeline.last_detector_mask = detector_mask
    pipeline.inpainter = _UnexpectedInpainter()
    return pipeline


class InpaintRegressionTests(unittest.TestCase):
    def test_simple_bubble_uses_background_outside_erase_mask(self):
        image = np.full((80, 80, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (28, 15), (51, 64), (0, 0, 0), thickness=-1)
        erase_mask = np.zeros((80, 80), dtype=np.uint8)
        cv2.rectangle(erase_mask, (25, 12), (54, 67), 255, thickness=-1)

        result = AdaptiveTextMask().generate(MaskRequest(image, (25, 12, 55, 68), erase_mask, 24))
        self.assertEqual(result.fill_color, (255, 255, 255))

        checker = np.indices((80, 80)).sum(axis=0) % 2
        complex_background = np.repeat((checker * 255).astype(np.uint8)[:, :, None], 3, axis=2)
        result = AdaptiveTextMask().generate(MaskRequest(complex_background, (25, 12, 55, 68), erase_mask, 24))
        self.assertIsNone(result.fill_color)

    def test_pipeline_accepts_replacement_component_and_changes_only_its_mask(self):
        image = np.full((80, 80, 3), (90, 100, 110), np.uint8)
        before = image.copy()
        calls = []
        class Replacement:
            def generate(self, request):
                calls.append(request)
                if request.image.flags.writeable:
                    raise AssertionError('component input must be read-only')
                mask = np.zeros(request.image.shape[:2], np.uint8)
                mask[20:25, 20:25] = 255
                return MaskResult(mask, mask.copy(), (10, 20, 30))
        pipeline = _pipeline(np.zeros(image.shape[:2], np.uint8))
        pipeline.text_mask_generator = Replacement()
        result = pipeline.inpaint_bubbles(image, [(20, 20, 60, 60, 0, 'dialogue', 16)])
        output = cv2.cvtColor(np.array(result), cv2.COLOR_RGB2BGR)
        mask = np.array(pipeline.current_erase_mask) > 0
        self.assertEqual(len(calls), 1)
        self.assertEqual(int(mask.sum()), 25)
        self.assertTrue(np.array_equal(output[~mask], before[~mask]))
        self.assertTrue(np.all(output[mask] == [10, 20, 30]))
        self.assertTrue(np.array_equal(image, before))

    def test_verified_gradient_and_screentone_bypass_lama_without_losing_texture(self):
        yy, xx = np.mgrid[:128, :192]
        gradient = np.stack((xx, yy, np.full_like(xx, 230)), axis=2).astype(np.uint8)
        dots = np.full_like(gradient, 235)
        dots[1::6, 1::6] = 20
        mask = np.zeros((128, 192), np.uint8)
        cv2.putText(mask, 'Hi', (55, 85), cv2.FONT_HERSHEY_SIMPLEX, 1.5, 255, 4)
        for background, strategy in ((gradient, 'colour-plane'), (dots, 'periodic-texture')):
            image = background.copy()
            image[mask > 0] = 0
            pipeline = _pipeline(mask)
            output = pipeline.inpaint_bubbles(image, [(50, 45, 110, 95, 0, 'dialogue', 32)])
            actual = cv2.cvtColor(np.array(output), cv2.COLOR_RGB2BGR)
            np.testing.assert_array_equal(actual, background)
            self.assertEqual(pipeline.last_mask_diagnostics[0]['repair_strategy'], strategy)

    def test_white_page_margin_does_not_replace_caption_paper(self):
        box = (48, 40, 128, 104)
        seed = np.zeros((144, 176), np.uint8)
        cv2.putText(seed, 'Hi', (58, 85), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 4)
        for paper in ((246, 249, 250), (165, 180, 200)):
            with self.subTest(paper=paper):
                background = np.full((*seed.shape, 3), 255, np.uint8)
                background[44:99, 52:120] = paper
                source = background.copy()
                source[seed > 0] = 20
                pipe = _pipeline(seed)
                output = pipe.inpaint_bubbles(source, [(*box, 0, 'dialogue', 32)])
                np.testing.assert_array_equal(np.asarray(output), background[..., ::-1])

    def test_printed_white_keyline_on_screentone_is_part_of_the_repair(self):
        background = np.full((150, 186, 3), (158, 168, 177), np.uint8)
        background[1::6, 1::6] = (22, 33, 44)
        seed = np.zeros(background.shape[:2], np.uint8)
        cv2.putText(seed, 'Hi', (58, 85), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 255, 4)
        outline = cv2.dilate(seed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
        source = background.copy()
        source[outline > 0] = 255
        source[seed > 0] = 20
        pipe = _pipeline(seed)
        output = pipe.inpaint_bubbles(source, [(45, 39, 144, 111, 0, 'dialogue', 42)])
        np.testing.assert_array_equal(np.asarray(output), background[..., ::-1])
        self.assertGreater(pipe.last_mask_diagnostics[0]['extra_outline_pixels'], 0)
        self.assertAlmostEqual(pipe.current_outline_ratios[(45, 39, 144, 111)], 7 / 42, delta=.04)
        self.assertEqual(pipe.last_mask_diagnostics[0]['repair_strategy'], 'periodic-texture')

    def test_white_highlight_continuing_past_text_is_not_a_keyline(self):
        background = np.full((100, 120, 3), 145, np.uint8)
        background[::4, ::5] = 35
        background[:58, 42:55] = 255
        seed = np.zeros(background.shape[:2], np.uint8)
        seed[48:66, 45:50] = 255
        image = background.copy()
        image[seed > 0] = 15
        result = AdaptiveTextMask().generate(MaskRequest(image, (36, 40, 65, 78), seed, 32))
        self.assertEqual(result.diagnostics['extra_outline_pixels'], 0)
        self.assertIsNone(result.source_outline_ratio)
        self.assertFalse(np.any(result.erase_mask[:35, 42:55]))

    def test_white_bubble_erases_missed_strokes_and_preserves_nearby_line(self):
        image = np.full((120, 120, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (8, 8), (111, 111), (0, 0, 0), thickness=2)
        cv2.line(image, (27, 35), (48, 35), (0, 0, 0), thickness=7)
        cv2.line(image, (48, 35), (48, 75), (0, 0, 0), thickness=7)
        cv2.line(image, (48, 55), (70, 55), (0, 0, 0), thickness=7)
        cv2.circle(image, (82, 80), 3, (0, 0, 0), thickness=-1)

        detector_mask = np.zeros((120, 120), dtype=np.uint8)
        cv2.line(detector_mask, (29, 35), (48, 35), 255, thickness=1)
        cv2.line(detector_mask, (48, 38), (48, 72), 255, thickness=1)
        cv2.line(detector_mask, (50, 55), (67, 55), 255, thickness=1)

        pipeline = _pipeline(detector_mask)
        result = pipeline.inpaint_bubbles(
            image.copy(),
            [(30, 25, 90, 90, 1, "radiating", 24, 1, "jpn")],
        )
        gray = cv2.cvtColor(np.array(result), cv2.COLOR_RGB2GRAY)

        self.assertGreaterEqual(int(gray[25:90, 30:90].min()), 236)
        self.assertGreaterEqual(int(gray[35, 28]), 236)
        self.assertLess(int(gray[60, 8]), 20)
        self.assertFalse(pipeline.current_outline_ratios)

    def test_overlapping_padded_regions_accumulate_layout_masks(self):
        image = np.full((100, 110, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (41, 35), (44, 48), (0, 0, 0), thickness=-1)
        cv2.rectangle(image, (65, 35), (68, 48), (0, 0, 0), thickness=-1)
        detector_mask = np.zeros((100, 110), dtype=np.uint8)
        detector_mask[35:49, 41:45] = 255
        detector_mask[35:49, 65:69] = 255

        pipeline = _pipeline(detector_mask)
        pipeline.inpaint_bubbles(
            image,
            [
                (30, 25, 45, 55, 1, "dialogue", 14, 1, "jpn"),
                (60, 25, 75, 55, 1, "dialogue", 14, 1, "jpn"),
            ],
        )
        layout_mask = np.array(pipeline.current_mask_image)

        # 第二个框的 15px 扩展区会覆盖这里；合并而非赋值才能保留第一个框。
        self.assertGreater(int(layout_mask[40, 47]), 0)
        self.assertGreater(int(layout_mask[40, 66]), 0)


class TypesettingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        font_path = (
            ROOT
            / "comic-translate-ai"
            / "font_file"
            / "CN"
            / "SourceHanSansSC-Medium-2.otf"
        )
        cls.typesetter = VerticalTypesetter(
            {"dialogue": str(font_path), "radiating": str(font_path)},
            16,
        )

    def test_detected_vertical_font_size_is_a_hard_cap(self):
        image = Image.new("RGB", (420, 420), "white")
        self.typesetter.draw_text(
            image,
            [190, 30, 216, 325],
            "有七轮炉暖炉桌还有大家在就完美了",
            "radiating",
            direction=1,
            target_font_size=24,
        )
        self.assertLessEqual(self.typesetter.last_font_size, 24)

        self.typesetter.draw_text(
            image,
            [80, 210, 118, 374],
            "谢谢那就麻烦准备米饭了",
            "dialogue",
            direction=1,
            target_font_size=13,
        )
        self.assertLessEqual(self.typesetter.last_font_size, 13)

    def test_tiny_region_fallback_respects_detected_font_size(self):
        self.typesetter.draw_text(
            Image.new("RGB", (60, 60), "white"),
            [20, 20, 25, 25],
            "图书馆",
            "dialogue",
            direction=1,
            target_font_size=10,
        )
        self.assertLessEqual(self.typesetter.last_font_size, 10)


if __name__ == "__main__":
    unittest.main()
