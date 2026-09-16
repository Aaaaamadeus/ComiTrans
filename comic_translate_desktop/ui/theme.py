"""Shared monochrome tokens; UI fonts never enter the typesetter config."""
from __future__ import annotations
from functools import lru_cache
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from ..config import AI_ROOT, ICON_PATH

COLORS = dict(paper='#FFFFFF', workspace='#F2F2F2', muted='#E8E8E8', ink='#111111', black='#000000', secondary='#595959', disabled='#777777', rule='#B8B8B8', canvas='#242424')
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
QFrame#topBar { background: @paper; border-bottom: 3px solid @ink; }
QLabel#brandTitle { color: @black; }
QLabel#pageTitle { font-size: 24px; font-weight: 800; }
QLabel#sectionTitle { font-size: 17px; font-weight: 700; }
QLabel[muted="true"], QLabel#brandSubtitle, QLabel#dropHint { color: @secondary; font-size: 12px; }
QLabel#statusPill { padding: 7px 12px; border: 2px solid @ink; background: @paper; font-weight: 600; }
QLabel#statusPill[state="running"], QLabel#statusPill[state="warming"] { background: @ink; color: @paper; }
QLabel#statusPill[state="error"], QLabel#statusPill[state="warning"] { border: 3px double @ink; }
QPushButton, QToolButton { min-height: 26px; padding: 5px 12px; border: 2px solid @ink; border-radius: 0; background: @paper; }
QPushButton:hover, QToolButton:hover { background: @muted; }
QPushButton:pressed, QToolButton:pressed { background: @rule; }
QPushButton:focus, QToolButton:focus { border: 2px dashed @ink; }
QPushButton[role="primary"], QPushButton[role="nav"]:checked { background: @ink; color: @paper; font-weight: 700; }
QPushButton[role="primary"]:focus, QPushButton[role="nav"]:checked:focus { border: 2px dashed @paper; }
QPushButton[role="primary"]:hover { background: @black; }
QPushButton[role="quiet"], QToolButton[role="quiet"] { border-color: transparent; background: transparent; }
QPushButton[role="nav"] { border: 1px solid @ink; padding: 8px 24px; font-size: 18px; font-weight: 800; }
QPushButton[role="quiet"]:hover, QToolButton[role="quiet"]:hover { background: @muted; }
QPushButton[role="quiet"]:focus, QToolButton[role="quiet"]:focus, QPushButton[role="nav"]:focus { border-color: @ink; }
QPushButton[compact="true"], QToolButton[compact="true"] { min-height: 22px; padding: 3px 8px; }
QPushButton:disabled, QToolButton:disabled, QPushButton[role="primary"]:disabled { background: @muted; color: @disabled; border-color: @rule; }
QGroupBox { margin-top: 20px; padding: 16px 0 0 0; border: none; border-top: 1px solid @rule; background: @paper; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 12px 0 0; background: @paper; }
QFrame#queuePanel, QFrame#workPanel, QFrame#editorPanel { background: @paper; }
QFrame#queuePanel { border-right: 4px solid @ink; }
QFrame#controlCard { background: @paper; border-bottom: 1px solid @rule; }
QFrame#logPanel { background: @paper; border-top: 2px solid @ink; }
QTabWidget::pane { border: none; background: @paper; }
QTabBar::tab { padding: 6px 16px; min-height: 24px; border: none; border-bottom: 2px solid @ink; background: @paper; }
QTabBar::tab:selected { background: @ink; color: @paper; }
QTabBar::tab:hover:!selected { background: @muted; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox { padding: 5px 8px; border: 2px solid @ink; border-radius: 0; background: @paper; selection-background-color: @ink; selection-color: @paper; }
QLineEdit, QComboBox, QSpinBox { min-height: 22px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-style: dashed; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QPlainTextEdit:disabled { background: @muted; color: @disabled; border-color: @rule; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox::down-arrow { image: url("@icons/chevron-down.svg"); width: 16px; height: 16px; }
QFrame#controlCard QLineEdit, QFrame#controlCard QComboBox { min-height: 20px; padding: 2px 6px; border-width: 1px; font-size: 13px; }
QFrame#controlCard QPushButton, QFrame#controlCard QToolButton { min-height: 22px; padding: 2px 8px; border-width: 1px; font-size: 13px; }
QSpinBox::up-button, QSpinBox::down-button { width: 20px; border: none; background: @paper; }
QSpinBox::up-arrow { image: url("@icons/chevron-up.svg"); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url("@icons/chevron-down.svg"); width: 12px; height: 12px; }
QListWidget, QTreeView { padding: 0; border: none; background: @paper; }
QListWidget::item { padding: 8px 4px; border-bottom: 1px solid @rule; }
QListWidget::item:selected { background: @ink; color: @paper; }
QListWidget::item:hover:!selected { background: @workspace; }
QFrame#dropZone { background: @workspace; border: 1px dashed @secondary; }
QFrame#dropZone[dragActive="true"] { border: 2px solid @ink; background: @muted; }
QLabel#dropTitle { font-weight: 600; }
QScrollArea { border: none; }
QScrollArea#previewCanvas, QLabel#previewLabel { background: @canvas; color: @paper; }
QWidget#emptyPreview { background: @paper; }
QSplitter::handle { background: @workspace; }
QSplitter::handle:hover { background: @rule; }
QScrollBar:vertical { width: 12px; background: @workspace; margin: 0; }
QScrollBar:horizontal { height: 12px; background: @workspace; margin: 0; }
QScrollBar::handle { background: @secondary; min-height: 24px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid @ink; background: @paper; }
QCheckBox::indicator:checked { background: @ink; image: url("@icons/check.svg"); }
QCheckBox:focus { border: 1px dashed @ink; }
QToolTip { padding: 6px 8px; border: 1px solid @ink; background: @paper; color: @ink; }
QMenu { background: @paper; border: 2px solid @ink; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: @ink; color: @paper; }
'''
for _token, _color in COLORS.items():
    APP_STYLESHEET = APP_STYLESHEET.replace(f'@{_token}', _color)
APP_STYLESHEET = APP_STYLESHEET.replace('@icons', (ICON_PATH.parent / 'ui' / 'icons').as_posix())
