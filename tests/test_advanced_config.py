from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel

from comic_translate_desktop import config
from comic_translate_core.detector_paths import LEGACY_PATH, LINE_FILE, SPLIT_PATH
from comic_translate_desktop.i18n import set_ui_language, tr
from comic_translate_desktop.ui.advanced_config import AdvancedConfigSection
from comic_translate_desktop.ui.api_config_page import ApiConfigPage
from tests.qt_utils import destroy_widget


class AdvancedConfigTests(unittest.TestCase):
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
        self.addCleanup(set_ui_language, 'zh-CN')
        set_ui_language('zh-CN')

    def test_load_clamps_every_tuning_knob_to_its_documented_range(self):
        config.save_ai_config({'max_workers': 0, 'pdf_dpi': 9999,
                               'font_size': 2, 'font_probe_samples': 99})
        loaded = config.load_ai_config()
        self.assertEqual(loaded['max_workers'], 1)
        self.assertEqual(loaded['pdf_dpi'], 400)
        self.assertEqual(loaded['font_size'], 8)
        self.assertEqual(loaded['font_probe_samples'], 5)

        config.save_ai_config({'max_workers': 'many', 'pdf_dpi': 'n/a',
                               'font_size': '', 'font_probe_samples': 'few'})
        loaded = config.load_ai_config()
        self.assertEqual(
            (loaded['max_workers'], loaded['pdf_dpi'], loaded['font_size'],
             loaded['font_probe_samples']),
            (4, 200, 16, 3))

    def test_model_defaults_resolve_under_the_models_root(self):
        defaults = config.model_defaults()
        self.assertEqual(set(defaults), {
            'detector_model', 'lama_model', 'charspot_ocr_model', 'ocr_model', 'baberu_ocr_model'})
        self.assertEqual(Path(defaults['lama_model']).parent.name, 'manga-lama')
        self.assertEqual(Path(defaults['charspot_ocr_model']).name, 'charspot-small')
        self.assertEqual(Path(defaults['ocr_model']).name, 'manga-ocr-onnx')
        self.assertEqual(Path(defaults['baberu_ocr_model']).name, 'baberu-ocr')
        loaded = config.load_ai_config()
        for key, value in defaults.items():
            self.assertEqual(loaded[key], value)

    def test_fingerprint_tracks_charspot_but_not_tuning_knobs(self):
        loaded = config.load_ai_config()
        baseline = config.config_fingerprint(loaded)
        self.assertEqual(
            baseline,
            config.config_fingerprint(dict(loaded, max_workers=8, pdf_dpi=96,
                                           font_size=40, font_probe_samples=5)))
        self.assertNotEqual(
            baseline,
            config.config_fingerprint(dict(loaded, charspot_ocr_model='D:/elsewhere/charspot')))

    def test_section_round_trips_values_and_reset_restores_defaults(self):
        config.save_ai_config({'max_workers': 7, 'pdf_dpi': 300, 'font_size': 24,
                               'font_probe_samples': 5, 'lama_model': 'D:/models/lama.onnx'})
        loaded = config.load_ai_config()
        section = AdvancedConfigSection(loaded)
        self.addCleanup(destroy_widget, section)
        values = section.values()
        self.assertEqual(values['max_workers'], 7)
        self.assertEqual(values['pdf_dpi'], 300)
        self.assertEqual(values['font_size'], 24)
        self.assertEqual(values['font_probe_samples'], 5)
        self.assertEqual(Path(values['lama_model']), Path('D:/models/lama.onnx'))
        self.assertIn('5', section._model_status.text())

        section.reset_to_defaults()
        values = section.values()
        self.assertEqual(
            (values['max_workers'], values['pdf_dpi'], values['font_size'],
             values['font_probe_samples']),
            (4, 200, 16, 3))
        self.assertEqual(Path(values['lama_model']),
                         Path(config.model_defaults()['lama_model']))

    def test_tuning_change_marks_the_settings_page_unsaved(self):
        page = ApiConfigPage(config.load_ai_config())
        self.addCleanup(destroy_widget, page)
        self.assertEqual(page._save_status.text(), tr('修改后点击保存，下次任务生效'))
        page._advanced._workers.setValue(9)
        self.assertIn('未保存', page._save_status.text())
        self.assertEqual(page.values()['max_workers'], 9)

    def test_settings_page_round_trips_advanced_values_through_config(self):
        page = ApiConfigPage(config.load_ai_config())
        self.addCleanup(destroy_widget, page)
        page._advanced._workers.setValue(9)
        page._advanced._pdf_dpi.setValue(300)
        page._advanced._path_fields['lama_model'].setText('D:/models/custom-lama.onnx')
        config.save_ai_config(page.values())

        saved = config.load_ai_config()
        self.assertEqual(saved['max_workers'], 9)
        self.assertEqual(saved['pdf_dpi'], 300)
        self.assertEqual(Path(saved['lama_model']), Path('D:/models/custom-lama.onnx'))
        page.load_config(saved)
        self.assertEqual(page.values()['max_workers'], 9)
        self.assertEqual(page.values()['pdf_dpi'], 300)
        self.assertEqual(Path(page.values()['lama_model']), Path('D:/models/custom-lama.onnx'))

    def test_saving_settings_keeps_automatic_detector_selection(self):
        models = self.root / 'models'
        with patch.object(config, 'MODELS_ROOT', models):
            legacy = models / LEGACY_PATH
            legacy.parent.mkdir(parents=True)
            legacy.touch()
            loaded = config.load_ai_config()
            self.assertEqual(Path(loaded['detector_model']), legacy)
            page = ApiConfigPage(loaded)
            self.addCleanup(destroy_widget, page)
            page._advanced._workers.setValue(6)
            config.save_ai_config(page.values())
            for part in (SPLIT_PATH, SPLIT_PATH.with_name(LINE_FILE)):
                path = models / part
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertEqual(Path(config.load_ai_config()['detector_model']), models / SPLIT_PATH)

    def test_an_inaccessible_model_does_not_prevent_opening_settings(self):
        blocked = self.root / 'unreadable.onnx'
        loaded = config.save_ai_config({'detector_model': str(blocked)})
        original = Path.is_file

        def check(path):
            if path == blocked:
                raise PermissionError('Access denied')
            return original(path)

        with patch.object(Path, 'is_file', check):
            page = ApiConfigPage(loaded)
        self.addCleanup(destroy_widget, page)
        self.assertIn(str(blocked), page._advanced._model_status.toolTip())

    def test_new_page_strings_are_translated_in_english_and_japanese(self):
        expected = {
            'en': dict(tab='04  Detailed settings', workers='Max parallel pages',
                       group='Model files', reset='Restore recommended defaults',
                       labels=['Detector model', 'Inpainting model', 'CharSpot OCR folder',
                               'manga-ocr folder', 'Baberu OCR folder']),
            'ja': dict(tab='04  詳細設定', workers='最大並列ページ数',
                       group='モデルファイル', reset='推奨の既定値に戻す',
                       labels=['検出モデル', '修復モデル', 'CharSpot OCR フォルダー',
                               'manga-ocr フォルダー', 'Baberu OCR フォルダー']),
        }
        for code, spec in expected.items():
            with self.subTest(language=code):
                set_ui_language(code)
                self.assertEqual(tr('04  详细配置'), spec['tab'])
                self.assertEqual(tr('最大并行页数'), spec['workers'])
                section = AdvancedConfigSection(config.load_ai_config())
                self.addCleanup(destroy_widget, section)
                labels = [label.text() for label in section.findChildren(QLabel)]
                groups = [group.title() for group in section.findChildren(QGroupBox)]
                self.assertIn(spec['workers'], labels)
                self.assertIn(spec['group'], groups)
                for label in spec['labels']:
                    self.assertIn(label, labels)
                self.assertEqual(section._reset_btn.text(), spec['reset'])
                if code == 'en':
                    # English captures must not leak any source-language label.
                    for text in labels + groups:
                        self.assertFalse(any('\u3400' <= char <= '\u9fff' for char in text), text)
        set_ui_language('zh-CN')


if __name__ == '__main__':
    unittest.main()
