from __future__ import annotations

from pathlib import Path
from functools import lru_cache
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QImageReader, QRegion
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QStackedLayout, QPushButton, QSizePolicy
from ..pdf_utils import render_pdf_preview
from ..config import ICON_PATH
from .halftone import COMPACT_BREAKPOINT, draw_corner_tones, draw_tone
from .theme import display_font


@lru_cache(maxsize=4)
def studio_illustration(asset_name):
    return QPixmap(str(ICON_PATH.parent / 'ui' / 'illustrations' / asset_name))


class MangaIllustration(QWidget):
    """Original studio art in empty states; page art itself is never decorated."""
    def __init__(self, parent=None, *, asset_name='studio-import-v1.png'):
        super().__init__(parent)
        self.setFixedSize(300, 210)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._pixmap = studio_illustration(asset_name)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._pixmap.isNull():
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            source = QRectF(self._pixmap.rect())
            scale = min(self.width() / source.width(), self.height() / source.height())
            width, height = source.width() * scale, source.height() * scale
            target = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
            p.drawPixmap(target, self._pixmap, source)
            p.end()
            return
        # Keep a small offline fallback if an installation omits the optional art.
        p.translate((self.width() - 180) / 2, (self.height() - 104) / 2)
        p.setPen(QPen(QColor('#111111'), 2))
        p.setBrush(QColor('#111111'))
        p.drawRect(54, 11, 82, 86)
        p.setBrush(QColor('#FFFFFF'))
        p.drawRect(49, 6, 82, 86)
        p.drawRect(57, 14, 28, 29)
        p.drawRect(91, 14, 32, 29)
        p.drawRect(57, 49, 66, 35)
        p.drawEllipse(65, 55, 26, 17)
        p.drawLine(78, 72, 75, 78)
        p.drawLine(98, 59, 114, 59)
        p.drawLine(98, 66, 111, 66)
        p.drawLine(98, 73, 116, 73)
        p.drawLine(21, 38, 36, 38)
        p.drawLine(28, 31, 28, 45)
        draw_tone(p, QRectF(144, 65, 28, 27), compact=self.window().width() < COMPACT_BREAKPOINT, profile='quiet')
        p.end()


class EmptyPreview(QWidget):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#FFFFFF'))
        draw_corner_tones(painter, QRectF(self.rect()),
                          compact=self.window().width() < COMPACT_BREAKPOINT)


