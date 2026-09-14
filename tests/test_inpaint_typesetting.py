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

        pipeline = _pipeline(erase_mask)
        self.assertTrue(pipeline._is_simple_bubble_v2(image, erase_mask))

        checker = np.indices((80, 80)).sum(axis=0) % 2
        complex_background = np.repeat((checker * 255).astype(np.uint8)[:, :, None], 3, axis=2)
        self.assertFalse(pipeline._is_simple_bubble_v2(complex_background))

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


if __name__ == "__main__":
    unittest.main()
