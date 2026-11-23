import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout
from PySide6.QtTest import QTest

from comic_translate_desktop import config
from comic_translate_desktop.ui import main_window
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.motion import set_reduced_motion
from tests.qt_utils import destroy_widget


class ContextPreferencesTests(unittest.TestCase):
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
        self.addCleanup(set_reduced_motion, False)
        set_reduced_motion(False)
        QSettings().remove('ui/preferencesVisible')

    def test_retention_persists_locks_resume_and_never_clears_cache_on_toggle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / '.cache/translation-context.json'
            cache.parent.mkdir()
            cache.write_text('existing cache', encoding='utf-8')
            with patch.object(config, 'CONFIG_PATH', root / 'config.yaml'), \
                    patch.object(config, 'PROJECT_ROOT', root), patch.object(MainWindow, '_start_warmup'):
                window = MainWindow()
                try:
                    self.assertFalse(window._retain_translation_context.isChecked())
                    window._resume_enabled.setChecked(False)
                    window._retain_translation_context.setChecked(True)
                    self.assertTrue(window._resume_enabled.isChecked())
                    self.assertFalse(window._resume_enabled.isEnabled())
                    self.assertTrue(config.load_ai_config()['retain_translation_context'])
                    self.assertTrue(config.load_ai_config()['resume_enabled'])
                    reopened = MainWindow()
                    try:
                        self.assertTrue(reopened._retain_translation_context.isChecked())
                        self.assertTrue(reopened._resume_enabled.isChecked())
                        self.assertFalse(reopened._resume_enabled.isEnabled())
                        reopened._retain_translation_context.setChecked(False)
                        self.assertTrue(reopened._resume_enabled.isEnabled())
                        self.assertFalse(config.load_ai_config()['retain_translation_context'])
                        self.assertEqual(cache.read_text(encoding='utf-8'), 'existing cache')
                    finally:
                        destroy_widget(reopened)
                finally:
                    destroy_widget(window)

    def test_backend_worker_enforces_resume_for_hand_edited_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(config, 'CONFIG_PATH', Path(temporary) / 'config.yaml'):
                loaded = config.save_ai_config({'resume_enabled': False, 'retain_translation_context': True})
                from comic_translate_desktop.worker import BatchWorker
                worker = BatchWorker([], temporary, loaded)
                self.assertTrue(worker._config['resume_enabled'])

    def test_context_controls_are_inside_every_clipping_parent_in_short_windows(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(config, 'CONFIG_PATH', Path(temporary) / 'config.yaml'), \
                    patch.object(MainWindow, '_start_warmup'):
                window = MainWindow()
                try:
                    window.resize(820, 480)
                    window.show()
                    window._pref_toggle.setChecked(True)
                    QTest.qWait(100)
                    window._pref_container.ensureWidgetVisible(window._resume_enabled, 0, 0)
                    QTest.qWait(50)
                    for checkbox in (window._retain_translation_context, window._resume_enabled):
                        for point in (checkbox.rect().topLeft(), checkbox.rect().bottomRight()):
                            parent = checkbox.parentWidget()
                            while parent is not None:
                                self.assertTrue(parent.rect().contains(checkbox.mapTo(parent, point)),
                                                (checkbox.text(), parent.objectName()))
                                parent = parent.parentWidget()
                finally:
                    destroy_widget(window)

    def test_preferences_opened_before_show_use_final_layout_height(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(config, 'CONFIG_PATH', root / 'config.yaml'), \
                    patch.object(config, 'PROJECT_ROOT', root), \
                    patch.object(MainWindow, '_start_warmup'):
                first = MainWindow()
                try:
                    first.resize(820, 480)
                    first._pref_toggle.setChecked(False)
                    first._pref_toggle.setChecked(True)
                    self.assertFalse(first._pref_container.isHidden())
                    self.assertIsNone(first._pref_animation)
                    self.assertEqual(first._pref_toggle.arrowType(), Qt.DownArrow)
                    first._ui_settings.sync()
                finally:
                    destroy_widget(first)

                restored = MainWindow()
                try:
                    self.assertTrue(restored._pref_toggle.isChecked())
                    restored.resize(1440, 900)
                    restored.show()
                    self.app.processEvents()
                    self.assertTrue(restored._pref_container.isVisible())
                    self.assertIsNone(restored._pref_animation)
                    self.assertEqual(restored._pref_columns.direction(), QHBoxLayout.LeftToRight)
                    self.assertEqual(restored._pref_container.maximumHeight(), restored._pref_target_height())
                finally:
                    destroy_widget(restored)

    def test_preferences_reversal_resize_and_bar_geometry_stay_stable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(config, 'CONFIG_PATH', root / 'config.yaml'), \
                    patch.object(config, 'PROJECT_ROOT', root), \
                    patch.object(MainWindow, '_start_warmup'), \
                    patch.object(main_window, 'reduced_motion', return_value=False):
                window = MainWindow()
                try:
                    window.resize(1280, 800)
                    window._pref_toggle.setChecked(False)
                    window.show()
                    self.app.processEvents()

                    bar_heights = []
                    src_heights = []
                    window._pref_toggle.setChecked(True)
                    opening = window._pref_animation
                    self.assertIsNotNone(opening)
                    self.assertEqual(window._pref_columns.direction(), QHBoxLayout.LeftToRight)
                    for step in range(1, 5):
                        opening.setCurrentTime((opening.duration() * step) // 4)
                        self.app.processEvents()
                        bar_heights.append(window._control_bar.height())
                        src_heights.append(window._source_language.height())
                    self.assertTrue(all(h >= 34 for h in bar_heights), bar_heights)
                    self.assertTrue(all(h >= 34 for h in src_heights), src_heights)

                    # Finish at 1280x800 and confirm bottom rows fit without clipping.
                    QTest.qWait(320)
                    self.app.processEvents()
                    vp_rect = window._pref_container.viewport().rect()
                    for widget in (window._resume_enabled, window._names_input):
                        box = QRect(
                            widget.mapTo(window._pref_container.viewport(), widget.rect().topLeft()),
                            widget.size(),
                        )
                        self.assertTrue(vp_rect.contains(box), (widget.objectName(), box, vp_rect))

                    # Test rapid reversal and mid-animation resize.
                    window._pref_toggle.setChecked(False)
                    closing = window._pref_animation
                    self.assertIsNotNone(closing)
                    closing.setCurrentTime(closing.duration() // 2)

                    window._pref_toggle.setChecked(True)
                    reopened = window._pref_animation
                    self.assertIsNotNone(reopened)
                    window._finish_preferences_animation(False, closing)
                    self.assertIs(window._pref_animation, reopened)
                    self.assertTrue(window._pref_container.isVisible())

                    window.resize(1024, 760)
                    self.app.processEvents()
                    self.assertIs(window._pref_animation, reopened)
                    self.assertTrue(window._pref_container.widgetResizable())
                    reopened.setCurrentTime(reopened.duration())
                    self.app.processEvents()
                    self.assertIsNone(window._pref_animation)
                    self.assertTrue(window._pref_container.isVisible())
                    self.assertEqual(window._pref_container.maximumHeight(), window._pref_target_height())
                finally:
                    destroy_widget(window)
