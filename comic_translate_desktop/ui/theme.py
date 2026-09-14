from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

from .. import config as app_config


APP_STYLESHEET = r"""
QMainWindow,
QWidget#appRoot {
    background-color: #f3f6fb;
    color: #18243a;
}

QWidget {
    font-size: 13px;
}

QFrame#topBar,
QFrame#controlCard,
QFrame#logPanel {
    background: #ffffff;
    border: 1px solid #e2e8f2;
    border-radius: 12px;
}

QFrame#topBar {
    border-bottom: 2px solid #dce7fb;
}

QLabel#brandTitle {
    color: #10203b;
    font-size: 20px;
    font-weight: 700;
}

QLabel#brandSubtitle,
QLabel[muted="true"] {
    color: #77839a;
    font-size: 12px;
}

QLabel#sectionTitle {
    color: #1b2c48;
    font-size: 14px;
    font-weight: 650;
}

QLabel#statusPill {
    padding: 6px 11px;
    border: 1px solid #dbe3ee;
    border-radius: 11px;
    background: #f6f8fb;
    color: #667085;
    font-size: 12px;
    font-weight: 600;
}

QLabel#statusPill[state="warming"] {
    background: #fff8e8;
    border-color: #f1d48c;
    color: #8a6116;
}

QLabel#statusPill[state="ready"],
QLabel#statusPill[state="success"] {
    background: #ebf8f1;
    border-color: #b8e3ca;
    color: #247a4a;
}

QLabel#statusPill[state="running"] {
    background: #ebf2ff;
    border-color: #bdd1fa;
    color: #245cc7;
}

QLabel#statusPill[state="stopping"],
QLabel#statusPill[state="warning"] {
    background: #fff4e8;
    border-color: #f2cda9;
    color: #a05a18;
}

QLabel#statusPill[state="error"] {
    background: #fff0f0;
    border-color: #f1c1c1;
    color: #b13b3b;
}

QPushButton,
QToolButton {
    min-height: 26px;
    padding: 4px 12px;
    border: 1px solid #d5deea;
    border-radius: 7px;
    background: #ffffff;
    color: #2c3b55;
    font-weight: 550;
}

QPushButton:hover,
QToolButton:hover {
    background: #f4f7fc;
    border-color: #9eb7df;
    color: #174d9f;
}

QPushButton:pressed,
QToolButton:pressed {
    background: #e9eff9;
}

QPushButton:disabled,
QToolButton:disabled {
    background: #f4f6f9;
    border-color: #e2e6ec;
    color: #a5adba;
}

QPushButton[role="primary"] {
    min-height: 30px;
    padding: 5px 17px;
    border-color: #2d6cdf;
    background: #2d6cdf;
    color: #ffffff;
    font-weight: 650;
}

QPushButton[role="primary"]:hover {
    border-color: #245fc8;
    background: #245fc8;
    color: #ffffff;
}

QPushButton[role="primary"]:pressed {
    background: #1e51ad;
}

QPushButton[role="primary"]:disabled {
    border-color: #c7d5ed;
    background: #c7d5ed;
    color: #f7f9fd;
}

QPushButton[role="danger"] {
    border-color: #edc8c8;
    background: #fff8f8;
    color: #b34242;
}

QPushButton[role="danger"]:hover {
    border-color: #df9f9f;
    background: #fff0f0;
    color: #9d3030;
}

QPushButton[role="quiet"],
QToolButton[role="quiet"] {
    background: transparent;
    border-color: transparent;
    color: #5d6b82;
}

QPushButton[role="quiet"]:hover,
QToolButton[role="quiet"]:hover {
    background: #edf3fc;
    border-color: #dbe6f6;
    color: #245cae;
}

QPushButton[compact="true"],
QToolButton[compact="true"] {
    min-height: 24px;
    padding: 3px 9px;
    font-size: 12px;
}

QGroupBox {
    margin-top: 13px;
    padding: 10px 10px 8px 10px;
    border: 1px solid #e0e7f1;
    border-radius: 12px;
    background: #ffffff;
    color: #46546b;
    font-weight: 650;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background: #f3f6fb;
    color: #53627a;
}

QTabWidget::pane {
    top: -1px;
    border: 1px solid #e0e7f1;
    border-radius: 10px;
    background: #ffffff;
}

QTabBar::tab {
    min-width: 88px;
    min-height: 29px;
    padding: 3px 14px;
    margin-right: 3px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    background: transparent;
    color: #738096;
    font-weight: 550;
}

QTabBar::tab:hover {
    background: #edf3fc;
    color: #315f9f;
}

QTabBar::tab:selected {
    background: #ffffff;
    border-color: #e0e7f1;
    border-bottom-color: #2d6cdf;
    color: #1c4f9d;
    font-weight: 650;
}

QLineEdit,
QPlainTextEdit,
QTextEdit,
QComboBox,
QSpinBox {
    min-height: 28px;
    padding: 3px 8px;
    border: 1px solid #d6deea;
    border-radius: 7px;
    background: #fbfcfe;
    color: #24334d;
    selection-background-color: #bcd2f7;
}

QLineEdit:hover,
QPlainTextEdit:hover,
QTextEdit:hover,
QComboBox:hover,
QSpinBox:hover {
    border-color: #b3c3da;
}

QLineEdit:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QComboBox:focus,
QSpinBox:focus {
    border: 1px solid #4f82df;
    background: #ffffff;
}

QLineEdit:disabled,
QPlainTextEdit:disabled,
QTextEdit:disabled,
QComboBox:disabled,
QSpinBox:disabled {
    background: #f2f4f7;
    color: #9aa3b2;
}

QPlainTextEdit[code="true"] {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}

QComboBox::drop-down {
    width: 26px;
    border: none;
}

QListWidget,
QTreeView {
    padding: 5px;
    border: 1px solid #dde5ef;
    border-radius: 9px;
    background: #f8fafd;
    outline: none;
}

QListWidget::item {
    padding: 6px;
    margin: 2px;
    border: 1px solid transparent;
    border-radius: 8px;
    color: #45536b;
}

QListWidget::item:hover {
    background: #edf3fc;
    border-color: #dbe6f7;
}

QListWidget::item:selected {
    background: #e5efff;
    border-color: #a9c6f4;
    color: #174f9f;
}

QFrame#dropZone {
    background: #f7faff;
    border: 1px dashed #a9bddb;
    border-radius: 10px;
}

QFrame#dropZone[dragActive="true"] {
    background: #e9f1ff;
    border: 2px solid #5f8edf;
}

QLabel#dropTitle {
    color: #294a78;
    font-weight: 650;
}

QLabel#dropHint {
    color: #7a879b;
    font-size: 11px;
}

QProgressBar {
    min-height: 11px;
    max-height: 11px;
    border: none;
    border-radius: 5px;
    background: #e7ecf3;
    color: transparent;
    text-align: center;
}

QProgressBar::chunk {
    border-radius: 5px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #5c8de7,
        stop: 1 #2d6cdf
    );
}

QFrame#stageCard {
    min-width: 74px;
    border: 1px solid #e0e6ef;
    border-radius: 9px;
    background: #f8fafd;
}

QFrame#stageCard[stageState="running"] {
    border: 1px solid #7aa3eb;
    background: #eaf2ff;
}

QFrame#stageCard[stageState="done"] {
    border: 1px solid #b8dfc8;
    background: #eef9f3;
}

QFrame#stageCard[stageState="failed"] {
    border: 1px solid #edbaba;
    background: #fff1f1;
}

QFrame#stageCard[stageState="cancelled"] {
    border: 1px solid #efd0ad;
    background: #fff6eb;
}

QLabel#stageNumber {
    color: #98a3b3;
    font-size: 10px;
    font-weight: 650;
}

QLabel#stageName {
    color: #33435d;
    font-size: 12px;
    font-weight: 650;
}

QLabel#stageStatus {
    color: #8a95a6;
    font-size: 10px;
}

QFrame#stageCard[stageState="running"] QLabel#stageStatus {
    color: #2d6cdf;
}

QFrame#stageCard[stageState="done"] QLabel#stageStatus {
    color: #2d8051;
}

QFrame#stageCard[stageState="failed"] QLabel#stageStatus {
    color: #ba4040;
}

QFrame#stageCard[stageState="cancelled"] QLabel#stageStatus {
    color: #aa6429;
}

QScrollArea#previewCanvas {
    border: none;
    border-radius: 8px;
    background: #141a24;
}

QLabel#previewLabel {
    color: #8e9bad;
    background: #141a24;
}

QSplitter::handle {
    background: transparent;
}

QSplitter::handle:hover {
    background: #d9e4f5;
}

QCheckBox {
    spacing: 7px;
    color: #3d4b62;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
}

QToolTip {
    padding: 5px 8px;
    border: 1px solid #cbd6e5;
    border-radius: 5px;
    background: #ffffff;
    color: #26354d;
}
"""


def refresh_style(widget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def install_ui_font(app) -> str:
    bundled_font = (
        app_config.AI_ROOT
        / "font_file"
        / "CN"
        / "special"
        / "LXGWWenKai-Regular.ttf"
    )
    family = "Microsoft YaHei UI"
    if bundled_font.exists():
        font_id = QFontDatabase.addApplicationFont(str(bundled_font))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if families:
            family = families[0]
    app.setFont(QFont(family, 10))
    return family
