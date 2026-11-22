"""Reusable manga composition in Qt logical coordinates, without overlay input."""
from __future__ import annotations
from ..i18n import tr

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from .theme import color, ui_font
from .halftone import COMPACT_BREAKPOINT, draw_tone
from .motion import reduced_motion

def label(parent, text, size, *, weight=QFont.Bold):
    result = QLabel(tr(text), parent)
    result.setFont(ui_font(size, weight))
    result.setAttribute(Qt.WA_TransparentForMouseEvents)
    return result


class PanelHeading(QWidget):
    """Open editorial heading; hierarchy comes from type and breathing room."""
    def __init__(self, number, title, parent=None, *, sidebar=False):
        super().__init__(parent)
        self.sidebar = sidebar
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(36 if sidebar else 32)
        self._number = label(self, number, 12, weight=QFont.Normal)
        self._number.setVisible(bool(number))
        self._number.setFont(ui_font(12, mono=True))
        self._number.setProperty('muted', True)
        self._number.setAlignment(Qt.AlignCenter)
        self._title = label(self, title, 18 if sidebar else 17, weight=QFont.Bold)
        self._title.setFont(ui_font(18 if sidebar else 17, QFont.Bold))
        self.setAccessibleName(f'{number} {title}'.strip())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        top = 2 if self.sidebar else 0
        self._number.setGeometry(0, top + 3, 24, 26)
        self._title.setGeometry(32 if self._number.text() else 0, top,
                                self._title.sizeHint().width() + 5, 30)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        end = min(w, self._title.x() + self._title.width() + 10)
        tone_width = min(72 if self.sidebar else 120, max(0, w - end - 12))
        if tone_width > 24:
            p.setOpacity(.28)
            draw_tone(p, QRectF(w - tone_width, 0, tone_width, h - 2),
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
        self._title = label(self, tr('等待任务'), 14, weight=QFont.Bold)
        self._detail = label(self, tr('添加漫画后，开始自动处理'), 12, weight=QFont.Normal)
        self._detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._detail.setProperty('muted', True)
        self._last_key = ('—', tr('等待任务'))
        self._pulse_until = 0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(16)
        self._pulse_timer.timeout.connect(self._step_pulse)

    def _step_pulse(self):
        if int(self._clock.elapsed()) >= self._pulse_until:
            self._pulse_until = 0
            self._pulse_timer.stop()
        self.update()

    def set_stage(self, number, title, detail):
        key = (str(number), str(title))
        changed = key != self._last_key
        self._last_key = key
        self._number.setText(tr(number))
        self._title.setText(tr(title))
        self._detail.setText(tr(detail))
        self.setToolTip(tr(detail))
        self.setAccessibleName(f'{title}，{detail}')
        self._place()
        if changed and self.isVisible() and not reduced_motion():
            self._pulse_until = int(self._clock.elapsed()) + 340
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
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

    def hideEvent(self, event):
        self._pulse_timer.stop()
        self._pulse_until = 0
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(color('paper')))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color('muted')))
        p.drawEllipse(QRectF(1, 4, 26, 26))
        if self._pulse_until > 0 and not reduced_motion():
            rem = self._pulse_until - int(self._clock.elapsed())
            if rem > 0:
                t = 1.0 - max(0.0, min(1.0, rem / 340.0))
                ring = QColor(color('ink'))
                ring.setAlpha(int(round(145 * ((1.0 - t) ** 2))))
                p.setPen(QPen(ring, 1.3))
                p.setBrush(Qt.NoBrush)
                r = 12.0 + 2.5 * t
                p.drawEllipse(QPointF(14.0, 17.0), r, r)
        p.end()
