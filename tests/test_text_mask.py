import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from comic_translate_core.text_mask import AdaptiveTextMask, MaskRequest, MaskResult, validate_result
from comic_translate_core.mask_debug import main, evaluate_masks


class TextMaskTests(unittest.TestCase):
    def fixture(self, background, foreground):
        image = np.empty((128, 192, 3), np.uint8)
        image[:] = background
        truth = np.zeros(image.shape[:2], np.uint8)
        cv2.putText(truth, 'Hi', (55, 85), cv2.FONT_HERSHEY_SIMPLEX, 1.5, 255, 4, cv2.LINE_AA)
        alpha = truth[..., None].astype(np.float32) / 255
        image = np.rint(image * (1-alpha) + np.array(foreground) * alpha).astype(np.uint8)
        seed = cv2.erode((truth > 200).astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
        return image, truth, seed

    def test_flat_black_white_and_coloured_backgrounds_keep_actual_colour(self):
        for background, foreground in [((255,)*3, (0,)*3), ((8,)*3, (248,)*3),
                                        ((40, 90, 180), (210, 40, 60))]:
            with self.subTest(background=background):
                image, truth, seed = self.fixture(background, foreground)
                before = image.copy()
                result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
                self.assertEqual(result.fill_color, background)
                self.assertGreater(evaluate_masks(result.erase_mask, (truth > 20).astype(np.uint8))['recall'], .98)
                self.assertTrue(np.array_equal(image, before))
                self.assertLess(np.count_nonzero(result.erase_mask), image.shape[0]*image.shape[1]*.15)

    def test_hair_overlap_bounds_growth_instead_of_following_connected_art(self):
        image, truth, seed = self.fixture((215,)*3, (0,)*3)
        for x in range(20, 180, 7):
            cv2.line(image, (x, 0), (x+20, 127), (30,)*3, 2)
        image[truth > 100] = 0
        result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
        self.assertIsNone(result.fill_color)
        limit = cv2.dilate(seed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25,25)))
        self.assertFalse(np.any((result.erase_mask > 0) & (limit == 0)))
        self.assertGreater(evaluate_masks(result.erase_mask, (truth > 100).astype(np.uint8))['recall'], .9)

    def test_screentone_and_colour_gradients_use_texture_repair(self):
        for style in ('dots', 'colour'):
            image, truth, seed = self.fixture((240,)*3, (0,)*3)
            if style == 'dots':
                for y in range(2, 128, 6):
                    for x in range(2, 192, 6):
                        image[y, x] = 40
            else:
                image[:, :, 0] = np.arange(192)[None, :]
                image[:, :, 1] = np.arange(128)[:, None]
            image[truth > 100] = 0
            result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
            self.assertIsNone(result.fill_color, style)
            self.assertEqual(np.count_nonzero(result.erase_mask[:25]), 0)
            self.assertGreater(evaluate_masks(result.erase_mask, (truth > 100).astype(np.uint8))['recall'], .9)

    def test_no_detector_and_edge_box_and_validation(self):
        image, truth, seed = self.fixture((255,)*3, (0,)*3)
        result = AdaptiveTextMask().generate(MaskRequest(image, (0, 0, 120, 100), None, 32))
        self.assertGreater(evaluate_masks(result.erase_mask, (truth > 20).astype(np.uint8))['recall'], .98)
        with self.assertRaises(ValueError):
            validate_result(MaskResult(np.ones((2,2), np.uint8), np.zeros((2,2), np.uint8)), (2,2))
        with self.assertRaises(ValueError):
            AdaptiveTextMask().generate(MaskRequest(image, (0,0,10,10), seed[:3], 32))

    def test_standalone_command_outputs_masks_and_metrics(self):
        image, truth, seed = self.fixture((255,)*3, (0,)*3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.fromarray(image).save(root/'input.png')
            Image.fromarray(seed).save(root/'seed.png')
            Image.fromarray(truth).save(root/'truth.png')
            self.assertEqual(main([str(root/'input.png'), '--box', '50', '45', '110', '95',
                '--detector', str(root/'seed.png'), '--reference-mask', str(root/'truth.png'),
                '--output', str(root/'result')]), 0)
            for name in ('erase.png', 'layout.png', 'overlay.png', 'diagnostics.json'):
                self.assertTrue((root/'result'/name).is_file())
