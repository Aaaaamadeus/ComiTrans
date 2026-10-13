"""Reusable manga composition in Qt logical coordinates, without overlay input."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from .theme import ui_font
from .halftone import COMPACT_BREAKPOINT, draw_tone

def label(parent, text, size, *, weight=QFont.Bold):
    result = QLabel(text, parent)
    result.setFont(ui_font(size, weight))
    result.setStyleSheet('QLabel { color: #111111; background: transparent; }')
    result.setAttribute(Qt.WA_TransparentForMouseEvents)
    return result


class PanelHeading(QWidget):
    """Open editorial heading; hierarchy comes from type and breathing room."""
    def __init__(self, number, title, parent=None, *, sidebar=False):
        super().__init__(parent)
        self.sidebar = sidebar
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(44 if sidebar else 36)
        self._number = label(self, number, 12, weight=QFont.Normal)
        self._number.setVisible(bool(number))
        self._number.setFont(ui_font(12, mono=True))
        self._number.setStyleSheet('QLabel { color: #777777; background: transparent; }')
        self._number.setAlignment(Qt.AlignCenter)
        self._title = label(self, title, 20 if sidebar else 18, weight=QFont.Bold)
        self._title.setFont(ui_font(20 if sidebar else 18, QFont.Bold))
        self.setAccessibleName(f'{number} {title}'.strip())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._number.setGeometry(0, 6 if self.sidebar else 0, 24, 30)
        self._title.setGeometry(34 if self._number.text() else 0, 4 if self.sidebar else 0,
                                self._title.sizeHint().width() + 5, 32)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor('#F8F8F8' if self.sidebar else '#FFFFFF'))
        end = min(w, self._title.x() + self._title.width() + 10)
        tone_width = min(96 if self.sidebar else 168, max(0, w - end - 12))
        if tone_width > 24:
            p.setOpacity(.46)
            draw_tone(p, QRectF(w - tone_width, 0, tone_width, h - 4),
                      compact=self.window().width() < COMPACT_BREAKPOINT,
                      profile='section', direction='right')
        p.end()


class StageFocus(QWidget):
    """Current real stage in a small circular marker, without a heavy title block."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(32)
        self._number = label(self, '—', 14, weight=QFont.Bold)
        self._number.setAlignment(Qt.AlignCenter)
        self._title = label(self, '等待任务', 14, weight=QFont.Bold)
        self._detail = label(self, '添加漫画后，开始自动处理', 12, weight=QFont.Normal)
        self._detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._detail.setStyleSheet('QLabel { color: #595959; background: transparent; }')

    def set_stage(self, number, title, detail):
        self._number.setText(number)
        self._title.setText(title)
        self._detail.setText(detail)
        self.setToolTip(detail)
        self.setAccessibleName(f'{title}，{detail}')
        self._place()
        self.update()

    def _place(self):
        self._number.setGeometry(0, 3, 28, 26)
        title_width = min(194, self._title.fontMetrics().horizontalAdvance(self._title.text()) + 12)
        self._title.setGeometry(40, 0, title_width, 30)
        detail_x = 40 + title_width + 18
        self._detail.setGeometry(detail_x, 0, max(0, self.width() - detail_x), 30)
        self._detail.setVisible(self.width() >= 420)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#FFFFFF'))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#EFEFEF'))
        p.drawEllipse(QRectF(1, 4, 26, 26))
        p.end()
