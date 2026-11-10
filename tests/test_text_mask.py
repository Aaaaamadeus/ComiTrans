import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from comic_translate_core.text_mask import AdaptiveTextMask, MaskRequest, MaskResult, validate_result
from comic_translate_core.mask_debug import main, evaluate_masks
from comic_translate_core.restoration import apply_restorations, make_region


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

    def test_jpeg_paper_with_dark_balloon_border_uses_masked_paper_fill(self):
        image, truth, seed = self.fixture((252,) * 3, (8,) * 3)
        cv2.rectangle(image, (46, 41), (115, 101), (25,) * 3, 2)
        image = cv2.imdecode(cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 84])[1], 1)
        result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
        self.assertIsNotNone(result.fill_color)
        self.assertTrue(all(249 <= channel <= 254 for channel in result.fill_color))
        self.assertFalse(result.erase_mask[41, 46:116].any())

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

    def test_missed_punctuation_is_cleared_by_box_fallback(self):
        image, truth, seed = self.fixture((255,)*3, (0,)*3)
        dot = np.zeros(image.shape[:2], np.uint8)
        cv2.circle(dot, (100, 88), 3, 255, -1)
        image[dot > 0] = 0
        result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
        self.assertIsNotNone(result.box_fill_mask)
        self.assertTrue(np.all(result.box_fill_mask[dot > 0] > 0))

    def test_box_fallback_keeps_a_crossing_balloon_border(self):
        image, truth, seed = self.fixture((255,)*3, (0,)*3)
        cv2.line(image, (108, 0), (108, 127), (20,)*3, 3)
        result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
        self.assertIsNotNone(result.box_fill_mask)
        border = np.zeros(image.shape[:2], bool)
        border[40:100, 106:111] = True
        self.assertFalse(np.any(result.box_fill_mask[border] > 0))
        self.assertGreater(result.diagnostics['protected_box_pixels'], 0)

    def test_box_fallback_preserves_sparse_art_outside_the_erase_mask(self):
        image = np.full((120, 160, 3), 248, np.uint8)
        seed = np.zeros(image.shape[:2], np.uint8)
        for x in (45, 60):
            image[46:66, x:x+6] = 10
            seed[46:66, x:x+6] = 255
        art = np.zeros(seed.shape, bool)
        art[78, 73:118:3] = True  # fifteen isolated screen dots
        art[70:73, 108:114] = True
        image[78, 73:118:3] = 20
        image[70:73, 108:114] = 238
        result = AdaptiveTextMask().generate(MaskRequest(image, (32, 30, 126, 93), seed, 16))
        self.assertIsNotNone(result.box_fill_mask)
        self.assertFalse(np.any((result.erase_mask | result.box_fill_mask)[art]))

    def test_box_fallback_requires_its_own_seeds(self):
        image, truth, seed = self.fixture((255,)*3, (0,)*3)
        leak = np.zeros_like(seed)
        cv2.circle(leak, (80, 39), 4, 255, -1)   # inside the dilated domain, above the box
        result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), leak, 32))
        self.assertIsNone(result.box_fill_mask)

    def test_long_vowel_mark_is_cleared_but_a_speed_line_is_protected(self):
        image, truth, seed = self.fixture((255,)*3, (0,)*3)
        cv2.line(image, (58, 60), (86, 60), (0,)*3, 3)
        result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
        self.assertIsNotNone(result.box_fill_mask)
        dash = np.zeros(image.shape[:2], np.uint8)
        cv2.line(dash, (58, 60), (86, 60), 255, 3)
        dash = cv2.dilate(dash, np.ones((3, 3), np.uint8)) > 0
        self.assertGreater(np.mean(result.box_fill_mask[dash] > 0), .9)

        image, truth, seed = self.fixture((255,)*3, (0,)*3)
        cv2.line(image, (55, 47), (150, 47), (0,)*3, 2)   # long line above the glyphs
        result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
        self.assertIsNotNone(result.box_fill_mask)
        line = np.zeros(image.shape[:2], np.uint8)
        cv2.line(line, (55, 47), (150, 47), 255, 2)
        line = cv2.dilate(line, np.ones((3, 3), np.uint8)) > 0
        self.assertFalse(np.any(result.box_fill_mask[line] > 0))
        self.assertGreater(result.diagnostics['protected_box_pixels'], 0)

    def test_restore_region_unions_fallback_and_reverts_exactly(self):
        image, truth, seed = self.fixture((255,)*3, (0,)*3)
        result = AdaptiveTextMask().generate(MaskRequest(image, (50, 45, 110, 95), seed, 32))
        erase = result.erase_mask
        fallback = result.box_fill_mask
        self.assertIsNotNone(fallback)
        restore = np.maximum(erase, fallback)
        # pretend the erase stage painted the whole fallback area
        processed = Image.fromarray(image.copy())
        plain = np.array(processed)
        plain[restore > 0] = 255
        processed = Image.fromarray(plain)
        left, top = 35, 30
        crop_mask = Image.fromarray(restore[top:95+15, left:110+15])
        region = make_region((50, 45, 110, 95), image.shape[:2][::-1], (left, top, 110+15, 95+15), crop_mask)
        item = {'box': [50, 45, 110, 95], 'restore_original': True, 'original_region': region}
        restored = apply_restorations(processed, Image.fromarray(image), [item])
        restored = np.array(restored)
        self.assertTrue(np.array_equal(restored[45:95, 50:110], image[45:95, 50:110]))

    def test_restore_region_respects_a_neighbouring_box(self):
        size = (192, 128)
        region_a = make_region((50, 45, 110, 95), size)
        region_b = make_region((105, 45, 165, 95), size)
        item_a = {'box': [50, 45, 110, 95], 'restore_original': True, 'original_region': region_a}
        item_b = {'box': [105, 45, 165, 95], 'restore_original': True, 'original_region': region_b}
        original = Image.fromarray(np.full((128, 192, 3), 255, np.uint8))
        processed = Image.fromarray(np.full((128, 192, 3), 40, np.uint8))
        restored = np.array(apply_restorations(processed, original, [item_a, item_b]))
        self.assertTrue(np.all(restored[45:95, 50:110] == 255))
        self.assertTrue(np.all(restored[45:95, 105:165] == 255))
