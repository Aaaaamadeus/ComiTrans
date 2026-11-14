from __future__ import annotations
from ..i18n import tr

from pathlib import Path
from functools import lru_cache
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QImageReader, QRegion
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QStackedLayout, QPushButton, QSizePolicy, QProgressBar
from ..pdf_utils import render_pdf_preview
from ..config import ICON_PATH
from .halftone import COMPACT_BREAKPOINT, draw_corner_tones, draw_tone
from .theme import color, display_font, theme_name
from .motion import fade_in


@lru_cache(maxsize=4)
def studio_illustration(asset_name):
    return QPixmap(str(ICON_PATH.parent / 'ui' / 'illustrations' / asset_name))


class MangaIllustration(QWidget):
    """Original studio art in empty states; page art itself is never decorated."""
    def __init__(self, parent=None, *, asset_name='studio-import-v1.png'):
        super().__init__(parent)
        self.setFixedSize(240, 168)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._pixmap = studio_illustration(asset_name)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._pixmap.isNull():
            if theme_name() == 'dark':
                # The line art is ink on transparency; give it a paper card to sit on.
                p.setPen(Qt.NoPen)
                p.setBrush(QColor('#F2F1EC'))
                p.drawRoundedRect(QRectF(self.rect()), 12, 12)
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
        p.setPen(QPen(QColor(color('ink')), 2))
        p.setBrush(QColor(color('ink')))
        p.drawRect(54, 11, 82, 86)
        p.setBrush(QColor(color('paper')))
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
        painter.fillRect(self.rect(), QColor(color('paper')))
        draw_corner_tones(painter, QRectF(self.rect()),
                          compact=self.window().width() < COMPACT_BREAKPOINT)


