"""Windows caption follows the app palette so the title bar is not a white strip."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QDialog, QMainWindow

from .theme import theme, theme_changed

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _colorref(value):
    value = value.lstrip('#')
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return red | (green << 8) | (blue << 16)


def apply_window_chrome(window):
    """Tint the native caption, border and text; no-op outside Windows."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes

        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        palette = theme()
        dark = 0 if palette['paper'].lower() == '#ffffff' else 1
        values = (
            (DWMWA_USE_IMMERSIVE_DARK_MODE, dark),
            (DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, dark),
            (DWMWA_CAPTION_COLOR, _colorref(palette['paper'])),
            (DWMWA_BORDER_COLOR, _colorref(palette['ruleStrong'])),
            (DWMWA_TEXT_COLOR, _colorref(palette['ink'])),
        )
        for attribute, value in values:
            data = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
        return True
    except Exception:
        return False


def watch_window_chrome(window):
    theme_changed.changed.connect(lambda *_: apply_window_chrome(window))


class _ChromeWatcher(QObject):
    """Every top-level window gets the current caption colours when it appears."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Show and isinstance(watched, (QMainWindow, QDialog)):
            apply_window_chrome(watched)
        return False


def install_window_chrome(app):
    if getattr(app, '_comitrans_chrome_watcher', None) is None:
        watcher = _ChromeWatcher(app)
        app.installEventFilter(watcher)
        app._comitrans_chrome_watcher = watcher
