from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from comic_translate_core.layout_options import normalize_text_color
from comic_translate_desktop import config
from comic_translate_desktop.ui.color_picker import TextColorPicker
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.worker import BatchWorker
from tests.qt_utils import destroy_widget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'comic-translate-ai/main'))
from vertical_typesetter import VerticalTypesetter


class TextColorTests(unittest.TestCase):
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
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in (('CONFIG_PATH', self.root / 'config.yaml'), ('PROJECT_ROOT', self.root)):
            setting = patch.object(config, name, value)
            setting.start()
            self.addCleanup(setting.stop)

    def test_rgb_color_normalization_and_safe_fallback(self):
        for value, expected in (('#F0a', '#ff00aa'), (' #1A2b3C ', '#1a2b3c'),
                                (None, None), ('', None), ('red', None), ('#zzzzzz', None),
                                ('#ff000080', None), ([], None), ({}, None)):
            self.assertEqual(normalize_text_color(value), expected)

    def typesetter(self):
        return VerticalTypesetter({'dialogue': str(config.AI_ROOT / config.FONT_DEFAULTS['dialogue'])}, 32)

    def test_custom_fill_reaches_both_directions_outlines_and_vertical_runs(self):
        setter = self.typesetter()
        for direction in (0, 1):
            for effect in ('auto', 'outlined', 'hollow'):
                with self.subTest(direction=direction, effect=effect):
                    image = Image.new('RGB', (400, 600), '#cccccc')
                    setter.draw_text(image, [40, 40, 360, 560], '故事……\n繼續——', 'dialogue',
                                     direction=direction, target_font_size=32, manual_layout=True,
                                     text_effect=effect, text_color='#1a72c5')
                    self.assertIn((26, 114, 197), image.getdata())
                    self.assertGreater(sum(b > r + 15 and g > r + 5 for r, g, b in image.getdata()), 50)
                    self.assertIsNotNone(setter.last_render_layer)
                    if direction == 1:
                        cells = setter.last_layout_debug
                        self.assertEqual(len({v['column'] for v in cells if v['char'] == '…'}), 1)
                        self.assertEqual(len({v['column'] for v in cells if v['char'] == '—'}), 1)

    def test_auto_and_invalid_colors_keep_legacy_effect_pixels_without_leaking(self):
        setter = self.typesetter()
        def render(effect, color=None):
            image = Image.new('RGB', (240, 340), '#cccccc')
            setter.draw_text(image, [20, 20, 220, 320], '漫畫', 'dialogue',
                             direction=1, target_font_size=32, manual_layout=True,
                             text_effect=effect, text_color=color)
            return image.tobytes()
        for effect in ('auto', 'outlined', 'hollow'):
            original = render(effect)
            self.assertNotEqual(original, render(effect, '#ef2345'))
            self.assertEqual(original, render(effect))
            self.assertEqual(original, render(effect, '#not-a-color'))

    def test_picker_confirm_cancel_and_reset_emit_only_real_changes(self):
        picker = TextColorPicker('#123456')
        self.addCleanup(destroy_widget, picker)
        changes = []
        picker.color_changed.connect(changes.append)
        with patch('comic_translate_desktop.ui.color_picker.QColorDialog.getColor', return_value=QColor()):
            picker.choose_button.click()
        self.assertEqual(changes, [])
        self.assertEqual(picker.color, '#123456')
        with patch('comic_translate_desktop.ui.color_picker.QColorDialog.getColor', return_value=QColor('#E34A62')):
            picker.choose_button.click()
        self.assertEqual(changes, ['#e34a62'])
        self.assertEqual(picker.choose_button.text(), '#E34A62')
        picker.reset_button.click()
        self.assertEqual(changes, ['#e34a62', None])
        self.assertIsNone(picker.color)
        self.assertFalse(picker.reset_button.isEnabled())

    def window(self):
        with patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
        self.addCleanup(destroy_widget, window)
        return window

    def test_default_color_persists_resets_and_reuses_pipeline(self):
        window = self.window()
        pipeline = SimpleNamespace(text_color=None)
        window.pipeline = pipeline
        fingerprint = config.config_fingerprint(window.config)
        window._translation_color.set_color('#2874a6', emit=True)
        self.assertEqual(config.load_ai_config()['text_color'], '#2874a6')
        self.assertIs(window.pipeline, pipeline)
        self.assertEqual(pipeline.text_color, '#2874a6')
        self.assertEqual(config.config_fingerprint(window.config), fingerprint)
        restored = self.window()
        self.assertEqual(restored._translation_color.color, '#2874a6')
        window._translation_color.reset_button.click()
        self.assertIsNone(config.load_ai_config()['text_color'])
        self.assertIsNone(pipeline.text_color)

    def test_failed_color_save_restores_selection_and_pipeline(self):
        config.save_ai_config({'text_color': '#204080'})
        window = self.window()
        pipeline = window.pipeline = SimpleNamespace(text_color='#204080')
        with patch('comic_translate_desktop.ui.main_window.save_ai_config', side_effect=OSError('read only')):
            window._translation_color.set_color('#ff0000', emit=True)
        self.assertEqual(window._translation_color.color, '#204080')
        self.assertEqual(pipeline.text_color, '#204080')
        self.assertEqual(config.load_ai_config()['text_color'], '#204080')

    def test_default_color_is_locked_during_translation_and_warmup(self):
        window = self.window()
        with patch.object(window, 'worker', object()):
            window._update_actions()
            self.assertFalse(window._translation_color.isEnabled())
        with patch.object(window, 'warmup_worker', SimpleNamespace(isRunning=lambda: True)):
            window._update_actions()
            self.assertFalse(window._translation_color.isEnabled())
        window._update_actions()
        self.assertTrue(window._translation_color.isEnabled())

    def test_worker_applies_color_without_rebuilding_models(self):
        settings = config.load_ai_config()
        settings['text_color'] = '#f37'
        pipeline = SimpleNamespace()
        BatchWorker._apply_api_config(pipeline, settings)
        self.assertEqual(pipeline.text_color, '#ff3377')


if __name__ == '__main__':
    unittest.main()
