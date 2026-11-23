from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QInputDialog, QLineEdit, QPushButton

from comic_translate_desktop import config
from comic_translate_desktop.i18n import tr
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.workflow_dialogs import (
    TerminologyDialog, TrialDialog, UsageDialog,
)
from tests.qt_utils import destroy_widget


class WorkflowDialogActionTests(unittest.TestCase):
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
        for name, value in (('PROJECT_ROOT', self.root), ('CONFIG_PATH', self.root / 'config.yaml')):
            setting = patch.object(config, name, value)
            setting.start()
            self.addCleanup(setting.stop)
        config.save_ai_config(dict(
            terminology_project='work',
            terminology_projects={'work': dict(name='原作品', terms=[dict(term='原译名')])},
        ))
        with patch.object(MainWindow, '_start_warmup'):
            self.window = MainWindow()
        self.addCleanup(self.destroy_window)
        self.window.setAttribute(Qt.WA_DontShowOnScreen)
        source = self.root / 'page.png'
        Image.new('RGB', (20, 30), 'white').save(source)
        self.window._add_paths([source])

    def destroy_window(self):
        self.window.editor_page._dirty = False
        destroy_widget(self.window)

    def use_modal(self, trigger, dialog_type, operate):
        errors, handled, destroyed = [], [], []

        def drive():
            dialog = self.app.activeModalWidget()
            try:
                self.assertIsInstance(dialog, dialog_type)
                handled.append(True)
                dialog.destroyed.connect(lambda *_: destroyed.append(True))
                operate(dialog)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                if dialog is not None and dialog.isVisible():
                    dialog.reject()

        def timeout():
            errors.append('The workflow dialog did not finish.')
            dialog = self.app.activeModalWidget()
            if isinstance(dialog, dialog_type):
                dialog.reject()

        driver, watchdog = QTimer(), QTimer()
        driver.setSingleShot(True)
        driver.timeout.connect(drive)
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(timeout)
        with patch('sys.excepthook', lambda kind, value, tb: errors.append(str(value))):
            driver.start(0)
            watchdog.start(5000)
            try:
                trigger()
            finally:
                driver.stop()
                watchdog.stop()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(handled, [True])
        self.assertEqual(errors, [])
        self.assertEqual(destroyed, [True])

    @staticmethod
    def press(dialog, standard_button):
        box = dialog.findChild(QDialogButtonBox)
        box.button(standard_button).click()

    def test_trial_confirmation_starts_selected_page_count(self):
        def confirm(dialog):
            dialog.pages.setValue(3)
            self.press(dialog, QDialogButtonBox.StandardButton.Ok)
        with patch.object(self.window, '_start_translation') as start:
            self.use_modal(self.window._trial_btn.click, TrialDialog, confirm)
        start.assert_called_once_with(trial_pages=3)

    def test_trial_cancel_does_not_start_translation(self):
        with patch.object(self.window, '_start_translation') as start:
            self.use_modal(self.window._trial_btn.click, TrialDialog,
                           lambda dialog: self.press(dialog, QDialogButtonBox.StandardButton.Cancel))
        start.assert_not_called()

    def test_terminology_save_persists_and_updates_the_task_summary(self):
        def save(dialog):
            dialog.name.setText('新作品名')
            dialog.table.setCurrentCell(0, 0)
            dialog.table.editItem(dialog.table.item(0, 0))
            editor = dialog.table.findChild(QLineEdit)
            self.assertIsNotNone(editor)
            editor.setText('真子')
            save_button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save)
            QTest.mouseClick(save_button, Qt.LeftButton)
        self.use_modal(self.window._task_terms_action.trigger, TerminologyDialog, save)
        saved = config.load_ai_config()['terminology_projects']['work']
        self.assertEqual(saved['name'], '新作品名')
        self.assertEqual(saved['terms'][0]['term'], '真子')
        self.assertIn('新作品名', self.window._terminology_summary.text())
        self.assertIn('新作品名', self.window._task_work_info.toolTip())

        def reopen(dialog):
            self.assertEqual(dialog.name.text(), '新作品名')
            self.assertEqual(dialog.table.item(0, 0).text(), '真子')
            dialog.reject()

        self.use_modal(self.window._task_terms_action.trigger, TerminologyDialog, reopen)

    def test_new_terminology_project_can_be_named_saved_and_reopened(self):
        def enter_name(prompt):
            prompt.setTextValue('新作品')
            self.press(prompt, QDialogButtonBox.StandardButton.Ok)

        def create(dialog):
            new_button = next(button for button in dialog.findChildren(QPushButton)
                              if button.text() == tr('新建作品'))
            self.use_modal(lambda: QTest.mouseClick(new_button, Qt.LeftButton),
                           QInputDialog, enter_name)
            self.assertEqual(dialog.name.text(), '新作品')
            self.press(dialog, QDialogButtonBox.StandardButton.Save)

        def reopen(dialog):
            self.assertEqual(dialog.name.text(), '新作品')
            self.assertGreaterEqual(dialog.project.findData('work'), 0)
            dialog.reject()

        self.use_modal(self.window._task_terms_action.trigger, TerminologyDialog, create)
        saved = config.load_ai_config()
        self.assertEqual(saved['terminology_projects'][saved['terminology_project']]['name'], '新作品')
        self.use_modal(self.window._task_terms_action.trigger, TerminologyDialog, reopen)

    def test_terminology_cancel_discards_changes(self):
        before = config.load_ai_config()
        def cancel(dialog):
            dialog.name.setText('不保存的名称')
            dialog.table.item(0, 0).setText('不保存的译名')
            self.press(dialog, QDialogButtonBox.StandardButton.Cancel)
        self.use_modal(self.window._task_terms_action.trigger, TerminologyDialog, cancel)
        self.assertEqual(config.load_ai_config(), before)

    def prepare_usage(self):
        self.window._last_usage_report = dict(
            scope=self.window._pricing_scope(), trial=True, outputs=[str(self.root / 'page.png')],
            model='fixture', completed_pages=1, planned_pages=1, total_pages=8,
            elapsed_seconds=1, processing_seconds=1,
            usage=dict(requests=1, reported=1, prompt_tokens=1000, completion_tokens=200),
        )
        self.window._update_actions()

    def test_usage_save_persists_prices(self):
        self.prepare_usage()
        def save(dialog):
            dialog.enabled.setChecked(True)
            dialog.input_price.setValue(2)
            dialog.output_price.setValue(4)
            dialog.currency.setCurrentText('CNY')
            next(button for button in dialog.findChildren(QPushButton)
                 if button.text() == tr('保存并关闭')).click()
        self.use_modal(self.window._task_usage_action.trigger, UsageDialog, save)
        saved = config.load_ai_config()['usage_pricing']
        self.assertEqual((saved['enabled'], saved['input'], saved['output'], saved['currency']),
                         (True, 2, 4, 'CNY'))
        self.assertEqual(saved['scope'], self.window._pricing_scope())

    def test_usage_cancel_does_not_save_prices(self):
        self.prepare_usage()
        before = config.load_ai_config()
        def cancel(dialog):
            dialog.enabled.setChecked(True)
            dialog.input_price.setValue(12)
            dialog.reject()
        self.use_modal(self.window._task_usage_action.trigger, UsageDialog, cancel)
        self.assertEqual(config.load_ai_config(), before)

    def test_usage_actions_dispatch_full_translation_or_editing(self):
        self.prepare_usage()
        for action, label in (('full', '翻译整本'), ('edit', '精修试译')):
            with self.subTest(action=action):
                with patch.object(self.window, '_start_translation') as start, \
                        patch.object(self.window.editor_page, 'request_import') as import_pages:
                    self.use_modal(
                        self.window._task_usage_action.trigger, UsageDialog,
                        lambda dialog: next(button for button in dialog.findChildren(QPushButton)
                                            if button.text() == tr(label)).click(),
                    )
                if action == 'full':
                    start.assert_called_once_with()
                    import_pages.assert_not_called()
                else:
                    start.assert_not_called()
                    import_pages.assert_called_once_with([str(self.root / 'page.png')])
                    self.assertIs(self.window.tabs.currentWidget(), self.window.editor_page)


if __name__ == '__main__':
    unittest.main()
