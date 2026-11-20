"""Shared monochrome tokens; UI fonts never enter the typesetter config."""
from __future__ import annotations
from functools import lru_cache
from weakref import ref as weakref
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QIcon, QPalette
from shiboken6 import isValid
from ..config import AI_ROOT, ICON_PATH
from ..i18n import ui_language

SPACING = (4, 8, 12, 16, 24, 32)
UI_FAMILIES = ['Source Han Sans SC', '思源黑体 CN', 'Noto Sans CJK SC', 'Microsoft YaHei UI', 'Microsoft YaHei']
JP_FAMILIES = ['Source Han Sans JP', 'Noto Sans CJK JP', 'Yu Gothic', 'Meiryo']
# Shipped with the app; registered only when the OS has no usable CJK UI face.
UI_FALLBACK_FONT = 'CN/SourceHanSansSC-Medium-2.otf'
# A UI label may only resolve to these; screenshot review scripts assert it.
UI_FONT_ALLOWLIST = frozenset(UI_FAMILIES + JP_FAMILIES)

PALETTES = {
    'light': dict(
        paper='#FFFFFF', workspace='#F8F8F8', muted='#EFEFEF', elevated='#FFFFFF',
        ink='#171717', black='#000000', secondary='#595959', disabled='#777777',
        rule='#DEDEDE', ruleStrong='#868686', canvas='#F3F3F3', pageEdge='#DEDEDE',
        guide='#2C6E96', guideHalo='#FFFFFF', tone='#111111', toneAlpha=1.0, toneBlend='multiply',
        scrollHandle='#B8B8B8', focusRing='#171717', iconDir='icons'),
    'dark': dict(
        paper='#17181B', workspace='#111214', muted='#24262B', elevated='#1E2024',
        ink='#EDEDEF', black='#FFFFFF', secondary='#A3A5AC', disabled='#6C6F76',
        rule='#34373D', ruleStrong='#7C818B', canvas='#0B0C0E', pageEdge='#3A3E45',
        guide='#2C6E96', guideHalo='#0B0C0E', tone='#FFFFFF', toneAlpha=0.22, toneBlend='source',
        scrollHandle='#4A4E57', focusRing='#EDEDEF', iconDir='icons/dark'),
}
COLORS = PALETTES['light']

_theme_mode = 'light'
_theme_request = 'light'
_theme_watched = False


class _ThemeHub(QObject):
    changed = Signal(str)


theme_changed = _ThemeHub()


def theme_name():
    return _theme_mode


def theme():
    return PALETTES[_theme_mode]


def color(name):
    return theme()[name]


def _ui_families(available):
    # A bundled display-only Heavy face must not become the body-text fallback.
    return [name for name in UI_FAMILIES if name in available and
            QFontDatabase.styles(name) != ['Heavy']]


def _register_ui_fallback():
    """Never let the handwritten log face become the interface font.

    Without an OS CJK sans (headless screenshots, stripped Windows installs),
    Qt picks any registered font that has the glyphs - in this app that is the
    bundled handwriting face, which is only meant for log lines.
    """
    return _bundled_font_families(UI_FALLBACK_FONT)


def resolved_ui_font_family(size=14):
    return QFontInfo(ui_font(size)).family()


def ui_font(size=14, weight=QFont.Normal, *, mono=False, japanese=False):
    available = set(QFontDatabase.families())
    preferred_ui = _ui_families(available)
    if not preferred_ui:
        _register_ui_fallback()
        available = set(QFontDatabase.families())
        preferred_ui = _ui_families(available)
    preferred = ((['JetBrains Mono', 'Consolas'] if mono else [])
                 + (JP_FAMILIES if japanese or ui_language() == 'ja' else [])
                 + (preferred_ui or UI_FAMILIES))
    families = [name for name in preferred if name in available and
                QFontDatabase.styles(name) != ['Heavy']]
    font = QFont()
    if families:
        font.setFamilies(families)
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


@lru_cache(maxsize=8)
def _bundled_font_families(relative_path, *, ui_asset=False):
    # Register on the GUI thread once; use Qt's actual family names, not filenames.
    root = ICON_PATH.parent / 'ui' / 'fonts' if ui_asset else AI_ROOT / 'font_file'
    path = root / relative_path
    font_id = QFontDatabase.addApplicationFont(str(path))
    return tuple(QFontDatabase.applicationFontFamilies(font_id)) if font_id >= 0 else ()


