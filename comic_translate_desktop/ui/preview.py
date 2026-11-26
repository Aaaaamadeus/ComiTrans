from __future__ import annotations
from ..i18n import tr

from pathlib import Path
from functools import lru_cache
import math
import time
import numpy as np
from PySide6.QtCore import Qt, QElapsedTimer, QRectF, QPointF, QSize, QTimer, Signal, QEvent
from PySide6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QPainter,
    QPen,
    QPixmap,
    QPointingDevice,
    QPolygonF,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QStackedLayout, QPushButton, QSizePolicy, QProgressBar
from ..pdf_utils import render_pdf_preview
from ..cbz import render_cbz_preview
from ..config import ICON_PATH
from .halftone import COMPACT_BREAKPOINT, draw_corner_tones, draw_tone
from .theme import color, display_font, theme_name, ui_font
from .motion import MonochromeShimmerBar, fade_in, reduced_motion


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
    regions_selected = Signal(object, str)
    region_context_menu = Signal(int, object)
    bubble_created = Signal(object)
    paint_stroke_started = Signal(float, float, float, object)
    paint_stroke_moved = Signal(float, float, float, object)
    paint_stroke_ended = Signal(float, float, float, object)
    paint_hover_moved = Signal(float, float)
    paint_alt_clicked = Signal(float, float)
    paint_right_clicked = Signal(float, float)
    paint_double_clicked = Signal(float, float)
    paint_canceled = Signal()
    tablet_eraser_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.region = self.image_size = None
        self.region_editable = False
        self.region_creation = False
        self.bubble_creation = False
        self.stretch_pixmap = False
        self.space_pan = False
        self.paint_active = False
        self.paint_brush_diameter = 12.0
        self.paint_show_brush_cursor = True
        self.paint_right_click_pick = True
        self.paint_symmetry = 'none'
        self.rotation_deg = 0.0
        self.flipped_h = False
        self.show_grid = False
        self.regions = []
        self.regions_visible = True
        self._hover_index = -1
        self._hover_strength = 0.0
        self._select_pulse_until = 0
        self._fx_clock = QElapsedTimer()
        self._fx_clock.start()
        self._fx_last_ms = 0.0
        self._fx_timer = QTimer(self)
        self._fx_timer.setInterval(16)
        self._fx_timer.timeout.connect(self._step_fx)
        self._region_drag = None
        self._paint_dragging = False
        self._tablet_down = False
        self._hover_img_pt = None
        self._selection_overlay_img = None
        self._selection_contours = []
        self._paint_preview = None
        self._clone_source_pt = None
        self._view_pixmap = None
        self._view_scale = 1.0
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TabletTracking, True)
        self.setAccessibleName(tr('漫画画布'))

    def _ensure_fx_timer(self):
        hovering = self._hover_index is not None and self._hover_index >= 0
        if reduced_motion() or not self.isVisible():
            self._hover_strength = 1.0 if hovering else 0.0
            self._select_pulse_until = 0
            self._fx_timer.stop()
            return
        self._fx_last_ms = float(self._fx_clock.elapsed())
        if not self._fx_timer.isActive():
            self._fx_timer.start()

    def trigger_select_pulse(self):
        if reduced_motion():
            self._select_pulse_until = 0
            self._fx_timer.stop()
            return
        if self.region is None or self._region_drag is not None or not self.isVisible():
            return
        self._select_pulse_until = int(self._fx_clock.elapsed()) + 240
        self._ensure_fx_timer()

    def _step_fx(self):
        now = float(self._fx_clock.elapsed())
        dt = max(1.0, min(48.0, now - self._fx_last_ms))
        self._fx_last_ms = now

        hovering = self._hover_index is not None and self._hover_index >= 0
        hover_target = 1.0 if hovering else 0.0
        rate = 1.0 - (2.718281828 ** (-dt / 36.0))
        self._hover_strength += (hover_target - self._hover_strength) * rate
        hover_done = abs(self._hover_strength - hover_target) <= 0.01
        if hover_done:
            self._hover_strength = hover_target

        pulse_done = now >= float(self._select_pulse_until)
        if pulse_done:
            self._select_pulse_until = 0

        if hover_done and pulse_done:
            self._fx_timer.stop()
        self.update()

    def set_regions(self, regions, visible=True):
        self.regions = list(regions or ())
        self.regions_visible = bool(visible)
        self._hover_index = -1
        self._hover_strength = 0.0
        self.update()

    def set_view(self, pixmap, scale, viewport):
        """Draw the page from its source pixmap; only the exposed rect is sampled."""
        self._view_pixmap = pixmap
        self._view_scale = max(0.01, float(scale))
        self.image_size = pixmap.size()
        self.setMinimumSize(0, 0)
        pw = pixmap.width() * self._view_scale
        ph = pixmap.height() * self._view_scale
        if self.rotation_deg != 0.0:
            rad = math.radians(self.rotation_deg)
            bw = abs(pw * math.cos(rad)) + abs(ph * math.sin(rad))
            bh = abs(pw * math.sin(rad)) + abs(ph * math.cos(rad))
        else:
            bw, bh = pw, ph
        self.setFixedSize(max(viewport.width(), round(bw)),
                          max(viewport.height(), round(bh)))
        self.update()

    def clear_view(self):
        self._view_pixmap = None
        self._view_scale = 1.0

    def view_transform(self) -> QTransform:
        t = QTransform()
        if self.rotation_deg == 0.0 and not self.flipped_h:
            return t
        page = self.page_rect()
        if page.isEmpty():
            return t
        center = page.center()
        t.translate(center.x(), center.y())
        if self.rotation_deg != 0.0:
            t.rotate(self.rotation_deg)
        if self.flipped_h:
            t.scale(-1.0, 1.0)
        t.translate(-center.x(), -center.y())
        return t

    def _untransform_point(self, point: QPointF) -> QPointF:
        if self.rotation_deg == 0.0 and not self.flipped_h:
            return QPointF(point)
        inv, ok = self.view_transform().inverted()
        return inv.map(QPointF(point)) if ok else QPointF(point)

    def widget_to_image(self, point: QPointF, *, clamp: bool = False) -> QPointF | None:
        page = self.page_rect()
        if page.isEmpty() or self.image_size is None or self.image_size.isEmpty():
            return None
        untransformed = self._untransform_point(point)
        if not clamp and not page.contains(untransformed):
            return None
        ix = (untransformed.x() - page.left()) * self.image_size.width() / page.width()
        iy = (untransformed.y() - page.top()) * self.image_size.height() / page.height()
        if clamp:
            ix = max(0.0, min(float(self.image_size.width() - 1e-3), ix))
            iy = max(0.0, min(float(self.image_size.height() - 1e-3), iy))
        return QPointF(ix, iy)

    def image_to_widget(self, img_pt: QPointF) -> QPointF:
        page = self.page_rect()
        if page.isEmpty() or self.image_size is None or self.image_size.isEmpty():
            return QPointF(img_pt)
        wx = page.left() + img_pt.x() * page.width() / self.image_size.width()
        wy = page.top() + img_pt.y() * page.height() / self.image_size.height()
        pos = QPointF(wx, wy)
        if self.rotation_deg != 0.0 or self.flipped_h:
            pos = self.view_transform().map(pos)
        return pos

    def set_selection_overlay(self, mask: np.ndarray | None, contours: list | None = None):
        if mask is None or mask.size == 0 or not np.any(mask > 0):
            self._selection_overlay_img = None
            self._selection_contours = []
        else:
            h, w = mask.shape[:2]
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            rgba[..., 0] = 44
            rgba[..., 1] = 110
            rgba[..., 2] = 150
            rgba[..., 3] = np.clip((mask.astype(np.float32) * (60.0 / 255.0)), 0, 60).astype(np.uint8)
            buf = np.ascontiguousarray(rgba)
            self._selection_overlay_img = QImage(buf.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
            polys = []
            for cnt in (contours or ()):
                if len(cnt) >= 2:
                    pts = [QPointF(float(pt[0][0]), float(pt[0][1])) for pt in cnt]
                    polys.append(QPolygonF(pts))
            self._selection_contours = polys
        self.update()

    def set_paint_preview_overlay(self, overlay: dict | None):
        self._paint_preview = overlay
        self.update()

    def set_clone_source_marker(self, point: tuple[float, float] | None):
        self._clone_source_pt = QPointF(point[0], point[1]) if point is not None else None
        self.update()

    def cancel_paint_drag(self):
        self._paint_dragging = False
        self._tablet_down = False
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self._paint_preview = None
        self.update()

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
        point = self._untransform_point(point)
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
        point = self._untransform_point(point)
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
            if self.region_creation or self.bubble_creation or self.paint_active:
                self.setCursor(Qt.CrossCursor)
            else:
                self.unsetCursor()
        else:
            self.setCursor(cursors[hit])

    def cancel_region_drag(self):
        self._region_drag = None
        self._selection_start = self._selection_rect = None
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self.unsetCursor()

    def tabletEvent(self, event):
        if not (self.paint_active and not self.space_pan and not self.region_creation
                and not self.bubble_creation and self.isEnabled()):
            super().tabletEvent(event)
            return
        etype = event.type()
        pressure = max(0.0, min(1.0, float(event.pressure())))
        if etype == QEvent.TabletPress:
            if event.button() == Qt.RightButton:
                if self.paint_right_click_pick:
                    pt = self.widget_to_image(event.position(), clamp=False)
                    if pt is not None:
                        self.paint_right_clicked.emit(pt.x(), pt.y())
                event.accept()
                return
            self.tablet_eraser_changed.emit(event.pointerType() == QPointingDevice.PointerType.Eraser)
            pt = self.widget_to_image(event.position(), clamp=False)
            if pt is not None:
                if event.modifiers() & Qt.AltModifier:
                    self.paint_alt_clicked.emit(pt.x(), pt.y())
                    event.accept()
                    return
                self._tablet_down = True
                self._paint_dragging = True
                self._hover_img_pt = pt
                self.setFocus(Qt.MouseFocusReason)
                self.paint_stroke_started.emit(pt.x(), pt.y(), pressure, event.modifiers())
            event.accept()
            return
        if etype == QEvent.TabletMove:
            pt = self.widget_to_image(event.position(), clamp=self._paint_dragging)
            if pt is not None:
                self._hover_img_pt = pt
                if self._tablet_down and self._paint_dragging:
                    self.paint_stroke_moved.emit(pt.x(), pt.y(), pressure, event.modifiers())
                else:
                    self.paint_hover_moved.emit(pt.x(), pt.y())
                    self.update()
            event.accept()
            return
        if etype == QEvent.TabletRelease:
            if self._tablet_down:
                self._tablet_down = False
                if self._paint_dragging:
                    self._paint_dragging = False
                    pt = self.widget_to_image(event.position(), clamp=True)
                    if pt is not None:
                        self.paint_stroke_ended.emit(pt.x(), pt.y(), pressure, event.modifiers())
            event.accept()
            return
        super().tabletEvent(event)

    def mousePressEvent(self, event):
        if self.paint_active and not self.space_pan and not self.region_creation and not self.bubble_creation:
            if self._tablet_down:
                event.accept()
                return
            if event.button() == Qt.RightButton and self.paint_right_click_pick:
                pt = self.widget_to_image(event.position(), clamp=False)
                if pt is not None:
                    self.paint_right_clicked.emit(pt.x(), pt.y())
                event.accept()
                return
            if event.button() == Qt.LeftButton:
                pt = self.widget_to_image(event.position(), clamp=False)
                if pt is not None:
                    self._hover_img_pt = pt
                    if event.modifiers() & Qt.AltModifier:
                        self.paint_alt_clicked.emit(pt.x(), pt.y())
                        event.accept()
                        return
                    self._paint_dragging = True
                    self.setFocus(Qt.MouseFocusReason)
                    self.grabMouse()
                    self.paint_stroke_started.emit(pt.x(), pt.y(), 1.0, event.modifiers())
                    event.accept()
                    return
        hit = self._region_hit(event.position())
        if (event.button() == Qt.LeftButton and not self.region_creation and not self.bubble_creation
                and self.page_rect().contains(self._untransform_point(event.position()))):
            if event.modifiers() & Qt.ShiftModifier:
                self._selection_start = QPointF(event.position())
                self._selection_rect = QRectF(self._selection_start, self._selection_start)
                self.setFocus(Qt.MouseFocusReason)
                self.grabMouse()
                event.accept()
                return
            if event.modifiers() & Qt.ControlModifier:
                index = self._region_at(event.position())
                if index is not None:
                    self.regions_selected.emit([index], 'toggle')
                    event.accept()
                    return
        if (self.bubble_creation and event.button() == Qt.LeftButton
                and self.page_rect().contains(self._untransform_point(event.position()))):
            self._region_drag = ('bubble_create', QPointF(event.position()), self.region)
            self.setFocus(Qt.MouseFocusReason)
            self.grabMouse()
            event.accept()
            return
        if (self.region_creation and event.button() == Qt.LeftButton
                and self.page_rect().contains(self._untransform_point(event.position())) and hit is None):
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

    def contextMenuEvent(self, event):
        if self.paint_active or self._region_drag is not None or self.region_creation or self.bubble_creation:
            event.accept() if self.paint_active else event.ignore()
            return
        index = self._region_at(QPointF(event.pos()))
        if index is not None:
            self.region_context_menu.emit(index, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def _drag_region_to(self, point):
        hit, start, original = self._region_drag
        start = self._untransform_point(start)
        point = self._untransform_point(point)
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
        if self.paint_active and not self.space_pan and not self.region_creation and not self.bubble_creation:
            if self._tablet_down:
                event.accept()
                return
            pt = self.widget_to_image(event.position(), clamp=self._paint_dragging)
            self._hover_img_pt = pt
            if self._paint_dragging and pt is not None:
                self.paint_stroke_moved.emit(pt.x(), pt.y(), 1.0, event.modifiers())
                self.update()
                event.accept()
                return
            if pt is not None:
                self.paint_hover_moved.emit(pt.x(), pt.y())
            self._region_cursor(None)
            self.update()
            event.accept()
            return
        if getattr(self, '_selection_start', None) is not None:
            self._selection_rect = QRectF(self._selection_start, event.position()).normalized().intersected(self.page_rect())
            self.update()
            event.accept()
            return
        if self._region_drag is not None:
            self._drag_region_to(event.position())
            event.accept()
            return
        hover = self._region_at(event.position())
        if hover != self._hover_index:
            self._hover_index = hover
            hovering = hover is not None and hover >= 0
            if hovering and not reduced_motion() and self.isVisible():
                self._hover_strength = 0.15
                self._ensure_fx_timer()
            else:
                self._hover_strength = 1.0 if hovering else 0.0
            self.update()
        hit = self._region_hit(event.position())
        self._region_cursor(hit)
        if hit is None and hover is not None:
            self.setCursor(Qt.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.paint_active and not self.space_pan and event.button() == Qt.LeftButton and self._paint_dragging:
            if self._tablet_down:
                event.accept()
                return
            self._paint_dragging = False
            if self.mouseGrabber() is self:
                self.releaseMouse()
            pt = self.widget_to_image(event.position(), clamp=True)
            if pt is not None:
                self.paint_stroke_ended.emit(pt.x(), pt.y(), 1.0, event.modifiers())
            self._region_cursor(None)
            event.accept()
            return
        if event.button() == Qt.LeftButton and getattr(self, '_selection_start', None) is not None:
            rect = self._selection_rect
            indices = [index for index, box in self.regions if rect.intersects(self._box_rect(box))]
            self._selection_start = self._selection_rect = None
            if self.mouseGrabber() is self:
                self.releaseMouse()
            self.regions_selected.emit(indices, 'add' if event.modifiers() & Qt.ControlModifier else 'replace')
            self.update()
            event.accept()
            return
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

    def mouseDoubleClickEvent(self, event):
        if self.paint_active and event.button() == Qt.LeftButton and not self.space_pan:
            pt = self.widget_to_image(event.position(), clamp=True)
            if pt is not None:
                self.paint_double_clicked.emit(pt.x(), pt.y())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.paint_active:
            self.cancel_paint_drag()
            self.paint_canceled.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and getattr(self, '_selection_start', None) is not None:
            self._selection_start = self._selection_rect = None
            if self.mouseGrabber() is self:
                self.releaseMouse()
            self.update()
            event.accept()
            return
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
        if self._hover_img_pt is not None:
            self._hover_img_pt = None
            if self.paint_active:
                self.update()
        if self._hover_index != -1:
            self._hover_index = -1
            self._hover_strength = 0.0
            self.update()
        if self._region_drag is None and not self._paint_dragging:
            self.unsetCursor()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._fx_timer.stop()
        self._select_pulse_until = 0
        self.cancel_region_drag()
        self.cancel_paint_drag()
        super().hideEvent(event)

    def event(self, event):
        if event.type() == QEvent.UngrabMouse:
            if getattr(self, '_region_drag', None) is not None:
                self._region_drag = None
                self.unsetCursor()
            if getattr(self, '_paint_dragging', False):
                self._paint_dragging = False
                self._tablet_down = False
        return super().event(event)

    def changeEvent(self, event):
        if event.type() == QEvent.EnabledChange and not self.isEnabled():
            self.cancel_region_drag()
            self.cancel_paint_drag()
        super().changeEvent(event)

    def paintEvent(self, event):
        if self._view_pixmap is not None and not self._view_pixmap.isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            page = self.page_rect()
            if self.rotation_deg != 0.0 or self.flipped_h:
                painter.setTransform(self.view_transform())
                painter.drawPixmap(page, self._view_pixmap, QRectF(self._view_pixmap.rect()))
            else:
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
        if self.image_size is None or self.image_size.isEmpty():
            return
        bounds = self.contentsRect()
        page = self.page_rect()
        if page.isEmpty():
            return
        painter = QPainter(self)
        transform = self.view_transform()
        has_xform = self.rotation_deg != 0.0 or self.flipped_h
        margin_rect = (
            transform.mapRect(page) if has_xform else page
        ).adjusted(-12, -12, 12, 12).toAlignedRect()
        margin = QRegion(bounds).subtracted(QRegion(margin_rect))
        painter.setClipRegion(margin)
        draw_corner_tones(painter, QRectF(bounds),
                          compact=self.window().width() < COMPACT_BREAKPOINT)
        painter.setClipping(False)
        if has_xform:
            painter.save()
            painter.setTransform(transform, True)
        shadow = QColor(color('black'))
        for spread, alpha in ((3, 18), (6, 10), (10, 5)):
            shadow.setAlpha(alpha)
            pen = QPen(shadow, 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(page.adjusted(-spread, -spread, spread, spread))
        edge = QPen(QColor(color('pageEdge')), 1)
        edge.setCosmetic(True)
        painter.setPen(edge)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(page.adjusted(.5, .5, -.5, -.5))

        sx = page.width() / self.image_size.width()
        sy = page.height() / self.image_size.height()

        if self.show_grid and self.paint_active:
            painter.save()
            painter.setClipRect(page)
            grid_step = 1
            if self._view_scale < 8.0:
                for cand in (8, 16, 32, 64, 128, 256):
                    if cand * self._view_scale >= 24.0:
                        grid_step = cand
                        break
                else:
                    grid_step = 256
            grid_color = QColor(color('guide'))
            grid_color.setAlpha(38)
            grid_pen = QPen(grid_color, 1)
            grid_pen.setCosmetic(True)
            painter.setPen(grid_pen)
            w_img, h_img = self.image_size.width(), self.image_size.height()
            for ix in range(grid_step, w_img, grid_step):
                wx = page.left() + ix * sx
                painter.drawLine(QPointF(wx, page.top()), QPointF(wx, page.bottom()))
            for iy in range(grid_step, h_img, grid_step):
                wy = page.top() + iy * sy
                painter.drawLine(QPointF(page.left(), wy), QPointF(page.right(), wy))
            painter.restore()

        if self._selection_overlay_img is not None and not self._selection_overlay_img.isNull():
            painter.save()
            painter.setClipRect(page)
            painter.drawImage(page, self._selection_overlay_img)
            if self._selection_contours:
                painter.setRenderHint(QPainter.Antialiasing)
                white_pen = QPen(QColor('#FFFFFF'), 1.2, Qt.SolidLine)
                white_pen.setCosmetic(True)
                dash_pen = QPen(QColor('#111111'), 1.2, Qt.CustomDashLine)
                dash_pen.setDashPattern([4, 4])
                dash_pen.setCosmetic(True)
                for poly in self._selection_contours:
                    mapped = QPolygonF([
                        QPointF(page.left() + pt.x() * sx, page.top() + pt.y() * sy)
                        for pt in poly
                    ])
                    painter.setPen(white_pen)
                    painter.drawPolygon(mapped)
                    painter.setPen(dash_pen)
                    painter.drawPolygon(mapped)
            painter.restore()

        if self._paint_preview:
            painter.save()
            painter.setClipRect(page)
            painter.setRenderHint(QPainter.Antialiasing)
            preview = self._paint_preview
            kind = preview.get('kind')
            w_pen = QPen(QColor('#FFFFFF'), 1.6, Qt.SolidLine)
            w_pen.setCosmetic(True)
            b_pen = QPen(QColor('#111111'), 1.1, Qt.DashLine)
            b_pen.setCosmetic(True)
            if kind == 'line':
                p0 = preview.get('p0')
                p1 = preview.get('p1')
                if p0 and p1:
                    q0 = QPointF(page.left() + p0[0] * sx, page.top() + p0[1] * sy)
                    q1 = QPointF(page.left() + p1[0] * sx, page.top() + p1[1] * sy)
                    painter.setPen(w_pen)
                    painter.drawLine(q0, q1)
                    painter.setPen(b_pen)
                    painter.drawLine(q0, q1)
            elif kind in ('rect', 'ellipse'):
                r = preview.get('rect')
                if r:
                    x0, y0, x1, y1 = r
                    qrect = QRectF(
                        page.left() + min(x0, x1) * sx,
                        page.top() + min(y0, y1) * sy,
                        abs(x1 - x0) * sx,
                        abs(y1 - y0) * sy,
                    )
                    painter.setBrush(Qt.NoBrush)
                    for pen in (w_pen, b_pen):
                        painter.setPen(pen)
                        if kind == 'ellipse':
                            painter.drawEllipse(qrect)
                        else:
                            painter.drawRect(qrect)
            elif kind in ('poly', 'polygon', 'lasso', 'polyline'):
                pts = preview.get('points') or ()
                if len(pts) >= 2:
                    poly = QPolygonF([
                        QPointF(page.left() + pt[0] * sx, page.top() + pt[1] * sy)
                        for pt in pts
                    ])
                    painter.setBrush(Qt.NoBrush)
                    for pen in (w_pen, b_pen):
                        painter.setPen(pen)
                        if preview.get('closed'):
                            painter.drawPolygon(poly)
                        else:
                            painter.drawPolyline(poly)
            painter.restore()

        if self._clone_source_pt is not None and self.paint_active:
            painter.save()
            painter.setClipRect(page)
            painter.setRenderHint(QPainter.Antialiasing)
            cx = page.left() + self._clone_source_pt.x() * sx
            cy = page.top() + self._clone_source_pt.y() * sy
            c_pen = QPen(QColor('#FFFFFF'), 1.8)
            c_pen.setCosmetic(True)
            k_pen = QPen(QColor('#111111'), 1.1)
            k_pen.setCosmetic(True)
            for pen in (c_pen, k_pen):
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPointF(cx, cy), 6.0, 6.0)
                painter.drawLine(QPointF(cx - 9.0, cy), QPointF(cx + 9.0, cy))
                painter.drawLine(QPointF(cx, cy - 9.0), QPointF(cx, cy + 9.0))
            painter.restore()

        if self.paint_active and self.paint_symmetry != 'none':
            painter.save()
            painter.setClipRect(page)
            sym_pen = QPen(QColor(color('guide')), 1.2, Qt.DashDotLine)
            sym_pen.setCosmetic(True)
            painter.setPen(sym_pen)
            if self.paint_symmetry in ('horizontal', 'both'):
                mid_x = page.center().x()
                painter.drawLine(QPointF(mid_x, page.top()), QPointF(mid_x, page.bottom()))
            if self.paint_symmetry in ('vertical', 'both'):
                mid_y = page.center().y()
                painter.drawLine(QPointF(page.left(), mid_y), QPointF(page.right(), mid_y))
            painter.restore()
        rubber = getattr(self, '_selection_rect', None)
        if rubber is not None:
            painter.setPen(QPen(QColor(color('guide')), 1, Qt.DashLine))
            tint = QColor(color('guide'))
            tint.setAlpha(25)
            painter.setBrush(tint)
            painter.drawRect(rubber)
        selected_index = None
        if self.regions_visible and self.regions:
            painter.setClipping(False)
            painter.setClipRect(page)
            painter.setRenderHint(QPainter.Antialiasing)
            for index, box in self.regions:
                rect = self._box_rect(box)
                if rect.isEmpty():
                    continue
                if self.region is not None and tuple(box) == tuple(self.region):
                    selected_index = index
                    continue
                guide = QColor(color('guide'))
                if index in getattr(self, 'selected_indices', set()):
                    pen = QPen(QColor(color('guide')), 2, Qt.SolidLine)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.setBrush(Qt.NoBrush)
                elif index == self._hover_index:
                    hs = max(0.25, min(1.0, self._hover_strength if self._hover_strength > 0 else 1.0))
                    halo = QColor(color('guideHalo'))
                    halo.setAlpha(int(round(180 * hs)))
                    halo_pen = QPen(halo, 2.5, Qt.SolidLine)
                    halo_pen.setCosmetic(True)
                    painter.setPen(halo_pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRect(rect)
                    guide.setAlpha(int(round(235 * hs)))
                    pen = QPen(guide, 1.5, Qt.SolidLine)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.setBrush(QColor(guide.red(), guide.green(), guide.blue(), int(round(24 * hs))))
                else:
                    guide.setAlpha(85)
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
            halo = QColor(color('guideHalo'))
            halo.setAlpha(200)
            halo_pen = QPen(halo, 2.5, Qt.SolidLine)
            halo_pen.setCosmetic(True)
            painter.setPen(halo_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            pen = QPen(QColor(color('guide')), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawRect(rect)
            if self._select_pulse_until > 0 and not reduced_motion():
                rem = self._select_pulse_until - int(self._fx_clock.elapsed())
                if rem > 0:
                    pt = 1.0 - max(0.0, min(1.0, rem / 240.0))
                    spread = 2.0 + 7.0 * pt
                    pulse_c = QColor(color('guide'))
                    pulse_c.setAlpha(int(round(165 * (1.0 - pt) ** 2)))
                    pulse_pen = QPen(pulse_c, 1.4, Qt.SolidLine)
                    pulse_pen.setCosmetic(True)
                    painter.setPen(pulse_pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRect(rect.adjusted(-spread, -spread, spread, spread))
            if selected_index is not None and rect.width() >= 24 and rect.height() >= 20:
                badge_text = f'{selected_index + 1:02d}'
                badge_font = ui_font(11, mono=True)
                badge_font.setBold(True)
                painter.setFont(badge_font)
                badge_w = max(22, painter.fontMetrics().horizontalAdvance(badge_text) + 10)
                badge_h = 18
                bx = max(page.left() + 2, min(page.right() - badge_w - 2, rect.left()))
                by = rect.top() - badge_h - 3 if rect.top() - badge_h - 3 >= page.top() + 2 else rect.top() + 3
                badge_rect = QRectF(bx, by, badge_w, badge_h)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(color('ink')))
                painter.drawRoundedRect(badge_rect, 4, 4)
                painter.setPen(QColor(color('paper')))
                painter.drawText(badge_rect, Qt.AlignCenter, badge_text)
            if self.region_editable and self.isEnabled():
                painter.setClipRect(page.adjusted(-5, -5, 5, 5))
                painter.setPen(QPen(QColor(color('guide')), 1.25))
                painter.setBrush(QColor(color('paper')))
                for handle in self._region_handles().values():
                    painter.drawRect(QRectF(handle.x() - 4, handle.y() - 4, 8, 8))
        if has_xform:
            painter.restore()
        if (self.paint_active and self.paint_show_brush_cursor
                and self._hover_img_pt is not None and not self.space_pan
                and self.isEnabled()):
            center = self.image_to_widget(self._hover_img_pt)
            radius = max(1.5, float(self.paint_brush_diameter) * self._view_scale * 0.5)
            painter.setClipping(False)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(Qt.NoBrush)
            outer_pen = QPen(QColor(0, 0, 0, 195), 1.4)
            outer_pen.setCosmetic(True)
            painter.setPen(outer_pen)
            painter.drawEllipse(center, radius + 0.6, radius + 0.6)
            inner_pen = QPen(QColor(255, 255, 255, 220), 1.1)
            inner_pen.setCosmetic(True)
            painter.setPen(inner_pen)
            painter.drawEllipse(center, max(0.8, radius - 0.3), max(0.8, radius - 0.3))
            if radius >= 5.0:
                dot_pen = QPen(QColor(0, 0, 0, 170), 1.0)
                dot_pen.setCosmetic(True)
                painter.setPen(dot_pen)
                painter.drawLine(QPointF(center.x() - 2.0, center.y()), QPointF(center.x() + 2.0, center.y()))
                painter.drawLine(QPointF(center.x(), center.y() - 2.0), QPointF(center.x(), center.y() + 2.0))
        painter.end()


class ImagePreview(QWidget):
    import_requested = Signal()
    region_edited = Signal(object)
    region_edit_finished = Signal()
    region_clicked = Signal(int)
    regions_selected = Signal(object, str)
    region_context_menu = Signal(int, object)
    bubble_created = Signal(object)
    paint_stroke_started = Signal(float, float, float, object)
    paint_stroke_moved = Signal(float, float, float, object)
    paint_stroke_ended = Signal(float, float, float, object)
    paint_hover_moved = Signal(float, float)
    paint_alt_clicked = Signal(float, float)
    paint_right_clicked = Signal(float, float)
    paint_double_clicked = Signal(float, float)
    paint_canceled = Signal()
    tablet_eraser_changed = Signal(bool)
    zoom_changed = Signal(object)
    color_picked = Signal(object)
    color_pick_canceled = Signal()

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
        self._color_picking = False
        self._suppress_context_until = 0.0
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
        self._state_bar = MonochromeShimmerBar()
        self._state_bar.setRange(0, 0)
        self._state_bar.setFixedWidth(180)
        self._state_bar.setFixedHeight(5)
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
        self._label.region_context_menu.connect(self.region_context_menu)
        self._label.bubble_created.connect(self.bubble_created)
        self._label.regions_selected.connect(self.regions_selected)
        self._connect_canvas_paint_signals(self._label)
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
        if event.type() == QEvent.ContextMenu and (
                self._color_picking or self._label.paint_active
                or time.monotonic() <= self._suppress_context_until):
            self._suppress_context_until = 0.0
            event.accept()
            return True
        if self._color_picking:
            if (event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape
                    or event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton):
                if event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
                    self._suppress_context_until = time.monotonic() + 0.25
                self.cancel_color_picking()
                return True
            if (event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton
                    and not self._space_pan):
                if watched is self._label:
                    pt = self._label.widget_to_image(event.position())
                    if pt is not None:
                        x, y = int(pt.x()), int(pt.y())
                        if 0 <= x < self._original.width() and 0 <= y < self._original.height():
                            # Sample native page pixels, excluding guides and display interpolation.
                            picked = self._original.toImage().pixelColor(x, y)
                            self.set_color_picking(False)
                            self.color_picked.emit(picked)
                return True
            if event.type() == QEvent.MouseButtonDblClick:
                return True
            if event.type() == QEvent.MouseMove and not self._space_pan and self._pan is None:
                self._label.setCursor(Qt.CrossCursor)
                return True
        elif event.type() == QEvent.MouseButtonPress:
            self._suppress_context_until = 0.0
        if event.type() == QEvent.Wheel:
            if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                step = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
                self._zoom_at(self._scale * step, self._viewport_position(watched, event))
            else:
                self._wheel_scroll(event)
            return True
        if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            if watched is self._label and (self._label.region_creation
                                           or self._label.paint_active
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
            suffix = Path(path).suffix.lower()
            if suffix == '.pdf':
                self.set_pixmap(QPixmap.fromImage(render_pdf_preview(path, QSize(1600, 1600))))
            elif suffix == '.cbz':
                self.set_pixmap(QPixmap.fromImage(render_cbz_preview(path, QSize(1600, 1600))))
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
        self.cancel_color_picking()
        self._label.cancel_paint_drag()
        self._label.set_selection_overlay(None)
        self._label.set_paint_preview_overlay(None)
        self._label.set_clone_source_marker(None)
        self._original = QPixmap()
        self.set_region(None)
        self._label.set_regions([])
        self._label.clear()
        self._label.clear_view()
        self._empty_title.setText(tr(text))
        self._stack.setCurrentWidget(self._empty)

    def set_loading(self, message=''):
        """Decoding a page: keep the previous panel out of the way."""
        self.cancel_color_picking()
        self._state_title.setText(tr('正在加载页面…'))
        self._state_message.setText(message or tr('正在解码原图与排版数据'))
        self._state_bar.setVisible(True)
        self._retry_btn.setVisible(False)
        self._retry_slot = None
        if self._stack.currentWidget() is not self._state_panel:
            self._stack.setCurrentWidget(self._state_panel)
            fade_in(self._state_panel)

    def set_error(self, message, retry=None):
        self.cancel_color_picking()
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
        if (self._color_picking or self._zoom_tool) and not self._space_pan:
            self._scroll.viewport().setCursor(Qt.CrossCursor)
            self._label.setCursor(Qt.CrossCursor)
        elif self._label.paint_active and not self._space_pan:
            self._scroll.viewport().setCursor(Qt.CrossCursor)
            self._label.setCursor(Qt.CrossCursor)
        elif self._space_pan:
            self._scroll.viewport().setCursor(Qt.OpenHandCursor)
            self._label.setCursor(Qt.OpenHandCursor)
        else:
            self._scroll.viewport().unsetCursor()
            self._label.unsetCursor()

    def set_color_picking(self, active):
        self.cancel_region_drag()
        self._color_picking = bool(active) and not self._original.isNull()
        self.set_region(self._label.region, editable=self._label.region_editable)
        if self._color_picking:
            self._label.setFocus(Qt.OtherFocusReason)
        self._update_canvas_cursor()

    def cancel_color_picking(self):
        if self._color_picking:
            self.set_color_picking(False)
            self.color_pick_canceled.emit()

    def hideEvent(self, event):
        self.cancel_color_picking()
        super().hideEvent(event)

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

    def set_selected_regions(self, indices):
        self._selected_regions = set(indices)
        self._label.selected_indices = self._selected_regions
        self._label.update()

    def set_region(self, box=None, *, editable=False):
        """Canvas-only selection guide; never alter the rendered/exported pixels."""
        prev_box = self._label.region
        new_box = tuple(box) if box is not None else None
        self._label.region = new_box
        self._label.region_editable = editable and box is not None
        self._label.setFocusPolicy(Qt.StrongFocus if (self._label.region_editable
                               or self._label.region_creation or self._label.bubble_creation
                               or self._color_picking or self._label.paint_active)
                               else Qt.NoFocus)
        self._label.setToolTip(tr(tr('拖动边角调整蒙版大小，框内拖动位置；Esc 恢复本次拖动前的范围')
                               if self._label.region_editable else ''))
        if (not self._label.region_editable and not self._label.region_creation
                and not self._label.bubble_creation):
            self.cancel_region_drag()
        if new_box is not None and new_box != prev_box and self._label._region_drag is None:
            self._label.trigger_select_pulse()
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

    def _connect_canvas_paint_signals(self, canvas: PageCanvas):
        canvas.paint_stroke_started.connect(self.paint_stroke_started)
        canvas.paint_stroke_moved.connect(self.paint_stroke_moved)
        canvas.paint_stroke_ended.connect(self.paint_stroke_ended)
        canvas.paint_hover_moved.connect(self.paint_hover_moved)
        canvas.paint_alt_clicked.connect(self.paint_alt_clicked)
        canvas.paint_right_clicked.connect(self.paint_right_clicked)
        canvas.paint_double_clicked.connect(self.paint_double_clicked)
        canvas.paint_canceled.connect(self.paint_canceled)
        canvas.tablet_eraser_changed.connect(self.tablet_eraser_changed)

    def set_paint_mode(
        self,
        active: bool,
        *,
        brush_diameter: float = 12.0,
        show_cursor: bool = True,
        right_click_pick: bool = True,
        symmetry: str = 'none',
    ):
        active = bool(active)
        if not active:
            self._label.cancel_paint_drag()
        else:
            self.cancel_region_drag()
        self._label.paint_active = active
        self._label.paint_brush_diameter = max(1.0, float(brush_diameter))
        self._label.paint_show_brush_cursor = bool(show_cursor)
        self._label.paint_right_click_pick = bool(right_click_pick)
        self._label.paint_symmetry = str(symmetry or 'none')
        self.set_region(self._label.region, editable=self._label.region_editable and not active)
        self._update_canvas_cursor()
        self._label.update()

    def update_paint_cursor(self, diameter: float, *, show: bool = True, symmetry: str = 'none'):
        self._label.paint_brush_diameter = max(1.0, float(diameter))
        self._label.paint_show_brush_cursor = bool(show)
        self._label.paint_symmetry = str(symmetry or 'none')
        self._label.update()

    def set_selection_overlay(self, mask: np.ndarray | None, contours: list | None = None):
        self._label.set_selection_overlay(mask, contours)

    def set_paint_preview_overlay(self, overlay: dict | None):
        self._label.set_paint_preview_overlay(overlay)

    def set_clone_source_marker(self, point: tuple[float, float] | None):
        self._label.set_clone_source_marker(point)

    def set_view_transform(self, rotation_deg: float = 0.0, flipped_h: bool = False, show_grid: bool = False):
        rot = float(rotation_deg)
        flip = bool(flipped_h)
        grid = bool(show_grid)
        changed_geom = (self._label.rotation_deg != rot) or (self._label.flipped_h != flip)
        self._label.rotation_deg = rot
        self._label.flipped_h = flip
        self._label.show_grid = grid
        if changed_geom:
            self._update_scaled()
        self._label.update()

    def set_original_image(self, image: QImage):
        """Fast in-place canvas refresh without clearing overlays or resetting zoom."""
        if image.isNull():
            return
        self._original = QPixmap.fromImage(image)
        self._label.image_size = self._original.size()
        if self._stack.currentWidget() is not self._scroll:
            self._stack.setCurrentWidget(self._scroll)
        self._update_scaled()

    def update_canvas_patch(self, box, image_patch: QImage):
        """Composite an incremental ROI QImage onto the live canvas pixmap at 60fps."""
        if self._original.isNull() or image_patch.isNull():
            return
        displayed = self._label.pixmap()
        if displayed is not None and displayed.cacheKey() == self._original.cacheKey():
            self._label.clear()
        del displayed
        painter = QPainter(self._original)
        try:
            painter.drawImage(int(box[0]), int(box[1]), image_patch)
        finally:
            painter.end()
        self._label._view_pixmap = self._original
        self._label.update()
