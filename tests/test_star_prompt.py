from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
from comic_translate_desktop import config
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.star_prompt import StarPrompt, REPOSITORY_URL, STAR_PROMPT_IDLE_MS


class StarPromptTests(unittest.TestCase):
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
        for key,value in (('PROJECT_ROOT',self.root),('CONFIG_PATH',self.root/'config.yaml')):
            setting = patch.object(config,key,value)
            setting.start()
            self.addCleanup(setting.stop)

    @staticmethod
    def destroy(widget):
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def prompt(self, *, idle_timeout_ms=STAR_PROMPT_IDLE_MS):
        parent = QWidget()
        parent.resize(820,480)
        parent.show()
        self.addCleanup(self.destroy,parent)
        prompt = StarPrompt(parent,idle_timeout_ms=idle_timeout_ms)
        return parent,prompt

    def window(self):
        with patch.object(MainWindow,'_start_warmup'):
            window = MainWindow()
        self.addCleanup(self.destroy,window)
        window.show()
        for index in range(3):
            path = self.root/f'{index}.png'
            Image.new('RGB',(30,40),'white').save(path)
            window._add_paths([path])
        return window

    def test_prompt_uses_eight_second_idle_timeout_and_is_non_modal(self):
        _,prompt = self.prompt()
        self.assertEqual(prompt._idle_timer.interval(),8000)
        self.assertFalse(prompt.isWindow())
        self.assertFalse(prompt.isModal())
        prompt.show_prompt()
        self.assertTrue(prompt.isVisible())

    def test_idle_timeout_hides_prompt_and_can_be_shown_again(self):
        _,prompt = self.prompt(idle_timeout_ms=40)
        prompt.show_prompt()
        QTest.qWait(100)
        self.assertFalse(prompt.isVisible())
        self.assertFalse(prompt._idle_timer.isActive())
        prompt.show_prompt()
        self.assertTrue(prompt.isVisible())
        self.assertTrue(prompt._idle_timer.isActive())

    def test_mouse_interaction_restarts_idle_timeout(self):
        _,prompt = self.prompt(idle_timeout_ms=180)
        prompt.show_prompt()
        QTest.qWait(100)
        QTest.mouseMove(prompt.star_button,QPoint(5,5))
        QTest.qWait(100)
        self.assertTrue(prompt.isVisible())
        QTest.qWait(120)
        self.assertFalse(prompt.isVisible())

    def test_close_button_hides_and_cancels_timeout(self):
        _,prompt = self.prompt()
        prompt.show_prompt()
        prompt.close_button.click()
        self.assertFalse(prompt.isVisible())
        self.assertFalse(prompt._idle_timer.isActive())

    def test_star_button_opens_repository_only_when_clicked(self):
        _,prompt = self.prompt()
        with patch('comic_translate_desktop.ui.star_prompt.QDesktopServices.openUrl',return_value=True) as opened:
            prompt.show_prompt()
            opened.assert_not_called()
            prompt.star_button.click()
            opened.assert_called_once()
            self.assertEqual(opened.call_args.args[0].toString(),REPOSITORY_URL)
        self.assertFalse(prompt.isVisible())

    def test_prompt_keeps_keyboard_focus_in_existing_input(self):
        parent,prompt = self.prompt()
        field = QLineEdit(parent)
        field.show()
        parent.activateWindow()
        field.setFocus()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(),field)
        prompt.show_prompt()
        self.app.processEvents()
        self.assertIs(self.app.focusWidget(),field)

    def test_probability_boundary_is_fifteen_percent(self):
        window = self.window()
        for probability,expected in ((0.0,True),(0.149999,True),(0.15,False),(0.999999,False)):
            with self.subTest(probability=probability),patch('comic_translate_desktop.ui.main_window.random.random',return_value=probability) as draw:
                window._star_prompt.dismiss()
                window._maybe_show_star_prompt()
                draw.assert_called_once()
                self.assertEqual(window._star_prompt.isVisible(),expected)

    def test_successful_batch_draws_probability_once_for_all_files(self):
        window = self.window()
        with patch('comic_translate_desktop.ui.main_window.random.random',return_value=0.1) as draw:
            window._on_finished(3,0)
            draw.assert_called_once()
        self.assertTrue(window._star_prompt.isVisible())

    def test_failure_empty_and_cancelled_batches_do_not_draw_probability(self):
        window = self.window()
        for success,failed,stopped in ((2,1,False),(0,0,False),(1,0,True),(3,0,True)):
            with self.subTest(success=success,failed=failed,stopped=stopped):
                window._stop_requested = stopped
                with patch.object(window,'_show_issue_prompt'),patch('comic_translate_desktop.ui.main_window.random.random') as draw:
                    window._on_finished(success,failed)
                    draw.assert_not_called()
                self.assertFalse(window._star_prompt.isVisible())

    def test_new_translation_hides_previous_prompt(self):
        window = self.window()
        window._star_prompt.show_prompt()
        window._set_running(True)
        self.assertFalse(window._star_prompt.isVisible())

    def test_prompt_tracks_bottom_right_when_window_resizes(self):
        window = self.window()
        window._star_prompt.show_prompt()
        for width,height in ((1440,900),(820,480)):
            window.resize(width,height)
            self.app.processEvents()
            parent = window.centralWidget()
            prompt = window._star_prompt
            self.assertTrue(parent.rect().contains(prompt.geometry()))
            self.assertEqual(parent.width()-prompt.x()-prompt.width(),16)
            self.assertEqual(parent.height()-prompt.y()-prompt.height(),16)
