"""HSV hue ring + SV square color wheel, sliders, and swatches."""
from __future__ import annotations

import math
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from .theme import color, theme_changed, ui_font


DEFAULT_SWATCHES = [
    '#000000', '#333333', '#666666', '#999999', '#CCCCCC', '#FFFFFF',
    '#E53935', '#FB8C00', '#FDD835', '#43A047', '#1E88E5', '#8E24AA',
]


def _hsv_to_rgb01(h_deg: float, s: float, v: float) -> tuple[float, float, float]:
    c = v * s
    hp = (h_deg % 360.0) / 60.0
    x = c * (1.0 - abs(hp % 2.0 - 1.0))
    if hp < 1.0:
        r1, g1, b1 = c, x, 0.0
    elif hp < 2.0:
        r1, g1, b1 = x, c, 0.0
    elif hp < 3.0:
        r1, g1, b1 = 0.0, c, x
    elif hp < 4.0:
        r1, g1, b1 = 0.0, x, c
    elif hp < 5.0:
        r1, g1, b1 = x, 0.0, c
    else:
        r1, g1, b1 = c, 0.0, x
    m = v - c
    return r1 + m, g1 + m, b1 + m


class _WheelCanvas(QWidget):
    hsv_changed = Signal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._h = 0.0
        self._s = 0.0
        self._v = 0.0
        self._drag = None
        self._ring_cache: tuple[int, QImage] | None = None
        self._sv_cache: tuple[int, int, QImage] | None = None
        self.setMinimumSize(136, 136)
        self.setMaximumHeight(184)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_hsv(self, h: float, s: float, v: float) -> None:
        self._h = h % 360.0
        self._s = max(0.0, min(1.0, s))
        self._v = max(0.0, min(1.0, v))
        self.update()

    def _geometry_metrics(self):
        side = max(80, min(self.width(), self.height()) - 6)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        outer_r = side / 2.0
        ring_w = max(12.0, outer_r * 0.19)
        inner_r = outer_r - ring_w
        half_sq = max(16.0, (inner_r - 4.0) / math.sqrt(2.0))
        sq_rect = QRectF(cx - half_sq, cy - half_sq, half_sq * 2.0, half_sq * 2.0)
        return cx, cy, outer_r, inner_r, sq_rect

    def _ring_image(self, side: int) -> QImage:
        if self._ring_cache is not None and self._ring_cache[0] == side:
            return self._ring_cache[1]
        yy, xx = np.mgrid[:side, :side].astype(np.float32)
        c = (side - 1) / 2.0
        outer_r = side / 2.0 - 1.0
        ring_w = max(12.0, outer_r * 0.19)
        inner_r = outer_r - ring_w
        dx = xx - c
        dy = yy - c
        r = np.sqrt(dx * dx + dy * dy)
        angle = (np.degrees(np.arctan2(dy, dx)) + 360.0) % 360.0
        hp = angle / 60.0
        x = 1.0 - np.abs(hp % 2.0 - 1.0)
        zeros = np.zeros_like(hp)
        ones = np.ones_like(hp)
        conds = [hp < 1.0, (hp >= 1.0) & (hp < 2.0), (hp >= 2.0) & (hp < 3.0),
                 (hp >= 3.0) & (hp < 4.0), (hp >= 4.0) & (hp < 5.0), hp >= 5.0]
        red = np.select(conds, [ones, x, zeros, zeros, x, ones])
        green = np.select(conds, [x, ones, ones, x, zeros, zeros])
        blue = np.select(conds, [zeros, zeros, x, ones, ones, x])
        alpha_outer = np.clip(outer_r + 0.5 - r, 0.0, 1.0)
        alpha_inner = np.clip(r - (inner_r - 0.5), 0.0, 1.0)
        alpha = np.minimum(alpha_outer, alpha_inner)
        rgba = np.empty((side, side, 4), dtype=np.uint8)
        rgba[..., 0] = np.clip(np.rint(red * 255.0), 0, 255)
        rgba[..., 1] = np.clip(np.rint(green * 255.0), 0, 255)
        rgba[..., 2] = np.clip(np.rint(blue * 255.0), 0, 255)
        rgba[..., 3] = np.clip(np.rint(alpha * 255.0), 0, 255)
        self._ring_rgba = np.ascontiguousarray(rgba)
        img = QImage(self._ring_rgba.data, side, side, side * 4, QImage.Format_RGBA8888).copy()
        self._ring_cache = (side, img)
        return img

    def _sv_image(self, sq_px: int) -> QImage:
        hue_q = round(self._h * 2.0)
        if self._sv_cache is not None and self._sv_cache[:2] == (sq_px, hue_q):
            return self._sv_cache[2]
        hr, hg, hb = _hsv_to_rgb01(self._h, 1.0, 1.0)
        s_grid = np.linspace(0.0, 1.0, sq_px, dtype=np.float32)[None, :, None]
        v_grid = np.linspace(1.0, 0.0, sq_px, dtype=np.float32)[:, None, None]
        hue_rgb = np.array([[[hr, hg, hb]]], dtype=np.float32)
        rgb = v_grid * ((1.0 - s_grid) + s_grid * hue_rgb)
        arr = np.ascontiguousarray(np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8))
        img = QImage(arr.data, sq_px, sq_px, sq_px * 3, QImage.Format_RGB888).copy()
        self._sv_cache = (sq_px, hue_q, img)
        return img

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx, cy, outer_r, inner_r, sq_rect = self._geometry_metrics()
        side = max(16, round(outer_r * 2.0))
        ring_img = self._ring_image(side)
        painter.drawImage(QRectF(cx - side / 2.0, cy - side / 2.0, side, side), ring_img)

        sq_px = max(12, round(sq_rect.width()))
        sv_img = self._sv_image(sq_px)
        painter.drawImage(sq_rect, sv_img)
        painter.setPen(QPen(QColor(color('ruleStrong')), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(sq_rect)

        # Hue marker on ring
        mid_r = (outer_r + inner_r) / 2.0
        rad = math.radians(self._h)
        hx = cx + math.cos(rad) * mid_r
        hy = cy + math.sin(rad) * mid_r
        painter.setPen(QPen(QColor('#FFFFFF'), 2.0))
        painter.drawEllipse(QPointF(hx, hy), 4.5, 4.5)
        painter.setPen(QPen(QColor('#111111'), 1.0))
        painter.drawEllipse(QPointF(hx, hy), 5.3, 5.3)

        # SV marker inside square
        sx = sq_rect.left() + self._s * sq_rect.width()
        sy = sq_rect.top() + (1.0 - self._v) * sq_rect.height()
        ring_color = '#FFFFFF' if self._v < 0.6 else '#111111'
        painter.setPen(QPen(QColor(ring_color), 1.75))
        painter.drawEllipse(QPointF(sx, sy), 4.5, 4.5)
        painter.end()

    def _update_from_point(self, pos: QPointF):
        cx, cy, outer_r, inner_r, sq_rect = self._geometry_metrics()
        if self._drag == 'hue':
            angle = (math.degrees(math.atan2(pos.y() - cy, pos.x() - cx)) + 360.0) % 360.0
            self._h = angle
            self.update()
            self.hsv_changed.emit(self._h, self._s, self._v)
        elif self._drag == 'sv':
            s = max(0.0, min(1.0, (pos.x() - sq_rect.left()) / max(1.0, sq_rect.width())))
            v = max(0.0, min(1.0, 1.0 - (pos.y() - sq_rect.top()) / max(1.0, sq_rect.height())))
            self._s, self._v = s, v
            self.update()
            self.hsv_changed.emit(self._h, self._s, self._v)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.position()
            cx, cy, outer_r, inner_r, sq_rect = self._geometry_metrics()
            r = math.hypot(pos.x() - cx, pos.y() - cy)
            if sq_rect.adjusted(-2, -2, 2, 2).contains(pos):
                self._drag = 'sv'
            elif inner_r - 3 <= r <= outer_r + 3:
                self._drag = 'hue'
            if self._drag is not None:
                self.grabMouse()
                self._update_from_point(pos)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self._update_from_point(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag is not None:
            self._update_from_point(event.position())
            self._drag = None
            if self.mouseGrabber() is self:
                self.releaseMouse()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PaintColorWheel(QWidget):
    """HSV color wheel with FG/BG swatches, RGB/HSV sliders, hex input, and saved swatches."""

    color_changed = Signal(object)
    bg_color_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fg = QColor('#000000')
        self._bg = QColor('#FFFFFF')
        self._editing_bg = False
        self._mode = 'HSV'
        self._syncing = False
        self._swatch_buttons: list[QPushButton] = []
        self._build_ui()
        self._load_swatches()
        self._sync_ui_from_active()
        theme_changed.changed.connect(self._refresh_theme_styles)

    def fg_color(self) -> QColor:
        return QColor(self._fg)

    def bg_color(self) -> QColor:
        return QColor(self._bg)

    def set_fg_color(self, qcolor: QColor, *, emit: bool = False) -> None:
        c = QColor(qcolor)
        if not c.isValid():
            return
        changed = c.rgb() != self._fg.rgb()
        self._fg = c
        if not self._editing_bg:
            self._sync_ui_from_active()
        else:
            self._refresh_fg_bg_buttons()
        if changed and emit:
            self.color_changed.emit(QColor(self._fg))

    def set_bg_color(self, qcolor: QColor, *, emit: bool = False) -> None:
        c = QColor(qcolor)
        if not c.isValid():
            return
        changed = c.rgb() != self._bg.rgb()
        self._bg = c
        if self._editing_bg:
            self._sync_ui_from_active()
        else:
            self._refresh_fg_bg_buttons()
        if changed and emit:
            self.bg_color_changed.emit(QColor(self._bg))

    def swap_colors(self) -> None:
        self._fg, self._bg = QColor(self._bg), QColor(self._fg)
        self._sync_ui_from_active()
        self.color_changed.emit(QColor(self._fg))
        self.bg_color_changed.emit(QColor(self._bg))

    def reset_colors(self) -> None:
        self._fg = QColor('#000000')
        self._bg = QColor('#FFFFFF')
        self._sync_ui_from_active()
        self.color_changed.emit(QColor(self._fg))
        self.bg_color_changed.emit(QColor(self._bg))

    def _active_color(self) -> QColor:
        return self._bg if self._editing_bg else self._fg

    def _set_active_color(self, qcolor: QColor, *, emit: bool = True) -> None:
        if self._editing_bg:
            self.set_bg_color(qcolor, emit=emit)
        else:
            self.set_fg_color(qcolor, emit=emit)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._wheel = _WheelCanvas()
        self._wheel.hsv_changed.connect(self._on_wheel_hsv)
        root.addWidget(self._wheel)

        # FG / BG swatch controls + mode switch + Hex input
        fgbg_row = QHBoxLayout()
        fgbg_row.setSpacing(4)
        self._fg_btn = QPushButton(tr('前'))
        self._fg_btn.setCheckable(True)
        self._fg_btn.setChecked(True)
        self._fg_btn.setFixedSize(34, 24)
        self._fg_btn.setToolTip(tr('前景色（点击切换编辑目标）'))
        self._fg_btn.clicked.connect(lambda: self._select_slot(False))
        fgbg_row.addWidget(self._fg_btn)

        self._bg_btn = QPushButton(tr('背'))
        self._bg_btn.setCheckable(True)
        self._bg_btn.setFixedSize(34, 24)
        self._bg_btn.setToolTip(tr('背景色（点击切换编辑目标）'))
        self._bg_btn.clicked.connect(lambda: self._select_slot(True))
        fgbg_row.addWidget(self._bg_btn)

        swap_btn = QToolButton()
        swap_btn.setText('⇄')
        swap_btn.setProperty('compact', True)
        swap_btn.setProperty('role', 'chip')
        swap_btn.setToolTip(tr('交换前景色与背景色 · X'))
        swap_btn.clicked.connect(self.swap_colors)
        fgbg_row.addWidget(swap_btn)

        reset_btn = QToolButton()
        reset_btn.setText('D')
        reset_btn.setProperty('compact', True)
        reset_btn.setProperty('role', 'chip')
        reset_btn.setToolTip(tr('重置为黑/白 · D'))
        reset_btn.clicked.connect(self.reset_colors)
        fgbg_row.addWidget(reset_btn)

        fgbg_row.addStretch(1)

        self._mode_btn = QPushButton('HSV')
        self._mode_btn.setProperty('compact', True)
        self._mode_btn.setProperty('role', 'chip')
        self._mode_btn.setToolTip(tr('切换 HSV / RGB 滑块模式'))
        self._mode_btn.clicked.connect(self._toggle_slider_mode)
        fgbg_row.addWidget(self._mode_btn)
        root.addLayout(fgbg_row)

        # Hex row
        hex_row = QHBoxLayout()
        hex_row.setSpacing(4)
        hex_lbl = QLabel('HEX')
        hex_lbl.setProperty('muted', True)
        hex_lbl.setFont(ui_font(11, mono=True))
        hex_row.addWidget(hex_lbl)
        self._hex_edit = QLineEdit('#000000')
        self._hex_edit.setFont(ui_font(12, mono=True))
        self._hex_edit.setMaxLength(7)
        self._hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_row.addWidget(self._hex_edit, 1)
        self._add_swatch_btn = QToolButton()
        self._add_swatch_btn.setText('+')
        self._add_swatch_btn.setProperty('compact', True)
        self._add_swatch_btn.setProperty('role', 'chip')
        self._add_swatch_btn.setToolTip(tr('将当前颜色保存到色板'))
        self._add_swatch_btn.clicked.connect(self._save_current_swatch)
        hex_row.addWidget(self._add_swatch_btn)
        root.addLayout(hex_row)

        # 3 Sliders (H/S/V or R/G/B)
        self._sliders: list[QSlider] = []
        self._slider_labels: list[QLabel] = []
        self._slider_vals: list[QLabel] = []
        slider_grid = QGridLayout()
        slider_grid.setContentsMargins(0, 0, 0, 0)
        slider_grid.setHorizontalSpacing(6)
        slider_grid.setVerticalSpacing(2)
        for row_idx in range(3):
            lbl = QLabel()
            lbl.setFont(ui_font(11, mono=True))
            lbl.setFixedWidth(14)
            slider = QSlider(Qt.Horizontal)
            slider.valueChanged.connect(self._on_slider_changed)
            val = QLabel('0')
            val.setFont(ui_font(11, mono=True))
            val.setFixedWidth(28)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            slider_grid.addWidget(lbl, row_idx, 0)
            slider_grid.addWidget(slider, row_idx, 1)
            slider_grid.addWidget(val, row_idx, 2)
            self._slider_labels.append(lbl)
            self._sliders.append(slider)
            self._slider_vals.append(val)
        root.addLayout(slider_grid)
        self._configure_slider_ranges()

        # Swatch palette grid
        self._swatch_frame = QFrame()
        self._swatch_grid = QGridLayout(self._swatch_frame)
        self._swatch_grid.setContentsMargins(0, 2, 0, 0)
        self._swatch_grid.setSpacing(3)
        root.addWidget(self._swatch_frame)

    def _select_slot(self, is_bg: bool):
        self._editing_bg = bool(is_bg)
        self._fg_btn.setChecked(not self._editing_bg)
        self._bg_btn.setChecked(self._editing_bg)
        self._sync_ui_from_active()

    def _toggle_slider_mode(self):
        self._mode = 'RGB' if self._mode == 'HSV' else 'HSV'
        self._mode_btn.setText(self._mode)
        self._configure_slider_ranges()
        self._sync_ui_from_active()

    def _configure_slider_ranges(self):
        self._syncing = True
        try:
            if self._mode == 'HSV':
                specs = (('H', 0, 359), ('S', 0, 100), ('V', 0, 100))
            else:
                specs = (('R', 0, 255), ('G', 0, 255), ('B', 0, 255))
            for idx, (name, lo, hi) in enumerate(specs):
                self._slider_labels[idx].setText(name)
                self._sliders[idx].setRange(lo, hi)
        finally:
            self._syncing = False

    def _on_wheel_hsv(self, h: float, s: float, v: float):
        if self._syncing:
            return
        r, g, b = _hsv_to_rgb01(h, s, v)
        qc = QColor(round(r * 255), round(g * 255), round(b * 255))
        self._set_active_color(qc, emit=True)

    def _on_slider_changed(self):
        if self._syncing:
            return
        v0, v1, v2 = (s.value() for s in self._sliders)
        if self._mode == 'HSV':
            r, g, b = _hsv_to_rgb01(v0, v1 / 100.0, v2 / 100.0)
            qc = QColor(round(r * 255), round(g * 255), round(b * 255))
        else:
            qc = QColor(v0, v1, v2)
        self._set_active_color(qc, emit=True)

    def _on_hex_edited(self):
        raw = self._hex_edit.text().strip()
        if not raw.startswith('#'):
            raw = '#' + raw
        qc = QColor(raw)
        if qc.isValid():
            self._set_active_color(qc, emit=True)
        else:
            self._hex_edit.setText(self._active_color().name().upper())

    def _sync_ui_from_active(self):
        self._syncing = True
        try:
            c = self._active_color()
            h, s, v, _ = c.getHsvF()
            h_deg = 0.0 if h < 0 else h * 360.0
            self._wheel.set_hsv(h_deg, s, v)
            self._hex_edit.setText(c.name().upper())
            if self._mode == 'HSV':
                vals = (round(h_deg) % 360, round(s * 100), round(v * 100))
            else:
                vals = (c.red(), c.green(), c.blue())
            for idx, value in enumerate(vals):
                self._sliders[idx].setValue(value)
                self._slider_vals[idx].setText(str(value))
            self._refresh_fg_bg_buttons()
        finally:
            self._syncing = False

    def _refresh_fg_bg_buttons(self):
        for btn, qc, active in (
            (self._fg_btn, self._fg, not self._editing_bg),
            (self._bg_btn, self._bg, self._editing_bg),
        ):
            fg_text = '#FFFFFF' if qc.lightness() < 128 else '#111111'
            border = color('ink') if active else color('ruleStrong')
            bw = 2 if active else 1
            btn.setStyleSheet(
                f'background:{qc.name()}; color:{fg_text}; border:{bw}px solid {border}; border-radius:4px; padding:1px;'
            )

    def _refresh_theme_styles(self, *_args):
        self._refresh_fg_bg_buttons()
        self._rebuild_swatches()
        self._wheel.update()

    def _load_swatches(self):
        raw = QSettings().value('ui/paintSwatches', None)
        if isinstance(raw, list) and raw:
            swatches = [str(item) for item in raw[:24]]
        else:
            swatches = list(DEFAULT_SWATCHES)
        self._swatches = swatches
        self._rebuild_swatches()

    def _save_current_swatch(self):
        hex_val = self._active_color().name().upper()
        if hex_val not in self._swatches:
            self._swatches.append(hex_val)
            self._swatches = self._swatches[-24:]
            QSettings().setValue('ui/paintSwatches', self._swatches)
            self._rebuild_swatches()

    def _rebuild_swatches(self):
        while self._swatch_grid.count():
            item = self._swatch_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._swatch_buttons.clear()
        cols = 6
        for idx, hex_str in enumerate(self._swatches):
            btn = QPushButton()
            btn.setFixedSize(22, 18)
            btn.setToolTip(hex_str)
            btn.setStyleSheet(
                f'background:{hex_str}; border:1px solid {color("ruleStrong")}; border-radius:3px; padding:0;'
            )
            btn.clicked.connect(lambda _=False, h=hex_str: self._set_active_color(QColor(h), emit=True))
            self._swatch_grid.addWidget(btn, idx // cols, idx % cols)
            self._swatch_buttons.append(btn)