class PageCanvas(QLabel):
    """Screentone lives in the canvas margin, outside the displayed page."""
    region_edited = Signal(object)
    region_edit_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.region = self.image_size = None
        self.region_editable = False
        self._region_drag = None
        self.setMouseTracking(True)
        self.setAccessibleName('漫画画布')

    def page_rect(self):
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return QRectF()
        bounds = self.contentsRect()
        size = pixmap.deviceIndependentSize()
        return QRectF(bounds.center().x() + .5 - size.width() / 2,
                      bounds.center().y() + .5 - size.height() / 2,
                      size.width(), size.height())

    def region_rect(self):
        page = self.page_rect()
        if self.region is None or self.image_size is None or page.isEmpty():
            return QRectF()
        x1, y1, x2, y2 = self.region
        scale_x = page.width() / self.image_size.width()
        scale_y = page.height() / self.image_size.height()
        return QRectF(page.left() + x1 * scale_x, page.top() + y1 * scale_y,
                      (x2 - x1) * scale_x, (y2 - y1) * scale_y)

    def _region_handles(self):
        rect = self.region_rect()
        return {
            'nw': rect.topLeft(), 'ne': rect.topRight(),
            'sw': rect.bottomLeft(), 'se': rect.bottomRight(),
            'n': QPointF(rect.center().x(), rect.top()),
            's': QPointF(rect.center().x(), rect.bottom()),
            'w': QPointF(rect.left(), rect.center().y()),
            'e': QPointF(rect.right(), rect.center().y()),
        }

    def _region_hit(self, point):
        if not self.region_editable or not self.isEnabled():
            return None
        rect, page = self.region_rect(), self.page_rect()
        if rect.isEmpty() or not page.adjusted(-8, -8, 8, 8).contains(point):
            return None
        for name, handle in self._region_handles().items():
            if abs(point.x() - handle.x()) <= 8 and abs(point.y() - handle.y()) <= 8:
                return name
        if rect.top() <= point.y() <= rect.bottom():
            if abs(point.x() - rect.left()) <= 6:
                return 'w'
            if abs(point.x() - rect.right()) <= 6:
                return 'e'
        if rect.left() <= point.x() <= rect.right():
            if abs(point.y() - rect.top()) <= 6:
                return 'n'
            if abs(point.y() - rect.bottom()) <= 6:
                return 's'
        return 'move' if rect.contains(point) and page.contains(point) else None

    def _region_cursor(self, hit):
        cursors = {'nw': Qt.SizeFDiagCursor, 'se': Qt.SizeFDiagCursor,
                   'ne': Qt.SizeBDiagCursor, 'sw': Qt.SizeBDiagCursor,
                   'n': Qt.SizeVerCursor, 's': Qt.SizeVerCursor,
                   'w': Qt.SizeHorCursor, 'e': Qt.SizeHorCursor, 'move': Qt.OpenHandCursor}
        if hit is None:
            self.unsetCursor()
        else:
            self.setCursor(cursors[hit])

    def cancel_region_drag(self):
        self._region_drag = None
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self.unsetCursor()

    def mousePressEvent(self, event):
        hit = self._region_hit(event.position())
        if event.button() == Qt.LeftButton and hit is not None:
            self._region_drag = (hit, QPointF(event.position()), tuple(self.region))
            self.setFocus(Qt.MouseFocusReason)
            self.grabMouse()
            if hit == 'move':
                self.setCursor(Qt.ClosedHandCursor)
            else:
                self._region_cursor(hit)
            event.accept()
            return
        super().mousePressEvent(event)

    def _drag_region_to(self, point):
        hit, start, original = self._region_drag
        page = self.page_rect()
        dx = round((point.x() - start.x()) * self.image_size.width() / page.width())
        dy = round((point.y() - start.y()) * self.image_size.height() / page.height())
        x1, y1, x2, y2 = map(int, original)
        if hit == 'move':
            width, height = x2 - x1, y2 - y1
            x1 = max(0, min(max(0, self.image_size.width() - width), x1 + dx))
            y1 = max(0, min(max(0, self.image_size.height() - height), y1 + dy))
            box = (x1, y1, x1 + width, y1 + height)
        else:
            if 'w' in hit:
                x1 = min(x2 - 1, max(0, x1 + dx))
            if 'e' in hit:
                x2 = max(x1 + 1, min(self.image_size.width(), x2 + dx))
            if 'n' in hit:
                y1 = min(y2 - 1, max(0, y1 + dy))
            if 's' in hit:
                y2 = max(y1 + 1, min(self.image_size.height(), y2 + dy))
            box = (x1, y1, x2, y2)
        if box != self.region:
            self.region = box
            self.update()
            self.region_edited.emit(box)

    def mouseMoveEvent(self, event):
        if self._region_drag is not None:
            self._drag_region_to(event.position())
            event.accept()
            return
        self._region_cursor(self._region_hit(event.position()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._region_drag is not None:
            self._drag_region_to(event.position())
            self.cancel_region_drag()
            self._region_cursor(self._region_hit(event.position()))
            self.region_edit_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._region_drag is not None:
            original = self._region_drag[2]
            self.cancel_region_drag()
            self.region = original
            self.region_edited.emit(original)
            self.region_edit_finished.emit()
            self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def leaveEvent(self, event):
        if self._region_drag is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.cancel_region_drag()
        super().hideEvent(event)

    def event(self, event):
        if event.type() == QEvent.UngrabMouse and getattr(self, '_region_drag', None) is not None:
            self._region_drag = None
            self.unsetCursor()
        return super().event(event)

    def changeEvent(self, event):
        if event.type() == QEvent.EnabledChange and not self.isEnabled():
            self.cancel_region_drag()
        super().changeEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        bounds = self.contentsRect()
        page = self.page_rect()
        painter = QPainter(self)
        margin = QRegion(bounds).subtracted(QRegion(page.adjusted(-12, -12, 12, 12).toAlignedRect()))
        painter.setClipRegion(margin)
        draw_corner_tones(painter, QRectF(bounds),
                          compact=self.window().width() < COMPACT_BREAKPOINT)
        if self.region is not None and self.image_size is not None:
            painter.setClipping(False)
            painter.setClipRect(page)
            rect = self.region_rect()
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor('#607D8B'), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            if self.region_editable and self.isEnabled():
                painter.setClipRect(page.adjusted(-5, -5, 5, 5))
                painter.setPen(QPen(QColor('#607D8B'), 1))
                painter.setBrush(QColor('#FFFFFF'))
                for handle in self._region_handles().values():
                    painter.drawRect(QRectF(handle.x() - 3.5, handle.y() - 3.5, 7, 7))


class ImagePreview(QWidget):
    import_requested = Signal()
    region_edited = Signal(object)
    region_edit_finished = Signal()

    def __init__(self, parent=None, *, import_action=False, illustration='studio-import-v1.png'):
        super().__init__(parent)
        self._original = QPixmap()
        self._zoom = None
        self.setMinimumSize(120, 100)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._empty = EmptyPreview()
        self._empty.setObjectName('emptyPreview')
        layout = QVBoxLayout(self._empty)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)
        layout.addStretch()
        content = QHBoxLayout()
        content.setSpacing(32)
        content.addStretch()
        self._art = MangaIllustration(asset_name=illustration)
        content.addWidget(self._art, 0, Qt.AlignVCenter)
        message_layout = QVBoxLayout()
        message_layout.setSpacing(12)
        self._empty_title = QLabel('从一页漫画开始' if import_action else '等待预览')
        self._empty_title.setObjectName('emptyPreviewTitle')
        self._empty_title.setFont(display_font(28))
        self._empty_title.setWordWrap(True)
        self._empty_title.setAlignment(Qt.AlignCenter)
        message_layout.addWidget(self._empty_title)
        self._hint = QLabel('导入原稿，让故事跨越语言。\n支持图片、PDF 与整个文件夹。' if import_action else '选择页面后在这里检查图像')
        self._hint.setProperty('muted', True)
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setMaximumWidth(340)
        message_layout.addWidget(self._hint)
        self.import_button = QPushButton('选择漫画  →')
        self.import_button.setProperty('role', 'primary')
        self.import_button.setVisible(import_action)
        self.import_button.clicked.connect(self.import_requested)
        message_layout.addWidget(self.import_button, 0, Qt.AlignHCenter)
        content.addLayout(message_layout)
        content.addStretch()
        layout.addLayout(content)
        layout.addStretch()
        self._stack.addWidget(self._empty)
        self._label = PageCanvas()
        self._label.region_edited.connect(self.region_edited)
        self._label.region_edit_finished.connect(self.region_edit_finished)
        self._label.setObjectName('previewLabel')
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._scroll = QScrollArea()
        self._scroll.setObjectName('previewCanvas')
        self._scroll.setWidget(self._label)
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.viewport().installEventFilter(self)
        self._stack.addWidget(self._scroll)

    def eventFilter(self, watched, event):
        if watched is self._scroll.viewport() and event.type() == QEvent.Resize:
            self.cancel_region_drag()
            self._update_scaled()
        return super().eventFilter(watched, event)

    def set_image(self, path):
        try:
            if Path(path).suffix.lower() == '.pdf':
                self.set_pixmap(QPixmap.fromImage(render_pdf_preview(path, QSize(1600, 1600))))
            else:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                self.set_pixmap(QPixmap.fromImage(reader.read()))
        except Exception as exc:
            self.clear(f'无法预览：{exc}')

    def set_pixmap(self, pixmap):
        self._original = pixmap
        self._label.image_size = pixmap.size()
        if pixmap.isNull():
            self.clear('无法读取图片')
            return
        self._stack.setCurrentWidget(self._scroll)
        self._update_scaled()

    def clear(self, text='等待预览'):
        self._original = QPixmap()
        self.set_region(None)
        self._label.clear()
        self._empty_title.setText(text)
        self._stack.setCurrentWidget(self._empty)

    def set_zoom(self, factor=None):
        self.cancel_region_drag()
        self._zoom = factor
        self._update_scaled()

    def set_region(self, box=None, *, editable=False):
        """Canvas-only selection guide; never alter the rendered/exported pixels."""
        self._label.region = tuple(box) if box is not None else None
        self._label.region_editable = editable and box is not None
        self._label.setFocusPolicy(Qt.StrongFocus if self._label.region_editable else Qt.NoFocus)
        self._label.setToolTip('拖动边角调整蒙版大小，框内拖动位置；Esc 恢复本次拖动前的范围'
                               if self._label.region_editable else '')
        if not self._label.region_editable:
            self.cancel_region_drag()
        self._label.update()

    def cancel_region_drag(self):
        self._label.cancel_region_drag()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._art.setVisible(self.height() >= 230 and self.width() >= 620)
        self._hint.setVisible(self.height() >= 170)
        self._update_scaled()

    def _update_scaled(self):
        if self._original.isNull():
            return
        if self._zoom is None:
            size = self._scroll.viewport().size() - QSize(24, 24)
            self._label.setMinimumSize(0, 0)
        else:
            size = self._original.size() * self._zoom
            self._label.setMinimumSize(size)
        if size.width() > 0 and size.height() > 0:
            dpr = self.devicePixelRatioF()
            pixmap = self._original.scaled(size * dpr, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(dpr)
            self._label.setPixmap(pixmap)
