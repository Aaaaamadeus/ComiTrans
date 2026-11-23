from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPaintEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QWidget
from shiboken6 import delete

from comic_translate_desktop.ui.motion import (
    _FocusLineOverlay, _MaterialMotionController, _RippleOverlay, reduced_motion, set_reduced_motion,
)


class MotionOverlayLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_saving_dialog_stops_the_pressed_buttons_ripple_before_deletion(self):
        self.addCleanup(set_reduced_motion, reduced_motion())
        set_reduced_motion(False)
        dialog = QDialog()
        self.addCleanup(delete, dialog)
        save = QPushButton('Save', dialog)
        motion = _MaterialMotionController(dialog)
        save.installEventFilter(motion)
        save.clicked.connect(dialog.accept)
        dialog.show()
        QTest.mousePress(save, Qt.LeftButton)
        ripple = save._motion_ripple_overlay
        self.assertTrue(ripple._timer.isActive())
        QTest.mouseRelease(save, Qt.LeftButton)
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertFalse(ripple._timer.isActive())
        self.assertFalse(ripple._ripples)

    def test_paint_with_only_native_widget_state(self):
        # Qt can dispatch paint while the Python wrapper has no animation state.
        for overlay_type in (_FocusLineOverlay, _RippleOverlay):
            with self.subTest(overlay=overlay_type.__name__):
                overlay = overlay_type.__new__(overlay_type)
                QWidget.__init__(overlay)
                try:
                    QApplication.sendEvent(overlay, QPaintEvent(overlay.rect()))
                finally:
                    delete(overlay)

    def test_native_initialization_can_dispatch_paint_before_constructor_returns(self):
        native_init = QWidget.__init__
        errors = []
        painted = []

        def record_error(kind, value, _traceback):
            errors.append(f'{kind.__name__}: {value}')

        def initialize_and_paint(widget, *args, **kwargs):
            native_init(widget, *args, **kwargs)
            if isinstance(widget, (_RippleOverlay, _FocusLineOverlay)):
                painted.append(type(widget).__name__)
                # Exercise a Qt virtual callback at the native constructor boundary.
                QApplication.sendEvent(widget, QPaintEvent(widget.rect()))

        for overlay_type, target_type in (
            (_RippleOverlay, QPushButton), (_FocusLineOverlay, QLineEdit),
        ):
            with self.subTest(overlay=overlay_type.__name__):
                target = target_type()
                try:
                    with patch('sys.excepthook', record_error), \
                            patch.object(QWidget, '__init__', initialize_and_paint):
                        overlay_type(target)
                finally:
                    delete(target)
        self.assertEqual(painted, ['_RippleOverlay', '_FocusLineOverlay'])
        self.assertEqual(errors, [])

    def test_initialized_overlay_still_draws_and_finishes_its_animation(self):
        errors = []
        target = QPushButton('Preferences')
        target.resize(180, 44)
        set_reduced_motion(False)
        try:
            with patch('sys.excepthook', lambda kind, value, tb: errors.append(str(value))):
                target.show()
                overlay = _RippleOverlay(target)
                overlay.trigger_ripple(QPointF(target.rect().center()))
                overlay.release_ripples()
                QTest.qWait(40)
                self.assertTrue(overlay._ripples)
                self.assertTrue(overlay._timer.isActive())
                self.assertFalse(target.grab().isNull())
                QTest.qWait(540)
                self.assertFalse(overlay._ripples)
                self.assertFalse(overlay._timer.isActive())
                self.assertEqual(errors, [])
        finally:
            delete(target)
            set_reduced_motion(False)


if __name__ == '__main__':
    unittest.main()
