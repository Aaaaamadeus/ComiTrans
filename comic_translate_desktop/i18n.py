"""Interface-only translations; never change model prompts or document text."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import sys

UI_LANGUAGES = (("zh-CN", "中文"), ("en", "English"), ("ja", "日本語"))
_language = "zh-CN"


def normalize_ui_language(value) -> str:
    code = str(value or "").strip().replace("_", "-").lower()
    if code == "en" or code.startswith("en-"):
        return "en"
    if code == "ja" or code.startswith("ja-"):
        return "ja"
    return "zh-CN"


def ui_language() -> str:
    return _language


def set_ui_language(value) -> str:
    global _language
    _language = normalize_ui_language(value)
    return _language


def catalog_directory() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / "assets" / "i18n"


@lru_cache(maxsize=2)
def load_ui_catalog(language: str) -> dict[str, str]:
    if language == "zh-CN":
        return {}
    try:
        return json.loads((catalog_directory() / f"{language}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # A damaged optional catalog must not prevent startup.


def tr(source, *, language=None, **values):
    if not isinstance(source, str):
        return source
    code = normalize_ui_language(language) if language is not None else _language
    result = load_ui_catalog(code).get(source, source)
    return result.format(**values) if values else result


def install_qt_language(app):
    """Localize Qt-owned buttons/menus as well as our own interface strings."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    previous = getattr(app, '_comitrans_qt_translator', None)
    if previous is not None:
        app.removeTranslator(previous)
    QLocale.setDefault(QLocale({'zh-CN': 'zh_CN', 'en': 'en_US', 'ja': 'ja_JP'}[_language]))
    translator = QTranslator(app)
    suffix = {'zh-CN': 'zh_CN', 'en': 'en', 'ja': 'ja'}[_language]
    if translator.load(f'qtbase_{suffix}', QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    app._comitrans_qt_translator = translator


def initialize_ui_language(app, *, choose_language=None):
    """Run once from the real entry point; constructing test windows never prompts."""
    from . import config
    settings = config.load_ai_config()
    set_ui_language(settings['ui_language'])
    install_qt_language(app)
    if not settings['ui_language_selected']:
        if choose_language is None:
            from .ui.language_dialog import choose_interface_language
            choose_language = choose_interface_language
        set_ui_language(choose_language(settings['ui_language']))
        install_qt_language(app)
        try:
            config.save_ai_config({'ui_language': _language, 'ui_language_selected': True})
        except OSError as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, tr('界面语言未保存'), tr('本次选择已应用，但无法保存：{error}', error=str(exc)))
    return _language
