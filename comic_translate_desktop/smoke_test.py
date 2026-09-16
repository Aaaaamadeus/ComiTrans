"""Opt-in release verification using a real Qt window and isolated preferences."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QFontInfo, QRawFont
from PySide6.QtSvg import QSvgRenderer

from . import __version__, config
from .ui.main_window import MainWindow


def run_smoke_test(app, output_dir):
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Exercise default local models without loading the user's API credentials.
    config.CONFIG_PATH = output / "smoke-defaults.yaml"
    config.PROJECT_ROOT = output
    config.DEFAULT_OUTPUT_DIR = output / "pages"
    app.setApplicationName("ComiTrans-Smoke-Test")
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(output / "settings"))
    window = MainWindow()
    window.show()
    result = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False))}

    def finish():
        if window.warmup_worker is not None:
            QTimer.singleShot(200, finish)
            return
        try:
            window._log_panel.flush_all()
            result["pipeline_ready"] = window.pipeline is not None
            result["brand_font"] = QFontInfo(window._brand_title.font()).family()
            result["log_font"] = QFontInfo(window._log_panel.view.font()).family()
            raw = QRawFont.fromFont(window._log_panel.view.font())
            result["missing_glyphs"] = [c for c in "日志翻译日本語かなカナABC0123" if not raw.supportsCharacter(ord(c))]
            result["svg_valid"] = QSvgRenderer(str(config.ICON_PATH.parent / "ui/icons/chevron-down.svg")).isValid()
            result["window_visible"] = window.isVisible()
            result["screenshot_saved"] = window.grab().save(str(output / "startup.png"))
            result["success"] = all((result["pipeline_ready"], result["svg_valid"], result["window_visible"],
                                     result["screenshot_saved"], result["brand_font"] == "Skribble",
                                     result["log_font"] == "Aa今日花晴 春懒猫困", not result["missing_glyphs"]))
        except Exception as exc:
            result.update(success=False, error=f"{type(exc).__name__}: {exc}")
        (output / "smoke-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.exit(0 if result["success"] else 1)

    QTimer.singleShot(300, finish)
    return app.exec()
