"""First-launch language choice, before loading models or constructing the main UI."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton, QRadioButton, QVBoxLayout,
)

from ..i18n import UI_LANGUAGES, normalize_ui_language, tr
from .theme import brand_font, theme, ui_font
from .window_chrome import apply_window_chrome


class InterfaceLanguageDialog(QDialog):
    def __init__(self, language='zh-CN', parent=None):
        super().__init__(parent)
        self.setWindowTitle('ComiTrans')
        self.setModal(True)
        self.setFixedWidth(560)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        palette = theme()
        self.setStyleSheet(f'QDialog {{ background: {palette["paper"]}; }}')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 26)
        layout.setSpacing(14)

        brand = QLabel('ComiTrans')
        brand.setObjectName('brandTitle')
        brand.setFont(brand_font(40))
        layout.addWidget(brand)

        kicker = QLabel('首次启动 · First launch · 初回起動')
        kicker.setProperty('muted', True)
        layout.addWidget(kicker)

        heading = QLabel('选择界面语言\nChoose your language\n表示言語を選ぶ')
        heading.setFont(ui_font(20, QFont.Bold))
        heading.setWordWrap(True)
        layout.addWidget(heading)
        layout.addSpacing(6)

        self._group = QButtonGroup(self)
        card_style = (
            f'QRadioButton {{ padding: 12px 14px; border: 1px solid {palette["rule"]}; '
            f'border-radius: 10px; background: {palette["paper"]}; spacing: 10px; }}'
            f'QRadioButton:hover {{ background: {palette["muted"]}; }}'
            f'QRadioButton:checked {{ border: 1px solid {palette["ink"]}; '
            f'background: {palette["muted"]}; font-weight: 700; }}'
            f'QRadioButton::indicator {{ width: 16px; height: 16px; }}'
        )
        current = normalize_ui_language(language)
        self._radios = {}
        for code, name in UI_LANGUAGES:
            radio = QRadioButton(name)
            radio.setStyleSheet(card_style)
            radio.setCursor(Qt.PointingHandCursor)
            radio.setAccessibleName(name)
            radio.setChecked(code == current)
            radio.toggled.connect(lambda checked, value=code: checked and self._set_language(value))
            self._group.addButton(radio)
            self._radios[code] = radio
            layout.addWidget(radio)
        layout.addSpacing(4)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty('muted', True)
        layout.addWidget(self.note)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.continue_button = QPushButton()
        self.continue_button.setProperty('role', 'primary')
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self.accept)
        actions.addWidget(self.continue_button)
        layout.addLayout(actions)

        self._language = current
        self._preview_language()

    def _set_language(self, code):
        self._language = code
        self._preview_language()

    def _preview_language(self):
        code = self._language
        self.note.setText(tr('以后可在设置中更改。界面语言不影响漫画译文语言。', language=code))
        self.continue_button.setText(tr('继续', language=code))
        self.continue_button.setAccessibleName(tr('继续', language=code))

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self)

    @property
    def selected_language(self):
        for code, radio in self._radios.items():
            if radio.isChecked():
                return code
        return 'zh-CN'


def choose_interface_language(language='zh-CN'):
    dialog = InterfaceLanguageDialog(language)
    result = dialog.exec()
    # Closing the chooser uses the requested Chinese default and records it once.
    selected = dialog.selected_language if result == QDialog.Accepted else 'zh-CN'
    dialog.deleteLater()
    return selected
