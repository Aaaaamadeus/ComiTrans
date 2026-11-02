from __future__ import annotations

import json
import os
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PIL import Image, ImageChops
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from comic_translate_desktop.background_repair import BackgroundRepair
from tests import test_editor_live_preview as fixtures


class BackgroundRepairTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EditorLivePreviewTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.EditorLivePreviewTests.tearDownClass.__func__)
    setUp = fixtures.EditorLivePreviewTests.setUp
    page = fixtures.EditorLivePreviewTests.page
    editor = fixtures.EditorLivePreviewTests.editor
    canvas_editor = fixtures.EditorLivePreviewTests.canvas_editor
    destroy_editor = staticmethod(fixtures.EditorLivePreviewTests.destroy_editor)

    @staticmethod
    def fake_repair(image, box):
        return Image.new(image.mode, (box[2] - box[0], box[3] - box[1]), '#123456')

    def repair(self, editor, box=(10, 10, 60, 60)):
        if not editor._repair_mode.isChecked():
            editor._repair_mode.click()
        editor._resize_region_from_canvas(box)
        with patch.object(editor._repair_engine, 'repair_region', side_effect=self.fake_repair):
            editor._repair_btn.click()
            self.wait_repair(editor)
        self.assertIn('背景已修补', editor._status.text())

    def wait_repair(self, editor):
        for _ in range(200):
            QTest.qWait(10)
            if editor._repair_worker is None:
                return
        self.fail('Repair worker did not finish')

    def test_repair_changes_only_background_and_undo_uses_exact_cached_pixels(self):
        output, layout = self.page()
        editor = self.editor(output)
        editor.apply_changes()
        before = editor._cleaned_image.copy()
        rendered = editor._rendered.tobytes()
        files = [path.read_bytes() for path in (output, layout, editor.cleaned_path)]
        self.repair(editor)
        box, patch_before, *_ = editor._repair_history[0]
        self.assertEqual(box, (10, 10, 60, 60))
        self.assertEqual(patch_before.size, (50, 50))
        self.assertEqual(patch_before.tobytes(), before.crop(box).tobytes())
        self.assertEqual(ImageChops.difference(before, editor._cleaned_image).getbbox(), (10, 10, 60, 60))
        self.assertTrue(editor._dirty)
        self.assertEqual(files, [path.read_bytes() for path in (output, layout, editor.cleaned_path)])
        with patch.object(editor._repair_engine, 'repair_region', side_effect=AssertionError('Undo must use cache')):
            self.assertTrue(editor.undo_background_repair())
        self.assertEqual(editor._cleaned_image.tobytes(), before.tobytes())
        self.assertEqual(editor._rendered.tobytes(), rendered)
        self.assertFalse(editor._dirty)
        self.assertFalse(editor._repair_history)
        self.assertFalse(editor._repair_undo.isEnabled())

    def test_multiple_repairs_undo_in_reverse_order_and_preserve_text_edits(self):
        output, _ = self.page()
        editor = self.editor(output)
        before = editor._cleaned_image.tobytes()
        self.repair(editor)
        first = editor._cleaned_image.tobytes()
        self.repair(editor, (40, 10, 90, 60))  # partially overlaps the first repair
        self.assertEqual(len(editor._repair_history), 2)
        editor._text_input.setPlainText('新的译文')
        self.assertTrue(editor.undo_background_repair())
        self.assertEqual(editor._cleaned_image.tobytes(), first)
        self.assertTrue(editor.undo_background_repair())
        self.assertEqual(editor._cleaned_image.tobytes(), before)
        self.assertEqual(editor.items[0]['text'], '新的译文')
        self.assertTrue(editor._dirty)

    def test_save_persists_background_releases_cache_and_new_undo_starts_at_saved_image(self):
        output, _ = self.page()
        editor = self.editor(output)
        self.repair(editor)
        expected = editor._cleaned_image.tobytes()
        rendered = editor._rendered.tobytes()
        self.assertTrue(editor.save_image())
        self.assertFalse(editor._repair_history)
        self.assertFalse(editor.undo_background_repair())
        with Image.open(output) as saved:
            self.assertEqual(saved.tobytes(), rendered)
        restored = self.editor(output)
        self.assertEqual(restored._cleaned_image.tobytes(), expected)
        restored.apply_changes()
        self.assertEqual(restored._rendered.tobytes(), rendered)
        self.repair(editor, (70, 10, 90, 60))
        editor.undo_background_repair()
        self.assertEqual(editor._cleaned_image.tobytes(), expected)
        self.assertFalse(editor._dirty)

    def test_save_staging_failure_keeps_files_draft_and_undo_cache(self):
        output, layout = self.page()
        editor = self.editor(output)
        paths = (output, layout, editor.cleaned_path)
        before = [path.read_bytes() for path in paths]
        self.repair(editor)
        with patch.object(type(layout), 'write_text', side_effect=OSError('read only')):
            self.assertFalse(editor.save_image())
        self.assertEqual(before, [path.read_bytes() for path in paths])
        self.assertTrue(editor._dirty)
        self.assertTrue(editor._repair_history)
        self.assertTrue(editor._repair_undo.isEnabled())
        self.assertTrue(editor.save_image())
        self.assertFalse(editor._repair_history)

    def test_save_commit_failure_restores_all_files_and_keeps_cache(self):
        output, layout = self.page()
        editor = self.editor(output)
        paths = (output, layout, editor.cleaned_path)
        before = [path.read_bytes() for path in paths]
        self.repair(editor)
        replace = os.replace
        def fail_cleaned(source, target):
            if target == editor.cleaned_path:
                raise OSError('locked cleaned file')
            return replace(source, target)
        with patch('comic_translate_desktop.background_repair.os.replace', side_effect=fail_cleaned):
            self.assertFalse(editor.save_image())
        self.assertEqual(before, [path.read_bytes() for path in paths])
        self.assertTrue(editor._repair_history)
        self.assertTrue(editor.undo_background_repair())
        self.assertFalse(editor._dirty)

    def test_inference_failure_preserves_prior_repair_and_retry_works(self):
        output, _ = self.page()
        editor = self.editor(output)
        self.repair(editor)
        before = editor._cleaned_image.tobytes()
        with patch.object(editor._repair_engine, 'repair_region', side_effect=RuntimeError('test inference failure')):
            editor._repair_btn.click()
            self.wait_repair(editor)
        self.assertIn('背景修补失败', editor._status.text())
        self.assertEqual(editor._cleaned_image.tobytes(), before)
        self.assertEqual(len(editor._repair_history), 1)
        self.assertTrue(editor._repair_btn.isEnabled())
        self.repair(editor, (70, 10, 90, 60))
        self.assertEqual(len(editor._repair_history), 2)

    def test_failed_preview_can_undo_or_retry_without_saving_stale_output(self):
        output, _ = self.page()
        editor = self.editor(output)
        editor.apply_changes()
        original = output.read_bytes()
        with patch.object(editor, 'render', side_effect=RuntimeError('preview failed')):
            box = (10, 10, 60, 60)
            editor._accept_background_repair(box, self.fake_repair(editor._cleaned_image, box))
            self.assertFalse(editor.save_image())
        self.assertEqual(output.read_bytes(), original)
        self.assertTrue(editor._repair_history)
        self.assertTrue(editor.undo_background_repair())
        self.assertFalse(editor._dirty)

    def test_switch_cancel_retains_cache_discard_releases_it_without_writing(self):
        output, _ = self.page()
        second, _ = self.page('second')
        editor = self.editor(output)
        cleaned = editor.cleaned_path
        original = cleaned.read_bytes()
        self.repair(editor)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
            self.assertFalse(editor.load_page(second))
        self.assertTrue(editor._repair_history)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            self.assertTrue(editor.load_page(second))
        self.assertFalse(editor._repair_history)
        self.assertFalse(editor._repair_mode.isChecked())
        self.assertIsNone(editor._repair_box)
        self.assertEqual(cleaned.read_bytes(), original)

    def test_running_worker_blocks_save_page_change_and_close_until_finished(self):
        output, _ = self.page()
        second, _ = self.page('second')
        editor = self.editor(output)
        editor._repair_mode.click()
        editor._resize_region_from_canvas((10, 10, 60, 60))
        release = threading.Event()
        def blocking(image, box):
            release.wait(5)
            return self.fake_repair(image, box)
        with patch.object(editor._repair_engine, 'repair_region', side_effect=blocking):
            editor._repair_btn.click()
            try:
                self.assertFalse(editor.save_image())
                self.assertFalse(editor.load_page(second))
                self.assertFalse(editor.confirm_discard())
                self.assertFalse(editor.close())
                self.assertFalse(editor._repair_btn.isEnabled())
                self.assertFalse(editor._save_btn.isEnabled())
                self.assertFalse(editor.page_list.isEnabled())
            finally:
                release.set()
                self.wait_repair(editor)
        self.assertTrue(editor._save_btn.isEnabled())
        self.assertTrue(editor.page_list.isEnabled())

    def test_empty_layout_supports_background_repair_and_save(self):
        output, layout = self.page()
        layout.write_text('[]', encoding='utf-8')
        editor = self.editor(output)
        self.assertTrue(editor._repair_mode.isEnabled())
        self.repair(editor)
        self.assertTrue(editor.save_image())
        restored = self.editor(output)
        self.assertEqual(restored._cleaned_image.tobytes(), editor._cleaned_image.tobytes())
        self.assertEqual(json.loads(layout.read_text(encoding='utf-8')), [])

    def test_missing_sidecars_disable_background_tools(self):
        output, _ = self.page()
        editor = self.editor(output)
        plain = self.root / 'missing.png'
        Image.new('RGB', (600, 700), 'white').save(plain)
        editor.load_page(plain)
        self.assertFalse(editor._repair_mode.isEnabled())
        self.assertFalse(editor._repair_btn.isEnabled())
        self.assertFalse(editor._repair_undo.isEnabled())

    def test_selection_coordinates_at_zoom_scroll_and_escape_preserve_text_geometry(self):
        for zoom in (.5, 1., 2.):
            with self.subTest(zoom=zoom):
                output, _ = self.page(f'zoom-{zoom}')
                editor = self.canvas_editor(output, zoom)
                original_box = list(editor.items[0]['mask_box'])
                editor._repair_mode.click()
                editor.preview._scroll.horizontalScrollBar().setValue(60)
                editor.preview._scroll.verticalScrollBar().setValue(100)
                self.app.processEvents()
                canvas = editor.preview._label
                page = canvas.page_rect()
                def point(x, y):
                    return (page.topLeft() + QPointF(x * page.width() / 600, y * page.height() / 700)).toPoint()
                QTest.mousePress(canvas, Qt.LeftButton, pos=point(300, 200))
                QTest.mouseMove(canvas, point(450, 350))
                QTest.mouseRelease(canvas, Qt.LeftButton, pos=point(450, 350))
                for actual, expected in zip(editor._repair_box, (300, 200, 450, 350)):
                    self.assertAlmostEqual(actual, expected, delta=1)
                selected = editor._repair_box
                QTest.mousePress(canvas, Qt.LeftButton, pos=point(50, 50))
                QTest.mouseMove(canvas, point(150, 150))
                QTest.keyClick(canvas, Qt.Key_Escape)
                QTest.mouseRelease(canvas, Qt.LeftButton, pos=point(150, 150))
                self.assertEqual(editor._repair_box, selected)
                self.assertEqual(editor.items[0]['mask_box'], original_box)
                self.assertFalse(editor._dirty)
                editor._repair_mode.click()
                self.assertEqual(canvas.region, tuple(original_box))


