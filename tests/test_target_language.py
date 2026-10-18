from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'comic-translate-ai' / 'main'))

from PySide6.QtCore import QSettings, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from comic_translate_core.chinese import ChineseConversionError, convert_chinese, normalize_target_language
from comic_translate_desktop import config
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.worker import BatchWorker
import comic_translator_pipeline as pipeline_module
from comic_translator_pipeline import ComicTranslatorPipeline, TranslationError


class ChineseOutputTests(unittest.TestCase):
    def test_script_conversion_handles_phrases_and_preserves_other_text(self):
        simplified = '发现头发变长了，漫画终于开始了。ABC 123？！\nかな～'
        traditional = '發現頭髮變長了，漫畫終於開始了。ABC 123？！\nかな～'
        self.assertEqual(convert_chinese(simplified, 'zh-Hant'), traditional)
        self.assertEqual(convert_chinese(traditional, 'zh-Hans'), simplified)
        self.assertEqual(convert_chinese('', 'zh-Hant'), '')

    def test_legacy_or_unknown_selection_defaults_to_simplified(self):
        for value in (None, '', 'zh-CN', 'unknown'):
            self.assertEqual(normalize_target_language(value), 'zh-Hans')
        for value in ('zh-Hant', 'zh_TW', 'zh-HK', 'traditional'):
            self.assertEqual(normalize_target_language(value), 'zh-Hant')

    def test_parallel_pages_can_convert_both_variants(self):
        jobs = [('发现头发变长了', 'zh-Hant', '發現頭髮變長了'),
                ('漫畫終於開始了', 'zh-Hans', '漫画终于开始了')] * 12
        with ThreadPoolExecutor(max_workers=4) as pool:
            actual = list(pool.map(lambda job: convert_chinese(job[0], job[1]), jobs))
        self.assertEqual(actual, [job[2] for job in jobs])

    @staticmethod
    def pipeline(target, *, multimodal=False):
        result = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
        result.api_key, result.api_base_url, result.translation_model = 'test-key', 'https://example.invalid/v1', 'test-model'
        result.translation_prompt, result.chinese_names = '保持轻松语气', '主角'
        result.source_language_name = '日语'
        result.target_language = target
        result.multimodal = multimodal
        result.progress_callback = result.cancel_callback = None
        return result

    def test_prompt_continuation_and_model_output_all_follow_selected_script(self):
        for target, target_name, response_texts, expected in (
            ('zh-Hant', '繁體中文', ['发现头发变长了', '漫画终于开始了'], ['發現頭髮變長了', '漫畫終於開始了']),
            ('zh-Hans', '简体中文', ['發現頭髮變長了', '漫畫終於開始了'], ['发现头发变长了', '漫画终于开始了']),
        ):
            for multimodal in (False, True):
                with self.subTest(target=target, multimodal=multimodal):
                    pipeline = self.pipeline(target, multimodal=multimodal)
                    client = Mock()
                    client.chat.completions.create.side_effect = [
                        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                            content=json.dumps({'translations': [text]}, ensure_ascii=False)))])
                        for text in response_texts
                    ]
                    with patch.object(pipeline_module, 'OpenAI', return_value=client):
                        actual = pipeline.translate_page_batch(['髪が伸びた', '漫画が始まる'], np.zeros((2, 2, 3), np.uint8))
                    self.assertEqual(actual, expected)
                    self.assertEqual(client.chat.completions.create.call_count, 2)
                    for call in client.chat.completions.create.call_args_list:
                        messages = call.kwargs['messages']
                        self.assertIn('目标语言：' + target_name, messages[0]['content'])
                        self.assertIn('译成' + target_name, messages[1]['content'][0]['text'])

    def test_blank_page_skips_api_and_conversion(self):
        pipeline = self.pipeline('zh-Hant')
        with patch.object(pipeline_module, 'OpenAI') as api, \
             patch.object(pipeline_module, 'convert_chinese') as converter:
            self.assertEqual(pipeline.translate_page_batch(['', '  '], None), ['', ''])
        api.assert_not_called()
        converter.assert_not_called()

    def test_local_conversion_failure_is_not_reported_as_network_failure(self):
        pipeline = self.pipeline('zh-Hant')
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"translations":["你好"]}'))])
        with patch.object(pipeline_module, 'OpenAI', return_value=client), \
             patch.object(pipeline_module, 'convert_chinese', side_effect=ChineseConversionError('本地简繁转换失败')):
            with self.assertRaisesRegex(TranslationError, '本地简繁转换失败') as error:
                pipeline.translate_page_batch(['こんにちは'], None)
        self.assertTrue(error.exception.fatal)
        self.assertEqual(client.chat.completions.create.call_count, 1)


