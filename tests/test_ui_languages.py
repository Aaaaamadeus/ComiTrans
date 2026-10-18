from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import string
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from comic_translate_desktop import config
from comic_translate_desktop.i18n import (
    UI_LANGUAGES, catalog_directory, initialize_ui_language, install_qt_language,
    load_ui_catalog, normalize_ui_language, set_ui_language, tr, ui_language,
)
from comic_translate_desktop.ui.language_dialog import InterfaceLanguageDialog, choose_interface_language
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.log_panel import LogPanel
from tests.qt_utils import destroy_widget

ROOT = Path(__file__).resolve().parents[1]


class UiLanguageTests(unittest.TestCase):
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
        self.addCleanup(self.restore_chinese)
        self.restore_chinese()

    def restore_chinese(self):
        set_ui_language('zh-CN')
        install_qt_language(self.app)

    @staticmethod
    def destroy_window(window):
        window.editor_page._dirty = False
        destroy_widget(window)

    def window(self, code='zh-CN'):
        config.save_ai_config({'ui_language': code, 'ui_language_selected': True})
        set_ui_language(code)
        with patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
        self.addCleanup(self.destroy_window, window)
        return window

    def test_chinese_is_default_regardless_of_os_locale_and_invalid_value(self):
        settings = config.load_ai_config()
        self.assertEqual(settings['ui_language'], 'zh-CN')
        self.assertFalse(settings['ui_language_selected'])
        for value, expected in ((None, 'zh-CN'), ('fr', 'zh-CN'), ('zh-TW', 'zh-CN'),
                                ('en_US', 'en'), ('en-GB', 'en'), ('ja-JP', 'ja')):
            self.assertEqual(normalize_ui_language(value), expected)

    def test_first_launch_selects_once_and_preserves_translation_settings(self):
        config.save_ai_config({'target_language': 'zh-Hant', 'chinese_names': '路飞\n娜美',
                               'translation_prompt': '保留原有背景', 'font_size': 37, 'custom_setting': 'keep'})
        chooser = Mock(return_value='ja')
        self.assertEqual(initialize_ui_language(self.app, choose_language=chooser), 'ja')
        chooser.assert_called_once_with('zh-CN')
        loaded = config.load_ai_config()
        self.assertTrue(loaded['ui_language_selected'])
        self.assertEqual(loaded['target_language'], 'zh-Hant')
        self.assertEqual(loaded['chinese_names'], '路飞\n娜美')
        self.assertEqual(loaded['translation_prompt'], '保留原有背景')
        self.assertEqual(loaded['font_size'], 37)
        self.assertEqual(loaded['raw']['custom_setting'], 'keep')
        chooser.reset_mock()
        self.assertEqual(initialize_ui_language(self.app, choose_language=chooser), 'ja')
        chooser.assert_not_called()

    def test_default_choice_is_persisted_so_chinese_also_prompts_only_once(self):
        chooser = Mock(return_value='zh-CN')
        initialize_ui_language(self.app, choose_language=chooser)
        initialize_ui_language(self.app, choose_language=chooser)
        chooser.assert_called_once()
        self.assertTrue(config.load_ai_config()['ui_language_selected'])

    def test_first_launch_write_failure_keeps_session_choice_and_reports_failure(self):
        with patch('comic_translate_desktop.config.save_ai_config', side_effect=OSError('read only')), \
             patch('PySide6.QtWidgets.QMessageBox.warning') as warning:
            initialize_ui_language(self.app, choose_language=lambda _: 'en')
        self.assertEqual(ui_language(), 'en')
        warning.assert_called_once()
        self.assertIn('not saved', warning.call_args.args[1])
        self.assertFalse(config.load_ai_config()['ui_language_selected'])

    def test_chooser_shows_native_names_and_previews_selected_language(self):
        dialog = InterfaceLanguageDialog()
        self.addCleanup(destroy_widget, dialog)
        self.assertEqual(dialog.selected_language, 'zh-CN')
        self.assertEqual([dialog.language_combo.itemText(i) for i in range(3)], ['中文', 'English', '日本語'])
        self.assertEqual(dialog.continue_button.text(), '继续')
        for code, expected in (('en', 'Continue'), ('ja', '続行')):
            dialog.language_combo.setCurrentIndex(dialog.language_combo.findData(code))
            self.assertEqual(dialog.continue_button.text(), expected)
        self.assertEqual(ui_language(), 'zh-CN')

    def test_native_qt_cancel_button_uses_selected_locale(self):
        for code, expected in (('en', 'Cancel'), ('ja', 'キャンセル'), ('zh-CN', '取消')):
            set_ui_language(code)
            install_qt_language(self.app)
            buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
            self.addCleanup(destroy_widget, buttons)
            self.assertIn(expected, buttons.button(QDialogButtonBox.Cancel).text())

    def test_closing_first_launch_chooser_uses_chinese_default(self):
        with patch('comic_translate_desktop.ui.language_dialog.InterfaceLanguageDialog') as dialog:
            dialog.return_value.exec.return_value = 0
            dialog.return_value.selected_language = 'ja'
            self.assertEqual(choose_interface_language(), 'zh-CN')
            dialog.return_value.deleteLater.assert_called_once()

    def test_all_catalog_keys_have_translations_and_matching_format_fields(self):
        en, ja = load_ui_catalog('en'), load_ui_catalog('ja')
        self.assertEqual(en.keys(), ja.keys())
        self.assertGreaterEqual(len(en), 475)
        for code, catalog in (('en', en), ('ja', ja)):
            for source, target in catalog.items():
                with self.subTest(code=code, source=source):
                    self.assertTrue(target)
                    if '{_0' in source or '{error}' in source:
                        fields = lambda text: sorted((name, spec, conversion) for _, name, spec, conversion
                                                    in string.Formatter().parse(text) if name is not None)
                        self.assertEqual(fields(source), fields(target))
        for path in (ROOT / 'comic_translate_desktop').rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr'
                        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                    source = node.args[0].value
                    if any('\u3400' <= char <= '\u9fff' for char in source):
                        self.assertIn(source, en, (path.name, node.lineno, source))

    def test_unknown_text_and_user_values_are_not_translated(self):
        set_ui_language('en')
        self.assertEqual(tr('未知的原文'), '未知的原文')
        self.assertEqual(tr('不可用：{_0}', _0='原稿「日本語」.png'), 'Unavailable: 原稿「日本語」.png')
        self.assertEqual(tr('此模式会将文本区域图片发送到配置的 OCR 服务。标准 HTTP 返回 {"text": "原文"}；完整接入协议见 docs/MULTILINGUAL_OCR.md。译文简繁在翻译页选择。').count('"text"'), 1)

    def test_frozen_catalog_path_and_missing_catalog_fallback(self):
        fake_root = self.root / 'frozen'
        with patch('sys._MEIPASS', str(fake_root), create=True):
            self.assertEqual(catalog_directory(), fake_root / 'assets/i18n')
        self.assertTrue((catalog_directory() / 'ja.json').is_file())
        load_ui_catalog.cache_clear()
        try:
            with patch('comic_translate_desktop.i18n.catalog_directory', return_value=fake_root):
                self.assertEqual(tr('设置', language='en'), '设置')
        finally:
            load_ui_catalog.cache_clear()

    def test_main_pages_choices_and_dynamic_counters_in_all_languages(self):
        for code, settings, translate, editor in (('zh-CN', '设置', '自动处理', '嵌字精修'),
                                                 ('en', 'Settings', 'Translate', 'Typesetting'),
                                                 ('ja', '設定', '自動翻訳', '写植調整')):
            with self.subTest(language=code):
                window = self.window(code)
                self.assertEqual(window._settings_btn.text(), settings)
                window.resize(1440, 900)
                window._apply_compact_layout()
                self.assertIn(translate, window._nav_auto.text())
                self.assertIn(editor, window._nav_editor.text())
                self.assertEqual(window.api_config_page._ui_language.currentData(), code)
                self.assertEqual(window._source_language.itemText(0), tr('日语'))
                self.assertEqual(window._target_language.itemText(0), tr('简体中文'))
                self.assertEqual(window._translation_alignment.itemText(0), tr('上对齐'))
                self.assertEqual(window._font_picker.combo.currentData(), '')
                path = self.root / f'原稿-{code}.png'
                Image.new('RGB', (30, 40), 'white').save(path)
                window._add_paths([path])
                self.assertEqual(window._file_count_label.text(), tr('{_0} 个文件', _0=1))
                self.assertIn(path.name, window.file_list.item(0).text())
                window._on_page_progress(2, 5)
                self.assertEqual(window._page_progress_label.text(), tr('已处理 {_0} / {_1} 页', _0=2, _1=5))
                self.assertIn(tr('气泡检测'), window.step_panel._labels['detect'][0].accessibleName())

    def test_settings_save_defers_language_until_next_launch_and_preserves_models(self):
        window = self.window()
        window.pipeline = Mock()
        pipeline = window.pipeline
        window.pipeline_fingerprint = config.config_fingerprint(window.config)
        before = config.load_ai_config()
        window.api_config_page._ui_language.setCurrentIndex(window.api_config_page._ui_language.findData('ja'))
        window._save_api_config()
        after = config.load_ai_config()
        self.assertEqual(after['ui_language'], 'ja')
        self.assertTrue(after['ui_language_selected'])
        self.assertEqual(window._settings_btn.text(), '设置')
        self.assertIn('下次启动', window.api_config_page._save_status.text())
        self.assertEqual(ui_language(), 'zh-CN')
        self.assertIs(window.pipeline, pipeline)
        for key in ('target_language', 'translation_font', 'font_map', 'source_language', 'vertical_alignment'):
            self.assertEqual(after[key], before[key])
        initialize_ui_language(self.app, choose_language=Mock(side_effect=AssertionError('already chosen')))
        self.assertEqual(ui_language(), 'ja')

    def test_failed_settings_save_retains_pending_language_and_current_config(self):
        window = self.window()
        window.api_config_page._ui_language.setCurrentIndex(window.api_config_page._ui_language.findData('en'))
        with patch('comic_translate_desktop.ui.main_window.save_ai_config', side_effect=OSError('read only')), \
             patch('comic_translate_desktop.ui.main_window.QMessageBox.warning') as warning:
            window._save_api_config()
        warning.assert_called_once()
        self.assertEqual(config.load_ai_config()['ui_language'], 'zh-CN')
        self.assertEqual(window.api_config_page._ui_language.currentData(), 'en')
        self.assertIn('未保存', window.api_config_page._save_status.text())

    def test_saving_interface_language_preserves_unsaved_editor_content_and_files(self):
        window = self.window()
        output = self.root / 'output/原稿.png'
        clean = self.root / 'output_cleaned/原稿_cleaned.png'
        layout = self.root / 'output_layout/原稿_layout.json'
        for path in (output, clean, layout):
            path.parent.mkdir()
        for path in (output, clean):
            Image.new('RGB', (400, 600), 'white').save(path)
        layout.write_text(json.dumps([dict(text='原译文', source_text='元のセリフ', style='dialogue',
            box=[30, 30, 300, 400], mask_box=[30, 30, 300, 400], direction=1,
            font_size=24)], ensure_ascii=False), encoding='utf-8')
        editor = window.editor_page
        editor.load_page(output)
        editor._text_input.setPlainText('未保存草稿\n日本語の名前')
        before = (output.read_bytes(), layout.read_bytes())
        window.api_config_page._ui_language.setCurrentIndex(window.api_config_page._ui_language.findData('en'))
        window._save_api_config()
        self.assertEqual(editor._text_input.toPlainText(), '未保存草稿\n日本語の名前')
        QTest.qWait(100)  # Debounced preview commits the still-pending editor row.
        self.assertEqual(editor.items[0]['text'], '未保存草稿\n日本語の名前')
        self.assertTrue(editor._dirty)
        self.assertEqual((output.read_bytes(), layout.read_bytes()), before)
        self.assertEqual(editor._source_text.toPlainText(), '元のセリフ')

    def test_backend_progress_keeps_stable_localized_state_and_raw_details(self):
        window = self.window('en')
        window.worker = Mock(task_id='task')
        original = '正在请求翻译 API: model，2 条文本'
        event = dict(task_id='task', page_id='1:1', document_index=0, page_label='原稿.png',
                     stage='translate', state='running', message=original)
        try:
            window._on_stage_event(event)
            self.assertEqual(window.stage_label.text(), '原稿.png · Running')
            self.assertEqual(window.stage_label.toolTip(), original)
            self.assertIn('Translate', window.stage_focus._title.text())
        finally:
            window.worker = None

    def test_error_classification_handles_raw_and_localized_logs(self):
        window = self.window('en')
        for message in ('[失败] 原始错误', '[ERROR] localized error', '[WARNING] warning'):
            self.assertEqual(LogPanel.level_for(message), 'WARN' if 'WARNING' in message else 'ERROR')
        with patch.object(window.diagnostics, 'add_error') as add:
            window._append_log(tr('[失败] {_0}: {_1}', _0='page.png', _1='failure'))
            add.assert_called_once()