class BackgroundRepairEngineTests(unittest.TestCase):
    def test_repair_white_scar_on_gradient_or_dots_with_native_neighbours(self):
        yy, xx = np.mgrid[:128, :160]
        gradient = np.stack((xx + 40, yy + 80, xx + 60), axis=2).astype(np.uint8)
        dots = np.full_like(gradient, 185)
        dots[2::5, 3::7] = 35
        for background in (gradient, dots):
            engine = BackgroundRepair('unused')
            source = Image.fromarray(background)
            box = (62, 52, 96, 80)
            source.paste('white', box)
            result = engine.repair(source, box)
            np.testing.assert_array_equal(np.asarray(result), background)
            self.assertIsNone(engine._inpainter)

    def test_model_only_replaces_selection_and_receives_context_mask(self):
        engine = BackgroundRepair('unused')
        source = Image.new('RGB', (400, 500), '#ddccbb')
        source.putpixel((110, 135), (30, 70, 45))  # irregular art in the context
        calls = []
        def model(image, mask):
            calls.append((image.size, mask.getbbox()))
            return Image.new('RGB', image.size, '#123456')
        engine._inpainter = model
        result = engine.repair(source, (120, 140, 150, 180))
        self.assertEqual(calls, [((158, 168), (64, 64, 94, 104))])
        self.assertEqual(ImageChops.difference(source, result).getbbox(), (120, 140, 150, 180))
        self.assertEqual(source.getpixel((120, 140)), (221, 204, 187))

    def test_large_selection_reaches_shared_tiler_at_original_resolution(self):
        engine = BackgroundRepair('unused')
        seen = []
        def model(image, mask):
            seen.append(image.size)
            return Image.new('RGB', image.size, 'black')
        engine._inpainter = model
        source = Image.new('RGB', (1800, 2400), 'white')
        result = engine.repair(source, (0, 0, 1500, 2000))
        self.assertEqual(seen[0], (1756, 2256))
        self.assertEqual(result.size, source.size)
        self.assertEqual(ImageChops.difference(source, result).getbbox(), (0, 0, 1500, 2000))

    def test_invalid_and_full_image_selections_are_rejected_before_loading_model(self):
        engine = BackgroundRepair('missing-model')
        source = Image.new('RGB', (100, 100), 'white')
        for box in ((1, 1, 1, 5), (-1, 0, 20, 30), (0, 0, 101, 100), (0, 0, 100, 100)):
            with self.subTest(box=box), self.assertRaises(ValueError):
                engine.repair(source, box)
        self.assertIsNone(engine._inpainter)
