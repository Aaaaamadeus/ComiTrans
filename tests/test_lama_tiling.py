import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'comic-translate-ai/main'))
from manga_lama import MangaLama, _SharedSession


class TilingTests(unittest.TestCase):
    def model(self, infer=None):
        model = MangaLama.__new__(MangaLama)
        model._tile_size = 768
        model.cancel_callback = None
        model._infer = infer or Mock(side_effect=lambda image, mask: Image.new('RGB', image.size, '#1679cc'))
        return model

    def test_large_odd_page_bounds_inference_and_preserves_unmasked_pixels_and_inputs(self):
        source = Image.fromarray(np.random.default_rng(2).integers(0, 256, (1667, 2139, 3), dtype=np.uint8))
        before = source.tobytes()
        mask = Image.new('L', source.size)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((450, 450, 1100, 1100), fill=255)  # crosses both seams
        draw.rectangle((2100, 1600, 2138, 1666), fill=255)  # bottom/right edges
        mask_before = mask.tobytes()
        model = self.model()
        result = model(source, mask)
        self.assertGreater(model._infer.call_count, 1)
        for call in model._infer.call_args_list:
            image, local_mask = call.args
            self.assertLessEqual(max(image.size), 768)
            self.assertEqual(image.size, local_mask.size)
        original, actual = np.asarray(source), np.asarray(result)
        selected = np.asarray(mask) > 0
        np.testing.assert_array_equal(actual[~selected], original[~selected])
        self.assertTrue(np.all(actual[selected] == [22, 121, 204]))
        self.assertEqual(result.size, source.size)
        self.assertEqual(source.tobytes(), before)
        self.assertEqual(mask.tobytes(), mask_before)

    def test_small_sparse_selection_uses_context_crop_without_resizing(self):
        image = Image.new('RGB', (3928, 5556), 'white')
        mask = Image.new('L', image.size)
        mask.paste(255, (1200, 1600, 1280, 1700))
        model = self.model()
        result = model(image, mask)
        crop, crop_mask = model._infer.call_args.args
        self.assertEqual(crop.size, (272, 292))
        self.assertEqual(crop_mask.getbbox(), (96, 96, 176, 196))
        self.assertEqual(result.size, image.size)
        self.assertEqual(model._infer.call_count, 1)

    def test_empty_mask_skips_model_and_mismatched_dimensions_fail(self):
        model = self.model()
        image = Image.new('RGB', (50, 60), 'white')
        self.assertEqual(model(image, Image.new('L', image.size)).tobytes(), image.tobytes())
        model._infer.assert_not_called()
        with self.assertRaises(ValueError):
            model(image, Image.new('L', (1, 1)))

    def test_overlap_blends_different_predictions_without_steps_or_original_bleed(self):
        counter = [0]
        def predict(image, mask):
            counter[0] += 1
            return Image.new('RGB', image.size, (50 * counter[0],) * 3)
        image = Image.new('RGB', (1100, 80), 'white')
        result = self.model(predict)(image, Image.new('L', image.size, 255))
        row = np.asarray(result)[20, :, 0].astype(int)
        self.assertGreater(row[575], row[512])
        self.assertLessEqual(np.abs(np.diff(row)).max(), 2)
        self.assertLess(row.max(), 255)

    def test_oom_retries_smaller_tiles_and_remembers_safe_size(self):
        attempts = []
        def predict(image, mask):
            attempts.append(image.size)
            if max(image.size) > 384:
                raise RuntimeError('Failed to allocate memory for requested buffer')
            return Image.new('RGB', image.size, 'black')
        model = self.model(predict)
        source = Image.new('RGB', (1000, 900), 'white')
        result = model(source, Image.new('L', source.size, 255))
        self.assertEqual(model._tile_size, 384)
        self.assertEqual(result.getextrema(), ((0, 0),) * 3)
        self.assertTrue(any(max(size) > 512 for size in attempts))
        attempts.clear()
        model(source, Image.new('L', source.size, 255))
        self.assertTrue(all(max(size) <= 384 for size in attempts))

    def test_unrelated_errors_propagate_and_exhausted_memory_is_actionable(self):
        image = Image.new('RGB', (1000, 900), 'white')
        mask = Image.new('L', image.size, 255)
        for error, expected in ((RuntimeError('invalid model'), 'invalid model'),
                                (MemoryError('allocation'), '最小分块仍内存不足')):
            model = self.model(Mock(side_effect=error))
            with self.assertRaisesRegex(RuntimeError, expected):
                model(image, mask)
        self.assertEqual(model._tile_size, 256)

    def test_cancellation_between_tiles_does_not_return_partial_page(self):
        model = self.model()
        model.cancel_callback = Mock(side_effect=[None, None, RuntimeError('cancelled')])
        image = Image.new('RGB', (2000, 900))
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            model(image, Image.new('L', image.size, 255))
        self.assertEqual(model._infer.call_count, 1)

    def test_real_preprocess_still_pads_within_tile_cap_and_crops_to_native_size(self):
        model = MangaLama.__new__(MangaLama)
        model._tile_size, model.cancel_callback = 768, None
        model.input_image_name, model.input_mask_name, model.output_name = 'image', 'mask', 'out'
        def run(names, inputs):
            tensor = inputs['image']
            self.assertEqual(tensor.dtype, np.float32)
            self.assertEqual(tensor.shape[2] % 8, 0)
            self.assertEqual(tensor.shape[3] % 8, 0)
            self.assertLessEqual(max(tensor.shape[2:]), 768)
            return [np.zeros_like(tensor)]
        model.onnx_session = Mock(run=Mock(side_effect=run), get_providers=lambda: ['CPUExecutionProvider'])
        model._session_resource = _SharedSession(model.onnx_session)
        image = Image.new('RGB', (1597, 961), 'white')
        result = model(image, Image.new('L', image.size, 255))
        self.assertEqual(result.size, image.size)
        self.assertEqual(result.getextrema(), ((0, 0),) * 3)


if __name__ == '__main__':
    unittest.main()
