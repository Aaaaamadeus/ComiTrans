from __future__ import annotations

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFocusEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QWidget,
)
from shiboken6 import delete

from comic_translate_desktop.ui.motion import (
    EMPHASIZED_DECELERATE,
    MonochromeShimmerBar,
    STANDARD,
    SlidingNavUnderline,
    StatusShimmerOverlay,
    _DrawerSlideOverlay,
    _MangaComboItemDelegate,
    _StackSlideOverlay,
    install_list_motion,
    install_material_motion,
    install_stack_motion,
    install_tab_motion,
    play_reveal_overlay,
    play_slide_overlay,
    reduced_motion,
    set_reduced_motion,
)
from comic_translate_desktop.ui.preview import ImagePreview
from comic_translate_desktop.ui.searchable_combo import SearchableFontCombo
from comic_translate_desktop.ui.theme import (
    PALETTES, apply_theme, build_stylesheet, set_themed_icon, theme, theme_name,
)


def _luminance(hex_color):
    value = hex_color.lstrip('#')
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def linear(channel):
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first, second):
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_both_palettes_keep_readable_contrast(self):
        for name, palette in PALETTES.items():
            with self.subTest(theme=name):
                self.assertGreaterEqual(_contrast(palette['ink'], palette['paper']), 4.5)
                self.assertGreaterEqual(_contrast(palette['secondary'], palette['paper']), 4.5)
                self.assertGreaterEqual(_contrast(palette['ruleStrong'], palette['paper']), 3.0)
                self.assertNotEqual(palette['canvas'], palette['paper'])

    def test_stylesheet_follows_the_active_theme(self):
        try:
            self.assertEqual(apply_theme(self.app, 'dark'), 'dark')
            self.assertEqual(theme_name(), 'dark')
            self.assertIn(PALETTES['dark']['paper'], build_stylesheet(theme()))
            self.assertIn('icons/dark', build_stylesheet(theme()))
            self.assertEqual(apply_theme(self.app, 'light'), 'light')
            self.assertNotIn('icons/dark', build_stylesheet(theme()))
            self.assertIn(apply_theme(self.app, 'auto'), ('light', 'dark'))
        finally:
            apply_theme(self.app, 'light')

    def test_theme_change_skips_destroyed_buttons_and_updates_live_icons(self):
        old, live = QPushButton(), QPushButton()
        apply_theme(self.app, 'light')
        set_themed_icon(old, 'chevron-down')
        set_themed_icon(live, 'chevron-down')
        old_key = live.icon().cacheKey()
        delete(old)
        try:
            apply_theme(self.app, 'dark')
            self.assertNotEqual(live.icon().cacheKey(), old_key)
        finally:
            apply_theme(self.app, 'light')

    def test_refactored_secondary_ui_modules_avoid_hardcoded_hex_colors(self):
        import re
        from pathlib import Path
        ui_dir = Path(__file__).resolve().parents[1] / 'comic_translate_desktop' / 'ui'
        hex_re = re.compile(r'#[0-9a-fA-F]{3,8}\b')
        for filename in (
            'api_config_page.py', 'advanced_config.py', 'gpu_setup_dialog.py',
            'language_dialog.py', 'star_prompt.py', 'font_library_dialog.py',
            'favorite_fonts.py', 'error_log_page.py', 'text_editor_dialog.py', 'update_notice.py',
        ):
            text = (ui_dir / filename).read_text(encoding='utf-8')
            self.assertEqual(hex_re.findall(text), [], filename)

    def test_material_motion_hooks_ripple_and_focus_underline(self):
        host = QWidget()
        layout = QHBoxLayout(host)
        btn = QPushButton('Action', host)
        edit = QLineEdit(host)
        layout.addWidget(btn)
        layout.addWidget(edit)
        host.resize(320, 60)
        host.show()
        QApplication.processEvents()
        try:
            set_reduced_motion(False)
            install_material_motion(self.app)
            QTest.mousePress(btn, Qt.LeftButton, pos=btn.rect().center())
            QTest.mouseRelease(btn, Qt.LeftButton, pos=btn.rect().center())
            overlay = getattr(btn, '_motion_ripple_overlay', None)
            self.assertIsNotNone(overlay)
            self.assertEqual(len(overlay._ripples), 1)

            QApplication.sendEvent(edit, QFocusEvent(QEvent.FocusIn, Qt.MouseFocusReason))
            focus_ov = getattr(edit, '_motion_focus_overlay', None)
            self.assertIsNotNone(focus_ov)
            self.assertEqual(focus_ov._target_progress, 1.0)
            QTest.qWait(50)
            self.assertGreater(focus_ov._progress, 0.0)

            set_reduced_motion(True)
            QApplication.sendEvent(edit, QFocusEvent(QEvent.FocusOut, Qt.MouseFocusReason))
            self.assertEqual(focus_ov._progress, 0.0)
        finally:
            set_reduced_motion(False)
            host.close()
            delete(host)

    def test_sliding_nav_and_tabs_and_list_rail_track_selection(self):
        host = QWidget()
        layout = QHBoxLayout(host)
        b1 = QPushButton('01 Auto', host)
        b2 = QPushButton('02 Editor', host)
        grp = QButtonGroup(host)
        for b in (b1, b2):
            b.setCheckable(True)
            b.setProperty('role', 'nav')
            grp.addButton(b)
            layout.addWidget(b)
        b1.setChecked(True)
        nav = SlidingNavUnderline(host, [b1, b2])

        tabs = QTabWidget(host)
        tabs.addTab(QWidget(), 'A')
        tabs.addTab(QWidget(), 'B')
        layout.addWidget(tabs)
        tab_ind = install_tab_motion(tabs)

        lst = QListWidget(host)
        lst.addItems(['page1', 'page2', 'page3'])
        layout.addWidget(lst)
        rail = install_list_motion(lst)

        host.resize(640, 180)
        host.show()
        QApplication.processEvents()
        try:
            set_reduced_motion(False)
            b2.setChecked(True)
            QTest.qWait(30)
            self.assertEqual(nav._target_x, float(b2.x()))

            tabs.setCurrentIndex(1)
            QTest.qWait(30)
            self.assertEqual(tabs.tabBar().property('animatedIndicator'), 'true')
            self.assertEqual(tab_ind._target_x, float(tabs.tabBar().tabRect(1).x()))

            lst.setCurrentRow(2)
            QTest.qWait(30)
            self.assertTrue(rail._has_rail)
            self.assertEqual(rail._target_top, float(lst.visualItemRect(lst.item(2)).top()))

            set_reduced_motion(True)
            b1.setChecked(True)
            self.assertEqual(nav._cur_x, float(b1.x()))
        finally:
            set_reduced_motion(False)
            host.close()
            delete(host)

    def test_status_shimmer_progress_bar_and_canvas_pulse(self):
        host = QWidget()
        layout = QHBoxLayout(host)
        pill = QFrame(host)
        pill.setFixedSize(120, 28)
        shimmer = StatusShimmerOverlay(pill)
        bar = MonochromeShimmerBar(host)
        bar.setRange(0, 0)
        bar.setFixedSize(180, 5)
        preview = ImagePreview()
        pix = QPixmap(200, 200)
        pix.fill(Qt.white)
        preview.set_pixmap(pix)
        layout.addWidget(pill)
        layout.addWidget(bar)
        layout.addWidget(preview)
        host.resize(520, 280)
        host.show()
        QApplication.processEvents()
        try:
            set_reduced_motion(False)
            shimmer.set_active(True)
            self.assertTrue(shimmer._timer.isActive())
            self.assertTrue(shimmer.isVisible())
            self.assertTrue(bar._timer.isActive())

            preview.set_region((10, 10, 80, 40), editable=True)
            self.assertGreater(preview._label._select_pulse_until, 0)
            self.assertIsNone(preview._label._region_drag)
            QTest.qWait(30)

            set_reduced_motion(True)
            shimmer.set_active(False)
            self.assertFalse(shimmer._timer.isActive())
            self.assertFalse(shimmer.isVisible())
            preview.set_region((20, 20, 70, 50), editable=True)
            self.assertEqual(preview._label._select_pulse_until, 0)
            self.assertTrue(reduced_motion())
        finally:
            set_reduced_motion(False)
            host.close()
            delete(host)

    def test_combo_polish_and_popup_animation_lifecycle(self):
        set_reduced_motion(False)
        install_material_motion(self.app)
        host = QWidget()
        layout = QHBoxLayout(host)
        plain = QComboBox(host)
        plain.addItems(['日本語', 'English', '한국어'])
        searchable = SearchableFontCombo(host)
        searchable.addItems(['自动匹配漫画风格', '思源黑体', '手写杂书体'])
        layout.addWidget(plain)
        layout.addWidget(searchable)
        host.resize(420, 80)
        host.show()
        QApplication.processEvents()
        try:
            for combo in (plain, searchable):
                self.assertTrue(getattr(combo, '_motion_combo_polished', False))
                self.assertIsNone(getattr(combo, '_motion_focus_overlay', None))
                view = combo.view()
                self.assertIsInstance(view.itemDelegate(), _MangaComboItemDelegate)
                popup = view.window()
                self.assertTrue(popup.testAttribute(Qt.WA_TranslucentBackground))
                combo.showPopup()
                QTest.qWait(40)
                combo.hidePopup()
                QApplication.processEvents()
                self.assertEqual(popup.windowOpacity(), 1.0)
        finally:
            set_reduced_motion(False)
            host.close()
            delete(host)

    def test_stack_slide_and_splitter_drawer_overlays_and_curves(self):
        self.assertLess(EMPHASIZED_DECELERATE.valueForProgress(0.1), 0.35)
        self.assertLess(STANDARD.valueForProgress(0.2), 0.15)

        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        stack = QStackedWidget(host)
        p1, p2 = QFrame(), QFrame()
        p1.setStyleSheet('background: #FFFFFF;')
        p2.setStyleSheet('background: #FFFFFF;')
        stack.addWidget(p1)
        stack.addWidget(p2)
        stack.setFixedSize(100, 120)

        splitter = QSplitter(Qt.Horizontal, host)
        left, center, right = QFrame(), QFrame(), QFrame()
        left.setStyleSheet('background: #F8F8F8;')
        center.setStyleSheet('background: #FFFFFF;')
        right.setStyleSheet('background: #F8F8F8;')
        for pane in (left, center, right):
            splitter.addWidget(pane)
        splitter.setSizes([110, 180, 110])

        layout.addWidget(stack)
        layout.addWidget(splitter, 1)
        host.resize(540, 200)
        host.show()
        QApplication.processEvents()
        try:
            set_reduced_motion(False)
            install_stack_motion(stack)
            overlay = stack._motion_stack_overlay
            self.assertIsInstance(overlay, _StackSlideOverlay)

            stack.setCurrentIndex(1)
            self.assertTrue(overlay.isVisible())
            QTest.qWait(200)
            self.assertFalse(overlay.isVisible())

            play_slide_overlay(left, edge='left', duration=90)
            left.hide()
            self.assertEqual(splitter.count(), 3)
            QTest.qWait(140)
            self.assertEqual(splitter.count(), 3)

            left.show()
            play_reveal_overlay(left, edge='left', duration=90)
            right.hide()
            right.show()
            play_reveal_overlay(right, edge='right', duration=90)
            self.assertEqual(splitter.count(), 3)

            left_ov = getattr(left, '_motion_transition_overlay', None)
            right_ov = getattr(right, '_motion_transition_overlay', None)
            self.assertIsInstance(left_ov, _DrawerSlideOverlay)
            self.assertIsInstance(right_ov, _DrawerSlideOverlay)
            self.assertIs(left_ov.parentWidget(), host)
            self.assertIs(right_ov.parentWidget(), host)
            self.assertLess(left_ov.x(), right_ov.x())

            QTest.qWait(150)
            self.assertIsNone(getattr(left, '_motion_transition_overlay', None))
            self.assertIsNone(getattr(right, '_motion_transition_overlay', None))
            self.assertEqual(splitter.count(), 3)

            set_reduced_motion(True)
            stack.setCurrentIndex(0)
            self.assertFalse(overlay.isVisible())
        finally:
            set_reduced_motion(False)
            host.close()
            delete(host)


if __name__ == '__main__':
    unittest.main()
