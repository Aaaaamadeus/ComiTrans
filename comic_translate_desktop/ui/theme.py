"""Shared monochrome tokens; UI fonts never enter the typesetter config."""
from __future__ import annotations
from functools import lru_cache
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from ..config import AI_ROOT, ICON_PATH

COLORS = dict(paper='#FFFFFF', workspace='#F8F8F8', muted='#EFEFEF', ink='#171717', black='#000000', secondary='#595959', disabled='#777777', rule='#DEDEDE', canvas='#F3F3F3')
SPACING = (4, 8, 12, 16, 24, 32)
UI_FAMILIES = ['Source Han Sans SC', '思源黑体 CN', 'Noto Sans CJK SC', 'Microsoft YaHei UI', 'Microsoft YaHei']
JP_FAMILIES = ['Source Han Sans JP', 'Noto Sans CJK JP', 'Yu Gothic', 'Meiryo']

def ui_font(size=14, weight=QFont.Normal, *, mono=False, japanese=False):
    available = set(QFontDatabase.families())
    preferred = (['JetBrains Mono', 'Consolas'] if mono else []) + (JP_FAMILIES if japanese else []) + UI_FAMILIES
    # A bundled display-only Heavy face must not become the body-text fallback.
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


def install_ui_font(app):
    font = ui_font()
    app.setFont(font)
    palette = QPalette()
    roles = {QPalette.Window:'workspace', QPalette.WindowText:'ink', QPalette.Base:'paper', QPalette.AlternateBase:'workspace', QPalette.Text:'ink', QPalette.Button:'paper', QPalette.ButtonText:'ink', QPalette.Highlight:'ink', QPalette.HighlightedText:'paper', QPalette.ToolTipBase:'paper', QPalette.ToolTipText:'ink', QPalette.Link:'ink', QPalette.LinkVisited:'secondary', QPalette.Light:'paper', QPalette.Midlight:'muted', QPalette.Mid:'rule', QPalette.Dark:'secondary', QPalette.Shadow:'black'}
    for role, token in roles.items():
        palette.setColor(role, QColor(COLORS[token]))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(COLORS['disabled']))
    app.setPalette(palette)
    return font.family()

