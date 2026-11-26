from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from comic_translate_core.paint_engine import (
    BrushEngine,
    BrushSettings,
    BrushTool,
    ImageFilters,
    SelectionEngine,
    StrokeStabilizer,
    available_brush_shapes,
    available_paper_textures,
    clear_custom_textures,
    load_custom_textures,
)
from comic_translate_desktop.background_repair import BackgroundRepair


class PaintEngineTests(unittest.TestCase):
    def setUp(self):
        clear_custom_textures()
        self.engine = BrushEngine()

    def _white_canvas(self, w=120, h=120):
        return np.full((h, w, 3), 255, dtype=np.uint8)

    def _run_stroke(self, canvas, settings, points, *, selection_mask=None, original_canvas=None,
                    protected_mask=None, clone_source=None):
        session = self.engine.start_stroke(
            canvas, settings,
            selection_mask=selection_mask,
            original_canvas=original_canvas,
            protected_mask=protected_mask,
            clone_source=clone_source,
        )
        session.begin(*points[0])
        for pt in points[1:-1]:
            session.add_point(*pt)
        if len(points) > 1:
            session.add_point(*points[-1])
        return session.end()

    def test_all_brush_tools_produce_expected_effects(self):
        # Pencil, Pen, Airbrush
        for tool in (BrushTool.PENCIL, BrushTool.PEN, BrushTool.AIRBRUSH):
            canvas = self._white_canvas()
            s = BrushSettings(tool=tool, color=(200, 20, 20), size=12, stabilizer=0)
            res = self._run_stroke(canvas, s, [(20, 60, 1.0), (100, 60, 1.0)])
            self.assertIsNotNone(res, tool)
            self.assertLess(canvas[60, 60, 1], 250, tool)

        # Binary: strictly target color or unchanged white (no antialiased grays)
        canvas = self._white_canvas()
        s_bin = BrushSettings(tool=BrushTool.BINARY, color=(0, 0, 0), size=9, stabilizer=0, opacity=1.0)
        self._run_stroke(canvas, s_bin, [(20, 60, 1.0), (80, 60, 1.0)])
        unique_vals = set(np.unique(canvas))
        self.assertEqual(unique_vals, {0, 255})

        # Marker: overlapping dabs in ONE stroke do not stack past opacity=0.4
        canvas = self._white_canvas()
        s_mark = BrushSettings(tool=BrushTool.MARKER, color=(0, 0, 0), size=16, opacity=0.4, stabilizer=0)
        self._run_stroke(canvas, s_mark, [(30, 60, 1.0), (50, 60, 1.0), (35, 60, 1.0), (50, 60, 1.0)])
        single_min = int(canvas[60, 40, 0])
        expected_val = round(255 * (1.0 - 0.4))
        self.assertGreaterEqual(single_min, expected_val - 2)
        # Second stroke layers further darkening
        self._run_stroke(canvas, s_mark, [(30, 60, 1.0), (50, 60, 1.0)])
        self.assertLess(int(canvas[60, 40, 0]), single_min - 20)

        # Watercolor & Brush: wet mix picks up blue background into red paint
        for tool in (BrushTool.WATERCOLOR, BrushTool.BRUSH):
            canvas = self._white_canvas()
            canvas[:, 20:60] = (0, 0, 255)
            s_wc = BrushSettings(tool=tool, color=(255, 0, 0), size=14, blending=0.7, persistence=0.8, dilution=0.3, stabilizer=0)
            self._run_stroke(canvas, s_wc, [(30, 60, 1.0), (80, 60, 1.0)])
            # Carried pigment onto white side contains noticeable blue channel from wash
            self.assertGreater(int(canvas[60, 75, 2]), 20, tool)
            self.assertLess(int(canvas[60, 75, 2]), 250, tool)

        # Blur: softens sharp black/white edge
        canvas = self._white_canvas()
        canvas[:, :60] = (0, 0, 0)
        s_blur = BrushSettings(tool=BrushTool.BLUR, size=18, opacity=1.0, blending=1.0, stabilizer=0)
        self._run_stroke(canvas, s_blur, [(60, 30, 1.0), (60, 90, 1.0)])
        mid = int(canvas[60, 60, 0])
        self.assertTrue(10 < mid < 245)

        # Smudge: drags black pigment rightwards onto white area
        canvas = self._white_canvas()
        canvas[:, :40] = (0, 0, 0)
        s_smudge = BrushSettings(tool=BrushTool.SMUDGE, size=14, opacity=1.0, persistence=0.85, blending=0.5, stabilizer=0)
        self._run_stroke(canvas, s_smudge, [(35, 60, 1.0), (60, 60, 1.0)])
        self.assertLess(int(canvas[60, 50, 0]), 230)

        # Eraser: color mode and original-restore mode
        orig = np.full((120, 120, 3), 180, dtype=np.uint8)
        canvas = np.zeros((120, 120, 3), dtype=np.uint8)
        self._run_stroke(canvas, BrushSettings(tool=BrushTool.ERASER, eraser_mode='color', bg_color=(255, 255, 255), size=12, stabilizer=0), [(30, 30, 1.0)])
        self.assertEqual(tuple(canvas[30, 30]), (255, 255, 255))
        self._run_stroke(canvas, BrushSettings(tool=BrushTool.ERASER, eraser_mode='original', size=12, stabilizer=0), [(80, 80, 1.0)], original_canvas=orig)
        self.assertEqual(tuple(canvas[80, 80]), (180, 180, 180))

        # Clone stamp: copies distinctive pattern from clone_source
        canvas = self._white_canvas()
        canvas[20:30, 20:30] = (10, 120, 220)
        s_clone = BrushSettings(tool=BrushTool.CLONE, size=10, opacity=1.0, stabilizer=0)
        self._run_stroke(canvas, s_clone, [(80, 80, 1.0)], clone_source=(25, 25))
        self.assertEqual(tuple(canvas[80, 80]), (10, 120, 220))

    def test_stabilizer_and_pressure_and_symmetry_and_protected_mask(self):
        # Stabilizer reduces zigzag jitter vs raw level=0
        stab0 = StrokeStabilizer(level=0, spacing_px=2.0)
        stab_s = StrokeStabilizer(level=18, spacing_px=2.0)
        pts0 = stab0.begin(0.0, 50.0, 1.0)
        ptss = stab_s.begin(0.0, 50.0, 1.0)
        for i in range(1, 20):
            y = 50.0 + (12.0 if i % 2 else -12.0)
            pts0.extend(stab0.push(i * 5.0, y, 1.0))
            ptss.extend(stab_s.push(i * 5.0, y, 1.0))
        ptss.extend(stab_s.finish())
        std0 = np.std([p[1] for p in pts0])
        stds = np.std([p[1] for p in ptss])
        self.assertLess(stds, std0 * 0.6)

        # Pressure size controls width
        c_low = self._white_canvas()
        c_high = self._white_canvas()
        s = BrushSettings(tool=BrushTool.PEN, color=(0, 0, 0), size=24, min_size_ratio=0.1, pressure_size=True, stabilizer=0)
        self._run_stroke(c_low, s, [(60, 60, 0.1)])
        self._run_stroke(c_high, s, [(60, 60, 1.0)])
        self.assertLess(np.count_nonzero(c_low[..., 0] < 200), np.count_nonzero(c_high[..., 0] < 200))

        # Horizontal symmetry mirrors left stroke onto right side
        canvas = self._white_canvas(120, 120)
        s_sym = BrushSettings(tool=BrushTool.PEN, color=(0, 0, 0), size=8, symmetry='horizontal', stabilizer=0)
        self._run_stroke(canvas, s_sym, [(20, 60, 1.0)])
        self.assertLess(canvas[60, 20, 0], 50)
        self.assertLess(canvas[60, 99, 0], 50)

        # Protected mask preserves restored bubble pixels across strokes & fills
        canvas = self._white_canvas(120, 120)
        prot = np.zeros((120, 120), dtype=np.uint8)
        prot[40:80, 40:80] = 255
        before_prot = canvas[40:80, 40:80].copy()
        self._run_stroke(canvas, BrushSettings(tool=BrushTool.PEN, color=(0, 0, 0), size=20, stabilizer=0), [(10, 60, 1.0), (110, 60, 1.0)], protected_mask=prot)
        self.assertTrue(np.array_equal(canvas[40:80, 40:80], before_prot))
        self.assertLess(canvas[60, 20, 0], 50)

    def test_selection_engine_and_bucket_fill_and_move(self):
        sel = SelectionEngine(120, 120)
        sel.apply_rect((20, 20, 60, 60), mode='replace')
        sel.apply_rect((40, 40, 80, 80), mode='add')
        self.assertEqual(sel.bbox(), (20, 20, 80, 80))
        sel.apply_rect((30, 30, 50, 50), mode='subtract')
        self.assertEqual(int(sel.mask[35, 35]), 0)
        self.assertEqual(int(sel.mask[25, 25]), 255)
        sel.apply_rect((20, 20, 40, 40), mode='intersect')
        self.assertEqual(sel.bbox(), (20, 20, 40, 40))

        # Lasso & poly lasso & select/deselect pen
        sel.clear()
        sel.apply_lasso([(10, 10), (50, 10), (50, 50), (10, 50)], mode='replace', antialias=False)
        self.assertGreater(int(sel.mask[30, 30]), 200)
        sel.paint_mask_stroke([(70, 70)], 8, erase=False, antialias=False)
        self.assertGreater(int(sel.mask[70, 70]), 200)
        sel.paint_mask_stroke([(70, 70)], 10, erase=True, antialias=False)
        self.assertEqual(int(sel.mask[70, 70]), 0)

        # Expand / contract / feather / invert / contours
        sel.clear()
        sel.apply_rect((40, 40, 60, 60))
        sel.expand(3)
        self.assertEqual(sel.bbox(), (37, 37, 63, 63))
        sel.contract(3)
        self.assertEqual(sel.bbox(), (40, 40, 60, 60))
        self.assertTrue(len(sel.contours()) >= 1)
        sel.feather(2)
        self.assertTrue(0 < int(sel.mask[39, 50]) < 255)
        sel.invert()
        self.assertEqual(int(sel.mask[0, 0]), 255)

        # Magic wand: contiguous vs global
        canvas = self._white_canvas()
        canvas[10:30, 10:30] = (0, 128, 255)
        canvas[70:90, 70:90] = (0, 128, 255)
        sel.apply_magic_wand(canvas, 15, 15, tolerance=5, contiguous=True, antialias=False)
        self.assertGreater(int(sel.mask[15, 15]), 200)
        self.assertEqual(int(sel.mask[80, 80]), 0)
        sel.apply_magic_wand(canvas, 15, 15, tolerance=5, contiguous=False, antialias=False)
        self.assertGreater(int(sel.mask[80, 80]), 200)

        # Bucket fill with gap_close=2 prevents leak through a 2px gap in a box outline
        canvas = self._white_canvas()
        canvas[20:80, 20:24] = 0
        canvas[20:80, 76:80] = 0
        canvas[20:24, 20:80] = 0
        canvas[76:80, 20:80] = 0
        canvas[76:80, 49:51] = 255  # 2px gap at bottom
        res = SelectionEngine.bucket_fill(canvas, 50, 50, (255, 0, 0), tolerance=10, contiguous=True, gap_close=2, expand_px=0)
        self.assertIsNotNone(res)
        self.assertEqual(tuple(canvas[50, 50]), (255, 0, 0))
        self.assertEqual(tuple(canvas[10, 10]), (255, 255, 255))

        # Move selection shifts pixels and clears source with bg_color
        canvas = self._white_canvas()
        canvas[20:40, 20:40] = (30, 40, 50)
        sel.apply_rect((20, 20, 40, 40))
        moved = SelectionEngine.move_selection(canvas, sel.mask, 30, 20, bg_color=(255, 255, 255))
        self.assertIsNotNone(moved)
        self.assertEqual(tuple(canvas[25, 25]), (255, 255, 255))
        self.assertEqual(tuple(canvas[45, 55]), (30, 40, 50))

    def test_shapes_gradients_filters_and_custom_textures(self):
        # Shapes: line, curve, rect, ellipse
        for tool, pts in (
            (BrushTool.LINE, [(10, 10), (100, 100)]),
            (BrushTool.CURVE, [(10, 60), (60, 10), (110, 60)]),
            (BrushTool.RECT_SHAPE, [(20, 20), (90, 90)]),
            (BrushTool.ELLIPSE_SHAPE, [(20, 20), (90, 90)]),
        ):
            canvas = self._white_canvas()
            s = BrushSettings(tool=tool, color=(0, 0, 0), size=4, shape_filled=(tool == BrushTool.ELLIPSE_SHAPE))
            res = self.engine.draw_shape(canvas, tool, pts, s)
            self.assertIsNotNone(res, tool)
            self.assertLess(int(canvas.min()), 100, tool)

        # Gradients: linear and radial
        canvas = self._white_canvas()
        s_grad = BrushSettings(tool=BrushTool.GRADIENT, color=(0, 0, 0), bg_color=(255, 255, 255), gradient_shape='linear', gradient_mode='fg_bg')
        self.engine.draw_gradient(canvas, (0, 0), (119, 0), s_grad)
        self.assertLess(int(canvas[60, 5, 0]), 30)
        self.assertGreater(int(canvas[60, 114, 0]), 225)

        canvas2 = self._white_canvas()
        s_rad = BrushSettings(tool=BrushTool.GRADIENT, color=(255, 0, 0), gradient_shape='radial', gradient_mode='fg_transparent')
        self.engine.draw_gradient(canvas2, (60, 60), (100, 60), s_rad)
        self.assertEqual(tuple(canvas2[60, 60]), (255, 0, 0))
        self.assertEqual(tuple(canvas2[0, 0]), (255, 255, 255))

        # All 8 ImageFilters (non-mutating and selection-mask aware)
        base = np.full((60, 60, 3), 120, dtype=np.uint8)
        base[:30, :30] = (200, 100, 50)
        base[45:55, 45:55] = (230, 230, 230)
        sel_mask = np.zeros((60, 60), dtype=np.uint8)
        sel_mask[0:40, 0:40] = 255

        for fn_call in (
            lambda: ImageFilters.adjust_hsl(base, 40, 20, 10, selection_mask=sel_mask),
            lambda: ImageFilters.adjust_brightness_contrast(base, 20, 25, selection_mask=sel_mask),
            lambda: ImageFilters.adjust_levels(base, 10, 1.4, 220, selection_mask=sel_mask),
            lambda: ImageFilters.gaussian_blur(base, 2.0, selection_mask=sel_mask),
            lambda: ImageFilters.sharpen(base, 120, 1.0, selection_mask=sel_mask),
            lambda: ImageFilters.invert_colors(base, selection_mask=sel_mask),
            lambda: ImageFilters.desaturate(base, selection_mask=sel_mask),
            lambda: ImageFilters.luminance_to_white(base, threshold=200, softness=10),
        ):
            snap = base.copy()
            res = fn_call()
            self.assertIsNotNone(res)
            self.assertTrue(np.array_equal(base, snap))

        # Custom texture loader
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'brshape').mkdir()
            (root / 'papertex').mkdir()
            Image.new('L', (32, 32), 0).save(root / 'brshape' / 'my_tip.bmp')
            Image.new('L', (32, 32), 128).save(root / 'papertex' / 'my_paper.png')
            loaded = load_custom_textures(root)
            self.assertIn('custom:my_tip', loaded['shapes'])
            self.assertIn('custom:my_paper', loaded['textures'])
            self.assertIn('custom:my_tip', available_brush_shapes())
            self.assertIn('custom:my_paper', available_paper_textures())

    def test_background_repair_mask_with_smooth_gradient_and_fallback(self):
        arr = np.zeros((220, 220, 3), dtype=np.uint8)
        for y in range(220):
            arr[y, :] = (220 - y // 4, 220 - y // 4, 220 - y // 4)
        expected = Image.fromarray(arr.copy())
        corrupted = arr.copy()
        corrupted[90:130, 90:130] = (0, 255, 0)
        mask = np.zeros((220, 220), dtype=np.uint8)
        mask[90:130, 90:130] = 255

        repair = BackgroundRepair('unused.onnx', device='cpu')
        box, repaired_patch = repair.repair_mask(Image.fromarray(corrupted), mask)
        self.assertEqual(box, (90, 90, 130, 130))
        self.assertEqual(repaired_patch.size, (40, 40))
        diff = np.abs(np.asarray(repaired_patch, dtype=np.int16) - np.asarray(expected.crop(box), dtype=np.int16))
        self.assertLessEqual(int(diff.max()), 3)

        # Fallback path when reconstruct_background returns None
        with patch('comic_translate_desktop.background_repair.reconstruct_background', return_value=None):
            class _FakeInpainter:
                def __call__(self, crop, m):
                    return Image.new('RGB', crop.size, (42, 43, 44))

            repair._inpainter = _FakeInpainter()
            box2, patch2 = repair.repair_mask(Image.fromarray(corrupted), mask)
            self.assertEqual(box2, (90, 90, 130, 130))
            self.assertEqual(patch2.getpixel((10, 10)), (42, 43, 44))


if __name__ == '__main__':
    unittest.main()
