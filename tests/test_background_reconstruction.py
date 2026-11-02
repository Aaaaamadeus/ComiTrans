import unittest

import numpy as np

from comic_translate_core.background_reconstruction import reconstruct_background


class BackgroundReconstructionTests(unittest.TestCase):
    def damaged(self, background):
        mask = np.zeros(background.shape[:2], np.uint8)
        mask[35:80, 45:100] = 255
        image = background.copy()
        image[mask > 0] = 0
        return image, mask

    def test_smooth_colour_gradient_is_restored_at_native_resolution(self):
        yy, xx = np.mgrid[:128, :192]
        background = np.stack((xx, yy, xx // 2 + yy // 2), axis=2).astype(np.uint8)
        image, mask = self.damaged(background)
        before = image.copy()
        result, strategy = reconstruct_background(image, mask)
        self.assertEqual(strategy, 'colour-plane')
        self.assertLessEqual(int(np.abs(result.astype(np.int16) - background).max()), 1)
        np.testing.assert_array_equal(result[mask == 0], image[mask == 0])
        np.testing.assert_array_equal(image, before)

    def test_regular_screentones_are_reconstructed_without_blurring_dots(self):
        for period in (2, 6, 11):
            with self.subTest(period=period):
                background = np.full((128, 192, 3), 238, np.uint8)
                background[1::period, 1::period] = (20, 30, 40)
                image, mask = self.damaged(background)
                reconstructed = reconstruct_background(image, mask)
                self.assertIsNotNone(reconstructed)
                result, strategy = reconstructed
                self.assertEqual(strategy, 'periodic-texture')
                np.testing.assert_array_equal(result, background)

    def test_nonperiodic_art_and_unsupported_edges_fall_back(self):
        background = np.random.default_rng(42).integers(0, 256, (128, 192, 3), dtype=np.uint8)
        image, mask = self.damaged(background)
        self.assertIsNone(reconstruct_background(image, mask))
        background[:] = 220
        background[10:115, 20] = 0  # a real line must veto a smooth fill
        image, mask = self.damaged(background)
        self.assertIsNone(reconstruct_background(image, mask))
        mask[:40, :40] = 255
        self.assertIsNone(reconstruct_background(image, mask))
