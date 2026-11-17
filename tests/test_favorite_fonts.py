from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from comic_translate_desktop import config
from comic_translate_desktop.font_library import available_fonts, font_reference
from comic_translate_desktop.ui.editor_page import EditorPage
from comic_translate_desktop.ui.favorite_fonts import FavoriteFontBar
from comic_translate_desktop.ui.searchable_combo import SearchableFontCombo
from tests.qt_utils import destroy_widget


class FavoriteFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.preferences = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.preferences.name)

    @classmethod
    def tearDownClass(cls):
        cls.preferences.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        QSettings().clear()
        for key, value in (('PROJECT_ROOT', self.root), ('CONFIG_PATH', self.root / 'config.yaml')):
            setting = patch.object(config, key, value)
            setting.start()
            self.addCleanup(setting.stop)
        self.references = [font_reference(font.path) for font in available_fonts()][:10]
        self.assertGreaterEqual(len(self.references), 10)

    def editor(self):
        output = self.root / 'output' / 'page.png'
        cleaned = self.root / 'output_cleaned' / 'page_cleaned.png'
        layout = self.root / 'output_layout' / 'page_layout.json'
        for file in (output, cleaned, layout):
            file.parent.mkdir(exist_ok=True)
        for file in (output, cleaned):
            Image.new('RGB', (400, 600), 'white').save(file)
        layout.write_text(json.dumps([
            dict(text='译文', box=[20, 20, 150, 300], style='dialogue', font_size=24),
            dict(text='保留', box=[220, 20, 350, 300], style='dialogue', font_size=24),
        ]), encoding='utf-8')
        editor = EditorPage()
        self.addCleanup(self.destroy_editor, editor)
        self.assertTrue(editor.load_page(output))
        editor.resize(1100, 800)
        editor.show()
        editor.activateWindow()
        self.app.processEvents()
        return editor

    @staticmethod
    def destroy_editor(editor):
        editor._dirty = False
        destroy_widget(editor)

    def bar(self):
        bar = FavoriteFontBar(config.load_ai_config())
        self.addCleanup(destroy_widget, bar)
        return bar

    def test_slots_persist_with_fixed_numbers_and_a_nine_font_limit(self):
        bar = self.bar()
        for reference in self.references[:9]:
            self.assertTrue(bar.add_font(reference))
        self.assertFalse(bar.add_font(self.references[9]))
        self.assertTrue(bar.add_font(self.references[0]))
        slots = list(bar.slots)
        slots[3] = ''
        bar.set_slots(slots)
        restored = self.bar()
        self.assertEqual(restored.slots, slots)
        self.assertTrue(restored.add_font(self.references[9]))
        self.assertEqual(restored.slots[3], self.references[9])
        self.assertEqual(restored.slots[8], self.references[8])

    def test_configure_cancel_and_accept_assign_exact_shortcut_slots(self):
        bar = self.bar()
        def edit(accept):
            dialog = self.app.activeModalWidget()
            self.assertIsInstance(dialog, QDialog)
            combos = dialog.findChildren(SearchableFontCombo)
            self.assertEqual(len(combos), 9)
            combos[8].setCurrentIndex(combos[8].findData(self.references[0]))
            actions = dialog.findChild(QDialogButtonBox)
            actions.button(QDialogButtonBox.Ok if accept else QDialogButtonBox.Cancel).click()
        QTimer.singleShot(0, lambda: edit(False))
        bar.configure()
        self.assertEqual(bar.slots, [''] * 9)
        QTimer.singleShot(0, lambda: edit(True))
        bar.configure()
        self.assertEqual(bar.slots, [''] * 8 + [self.references[0]])

    def test_digits_switch_only_selected_block_and_remain_normal_text_input(self):
        editor = self.editor()
        editor._favorite_fonts.set_slots(self.references[:9])
        editor.block_list.setFocus()
        self.app.processEvents()
        for slot in range(9):
            QTest.keyClick(editor.block_list, Qt.Key_1 + slot)
            self.assertEqual(editor.items[0].get('font_reference'), self.references[slot])
            self.assertNotIn('font_reference', editor.items[1])
        editor._text_input.setFocus()
        editor._text_input.selectAll()
        QTest.keyClicks(editor._text_input, '123456789')
        self.assertEqual(editor._text_input.toPlainText(), '123456789')
        self.assertEqual(editor.items[0]['font_reference'], self.references[8])
        editor._size_spin.setFocus()
        QTest.keyClick(editor._size_spin, Qt.Key_1)
        self.assertEqual(editor.items[0]['font_reference'], self.references[8])
        self.assertTrue(editor.save_image())
        saved = json.loads(editor.layout_path.read_text(encoding='utf-8'))
        self.assertEqual(saved[0]['font_reference'], self.references[8])
        self.assertNotIn('font_reference', saved[1])

    def test_add_current_font_resolves_style_and_missing_fonts_are_unavailable(self):
        editor = self.editor()
        editor._style_combo.setCurrentIndex(editor._style_combo.findData('serious'))
        editor._favorite_fonts.add_button.click()
        self.assertEqual(editor._favorite_fonts.slots[0], font_reference(editor.config['font_map']['serious']))
        editor._favorite_fonts.set_slots(['missing.ttf'])
        self.assertFalse(editor._favorite_fonts.activate(0))
        self.assertIn('不可用', editor._favorite_fonts.buttons[0].toolTip())