def log_font(size=18):
    """Legible handwritten log messages, with ordinary CJK fallback if unavailable."""
    font = ui_font(size)
    families = list(_bundled_font_families('AaJinRiHuaQing-ChunLanMaoKun.ttf', ui_asset=True))
    if families:
        font.setFamilies(families + font.families())
    return font


def brand_font(size=48):
    """Use the supplied Skribble face without synthetic bold or italic styling."""
    font = ui_font(size)
    families = list(_bundled_font_families('Skribble.ttf', ui_asset=True))
    if families:
        font.setFamilies(families + font.families())
    return font


def display_font(size, *, italic=False):
    font = ui_font(size, QFont.Black)
    families = list(_bundled_font_families('CN/SourceHanSansSC-Heavy-2.otf'))
    if families:
        font.setFamilies(families + font.families())
        font.setStyleName('Heavy')
    font.setItalic(italic)
    return font


def resolve_theme(mode, app=None):
    if mode in PALETTES:
        return mode
    if mode == 'auto' and app is not None:
        try:
            scheme = app.styleHints().colorScheme()
            return 'dark' if scheme == Qt.ColorScheme.Dark else 'light'
        except Exception:
            return 'light'
    return 'light'


def build_stylesheet(palette=None):
    palette = palette or theme()
    sheet = APP_STYLESHEET_TEMPLATE
    # Longest first: "@ruleStrong" must not be eaten by "@rule".
    for token in sorted(palette, key=len, reverse=True):
        sheet = sheet.replace(f'@{token}', str(palette[token]))
    icons = (ICON_PATH.parent / 'ui' / palette['iconDir']).as_posix()
    return sheet.replace('@icons', icons)


def apply_palette(app, palette=None):
    palette = palette or theme()
    qt_palette = QPalette()
    roles = {
        QPalette.Window: 'workspace', QPalette.WindowText: 'ink', QPalette.Base: 'paper',
        QPalette.AlternateBase: 'workspace', QPalette.Text: 'ink', QPalette.Button: 'paper',
        QPalette.ButtonText: 'ink', QPalette.Highlight: 'ink', QPalette.HighlightedText: 'paper',
        QPalette.ToolTipBase: 'elevated', QPalette.ToolTipText: 'ink', QPalette.Link: 'ink',
        QPalette.LinkVisited: 'secondary', QPalette.Light: 'paper', QPalette.Midlight: 'muted',
        QPalette.Mid: 'rule', QPalette.Dark: 'secondary', QPalette.Shadow: 'black',
    }
    for role, token in roles.items():
        qt_palette.setColor(role, QColor(palette[token]))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        qt_palette.setColor(QPalette.Disabled, role, QColor(palette['disabled']))
    app.setPalette(qt_palette)


def apply_theme(app, mode='light'):
    """Switch the whole app between the paper and night palettes at runtime."""
    global _theme_mode, _theme_request, _theme_watched
    if app is None:
        return _theme_mode
    _theme_request = mode if mode in ('auto', 'light', 'dark') else 'light'
    resolved = resolve_theme(mode, app)
    changed = resolved != _theme_mode
    _theme_mode = resolved
    apply_palette(app)
    app.setStyleSheet(build_stylesheet())
    from .motion import install_material_motion
    install_material_motion(app)
    if not _theme_watched:
        _theme_watched = True
        try:
            app.styleHints().colorSchemeChanged.connect(
                lambda *_: apply_theme(app, 'auto') if _theme_request == 'auto' else None)
        except Exception:
            pass
    if changed:
        for widget in app.allWidgets():
            widget.update()
        theme_changed.changed.emit(resolved)
    return resolved


def install_ui_font(app):
    font = ui_font()
    app.setFont(font)
    apply_palette(app)
    app.setStyleSheet(build_stylesheet())
    from .motion import install_material_motion
    install_material_motion(app)
    return font.family()


