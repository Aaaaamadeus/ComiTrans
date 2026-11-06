"""An opaque text-color picker shared by translation preferences and the editor."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QPushButton, QToolButton, QWidget

from comic_translate_core.layout_options import normalize_text_color
from ..i18n import tr
from .theme import color


class TextColorPicker(QWidget):
    color_changed = Signal(object)

    def __init__(self, color=None, parent=None):
        super().__init__(parent)
        self._color = normalize_text_color(color)
        self._default_color = '#000000'
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.choose_button = QPushButton()
        self.choose_button.setMinimumWidth(128)
        self.choose_button.setAccessibleName(tr('选择文字颜色'))
        self.choose_button.setToolTip(tr('点击选择颜色，支持 RGB 与十六进制色值。'))
        self.choose_button.setProperty('compact', True)
        self.choose_button.clicked.connect(self.choose_color)
        row.addWidget(self.choose_button, 1)
        self.reset_button = QToolButton()
        self.reset_button.setText(tr('重置'))
        self.reset_button.setProperty('compact', True)
        self.reset_button.setProperty('role', 'quiet')
        self.reset_button.setAccessibleName(tr('恢复默认颜色'))
        self.reset_button.setToolTip(tr('恢复默认颜色'))
        self.reset_button.clicked.connect(lambda: self.set_color(None, emit=True))
        row.addWidget(self.reset_button)
        self._refresh()

    @property
    def color(self):
        return self._color

    def set_color(self, value, *, emit=False):
        color = normalize_text_color(value)
        changed = color != self._color
        self._color = color
        self._refresh()
        if changed and emit:
            self.color_changed.emit(color)

    def set_default_color(self, value):
        self._default_color = normalize_text_color(value) or '#000000'
        self._refresh()

    def _refresh(self):
        swatch = QPixmap(20, 20)
        swatch.fill(Qt.transparent)
        painter = QPainter(swatch)
        painter.setPen(QColor(color('ruleStrong')))
        painter.setBrush(QColor(self._color or self._default_color))
        painter.drawRoundedRect(1, 1, 18, 18, 3, 3)
        painter.end()
        self.choose_button.setIcon(QIcon(swatch))
        self.choose_button.setText(self._color.upper() if self._color else tr('默认颜色'))
        self.reset_button.setEnabled(self._color is not None)

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self._color or self._default_color), self,
                                      tr('选择文字颜色'), QColorDialog.DontUseNativeDialog)
        if color.isValid():
            self.set_color(color.name(), emit=True)
