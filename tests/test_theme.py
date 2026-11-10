from __future__ import annotations

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QPushButton
from shiboken6 import delete

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


if __name__ == '__main__':
    unittest.main()