def refresh_style(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()

APP_STYLESHEET = '''
QMainWindow, QWidget#appRoot { background: @workspace; color: @ink; }
QWidget { color: @ink; }
QFrame#topBar { background: @paper; border: none; }
QLabel#brandTitle { color: @black; }
QLabel#pageTitle { font-size: 24px; font-weight: 800; }
QLabel#sectionTitle { font-size: 17px; font-weight: 700; }
QLabel#emptyPreviewTitle { font-size: 28px; font-weight: 800; }
QLabel[muted="true"], QLabel#brandSubtitle, QLabel#dropHint { color: @secondary; font-size: 12px; }
QLabel#fieldCaption { font-size: 13px; font-weight: 700; padding-top: 6px; }
QLabel#statusPill { padding: 6px 10px; border: none; background: transparent; font-size: 12px; color: @secondary; }
QLabel#statusPill[state="running"], QLabel#statusPill[state="warming"] { color: @ink; font-weight: 700; }
QLabel#statusPill[state="error"], QLabel#statusPill[state="warning"] { color: @ink; font-weight: 700; }
QPushButton, QToolButton { min-height: 26px; padding: 6px 14px; border: 1px solid transparent; border-radius: 8px; background: transparent; }
QPushButton:hover, QToolButton:hover { background: @muted; }
QPushButton:pressed, QToolButton:pressed { background: @rule; }
QPushButton:focus, QToolButton:focus { border: 1px solid @rule; }
QPushButton[role="primary"] { background: @ink; color: @paper; border: 1px solid @ink; border-radius: 14px; padding: 8px 20px; font-weight: 700; }
QPushButton[role="primary"]:focus { border: 1px solid @secondary; }
QPushButton[role="primary"]:hover { background: @black; }
QPushButton[role="quiet"], QToolButton[role="quiet"] { border-color: transparent; background: transparent; color: @secondary; }
QPushButton[role="nav"] { border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 8px 12px; font-size: 15px; color: @secondary; }
QPushButton[role="nav"]:checked { border-bottom: 2px solid @ink; color: @ink; background: transparent; font-weight: 700; }
QPushButton[role="nav"]:hover { background: transparent; color: @ink; border-bottom-color: @rule; }
QPushButton[role="nav"]:checked:hover { border-bottom-color: @ink; }
QPushButton[role="utility"] { border: 1px solid transparent; background: transparent; padding: 5px 10px; }
QPushButton[role="utility"]:checked { background: @muted; color: @ink; border-color: transparent; }
QPushButton[role="utility"]:hover:!checked { background: @muted; }
QPushButton[role="utility"]:focus { border: 1px solid @rule; }
QPushButton[role="quiet"]:hover, QToolButton[role="quiet"]:hover { background: @muted; }
QPushButton[role="quiet"]:focus, QToolButton[role="quiet"]:focus { border-color: @rule; }
QPushButton[role="nav"]:focus { border-bottom-color: @ink; }
QPushButton[compact="true"], QToolButton[compact="true"] { min-height: 22px; padding: 3px 8px; }
QPushButton:disabled, QToolButton:disabled { background: transparent; color: @disabled; border-color: transparent; }
QPushButton[role="primary"]:disabled { background: @muted; color: @disabled; border-color: transparent; }
QGroupBox { margin-top: 24px; padding: 16px 0 0 0; border: none; background: transparent; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 12px 0 0; background: transparent; }
QFrame#queuePanel, QFrame#workPanel, QFrame#editorPanel { background: @paper; }
QFrame#pageBody, QFrame#editorToolbar, QFrame#editorInspector, QFrame#canvasPanel { background: @paper; }
QFrame#editorToolbar { border-bottom: 1px solid @rule; }
QFrame#editorInspector { background: @workspace; border: none; border-radius: 12px; }
QFrame#editorInspector QFrame#editorPanel { background: @workspace; }
QFrame#pageActions { background: @paper; border: none; }
QFrame#inspectorActions { background: @workspace; border: none; }
QLabel#editorStatus { background: @workspace; padding: 8px 12px; color: @secondary; font-size: 12px; }
QFrame#queuePanel { background: @workspace; border: none; }
QFrame#controlCard { background: @paper; border: none; }
QFrame#logPanel { background: @paper; border-top: 1px solid @rule; }
QTabWidget::pane { border: none; background: @paper; }
QTabBar::tab { padding: 7px 14px; min-height: 24px; border: none; border-bottom: 2px solid transparent; background: transparent; color: @secondary; font-weight: 500; }
QTabBar::tab:selected { background: transparent; color: @ink; border-bottom: 2px solid @ink; font-weight: 700; }
QTabBar::tab:hover:!selected { background: transparent; color: @ink; border-bottom: 2px solid @rule; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox { padding: 7px 10px; border: 1px solid transparent; border-radius: 8px; background: @workspace; selection-background-color: @ink; selection-color: @paper; }
QLineEdit, QComboBox, QSpinBox { min-height: 26px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: @rule; background: @paper; }
QPlainTextEdit[readOnly="true"] { border: none; background: transparent; }
QPlainTextEdit[readOnly="true"]:focus { border: none; background: transparent; }
QPlainTextEdit#logContent, QPlainTextEdit#logContent:focus { border: none; background: @paper; padding: 8px 10px; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QPlainTextEdit:disabled { background: @workspace; color: @disabled; border-color: transparent; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox::down-arrow { image: url("@icons/chevron-down.svg"); width: 16px; height: 16px; }
QFrame#controlCard QLineEdit, QFrame#controlCard QComboBox { min-height: 22px; padding: 3px 8px; border-color: transparent; font-size: 13px; }
QFrame#controlCard QLineEdit:focus, QFrame#controlCard QComboBox:focus { border-color: @rule; }
QFrame#controlCard QPushButton, QFrame#controlCard QToolButton { min-height: 24px; padding: 3px 10px; border-color: transparent; font-size: 13px; }
QFrame#controlCard QPushButton[role="primary"] { border-radius: 10px; }
QComboBox QLineEdit#fontSearchEditor, QComboBox QLineEdit#fontSearchEditor:focus { padding: 0; min-height: 0; border: none; border-radius: 0; background: transparent; }
QLineEdit#fontSearchEditor QToolButton { padding: 0; min-height: 0; min-width: 0; border: none; border-radius: 0; background: transparent; }
QSpinBox::up-button, QSpinBox::down-button { width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow { image: url("@icons/chevron-up.svg"); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url("@icons/chevron-down.svg"); width: 12px; height: 12px; }
QListWidget, QTreeView { padding: 0; border: none; background: transparent; }
QListWidget::item { padding: 8px 6px; border: none; border-left: 2px solid transparent; }
QListWidget::item:selected { background: @muted; color: @ink; border-left: 2px solid @ink; }
QListWidget::item:hover:!selected { background: @workspace; }
QFrame#dropZone { background: transparent; border: none; border-radius: 12px; }
QFrame#dropZone[dragActive="true"] { border: 1px solid @ink; background: @muted; }
QLabel#dropTitle { font-weight: 600; }
QScrollArea { border: none; }
QScrollArea#previewCanvas, QLabel#previewLabel { background: @canvas; color: @paper; }
QWidget#emptyPreview { background: @paper; }
QSplitter::handle { background: @paper; }
QSplitter::handle:hover { background: @muted; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 0; }
QScrollBar::handle { background: #B8B8B8; border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #B8B8B8; border-radius: 4px; background: @paper; }
QCheckBox::indicator:checked { background: @ink; image: url("@icons/check.svg"); }
QCheckBox:focus { color: @black; }
QToolTip { padding: 6px 8px; border: 1px solid @rule; border-radius: 6px; background: @paper; color: @ink; }
QMenu { background: @paper; border: 1px solid @rule; padding: 4px; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: @ink; color: @paper; }
'''
for _token, _color in COLORS.items():
    APP_STYLESHEET = APP_STYLESHEET.replace(f'@{_token}', _color)
APP_STYLESHEET = APP_STYLESHEET.replace('@icons', (ICON_PATH.parent / 'ui' / 'icons').as_posix())
