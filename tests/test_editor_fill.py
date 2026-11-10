from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
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


if __name__ == '__main__':
    unittest.main()