class TargetLanguageUiTests(unittest.TestCase):
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

    def window(self):
        with patch.object(MainWindow, '_start_warmup'):
            result = MainWindow()
        self.addCleanup(self.destroy_window, result)
        return result

    @staticmethod
    def destroy_window(window):
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_font_and_alignment_controls_are_inside_collapsed_translation_preferences(self):
        window = self.window()
        window.show()
        self.app.processEvents()
        self.assertTrue(window._pref_container.isAncestorOf(window._font_picker))
        self.assertTrue(window._pref_container.isAncestorOf(window._translation_alignment))
        self.assertFalse(window._font_picker.isVisible())
        self.assertFalse(window._translation_alignment.isVisible())
        window._pref_toggle.click()
        self.app.processEvents()
        self.assertTrue(window._font_picker.isVisible())
        self.assertTrue(window._translation_alignment.isVisible())
        window._pref_toggle.click()
        self.assertFalse(window._font_picker.isVisible())
        self.assertFalse(window._translation_alignment.isVisible())

    def test_default_alignment_persists_without_reloading_models_or_changing_fonts(self):
        self.assertEqual(config.load_ai_config()['vertical_alignment'], 'center')
        window = self.window()
        before = config.config_fingerprint(window.config)
        pipeline = SimpleNamespace(vertical_alignment='center')
        window.pipeline = pipeline
        fonts = dict(window.config['font_map'])
        for alignment in ('top', 'bottom', 'center'):
            window._translation_alignment.setCurrentIndex(window._translation_alignment.findData(alignment))
            self.assertEqual(config.load_ai_config()['vertical_alignment'], alignment)
            self.assertEqual(pipeline.vertical_alignment, alignment)
            self.assertIs(window.pipeline, pipeline)
            self.assertEqual(config.config_fingerprint(window.config), before)
            self.assertEqual(window.config['font_map'], fonts)
        window._translation_alignment.setCurrentIndex(window._translation_alignment.findData('bottom'))
        restored = self.window()
        self.assertEqual(restored._translation_alignment.currentData(), 'bottom')

    def test_default_alignment_save_failure_restores_old_choice(self):
        window = self.window()
        with patch('comic_translate_desktop.ui.main_window.save_ai_config', side_effect=OSError('read-only')):
            window._translation_alignment.setCurrentIndex(window._translation_alignment.findData('top'))
        self.assertEqual(window._translation_alignment.currentData(), 'center')
        self.assertEqual(window.config['vertical_alignment'], 'center')

    def test_default_alignment_locked_during_translation_and_warmup(self):
        window = self.window()
        for attribute in ('worker', 'warmup_worker'):
            setattr(window, attribute, SimpleNamespace(isRunning=lambda: True))
            try:
                window._update_actions()
                self.assertFalse(window._translation_alignment.isEnabled())
                self.assertFalse(window._font_picker.isEnabled())
            finally:
                setattr(window, attribute, None)
            window._update_actions()
            self.assertTrue(window._translation_alignment.isEnabled())

    def test_worker_snapshots_default_alignment_for_reused_pipeline(self):
        settings = config.load_ai_config()
        settings['vertical_alignment'] = 'top'
        worker = BatchWorker([], self.root, settings)
        settings['vertical_alignment'] = 'bottom'
        pipeline = SimpleNamespace(vertical_alignment='center')
        worker._apply_api_config(pipeline, worker._config)
        self.assertEqual(pipeline.vertical_alignment, 'top')
        self.assertEqual(worker._config['vertical_alignment'], 'top')

    def test_workbench_choice_persists_preserves_fonts_and_reuses_models(self):
        self.assertEqual(config.load_ai_config()['target_language'], 'zh-Hans')
        chosen_font = 'font_file/TC/03-Iansui/Iansui-Regular.ttf'
        config.save_ai_config({'translation_font': chosen_font})
        window = self.window()
        pipeline = SimpleNamespace(target_language='zh-Hans')
        window.pipeline = pipeline
        before = config.config_fingerprint(window.config)
        self.assertTrue(window.translate_tab.isAncestorOf(window._target_language))
        window._target_language.setCurrentIndex(window._target_language.findData('zh-Hant'))
        loaded = config.load_ai_config()
        self.assertEqual(loaded['target_language'], 'zh-Hant')
        self.assertEqual(config.load_yaml(config.CONFIG_PATH)['translation_font'], chosen_font)
        self.assertIs(window.pipeline, pipeline)
        self.assertEqual(pipeline.target_language, 'zh-Hant')
        self.assertEqual(config.config_fingerprint(loaded), before)
        self.assertIn('繁體中文', window._elapsed_label.text())
        self.assertIn('從這裏開始', window._font_picker.preview.toolTip())
        restored = self.window()
        self.assertEqual(restored._target_language.currentData(), 'zh-Hant')
        restored._target_language.setCurrentIndex(restored._target_language.findData('zh-Hans'))
        self.assertEqual(config.load_ai_config()['target_language'], 'zh-Hans')

    def test_save_failure_restores_previous_selection(self):
        window = self.window()
        with patch('comic_translate_desktop.ui.main_window.save_ai_config', side_effect=OSError('config read-only')):
            window._target_language.setCurrentIndex(window._target_language.findData('zh-Hant'))
        self.assertEqual(window._target_language.currentData(), 'zh-Hans')
        self.assertEqual(window.config['target_language'], 'zh-Hans')
        self.assertEqual(config.load_ai_config()['target_language'], 'zh-Hans')

    def test_worker_snapshots_selection_and_updates_reused_pipeline(self):
        original = config.load_ai_config()
        original['target_language'] = 'zh-Hant'
        worker = BatchWorker([], self.root, original)
        original['target_language'] = 'zh-Hans'
        pipeline = SimpleNamespace(target_language='zh-Hans')
        worker._apply_api_config(pipeline, worker._config)
        self.assertEqual(pipeline.target_language, 'zh-Hant')
        self.assertEqual(worker._config['target_language'], 'zh-Hant')

    def test_translation_controls_are_disabled_during_a_batch(self):
        window = self.window()
        window.worker = object()
        try:
            window._update_actions()
            self.assertFalse(window._target_language.isEnabled())
        finally:
            window.worker = None
        window._update_actions()
        self.assertTrue(window._target_language.isEnabled())


if __name__ == '__main__':
    unittest.main()
