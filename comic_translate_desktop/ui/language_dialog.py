"""First-launch language choice, before loading models or constructing the main UI."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton, QVBoxLayout,
)

from ..i18n import UI_LANGUAGES, normalize_ui_language, tr
from .halftone import draw_tone
from .theme import brand_font, color, refresh_style, ui_font
from .window_chrome import apply_window_chrome


_HEADINGS = {
    'zh-CN': '选择界面语言',
    'en': 'Choose your interface language',
    'ja': '表示言語を選択してください',
}

_CARD_PREVIEWS = {
    'zh-CN': '自动处理 · 嵌字精修',
    'en': 'Translate · Typesetting',
    'ja': '自動翻訳 · 写植調整',
}


class _LanguageCard(QFrame):
    """Clickable monochrome card wrapping each language radio option."""

    def __init__(self, radio, preview_text, *, japanese=False, parent=None):
        super().__init__(parent)
        self.radio = radio
        self.setObjectName('langCard')
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(12)
        row.addWidget(radio)
        row.addStretch(1)
        preview = QLabel(preview_text)
        preview.setProperty('muted', True)
        preview.setFont(ui_font(12, japanese=japanese))
        preview.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(preview)
        radio.toggled.connect(self._sync_selected)
        self._sync_selected(radio.isChecked())

    def _sync_selected(self, checked):
        self.setProperty('selected', bool(checked))
        refresh_style(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.radio.click()
        super().mousePressEvent(event)


class InterfaceLanguageDialog(QDialog):
    def __init__(self, language='zh-CN', parent=None):
        super().__init__(parent)
        self.setObjectName('paperDialog')
        self.setWindowTitle('ComiTrans')
        self.setModal(True)
        self.setMinimumWidth(460)
        self.resize(520, 470)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand = QLabel('ComiTrans')
        brand.setObjectName('brandTitle')
        brand.setFont(brand_font(38))
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        lang_pill = QLabel('中文 · EN · 日本語')
        lang_pill.setObjectName('badgePill')
        lang_pill.setFont(ui_font(11, mono=True))
        brand_row.addWidget(lang_pill, 0, Qt.AlignVCenter)
        layout.addLayout(brand_row)

        self._heading = QLabel()
        self._heading.setFont(ui_font(20, QFont.Bold))
        self._heading.setWordWrap(True)
        layout.addWidget(self._heading)

        kicker = QLabel('首次启动 · First launch · 初回起動')
        kicker.setProperty('muted', True)
        layout.addWidget(kicker)
        layout.addSpacing(4)

        self._group = QButtonGroup(self)
        current = normalize_ui_language(language)
        self._radios = {}
        cards_layout = QVBoxLayout()
        cards_layout.setSpacing(10)
        for code, name in UI_LANGUAGES:
            radio = QRadioButton(name)
            radio.setObjectName('langRadio')
            radio.setFont(ui_font(15, QFont.Bold, japanese=(code == 'ja')))
            radio.setCursor(Qt.PointingHandCursor)
            radio.setAccessibleName(name)
            radio.setChecked(code == current)
            radio.toggled.connect(lambda checked, value=code: checked and self._set_language(value))
            self._group.addButton(radio)
            self._radios[code] = radio
            card = _LanguageCard(radio, _CARD_PREVIEWS[code], japanese=(code == 'ja'), parent=self)
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)
        layout.addSpacing(4)

        divider = QFrame()
        divider.setObjectName('hairlineRule')
        layout.addWidget(divider)

        actions = QHBoxLayout()
        actions.setSpacing(16)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty('muted', True)
        actions.addWidget(self.note, 1)
        self.continue_button = QPushButton()
        self.continue_button.setProperty('role', 'primary')
        self.continue_button.setDefault(True)
        self.continue_button.setCursor(Qt.PointingHandCursor)
        self.continue_button.clicked.connect(self.accept)
        actions.addWidget(self.continue_button, 0, Qt.AlignVCenter)
        layout.addLayout(actions)

        self._language = current
        self._preview_language()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(color('paper')))
        tone_width = min(160.0, self.width() * 0.32)
        tone_height = 84.0
        painter.setOpacity(0.24)
        draw_tone(painter, QRectF(self.width() - tone_width - 12, 10, tone_width, tone_height),
                  profile='quiet', direction='right')
        painter.end()

    def _set_language(self, code):
        self._language = code
        self._preview_language()

    def _preview_language(self):
        code = self._language
        self._heading.setText(_HEADINGS.get(code, _HEADINGS['zh-CN']))
        self._heading.setFont(ui_font(20, QFont.Bold, japanese=(code == 'ja')))
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