class PageCanvas(QLabel):
    """Screentone lives in the canvas margin, outside the displayed page."""
    region_edited = Signal(object)
    region_edit_finished = Signal()
    region_clicked = Signal(int)
    bubble_created = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.region = self.image_size = None
        self.region_editable = False
        self.region_creation = False
        self.bubble_creation = False
        self.stretch_pixmap = False
        self.space_pan = False
        self.regions = []
        self.regions_visible = True
        self._hover_index = -1
        self._region_drag = None
        self._view_pixmap = None
        self._view_scale = 1.0
        self.setMouseTracking(True)
        self.setAccessibleName(tr('漫画画布'))

    def set_regions(self, regions, visible=True):
        self.regions = list(regions or ())
        self.regions_visible = bool(visible)
        self._hover_index = -1
        self.update()

    def set_view(self, pixmap, scale, viewport):
        """Draw the page from its source pixmap; only the exposed rect is sampled."""
        self._view_pixmap = pixmap
        self._view_scale = max(0.01, float(scale))
        self.image_size = pixmap.size()
        self.setMinimumSize(0, 0)
        self.setFixedSize(max(viewport.width(), round(pixmap.width() * self._view_scale)),
                          max(viewport.height(), round(pixmap.height() * self._view_scale)))
        self.update()

    def clear_view(self):
        self._view_pixmap = None
        self._view_scale = 1.0

    def page_rect(self):
        if self._view_pixmap is not None and not self._view_pixmap.isNull():
            bounds = self.contentsRect()
            width = self._view_pixmap.width() * self._view_scale
            height = self._view_pixmap.height() * self._view_scale
            return QRectF(bounds.center().x() + .5 - width / 2,
                          bounds.center().y() + .5 - height / 2, width, height)
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return QRectF()
        bounds = self.contentsRect()
        if self.stretch_pixmap:
            return QRectF(bounds)
        size = pixmap.deviceIndependentSize()
        return QRectF(bounds.center().x() + .5 - size.width() / 2,
                      bounds.center().y() + .5 - size.height() / 2,
                      size.width(), size.height())

    def _box_rect(self, box):
        page = self.page_rect()
        if box is None or self.image_size is None or page.isEmpty():
            return QRectF()
        x1, y1, x2, y2 = box
        scale_x = page.width() / self.image_size.width()
        scale_y = page.height() / self.image_size.height()
        return QRectF(page.left() + x1 * scale_x, page.top() + y1 * scale_y,
                      (x2 - x1) * scale_x, (y2 - y1) * scale_y)

    def region_rect(self):
        return self._box_rect(self.region)

    def _region_at(self, point):
        """Topmost text box under the cursor; inner (smaller) boxes win."""
        if not self.regions_visible or not self.regions or self.image_size is None:
            return None
        page = self.page_rect()
        if page.isEmpty() or not page.adjusted(-4, -4, 4, 4).contains(point):
            return None
        hits = []
        for index, box in self.regions:
            rect = self._box_rect(box)
            if not rect.isEmpty() and rect.adjusted(-2, -2, 2, 2).contains(point):
                hits.append((rect.width() * rect.height(), index))
        return min(hits)[1] if hits else None

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
        if self.space_pan:
            self.setCursor(Qt.OpenHandCursor)
            return
        cursors = {'nw': Qt.SizeFDiagCursor, 'se': Qt.SizeFDiagCursor,
                   'ne': Qt.SizeBDiagCursor, 'sw': Qt.SizeBDiagCursor,
                   'n': Qt.SizeVerCursor, 's': Qt.SizeVerCursor,
                   'w': Qt.SizeHorCursor, 'e': Qt.SizeHorCursor, 'move': Qt.OpenHandCursor}
        if hit is None:
            if self.region_creation or self.bubble_creation:
                self.setCursor(Qt.CrossCursor)
            else:
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
        if (self.bubble_creation and event.button() == Qt.LeftButton
                and self.page_rect().contains(event.position())):
            self._region_drag = ('bubble_create', QPointF(event.position()), self.region)
            self.setFocus(Qt.MouseFocusReason)
            self.grabMouse()
            event.accept()
            return
        if (self.region_creation and event.button() == Qt.LeftButton
                and self.page_rect().contains(event.position()) and hit is None):
            self._region_drag = ('create', QPointF(event.position()), self.region)
            self.setFocus(Qt.MouseFocusReason)
            self.grabMouse()
            event.accept()
            return
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
        if event.button() == Qt.LeftButton and hit is None and not self.region_creation:
            index = self._region_at(event.position())
            if index is not None:
                self.setFocus(Qt.MouseFocusReason)
                self.region_clicked.emit(index)
                event.accept()
                return
        super().mousePressEvent(event)

    def _drag_region_to(self, point):
        hit, start, original = self._region_drag
        page = self.page_rect()
        dx = round((point.x() - start.x()) * self.image_size.width() / page.width())
        dy = round((point.y() - start.y()) * self.image_size.height() / page.height())
        if hit in ('create', 'bubble_create'):
            def image_point(position):
                return (max(0, min(self.image_size.width(), round((position.x() - page.left()) * self.image_size.width() / page.width()))),
                        max(0, min(self.image_size.height(), round((position.y() - page.top()) * self.image_size.height() / page.height()))))
            sx, sy = image_point(start)
            ex, ey = image_point(point)
            box = (min(sx, ex), min(sy, ey), max(sx, ex), max(sy, ey))
            box = box if box[0] < box[2] and box[1] < box[3] else None
            if box != self.region:
                self.region = box
                self.update()
                if hit == 'create':
                    self.region_edited.emit(box)
            return
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
        hover = self._region_at(event.position())
        if hover != self._hover_index:
            self._hover_index = hover
            self.update()
        hit = self._region_hit(event.position())
        self._region_cursor(hit)
        if hit is None and hover is not None:
            self.setCursor(Qt.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._region_drag is not None:
            self._drag_region_to(event.position())
            drag = self._region_drag
            if drag[0] == 'bubble_create' and self.region is not None:
                created = tuple(self.region)
                self.cancel_region_drag()
                self.region = None
                self.update()
                self.bubble_created.emit(created)
                event.accept()
                return
            self.cancel_region_drag()
            self._region_cursor(self._region_hit(event.position()))
            self.region_edit_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._region_drag is not None:
            if self._region_drag[0] == 'bubble_create':
                self.cancel_region_drag()
                self.region = None
                self.update()
                event.accept()
                return
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
        if self._hover_index != -1:
            self._hover_index = -1
            self.update()
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
        if self._view_pixmap is not None and not self._view_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            page = self.page_rect()
            clip = QRectF(event.rect()).intersected(page)
            if not clip.isEmpty() and self._view_scale > 0:
                source = QRectF((clip.left() - page.left()) / self._view_scale,
                                (clip.top() - page.top()) / self._view_scale,
                                clip.width() / self._view_scale,
                                clip.height() / self._view_scale)
                painter.drawPixmap(clip, self._view_pixmap, source)
            painter.end()
        elif self.stretch_pixmap:
            pixmap = self.pixmap()
            if pixmap is not None and not pixmap.isNull():
                painter = QPainter(self)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                # Paint only the exposed viewport; never allocate a full-page zoomed bitmap.
                painter.drawPixmap(QRectF(self.contentsRect()), pixmap, QRectF(pixmap.rect()))
                painter.end()
        else:
            super().paintEvent(event)
        self._paint_canvas_overlay()

    def _paint_canvas_overlay(self):
        if self.image_size is None:
            return
        bounds = self.contentsRect()
        page = self.page_rect()
        if page.isEmpty():
            return
        painter = QPainter(self)
        margin = QRegion(bounds).subtracted(QRegion(page.adjusted(-12, -12, 12, 12).toAlignedRect()))
        painter.setClipRegion(margin)
        draw_corner_tones(painter, QRectF(bounds),
                          compact=self.window().width() < COMPACT_BREAKPOINT)
        painter.setClipping(False)
        edge = QPen(QColor(color('pageEdge')), 1)
        edge.setCosmetic(True)
        painter.setPen(edge)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(page.adjusted(.5, .5, -.5, -.5))
        if self.regions_visible and self.regions:
            painter.setClipping(False)
            painter.setClipRect(page)
            painter.setRenderHint(QPainter.Antialiasing)
            for index, box in self.regions:
                rect = self._box_rect(box)
                if rect.isEmpty() or (self.region is not None and tuple(box) == tuple(self.region)):
                    continue
                guide = QColor(color('guide'))
                if index == self._hover_index:
                    guide.setAlpha(220)
                    pen = QPen(guide, 1.5, Qt.SolidLine)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.setBrush(QColor(guide.red(), guide.green(), guide.blue(), 28))
                else:
                    guide.setAlpha(90)
                    pen = QPen(guide, 1, Qt.DashLine)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)
            painter.setBrush(Qt.NoBrush)
        if self.region is not None:
            painter.setClipping(False)
            painter.setClipRect(page)
            rect = self.region_rect()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(color('guide')), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            if self.region_editable and self.isEnabled():
                painter.setClipRect(page.adjusted(-5, -5, 5, 5))
                painter.setPen(QPen(QColor(color('guide')), 1))
                painter.setBrush(QColor(color('paper')))
                for handle in self._region_handles().values():
                    painter.drawRect(QRectF(handle.x() - 3.5, handle.y() - 3.5, 7, 7))
        painter.end()


