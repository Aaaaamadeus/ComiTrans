from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from comic_translate_desktop import config
from comic_translate_desktop.pdf_project import project_link_path
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.motion import set_reduced_motion
from tests.qt_utils import destroy_widget


class RetouchAndMotionTests(unittest.TestCase):
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
        self.addCleanup(set_reduced_motion, False)
        set_reduced_motion(False)
        QSettings().remove('ui/preferencesVisible')
        QSettings().remove('ui/lastBatchOutputs')

    def window(self):
        with patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
        self.addCleanup(self.destroy_window, window)
        return window

    @staticmethod
    def destroy_window(window):
        window.editor_page._dirty = False
        destroy_widget(window)

    def fixture(self, name='page'):
        source = self.root / 'source' / f'{name}.png'
        output = self.root / 'output' / f'{name}_translated.png'
        for file in (source, output):
            file.parent.mkdir(exist_ok=True)
            Image.new('RGB', (80, 120), 'white').save(file)
        cleaned = self.root / 'output_cleaned' / f'{name}_translated_cleaned.png'
        layout = self.root / 'output_layout' / f'{name}_translated_layout.json'
        cleaned.parent.mkdir(exist_ok=True)
        layout.parent.mkdir(exist_ok=True)
        Image.new('RGB', (80, 120), 'white').save(cleaned)
        layout.write_text('[{"text": "译文", "source_text": "原文", "box": [4, 4, 40, 80], '
                          '"direction": 1}]', encoding='utf-8')
        return source, output

    def wait_editor(self, window):
        for _ in range(300):
            if not window.editor_page.page_io_busy:
                return
            QTest.qWait(10)
        self.fail('editor page index did not finish')

    def test_one_click_retouch_adds_every_result_and_persists_for_the_next_window(self):
        first_source, first_output = self.fixture('first')
        second_source, second_output = self.fixture('second')
        window = self.window()
        window._add_paths([first_source, second_source])
        window._on_image_done(str(first_source), str(first_output))
        window._on_image_done(str(second_source), str(second_output))
        self.assertTrue(window._edit_all_btn.isEnabled())
        window._edit_all_btn.click()
        self.assertIs(window.tabs.currentWidget(), window.editor_page)
        self.wait_editor(window)
        self.assertEqual(window.editor_page.page_list.count(), 2)
        self.assertEqual(
            sorted(window._editable_outputs()),
            sorted([str(first_output), str(second_output)]))

        QSettings().sync()
        restored = self.window()
        self.assertEqual(
            sorted(restored._editable_outputs()),
            sorted([str(first_output), str(second_output)]))
        self.assertTrue(restored._edit_all_btn.isEnabled())

    def test_one_click_retouch_skips_outputs_that_disappeared(self):
        source, output = self.fixture()
        window = self.window()
        window._add_paths([source])
        window._on_image_done(str(source), str(output))
        missing = self.root / 'output' / 'gone_translated.png'
        window._last_outputs = [str(missing), str(output)]
        window._update_actions()
        self.assertTrue(window._edit_all_btn.isEnabled())
        window._edit_all_btn.click()
        self.wait_editor(window)
        self.assertEqual(window.editor_page.page_list.count(), 1)
        window._last_outputs = [str(missing)]
        window._update_actions()
        self.assertFalse(window._edit_all_btn.isEnabled())

    def test_one_click_retouch_keeps_valid_pages_when_a_pdf_link_is_invalid(self):
        _, output = self.fixture()
        broken = output.with_name('broken.pdf')
        broken.touch()
        project_link_path(broken).write_text('{}', encoding='utf-8')
        window = self.window()
        window._last_outputs = [str(broken), str(output)]
        window._update_actions()
        window._edit_all_btn.click()
        self.wait_editor(window)
        self.assertEqual(window.editor_page.page_list.count(), 1)
        self.assertEqual(window.editor_page.output_path, output)
        self.assertIn('broken.pdf', window.editor_page._status.toolTip())

    def test_translation_cuda_toggle_persists_and_reloads_the_pipeline(self):
        config.save_ai_config({'use_gpu': True})
        window = self.window()
        self.assertTrue(window._cuda_toggle.isChecked())
        window.pipeline = object()
        window.pipeline_fingerprint = ('cached',)
        window._cuda_toggle.click()
        self.assertFalse(config.load_ai_config()['use_gpu'])
        self.assertFalse(window.api_config_page._gpu_check.isChecked())
        self.assertIsNone(window.pipeline)
        self.assertIsNone(window.pipeline_fingerprint)
        restored = self.window()
        self.assertFalse(restored._cuda_toggle.isChecked())
        restored._cuda_toggle.click()
        self.assertTrue(config.load_ai_config()['use_gpu'])

    def test_preferences_height_animates_without_an_opacity_effect(self):
        window = self.window()
        window.resize(1440, 900)
        window.show()
        self.app.processEvents()
        window._pref_toggle.setChecked(True)
        self.assertTrue(window._pref_animating)
        self.assertTrue(window._pref_container.isVisible())
        self.assertIsNone(window._pref_container.graphicsEffect())
        QTest.qWait(320)
        self.assertFalse(window._pref_animating)
        target = window._pref_target_height()
        self.assertEqual(window._pref_container.minimumHeight(), target)
        self.assertEqual(window._pref_container.maximumHeight(), target)
        window._pref_toggle.setChecked(False)
        QTest.qWait(260)
        self.assertFalse(window._pref_animating)
        self.assertFalse(window._pref_container.isVisible())
        self.assertEqual(window._pref_container.maximumHeight(), 0)

    def test_reduced_motion_and_restored_open_state_apply_without_animation(self):
        window = self.window()
        set_reduced_motion(True)
        window.resize(1440, 900)
        window.show()
        self.app.processEvents()
        window._pref_toggle.setChecked(True)
        self.assertFalse(window._pref_animating)
        self.assertEqual(window._pref_container.maximumHeight(), window._pref_target_height())
        set_reduced_motion(False)

        QSettings().setValue('ui/preferencesVisible', True)
        restored = self.window()
        restored.resize(1440, 900)
        restored.show()
        self.app.processEvents()
        self.assertTrue(restored._pref_toggle.isChecked())
        self.assertTrue(restored._pref_container.isVisible())
        self.assertFalse(restored._pref_animating)
        self.assertIsNone(restored._pref_animation)
        self.assertEqual(restored._pref_container.maximumHeight(),
                         restored._pref_target_height())


if __name__ == '__main__':
    unittest.main()