def refresh_style(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


_icon_buttons = []


@lru_cache(maxsize=64)
def themed_icon(name, theme_key):
    path = ICON_PATH.parent / 'ui' / PALETTES[theme_key]['iconDir'] / f'{name}.svg'
    return QIcon(str(path))


def set_themed_icon(button, name, size=14):
    button.setProperty('themedIcon', name)
    button.setIconSize(QSize(size, size))
    button.setIcon(themed_icon(name, theme_name()))
    _icon_buttons.append(weakref(button))


def refresh_themed_icons():
    alive = []
    for reference in _icon_buttons:
        widget = reference()
        if widget is None or not isValid(widget):
            continue
        name = widget.property('themedIcon')
        if name:
            widget.setIcon(themed_icon(name, theme_name()))
        alive.append(reference)
    _icon_buttons[:] = alive


theme_changed.changed.connect(lambda *_: refresh_themed_icons())


APP_STYLESHEET_TEMPLATE = '''
QMainWindow, QWidget#appRoot { background: @workspace; color: @ink; }
QWidget { color: @ink; }
QFrame#topBar { background: @paper; border: none; border-bottom: 1px solid @rule; }
QLabel#brandTitle { color: @black; }
QLabel#pageTitle { font-size: 24px; font-weight: 800; }
QLabel#sectionTitle { font-size: 17px; font-weight: 700; }
QLabel#emptyPreviewTitle { font-size: 28px; font-weight: 800; }
QLabel[muted="true"], QLabel#brandSubtitle, QLabel#dropHint { color: @secondary; font-size: 12px; }
QLabel#fieldCaption { font-size: 13px; font-weight: 700; padding-top: 4px; }
QLabel#barCaption { font-size: 12px; font-weight: 700; color: @secondary; }
QLabel#cardTitle { font-size: 13px; font-weight: 700; color: @ink; }
QLabel#fontChoiceName { color: @secondary; font-size: 12px; padding: 2px 0 2px 0; }
QFrame#statusPill { background: transparent; border: none; }
QFrame#statusPill[active="true"] { background: @muted; border-radius: 10px; }
QLabel#statusText { font-size: 12px; color: @secondary; background: transparent; }
QLabel#statusText[state="running"], QLabel#statusText[state="warming"],
QLabel#statusText[state="error"], QLabel#statusText[state="warning"] { color: @ink; font-weight: 700; }
QLabel#statusDot { background: @secondary; border: none; border-radius: 4px; }
QLabel#statusDot[state="running"], QLabel#statusDot[state="warming"],
QLabel#statusDot[state="ready"], QLabel#statusDot[state="success"],
QLabel#statusDot[state="stopping"] { background: @ink; }
QLabel#statusDot[state="warning"], QLabel#statusDot[state="error"] {
    background: transparent; border: 2px solid @ink; }
QPushButton, QToolButton { min-height: 26px; padding: 6px 14px; border: 1px solid transparent; border-radius: 8px; background: transparent; }
QPushButton:hover, QToolButton:hover { background: @muted; }
QPushButton:pressed, QToolButton:pressed { background: @rule; }
QPushButton:focus, QToolButton:focus { border: 1px solid @ruleStrong; }
QPushButton[role="primary"] { background: @ink; color: @paper; border: 1px solid @ink; border-radius: 14px; padding: 8px 20px; font-weight: 700; }
QPushButton[role="primary"]:focus { border: 1px solid @secondary; }
QPushButton[role="primary"]:hover { background: @black; }
QPushButton[role="quiet"], QToolButton[role="quiet"] { border-color: transparent; background: transparent; color: @secondary; }
QPushButton[role="nav"] { border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 8px 12px; font-size: 15px; color: @secondary; }
QPushButton[role="nav"]:checked { border-bottom: 2px solid @ink; color: @ink; background: transparent; font-weight: 700; }
QPushButton[role="nav"]:hover { background: transparent; color: @ink; border-bottom-color: @rule; }
QPushButton[role="nav"]:checked:hover { border-bottom-color: @ink; }
QPushButton[role="nav"][animatedIndicator="true"]:checked,
QPushButton[role="nav"][animatedIndicator="true"]:checked:hover { border-bottom-color: transparent; }
QPushButton[role="utility"], QToolButton[role="utility"] { border: 1px solid @rule; background: @paper; color: @ink; padding: 5px 10px; border-radius: 8px; }
QPushButton[role="utility"]:checked, QToolButton[role="utility"]:checked { background: @muted; color: @ink; border: 1.5px solid @ink; }
QPushButton[role="utility"]:hover:!checked, QToolButton[role="utility"]:hover:!checked { background: @muted; border-color: @ruleStrong; }
QPushButton[role="utility"]:focus, QToolButton[role="utility"]:focus { border: 1.5px solid @focusRing; }
QPushButton[role="utility"]:disabled, QToolButton[role="utility"]:disabled { background: transparent; color: @disabled; border-color: @rule; }
QPushButton[role="chip"], QToolButton[role="chip"] { border: 1px solid @rule; background: @paper; color: @ink; border-radius: 7px; padding: 3px 9px; }
QPushButton[role="chip"]:hover:!checked, QToolButton[role="chip"]:hover:!checked { background: @muted; border-color: @ruleStrong; }
QPushButton[role="chip"]:checked, QToolButton[role="chip"]:checked { background: @muted; color: @ink; border: 1.5px solid @ink; }
QPushButton[role="chip"]:focus, QToolButton[role="chip"]:focus { border: 1.5px solid @focusRing; }
QPushButton[role="chip"]:disabled, QToolButton[role="chip"]:disabled { background: transparent; color: @disabled; border-color: transparent; }
QToolButton#blockNavBtn, QPushButton#zoomStepBtn { padding: 0px; }
QToolButton#blockNavBtn:disabled, QPushButton#zoomStepBtn:disabled { border: 1px solid @rule; background: transparent; }
QPushButton[role="retry"] { border: 1px solid @ruleStrong; border-radius: 10px; padding: 6px 16px; background: @paper; }
QPushButton[role="retry"]:hover { background: @muted; }
QPushButton[role="quiet"]:hover, QToolButton[role="quiet"]:hover { background: @muted; }
QPushButton[role="quiet"]:focus, QToolButton[role="quiet"]:focus { border-color: @ruleStrong; }
QPushButton[role="nav"]:focus { border-bottom-color: @ink; }
QPushButton[compact="true"], QToolButton[compact="true"] { min-height: 22px; padding: 3px 9px; }
QPushButton:disabled, QToolButton:disabled { background: transparent; color: @disabled; border-color: transparent; }
QPushButton[role="primary"]:disabled { background: @muted; color: @disabled; border-color: transparent; }
QGroupBox { margin-top: 24px; padding: 16px 0 0 0; border: none; background: transparent; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 12px 0 0; background: transparent; }
QFrame#queuePanel, QFrame#workPanel, QFrame#editorPanel { background: @paper; }
QFrame#pageBody, QFrame#editorToolbar, QFrame#canvasPanel { background: @paper; }
QFrame#editorToolbar { border-bottom: 1px solid @rule; }
QFrame#favoriteFontsBar, QFrame#canvasToolBar { background: @workspace; border: 1px solid @rule; border-radius: 10px; }
QFrame#toolbarDivider { background: @rule; border: none; }
QFrame#editorSidebar, QFrame#editorInspector { background: @workspace; border: 1px solid @rule; border-radius: 12px; }
QFrame#editorSidebar QFrame#editorPanel, QFrame#editorInspector QFrame#editorPanel { background: @workspace; }
QFrame#inspectorHeader { background: transparent; border-bottom: 1px solid @rule; }
QFrame#inspectorCard { background: @paper; border: 1px solid @rule; border-radius: 10px; }
QFrame#inspectorScrollContent { background: transparent; }
QScrollArea#inspectorScroll { background: transparent; border: none; }
QFrame#pageActions { background: @paper; border: none; border-top: 1px solid @rule; }
QFrame#sidebarFooter { background: transparent; border: none; border-top: 1px solid @rule; }
QFrame#inspectorActions { background: transparent; border: none; border-top: 1px solid @rule; }
QLabel#editorStatus { background: @workspace; border: 1px solid @rule; border-radius: 8px; padding: 5px 12px; color: @secondary; font-size: 12px; }
QFrame#queuePanel { background: @workspace; border: none; }
QFrame#controlCard { background: @paper; border: none; }
QFrame#starPrompt { background: @elevated; border: 1px solid @rule; border-radius: 14px; }
QFrame#starPrompt QLabel { background: transparent; border: none; }
QLabel#starPromptTitle { font-weight: 700; font-size: 15px; }
QFrame#starPrompt QToolButton { padding: 0; min-width: 24px; min-height: 24px; font-size: 20px; }
QFrame#logPanel { background: @paper; border-top: 1px solid @rule; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { padding: 7px 14px; min-height: 24px; border: none; border-bottom: 2px solid transparent; background: transparent; color: @secondary; font-weight: 500; }
QTabBar::tab:selected { background: transparent; color: @ink; border-bottom: 2px solid @ink; font-weight: 700; }
QTabBar[animatedIndicator="true"]::tab:selected { border-bottom-color: transparent; }
QTabBar::tab:hover:!selected { background: transparent; color: @ink; border-bottom: 2px solid @rule; }
QFrame#editorInspector QTabBar::tab { padding: 5px 12px; min-height: 20px; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox { padding: 6px 9px; border: 1px solid transparent; border-bottom: 1px solid @ruleStrong; border-radius: 8px; background: @workspace; selection-background-color: @ink; selection-color: @paper; }
QLineEdit, QSpinBox, QDoubleSpinBox { min-height: 26px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: transparent; border-bottom: 1px solid @focusRing; background: @paper; }
QComboBox { combobox-popup: 0; min-height: 26px; padding: 5px 6px 5px 10px; border: 1px solid @rule; border-radius: 8px; background: @workspace; color: @ink; selection-background-color: @ink; selection-color: @paper; }
QComboBox:hover { border-color: @ruleStrong; background: @paper; }
QComboBox:focus, QComboBox:on { border: 1.5px solid @ink; background: @paper; }
QComboBox:disabled { background: @workspace; color: @disabled; border-color: @rule; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 26px; border: none; background: transparent; border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
QComboBox::down-arrow { image: url("@icons/chevron-down.svg"); width: 14px; height: 14px; }
QComboBox::down-arrow:on { image: url("@icons/chevron-up.svg"); width: 14px; height: 14px; }
QComboBox QLineEdit, QComboBox QLineEdit:focus { padding: 0; min-height: 0; border: none; border-radius: 0; background: transparent; }
QComboBox QAbstractItemView, QCompleter QAbstractItemView { background: @elevated; color: @ink; border: 1px solid @ruleStrong; border-radius: 10px; padding: 4px; outline: none; selection-background-color: @ink; selection-color: @paper; }
QComboBox QAbstractItemView::item, QCompleter QAbstractItemView::item { min-height: 28px; padding: 4px 10px; border-radius: 6px; color: @ink; background: transparent; }
QComboBox QAbstractItemView::item:hover, QCompleter QAbstractItemView::item:hover { background: @muted; color: @ink; }
QComboBox QAbstractItemView::item:selected, QCompleter QAbstractItemView::item:selected { background: @ink; color: @paper; }
QFrame#inspectorCard QSpinBox, QFrame#inspectorCard QDoubleSpinBox { min-height: 18px; padding: 2px 7px; border: 1px solid @rule; border-bottom: 1px solid @ruleStrong; background: @workspace; }
QFrame#inspectorCard QSpinBox:focus, QFrame#inspectorCard QDoubleSpinBox:focus { border: 1px solid @focusRing; background: @paper; }
QFrame#inspectorCard QComboBox { min-height: 22px; padding: 3px 4px 3px 8px; border: 1px solid @rule; border-radius: 7px; background: @workspace; }
QFrame#inspectorCard QComboBox:hover { border-color: @ruleStrong; background: @paper; }
QFrame#inspectorCard QComboBox:focus, QFrame#inspectorCard QComboBox:on { border: 1.5px solid @ink; background: @paper; }
QPlainTextEdit[readOnly="true"] { border: none; background: transparent; }
QPlainTextEdit[readOnly="true"]:focus { border: none; background: transparent; }
QPlainTextEdit#logContent, QPlainTextEdit#logContent:focus { border: none; background: @paper; padding: 8px 10px; }
QPlainTextEdit#prefInput { background: @workspace; border: 1px solid @rule; border-radius: 8px; padding: 6px 8px; }
QPlainTextEdit#prefInput:focus { border-color: @ruleStrong; background: @paper; }
QPlainTextEdit#textInput { background: @paper; border: 1px solid @rule; border-radius: 8px; padding: 8px 10px; font-size: 15px; }
QPlainTextEdit#textInput:focus { border: 1.5px solid @focusRing; background: @paper; }
QPlainTextEdit#textSource { background: @paper; border: 1px solid @rule; border-radius: 8px; padding: 7px 10px; font-size: 14px; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QPlainTextEdit:disabled { background: @workspace; color: @disabled; border-color: transparent; }
QFrame#inspectorCard QComboBox:disabled, QFrame#inspectorCard QSpinBox:disabled, QFrame#inspectorCard QDoubleSpinBox:disabled { background: @workspace; color: @disabled; border-color: @rule; }
QFrame#controlCard QLineEdit { min-height: 28px; padding: 4px 10px; border-color: transparent; font-size: 13px; }
QFrame#controlCard QLineEdit:focus { border-color: @ruleStrong; }
QFrame#controlCard QComboBox { min-height: 28px; padding: 4px 6px 4px 10px; border: 1px solid @rule; border-radius: 8px; background: @workspace; font-size: 13px; }
QFrame#controlCard QComboBox:hover { border-color: @ruleStrong; background: @paper; }
QFrame#controlCard QComboBox:focus, QFrame#controlCard QComboBox:on { border: 1.5px solid @ink; background: @paper; }
QFrame#controlCard QPushButton, QFrame#controlCard QToolButton { min-height: 28px; padding: 4px 12px; border-color: transparent; font-size: 13px; }
QFrame#controlCard QPushButton[role="primary"] { border-radius: 10px; min-height: 32px; }
QFrame#optionDivider { background: @rule; border: none; margin: 6px 0; }
QLabel#optionArrow { color: @secondary; padding: 0 2px; }
QLabel#cudaHelp { background: @muted; color: @secondary; border: 1px solid @rule;
    border-radius: 9px; font-size: 11px; font-weight: 700; }
QLabel#cudaHelp:hover { color: @ink; border-color: @ruleStrong; }
QComboBox QLineEdit#fontSearchEditor, QComboBox QLineEdit#fontSearchEditor:focus { padding: 0; min-height: 0; border: none; border-radius: 0; background: transparent; }
QLineEdit#fontSearchEditor QToolButton { padding: 0; min-height: 0; min-width: 0; border: none; border-radius: 0; background: transparent; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button { width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("@icons/chevron-up.svg"); width: 12px; height: 12px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("@icons/chevron-down.svg"); width: 12px; height: 12px; }
QListWidget, QTreeView { padding: 0; border: none; background: transparent; }
QListWidget::item { padding: 8px 6px; border: none; border-left: 2px solid transparent; }
QListWidget::item:selected { background: @muted; color: @ink; border-left: 2px solid @ink; }
QListWidget::item:hover:!selected { background: @workspace; }
QListWidget#blockList { background: @paper; border: 1px solid @rule; border-radius: 8px; padding: 3px; }
QListWidget#blockList::item { padding: 2px 4px; border: none; }
QListWidget#pageList::item { border-radius: 6px; padding: 6px 6px; margin: 1px 0; border: 1px solid transparent; border-left: 2px solid transparent; }
QListWidget#pageList::item:selected { background: @paper; color: @ink; border: 1px solid @rule; border-left: 3px solid @ink; border-top-left-radius: 2px; border-bottom-left-radius: 2px; border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
QListWidget#pageList::item:hover:!selected { background: @muted; }
QFrame#dropZone { background: transparent; border: 1px dashed @ruleStrong; border-radius: 12px; }
QFrame#dropZone[dragActive="true"] { border: 1.5px solid @ink; background: @muted; }
QLabel#dropTitle { font-weight: 600; }
QScrollArea { border: none; }
QScrollArea#previewCanvas, QLabel#previewLabel { background: @canvas; color: @paper; }
QWidget#emptyPreview { background: @paper; }
QWidget#canvasState { background: @paper; }
QLabel#zoomHud { background: @ink; color: @paper; border-radius: 10px; padding: 4px 10px; font-size: 12px; font-weight: 600; }
QLabel#canvasStateTitle { font-size: 20px; font-weight: 700; color: @ink; }
QProgressBar#canvasStateBar { background: @muted; border: none; border-radius: 2px; min-height: 4px; max-height: 4px; }
QProgressBar#canvasStateBar::chunk { background: @ink; border-radius: 2px; }
QSplitter::handle { background: @paper; }
QSplitter::handle:hover { background: @muted; }
QSplitter#inspectorSplitter::handle { background: @rule; margin: 3px 36px; border-radius: 2px; }
QSplitter#inspectorSplitter::handle:hover { background: @ruleStrong; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 0; }
QScrollBar::handle { background: @scrollHandle; border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid @ruleStrong; border-radius: 4px; background: @paper; }
QCheckBox::indicator:checked { background: @ink; image: url("@icons/check.svg"); }
QCheckBox:focus { color: @black; }
QToolTip { padding: 6px 8px; border: 1px solid @rule; border-radius: 6px; background: @elevated; color: @ink; }
QMenu { background: @elevated; border: 1px solid @rule; padding: 4px; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: @ink; color: @paper; }
'''

APP_STYLESHEET = build_stylesheet(PALETTES['light'])
