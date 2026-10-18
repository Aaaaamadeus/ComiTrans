from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from tests.qt_utils import destroy_widget
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import ImageFont
from PySide6.QtCore import Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from comic_translate_desktop import config
from comic_translate_desktop.font_library import (
    available_fonts, font_description, font_display_name, font_reference, inspect_font,
    resolve_font_reference,
)
from comic_translate_desktop.ui.font_picker import TranslationFontPicker
from comic_translate_desktop.ui.searchable_combo import SearchableFontCombo

ROOT = Path(__file__).resolve().parents[1]
FONT_ROOT = ROOT / 'comic-translate-ai' / 'font_file' / 'TC'


class BundledFontTests(unittest.TestCase):
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
        for key, value in (('PROJECT_ROOT', self.root), ('CONFIG_PATH', self.root / 'config.yaml')):
            setting = patch.object(config, key, value)
            setting.start()
            self.addCleanup(setting.stop)

    def test_all_curated_fonts_and_notices_are_bundled_intact_and_render_offline(self):
        manifest = json.loads((FONT_ROOT / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['families']), 10)
        self.assertEqual(sum(len(f['fonts']) for f in manifest['families']), 12)
        for asset in manifest['assets']:
            with self.subTest(file=asset['file']):
                path = FONT_ROOT / asset['file']
                self.assertEqual(path.stat().st_size, asset['bytes'])
                self.assertEqual(sha256(path.read_bytes()).hexdigest(), asset['sha256'])
        available = {font.path for font in available_fonts()}
        for family in manifest['families']:
            for item in family['fonts']:
                path = FONT_ROOT / item['file']
                with self.subTest(font=family['name'], file=item['file']):
                    self.assertIn(path, available)
                    face = ImageFont.truetype(str(path), 24)
                    self.assertIsNotNone(face.getmask(manifest['sample_text']).getbbox())
                    self.assertTrue((path.parent / (path.stem + '-EMBEDDED-NOTICES.txt')).is_file())
            self.assertTrue(family['upstream_notices'])

    def test_bundled_reference_survives_app_relocation_and_frozen_resource_root(self):
        original = FONT_ROOT / '08-SourceHanSansTC' / 'SourceHanSansTC-Heavy.otf'
        reference = font_reference(original)
        self.assertEqual(reference, 'font_file/TC/08-SourceHanSansTC/SourceHanSansTC-Heavy.otf')
        config.save_ai_config({'translation_font': reference})
        moved_ai = self.root / 'moved-app' / '_internal' / 'comic-translate-ai'
        destination = moved_ai / reference
        destination.parent.mkdir(parents=True)
        shutil.copyfile(original, destination)
        with patch.object(config, 'AI_ROOT', moved_ai):
            self.assertEqual(resolve_font_reference(reference), destination)
            loaded = config.load_ai_config()
            self.assertTrue(loaded['translation_font_active'])
            self.assertEqual(set(loaded['font_map'].values()), {str(destination)})
            self.assertIn(destination, {font.path for font in available_fonts(loaded)})

    def test_manga_effect_fonts_include_both_scripts_and_original_notices(self):
        root = FONT_ROOT.parent / 'Manga'
        manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['families']), 2)
        available = {font.path for font in available_fonts()}
        for asset in manifest['assets']:
            path = root / asset['file']
            self.assertEqual(path.stat().st_size, asset['bytes'])
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), asset['sha256'])
        for family in manifest['families']:
            self.assertEqual(len(family['fonts']), 2)
            self.assertTrue((root / family['id'] / 'SIL_Open_Font_License_1.1.txt').is_file())
            for item in family['fonts']:
                path = root / item['file']
                self.assertIn(path, available)
                face = inspect_font(path)
                label = font_display_name(face)
                self.assertIn('简体' if 'CJKsc' in path.name else '繁体', label)
                self.assertIn('特黑', label)
                self.assertEqual(item['sample_missing'], '')
                self.assertIsNotNone(ImageFont.truetype(str(path), 32).getmask(manifest['sample_text']).getbbox())

    def test_bundled_fonts_have_short_chinese_names_and_explicit_weights(self):
        medium = inspect_font(FONT_ROOT / '08-SourceHanSansTC' / 'SourceHanSansTC-Medium.otf')
        heavy = inspect_font(FONT_ROOT / '08-SourceHanSansTC' / 'SourceHanSansTC-Heavy.otf')
        self.assertEqual(font_display_name(medium), '思源黑体（繁体） · 中粗')
        self.assertEqual(font_display_name(heavy), '思源黑体（繁体） · 特粗')
        self.assertIn('Source Han Sans TC', font_description(heavy))
        loaded = config.save_ai_config({'translation_font': font_reference(heavy.path)})
        picker = TranslationFontPicker(loaded)
        self.addCleanup(destroy_widget, picker)
        self.assertEqual(picker.combo.currentData(), font_reference(heavy.path))
        self.assertIn(font_display_name(heavy), picker.name_label.text())
        self.assertTrue(picker.name_label.wordWrap())

    def test_original_name_search_selects_correct_reference_even_when_labels_match(self):
        combo = SearchableFontCombo()
        self.addCleanup(destroy_widget, combo)
        combo.addItem('源泉圆体 · 常规', 'tw')
        combo.setItemData(0, 'GenSenRounded2 TW Regular', Qt.ToolTipRole)
        combo.addItem('源泉圆体 · 常规', 'tc')
        combo.setItemData(1, 'GenSenRounded2 TC Regular', Qt.ToolTipRole)
        changes = []
        combo.currentIndexChanged.connect(lambda index: changes.append(combo.itemData(index)))
        combo.show()
        combo.lineEdit().setFocus()
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), 'gensenrounded2 tc')
        QTest.qWait(30)
        self.assertEqual(combo.currentData(), 'tw')
        self.assertEqual(changes, [])
        popup = combo.completer().popup()
        self.assertEqual(combo.completer().completionCount(), 1)
        popup.setCurrentIndex(combo.completer().completionModel().index(0, 0))
        QTest.keyClick(popup, Qt.Key_Return)
        self.assertEqual(combo.currentData(), 'tc')
        self.assertEqual(changes, ['tc'])


if __name__ == '__main__':
    unittest.main()
