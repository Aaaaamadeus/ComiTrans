"""Reusable manga composition in Qt logical coordinates, without overlay input."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from .theme import display_font, ui_font
from .halftone import COMPACT_BREAKPOINT, draw_tone

FRAME_WIDTH = 3.0
HARD_SHADOW = 4.0


def polygon(points):
    return QPolygonF([QPointF(x, y) for x, y in points])


def label(parent, text, size, *, inverse=False, weight=QFont.Bold):
    result = QLabel(text, parent)
    result.setFont(ui_font(size, weight))
    result.setStyleSheet('QLabel { color: %s; background: transparent; }' % ('#FFFFFF' if inverse else '#111111'))
    result.setAttribute(Qt.WA_TransparentForMouseEvents)
    return result


class OutlinedNumber(QWidget):
    """Large white chapter glyphs cut into a field of black screentone."""
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAccessibleName(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addText(0, 0, display_font(160, italic=True), self.text)
        bounds = path.boundingRect()
        scale = min((self.width() - 10) / bounds.width(), (self.height() + 8) / bounds.height())
        transform = QTransform()
        transform.translate((self.width() - bounds.width() * scale) / 2, -4)
        transform.scale(scale, scale)
        transform.translate(-bounds.left(), -bounds.top())
        painter.setPen(QPen(QColor('#111111'), 3.5, Qt.SolidLine, Qt.SquareCap, Qt.RoundJoin))
        painter.setBrush(QColor('#FFFFFF'))
        painter.drawPath(transform.map(path))


class ChapterBanner(QWidget):
    """Magazine masthead: cropped chapter, oversized headline, dense edge tones."""
    def __init__(self, number, title, subtitle, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(136)
        self._compact = False
        self._number = OutlinedNumber(number, self)
        self._title = label(self, title, 58, weight=QFont.Black)
        self._subtitle = label(self, subtitle, 18, weight=QFont.Bold)
        self._edition = label(self, '漫画翻訳', 20, inverse=True)
        self._edition_second = label(self, '一頁ずつ磨く', 20, inverse=True)
        self.setAccessibleName(f'{number} {title}，{subtitle}')

    def set_compact(self, compact, *, tight=False):
        height = (60 if tight else 76) if compact else 136
        if compact != self._compact or self.height() != height:
            self._compact = compact
            self.setFixedHeight(height)
            self._subtitle.setVisible(not compact)
            self._place()
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def _place(self):
        w, h = self.width(), self.height()
        self._number_width = 132 if self._compact else 242
        self._number.setGeometry(0, 1, self._number_width, h - 3)
        x = self._number_width + (12 if self._compact else 26)
        size = (min(36, max(25, (w - x - 100) // max(1, len(self._title.text()))))
                if self._compact else min(58, max(32, (w - x - 180) // max(1, len(self._title.text())))))
        self._title.setFont(display_font(size, italic=True))
        self._title.setGeometry(x, 2 if self._compact else 5, w - x - 20, h - 4 if self._compact else 86)
        self._subtitle.setGeometry(x + 4, 91, max(0, w - x - 24), 29)
        self._edition.setFont(display_font(20))
        self._edition_second.setFont(display_font(20))
        self._edition.setGeometry(w - 184, 40, 140, 30)
        self._edition_second.setGeometry(w - 170, 79, 150, 30)
        show_edition = not self._compact and w > 1220
        self._edition.setVisible(show_edition)
        self._edition_second.setVisible(show_edition)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor('#FFFFFF'))
        number_width = 132 if self._compact else 242
        compact = self.window().width() < COMPACT_BREAKPOINT
        draw_tone(p, QRectF(0, 0, number_width + 42, h), compact=compact, profile='section')
        # Reserve a solid white island for headline and subtitle.
        text_end = self._title.x() + self._title.fontMetrics().horizontalAdvance(self._title.text()) + 28
        tone_start = min(w - 72, max(text_end, int(w * .53)))
        draw_tone(p, QRectF(tone_start, 0, w - tone_start, h),
                  compact=compact, profile='hero', direction='right')
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#FFFFFF'))
        p.drawPolygon(polygon([(number_width + 12, 0), (tone_start + 20, 0),
                               (tone_start - 26, h), (number_width + 38, h)]))
        p.setBrush(QColor('#000000'))
        if self._edition.isVisible():
            p.drawPolygon(polygon([(w-192, 37), (w-33, 23), (w-41, 70), (w-200, 80)]))
            p.drawPolygon(polygon([(w-179, 77), (w-12, 65), (w-20, 112), (w-187, 124)]))
        if not self._compact:
            x = self._subtitle.x() + self._subtitle.fontMetrics().horizontalAdvance(self._subtitle.text()) + 22
            if x + 98 < tone_start:
                for offset, width in ((0, 56), (64, 10), (82, 10)):
                    p.drawPolygon(polygon([(x+offset+12, 103), (x+offset+width+12, 103),
                                           (x+offset+width, 124), (x+offset, 124)]))
        p.setPen(QPen(QColor('#111111'), 2))
        p.drawLine(QPointF(0, h - 1), QPointF(w, h - 1))
        p.end()


class PanelHeading(QWidget):
    """An edge-built tone triangle above a sidebar or beside a section title."""
    def __init__(self, number, title, parent=None, *, sidebar=False):
        super().__init__(parent)
        self.sidebar = sidebar
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(54 if sidebar else 40)
        self._number = label(self, number, 21, inverse=True, weight=QFont.Black)
        self._number.setAlignment(Qt.AlignCenter)
        self._title = label(self, title, 24 if sidebar else 20, inverse=not sidebar, weight=QFont.Black)
        self._title.setFont(display_font(24 if sidebar else 20))
        self.setAccessibleName(f'{number} {title}')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._number.setGeometry(0, 7 if self.sidebar else 0, 32, 36)
        self._title.setGeometry(42, 6 if self.sidebar else 0, self._title.sizeHint().width() + 5, 38)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor('#FFFFFF'))
        end = min(w, self._title.x() + self._title.width() + 10)
        draw_tone(p, QRectF(end - 8, 0, w - end + 8, h - 3),
                  compact=self.window().width() < COMPACT_BREAKPOINT,
                  profile='section', direction='right' if self.sidebar else 'left')
        if self.sidebar:
            p.fillRect(QRectF(0, 0, end - 8, h - 3), QColor('#FFFFFF'))
            p.fillRect(QRectF(0, 7, 32, 36), QColor('#111111'))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#111111'))
            p.drawPolygon(polygon([(0, 0), (end, 0), (end-9, 37), (0, 37)]))
        p.setPen(QPen(QColor('#111111'), 1))
        p.drawLine(QPointF(0, h - 1), QPointF(w, h - 1))
        p.end()


class StageFocus(QWidget):
    """Current real event in an ink label, with a large offset stage number."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(32)
        self._number = label(self, '—', 23, weight=QFont.Black)
        self._number.setAlignment(Qt.AlignCenter)
        self._title = label(self, '等待任务', 15, inverse=True, weight=QFont.Bold)
        self._detail = label(self, '添加漫画后，开始自动处理', 12, weight=QFont.Normal)
        self._detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def set_stage(self, number, title, detail):
        self._number.setText(number)
        self._title.setText(title)
        self._detail.setText(detail)
        self.setToolTip(detail)
        self.setAccessibleName(f'{title}，{detail}')
        self._place()
        self.update()

    def _place(self):
        self._number.setGeometry(0, 3, 42, 26)
        self._title.setGeometry(54, 0, 192, 28)
        self._detail.setGeometry(268, 0, max(0, self.width() - 268), 30)
        self._detail.setVisible(self.width() >= 420)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#FFFFFF'))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#000000'))
        p.drawPolygon(polygon([(12, 0), (254, 0), (244, 28), (12, 28)]))
        p.drawRect(QRectF(3, 6, 42, 25))
        p.setPen(QPen(QColor('#111111'), 2))
        p.setBrush(QColor('#FFFFFF'))
        p.drawRect(QRectF(1, 3, 42, 25))
        p.end()