class ImagePreview(QWidget):
    import_requested = Signal()
    region_edited = Signal(object)
    region_edit_finished = Signal()
    region_clicked = Signal(int)
    bubble_created = Signal(object)
    zoom_changed = Signal(object)

    MIN_ZOOM, MAX_ZOOM = 0.05, 8.0

    def __init__(self, parent=None, *, import_action=False, illustration='studio-import-v1.png'):
        super().__init__(parent)
        self._original = QPixmap()
        self._zoom = None
        self._fit_width = False
        self._scale = 1.0
        self._pan = None
        self._space_pan = False
        self._zoom_tool = False
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
        self._empty_title = QLabel(tr('从一页漫画开始') if import_action else tr('等待预览'))
        self._empty_title.setObjectName('emptyPreviewTitle')
        self._empty_title.setFont(display_font(28))
        self._empty_title.setWordWrap(True)
        self._empty_title.setAlignment(Qt.AlignCenter)
        message_layout.addWidget(self._empty_title)
        self._hint = QLabel(tr('导入原稿，让故事跨越语言。\n支持图片、PDF 与整个文件夹。') if import_action else tr('选择页面后在这里检查图像'))
        self._hint.setProperty('muted', True)
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setMaximumWidth(340)
        message_layout.addWidget(self._hint)
        self.import_button = QPushButton(tr('选择漫画  →'))
        self.import_button.setProperty('role', 'primary')
        self.import_button.setVisible(import_action)
        self.import_button.clicked.connect(self.import_requested)
        message_layout.addWidget(self.import_button, 0, Qt.AlignHCenter)
        content.addLayout(message_layout)
        content.addStretch()
        layout.addLayout(content)
        layout.addStretch()
        self._stack.addWidget(self._empty)
        self._state_panel = QWidget()
        self._state_panel.setObjectName('canvasState')
        state_layout = QVBoxLayout(self._state_panel)
        state_layout.setContentsMargins(32, 32, 32, 32)
        state_layout.setSpacing(10)
        state_layout.addStretch()
        self._state_title = QLabel()
        self._state_title.setObjectName('canvasStateTitle')
        self._state_title.setAlignment(Qt.AlignCenter)
        self._state_title.setWordWrap(True)
        state_layout.addWidget(self._state_title)
        self._state_bar = QProgressBar()
        self._state_bar.setRange(0, 0)
        self._state_bar.setFixedWidth(180)
        self._state_bar.setTextVisible(False)
        self._state_bar.setObjectName('canvasStateBar')
        state_layout.addWidget(self._state_bar, 0, Qt.AlignHCenter)
        self._state_message = QLabel()
        self._state_message.setProperty('muted', True)
        self._state_message.setAlignment(Qt.AlignCenter)
        self._state_message.setWordWrap(True)
        self._state_message.setMaximumWidth(420)
        state_layout.addWidget(self._state_message, 0, Qt.AlignHCenter)
        self._retry_btn = QPushButton(tr('重试'))
        self._retry_btn.setProperty('role', 'retry')
        self._retry_btn.clicked.connect(self._retry_failed_page)
        state_layout.addWidget(self._retry_btn, 0, Qt.AlignHCenter)
        state_layout.addStretch()
        self._retry_slot = None
        self._stack.addWidget(self._state_panel)
        self._label = PageCanvas()
        self._label.region_edited.connect(self.region_edited)
        self._label.region_edit_finished.connect(self.region_edit_finished)
        self._label.region_clicked.connect(self.region_clicked)
        self._label.bubble_created.connect(self.bubble_created)
        self._label.installEventFilter(self)
        self._label.setObjectName('previewLabel')
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._scroll = QScrollArea()
        self._scroll.setObjectName('previewCanvas')
        self._scroll.setWidget(self._label)
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.viewport().installEventFilter(self)
        self._stack.addWidget(self._scroll)

    def eventFilter(self, watched, event):
        viewport = self._scroll.viewport()
        if watched is viewport:
            if event.type() == QEvent.Resize:
                self.cancel_region_drag()
                self._update_scaled()
                return super().eventFilter(watched, event)
        elif watched is not self._label:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Wheel:
            if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                step = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
                self._zoom_at(self._scale * step, self._viewport_position(watched, event))
            else:
                self._wheel_scroll(event)
            return True
        if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            if watched is self._label and (self._label.region_creation
                                           or self._label._region_hit(event.position()) is not None):
                return super().eventFilter(watched, event)
            self.set_zoom(None if self._zoom is not None or self._fit_width else 1.0)
            return True
        if (event.type() == QEvent.MouseButtonPress and self._zoom_tool
                and not self._space_pan and event.button() == Qt.LeftButton and watched is self._label):
            factor = self._scale / 1.6 if event.modifiers() & Qt.AltModifier else self._scale * 1.6
            self._zoom_at(factor, self._viewport_position(watched, event))
            return True
        if event.type() == QEvent.MouseButtonPress and (
                event.button() == Qt.MiddleButton
                or (event.button() == Qt.LeftButton and self._space_pan)):
            self._pan = (QPointF(event.position()),
                         self._scroll.horizontalScrollBar().value(),
                         self._scroll.verticalScrollBar().value())
            viewport.setCursor(Qt.ClosedHandCursor)
            return True
        if event.type() == QEvent.MouseMove and self._pan is not None:
            start, left, top = self._pan
            self._scroll.horizontalScrollBar().setValue(
                round(left - (event.position().x() - start.x())))
            self._scroll.verticalScrollBar().setValue(
                round(top - (event.position().y() - start.y())))
            return True
        if event.type() == QEvent.MouseButtonRelease and self._pan is not None:
            self._pan = None
            viewport.setCursor(Qt.OpenHandCursor if self._space_pan else Qt.ArrowCursor)
            if not self._space_pan:
                viewport.unsetCursor()
            return True
        return super().eventFilter(watched, event)

    def _viewport_position(self, watched, event):
        if watched is self._label:
            return QPointF(self._label.mapTo(self._scroll.viewport(), event.position().toPoint()))
        return event.position()

    def _wheel_scroll(self, event):
        delta = event.pixelDelta()
        if delta.isNull():
            angle = event.angleDelta()
            dx, dy = (angle.x() // 120) * 60, (angle.y() // 120) * 60
        else:
            dx, dy = delta.x(), delta.y()
        if event.modifiers() & Qt.ShiftModifier and dx == 0:
            dx, dy = dy, 0
        horizontal = self._scroll.horizontalScrollBar()
        vertical = self._scroll.verticalScrollBar()
        horizontal.setValue(horizontal.value() - dx)
        vertical.setValue(vertical.value() - dy)

    def set_image(self, path):
        try:
            if Path(path).suffix.lower() == '.pdf':
                self.set_pixmap(QPixmap.fromImage(render_pdf_preview(path, QSize(1600, 1600))))
            else:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                self.set_pixmap(QPixmap.fromImage(reader.read()))
        except Exception as exc:
            self.clear(tr('无法预览：{_0}', _0=exc))

    def set_pixmap(self, pixmap):
        self._original = pixmap
        self._label.image_size = pixmap.size()
        if pixmap.isNull():
            self.clear(tr('无法读取图片'))
            return
        self._stack.setCurrentWidget(self._scroll)
        self._label.clear()
        self._update_scaled()
        fade_in(self._scroll)

    def update_regions(self, image, regions):
        from PIL.ImageQt import ImageQt
        if not regions:
            return
        displayed = self._label.pixmap()
        if displayed is not None and displayed.cacheKey() == self._original.cacheKey():
            self._label.clear()
        del displayed
        painter = QPainter(self._original)
        try:
            for box in regions:
                painter.drawImage(box[0], box[1], ImageQt(image.crop(box)))
        finally:
            painter.end()
        self._update_scaled()

    def clear(self, text=tr('等待预览')):
        self._original = QPixmap()
        self.set_region(None)
        self._label.set_regions([])
        self._label.clear()
        self._label.clear_view()
        self._empty_title.setText(tr(text))
        self._stack.setCurrentWidget(self._empty)

    def set_loading(self, message=''):
        """Decoding a page: keep the previous panel out of the way."""
        self._state_title.setText(tr('正在加载页面…'))
        self._state_message.setText(message or tr('正在解码原图与排版数据'))
        self._state_bar.setVisible(True)
        self._retry_btn.setVisible(False)
        self._retry_slot = None
        if self._stack.currentWidget() is not self._state_panel:
            self._stack.setCurrentWidget(self._state_panel)
            fade_in(self._state_panel)

    def set_error(self, message, retry=None):
        self._state_title.setText(tr('这一页没有打开'))
        self._state_message.setText(str(message))
        self._state_bar.setVisible(False)
        self._retry_slot = retry
        self._retry_btn.setVisible(retry is not None)
        self._stack.setCurrentWidget(self._state_panel)
        fade_in(self._state_panel)

    def _retry_failed_page(self):
        slot, self._retry_slot = self._retry_slot, None
        if slot is not None:
            slot()

    def set_zoom(self, factor=None):
        self.cancel_region_drag()
        self._zoom = None if factor is None else max(self.MIN_ZOOM, min(self.MAX_ZOOM, float(factor)))
        self._fit_width = False
        self._update_scaled()
        self.zoom_changed.emit(None if self._zoom is None else self._scale)

    def set_space_pan(self, active):
        """Temporary Hand tool, the way Photoshop binds the Space bar."""
        self._space_pan = bool(active)
        self._label.space_pan = self._space_pan
        self._update_canvas_cursor()

    def set_zoom_tool(self, active):
        """Photoshop-style Zoom tool: click to zoom in, Alt+click to zoom out."""
        self._zoom_tool = bool(active)
        self._update_canvas_cursor()

    def _update_canvas_cursor(self):
        if self._pan is not None:
            return
        if self._zoom_tool:
            self._scroll.viewport().setCursor(Qt.CrossCursor)
            self._label.setCursor(Qt.CrossCursor)
        elif self._space_pan:
            self._scroll.viewport().setCursor(Qt.OpenHandCursor)
            self._label.setCursor(Qt.OpenHandCursor)
        else:
            self._scroll.viewport().unsetCursor()
            self._label.unsetCursor()

    def set_fit_width(self):
        self.cancel_region_drag()
        self._zoom = None
        self._fit_width = True
        self._update_scaled()
        self.zoom_changed.emit('width')

    def zoom_by(self, factor):
        self._zoom_at(self._scale * factor, QPointF(self._scroll.viewport().rect().center()))

    def _zoom_at(self, factor, position):
        """Zoom around a viewport point so the page pixel under it stays put."""
        if self._original.isNull():
            return
        position = QPointF(position)
        page = self._label.page_rect()
        if page.isEmpty():
            return
        horizontal = self._scroll.horizontalScrollBar()
        vertical = self._scroll.verticalScrollBar()
        image_x = (position.x() + horizontal.value() - page.left()) / self._scale
        image_y = (position.y() + vertical.value() - page.top()) / self._scale
        self._zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, float(factor)))
        self._fit_width = False
        self._update_scaled()
        page = self._label.page_rect()
        horizontal.setValue(round(page.left() + image_x * self._scale - position.x()))
        vertical.setValue(round(page.top() + image_y * self._scale - position.y()))
        self.zoom_changed.emit(self._scale)

    def set_region_creation(self, enabled):
        self.cancel_region_drag()
        self._label.region_creation = enabled
        self._label.bubble_creation = False
        self.set_region(None)

    def set_bubble_creation(self, enabled):
        self.cancel_region_drag()
        self._label.bubble_creation = bool(enabled)
        self._label.region_creation = False
        self.set_region(None)

    def set_regions(self, regions, visible=True):
        """All text boxes of the page, in image coordinates; click to select."""
        self._label.set_regions(regions, visible)

    def set_region(self, box=None, *, editable=False):
        """Canvas-only selection guide; never alter the rendered/exported pixels."""
        self._label.region = tuple(box) if box is not None else None
        self._label.region_editable = editable and box is not None
        self._label.setFocusPolicy(Qt.StrongFocus if (self._label.region_editable
                               or self._label.region_creation or self._label.bubble_creation)
                               else Qt.NoFocus)
        self._label.setToolTip(tr(tr('拖动边角调整蒙版大小，框内拖动位置；Esc 恢复本次拖动前的范围')
                               if self._label.region_editable else ''))
        if (not self._label.region_editable and not self._label.region_creation
                and not self._label.bubble_creation):
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
        viewport = self._scroll.viewport().size()
        width = max(1, self._original.width())
        height = max(1, self._original.height())
        if self._zoom is not None:
            scale = max(self.MIN_ZOOM, min(self.MAX_ZOOM, float(self._zoom)))
        elif self._fit_width:
            scale = max(self.MIN_ZOOM, (viewport.width() - 24) / width)
        else:
            scale = min((viewport.width() - 24) / width, (viewport.height() - 24) / height)
            scale = max(self.MIN_ZOOM, scale)
        self._scale = scale
        self._label.set_view(self._original, scale, viewport)
