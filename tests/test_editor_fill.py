from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from comic_translate_desktop import config
from comic_translate_desktop.ui.editor_page import EditorPage
from tests.qt_utils import destroy_widget


class EditorFillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for key, value in (('PROJECT_ROOT', self.root), ('CONFIG_PATH', self.root / 'config.yaml')):
            setting = patch.object(config, key, value)
            setting.start()
            self.addCleanup(setting.stop)

    def fixture(self):
        output = self.root / 'output' / 'page.png'
        cleaned = self.root / 'output_cleaned' / 'page_cleaned.png'
        layout = self.root / 'output_layout' / 'page_layout.json'
        for file in (output, cleaned, layout):
            file.parent.mkdir(exist_ok=True)
        for file in (output, cleaned):
            Image.new('RGB', (200, 300), '#ffeedd').save(file)
        layout.write_text(json.dumps([dict(
            text='译文', source_text='原文', box=[100, 120, 160, 240], style='dialogue',
            font_size=18, direction=1, offset_x=0, offset_y=0)], ensure_ascii=False),
            encoding='utf-8')
        return output, cleaned, layout

    def editor(self, output):
        editor = EditorPage()
        self.addCleanup(self.destroy_editor, editor)
        self.assertTrue(editor.load_page(output))
        return editor

    @staticmethod
    def destroy_editor(editor):
        editor._dirty = False
        destroy_widget(editor)

    def test_fill_white_then_black_can_be_undone_and_saved(self):
        output, cleaned, _layout = self.fixture()
        editor = self.editor(output)
        editor._repair_box = (20, 20, 80, 80)
        editor._fill_repair_region((255, 255, 255))
        self.assertEqual(editor._cleaned_image.getpixel((40, 40)), (255, 255, 255))
        self.assertTrue(editor._dirty)
        self.assertTrue(editor.undo_background_repair())
        self.assertEqual(editor._cleaned_image.getpixel((40, 40)), (255, 238, 221))
        self.assertFalse(editor.undo_background_repair())

        editor._fill_repair_region((255, 255, 255))
        self.assertTrue(editor.save_image())
        with Image.open(output) as saved:
            self.assertEqual(saved.getpixel((40, 40)), (255, 255, 255))
        with Image.open(cleaned) as saved:
            self.assertEqual(saved.getpixel((40, 40)), (255, 255, 255))

        editor._repair_box = (90, 90, 150, 150)
        editor._fill_repair_region((0, 0, 0))
        self.assertEqual(editor._cleaned_image.getpixel((120, 120)), (0, 0, 0))
        self.assertTrue(editor.undo_background_repair())
        self.assertEqual(editor._cleaned_image.getpixel((120, 120)), (255, 238, 221))
        self.assertTrue(editor.save_image())
        with Image.open(output) as saved:
            self.assertEqual(saved.getpixel((120, 120)), (255, 238, 221))
            self.assertEqual(saved.getpixel((40, 40)), (255, 255, 255))

    def test_fill_refuses_boxes_that_overlap_a_restored_bubble(self):
        output, _cleaned, _layout = self.fixture()
        editor = self.editor(output)
        editor.items[0]['restore_original'] = True
        editor._repair_box = (110, 130, 150, 180)
        before = editor._cleaned_image.copy()
        editor._fill_repair_region((255, 255, 255))
        self.assertEqual(editor._cleaned_image.tobytes(), before.tobytes())
        self.assertIn('已还原', editor._status.text())

    def test_fill_rejects_a_box_outside_the_image(self):
        output, _cleaned, _layout = self.fixture()
        editor = self.editor(output)
        editor._repair_box = (-5, 0, 10, 10)
        before = editor._cleaned_image.copy()
        editor._fill_repair_region((255, 255, 255))
        self.assertEqual(editor._cleaned_image.tobytes(), before.tobytes())
        self.assertIn('超出', editor._status.text())

    def test_custom_fill_dialog_cancel_apply_undo_save_and_reload(self):
        output, cleaned, _layout = self.fixture()
        editor = self.editor(output)
        editor._repair_box = (20, 20, 80, 80)
        editor._update_repair_controls()
        before = editor._cleaned_image.tobytes()
        with patch('comic_translate_desktop.ui.editor_page.QColorDialog.getColor', return_value=QColor()):
            editor._fill_color_btn.click()
        self.assertEqual(editor._fill_color.name(), '#ffffff')
        self.assertFalse(editor._dirty)
        with patch('comic_translate_desktop.ui.editor_page.QColorDialog.getColor', return_value=QColor('#12ab5d')):
            editor._fill_color_btn.click()
        self.assertEqual(editor._cleaned_image.tobytes(), before)
        self.assertFalse(editor._dirty)
        editor._fill_custom_btn.click()
        self.assertEqual(editor._cleaned_image.getpixel((40, 40)), (18, 171, 93))
        self.assertEqual(editor._cleaned_image.getpixel((80, 80)), (255, 238, 221))
        self.assertIn('#12AB5D', editor._status.text())
        self.assertTrue(editor.undo_background_repair())
        self.assertEqual(editor._cleaned_image.tobytes(), before)
        editor._fill_custom_btn.click()
        self.assertTrue(editor.save_image())
        restored = self.editor(output)
        self.assertEqual(restored._cleaned_image.getpixel((40, 40)), (18, 171, 93))
        with Image.open(cleaned) as saved:
            self.assertEqual(saved.getpixel((40, 40)), (18, 171, 93))

    def test_pick_color_preserves_selection_and_pixels_in_single_and_strip_views(self):
        output, _cleaned, _layout = self.fixture()
        editor = self.editor(output)
        editor.resize(1100, 800)
        editor.show()
        editor._focus_btn.setChecked(True)
        self.app.processEvents()
        editor._repair_mode.setChecked(True)
        editor._repair_box = (20, 20, 80, 80)
        editor._cleaned_image.paste((18, 171, 93), (36, 56, 45, 65))
        editor._preview_dirty = True
        self.assertTrue(editor.apply_changes())
        editor._update_region_guide()
        for continuous, zoom in ((False, .5), (False, 2), (True, .5), (True, 2)):
            with self.subTest(continuous=continuous, zoom=zoom):
                editor._strip_toggle.setChecked(continuous)
                editor.preview.set_zoom(zoom)
                self.app.processEvents()
                editor.preview._scroll.verticalScrollBar().setValue(50)
                before = editor._cleaned_image.tobytes()
                history = list(editor._repair_history)
                dirty = editor._dirty
                editor._zoom_tool_btn.setChecked(True)
                editor._pick_fill_btn.click()
                canvas = editor.preview._label
                page = canvas.page_rect()
                point = QPointF(page.left() + 40.5 * page.width() / 200,
                                page.top() + 60.5 * page.height() / 300).toPoint()
                QTest.mouseClick(canvas, Qt.LeftButton, pos=point)
                self.assertEqual(editor._fill_color.name(), '#12ab5d')
                self.assertFalse(editor._pick_fill_btn.isChecked())
                self.assertFalse(editor.preview._color_picking)
                self.assertEqual(editor._repair_box, (20, 20, 80, 80))
                self.assertIsNone(canvas._region_drag)
                self.assertEqual(editor._repair_history, history)
                self.assertEqual(editor._dirty, dirty)
                self.assertEqual(editor._cleaned_image.tobytes(), before)
                self.assertEqual(editor.preview._zoom, zoom)

    def test_pick_cancel_outside_page_busy_and_mode_switch(self):
        output, _cleaned, _layout = self.fixture()
        editor = self.editor(output)
        editor.resize(1100, 800)
        editor.show()
        editor._focus_btn.setChecked(True)
        self.app.processEvents()
        editor._strip_toggle.setChecked(False)
        editor.preview.set_zoom(.5)
        before = editor._cleaned_image.tobytes()
        for cancel in ('escape', 'right', 'busy', 'mode'):
            editor._pick_fill_btn.click()
            self.assertTrue(editor.preview._color_picking)
            canvas = editor.preview._label
            QTest.mouseClick(canvas, Qt.LeftButton, pos=QPoint(1, 1))
            self.assertTrue(editor.preview._color_picking)
            if cancel == 'escape':
                QTest.keyClick(canvas, Qt.Key_Escape)
            elif cancel == 'right':
                QTest.mouseClick(canvas, Qt.RightButton)
            elif cancel == 'busy':
                editor._requesting_page = True
                editor._update_repair_controls()
                editor._requesting_page = False
                editor._update_repair_controls()
            else:
                editor._strip_toggle.toggle()
            self.assertFalse(editor.preview._color_picking)
            self.assertFalse(editor._pick_fill_btn.isChecked())
            self.assertEqual(editor._fill_color.name(), '#ffffff')
            self.assertEqual(editor._cleaned_image.tobytes(), before)

    def test_custom_fill_controls_respect_restored_region_and_background_jobs(self):
        output, _cleaned, _layout = self.fixture()
        editor = self.editor(output)
        editor.items[0]['restore_original'] = True
        editor._repair_box = (110, 130, 150, 180)
        editor._update_repair_controls()
        self.assertFalse(editor._fill_custom_btn.isEnabled())
        editor._fill_color = QColor('#12ab5d')
        before = editor._cleaned_image.tobytes()
        editor._fill_repair_region(editor._fill_color.getRgb()[:3])
        self.assertEqual(editor._cleaned_image.tobytes(), before)
        editor._repair_worker = object()
        editor._update_repair_controls()
        self.assertFalse(editor._pick_fill_btn.isEnabled())
        self.assertFalse(editor._fill_color_btn.isEnabled())
        editor._repair_worker = None


if __name__ == '__main__':
    unittest.main()
