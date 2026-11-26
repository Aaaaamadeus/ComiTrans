"""Interactive live-preview filter & color adjustment dialog for the paint retouch studio."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from ..i18n import tr
from .theme import ui_font


FILTER_TITLES = {
    'hsl': '色相 / 饱和度 / 明度',
    'bc': '亮度 / 对比度',
    'levels': '色阶调整',
    'blur': '高斯模糊',
    'sharpen': '锐化',
    'luma_white': '白底提纯（扫描去灰）',
}


class PaintFilterDialog(QDialog):
    """Parameter dialog with throttled canvas live preview."""

    preview_requested = Signal(dict)
    preview_canceled = Signal()

    def __init__(self, filter_kind: str, parent=None):
        super().__init__(parent)
        self.filter_kind = filter_kind
        self._controls: list[tuple[str, QSlider, QSpinBox | QDoubleSpinBox, float, float]] = []
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self._emit_preview)
        self._syncing = False
        self.setWindowTitle(tr(FILTER_TITLES.get(filter_kind, '滤镜与调色')))
        self.setMinimumWidth(340)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        specs = self._specs_for_kind()
        for row_idx, (key, label_text, default, minimum, maximum, scale, decimals) in enumerate(specs):
            lbl = QLabel(tr(label_text))
            lbl.setFont(ui_font(12))
            slider = QSlider(Qt.Horizontal)
            slider.setRange(round(minimum * scale), round(maximum * scale))
            slider.setValue(round(default * scale))
            if decimals > 0:
                spin = QDoubleSpinBox()
                spin.setDecimals(decimals)
                spin.setSingleStep(1.0 / scale)
            else:
                spin = QSpinBox()
            spin.setRange(minimum, maximum)
            spin.setValue(default)
            spin.setFixedWidth(74)

            def _slider_moved(val, sp=spin, sc=scale):
                if self._syncing:
                    return
                self._syncing = True
                sp.setValue(val / sc if sc != 1 else val)
                self._syncing = False
                self._schedule_preview()

            def _spin_changed(val, sl=slider, sc=scale):
                if self._syncing:
                    return
                self._syncing = True
                sl.setValue(round(val * sc))
                self._syncing = False
                self._schedule_preview()

            slider.valueChanged.connect(_slider_moved)
            spin.valueChanged.connect(_spin_changed)

            grid.addWidget(lbl, row_idx, 0)
            grid.addWidget(slider, row_idx, 1)
            grid.addWidget(spin, row_idx, 2)
            self._controls.append((key, slider, spin, default, scale))

        root.addLayout(grid)

        self._live_check = QCheckBox(tr('实时预览'))
        self._live_check.setChecked(True)
        self._live_check.toggled.connect(self._on_live_toggled)
        root.addWidget(self._live_check)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._reset_btn = QPushButton(tr('重置参数'))
        self._reset_btn.setProperty('role', 'chip')
        self._reset_btn.setProperty('compact', True)
        self._reset_btn.clicked.connect(self.reset_defaults)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch(1)

        self._cancel_btn = QPushButton(tr('取消'))
        self._cancel_btn.setProperty('role', 'chip')
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._ok_btn = QPushButton(tr('确定'))
        self._ok_btn.setProperty('role', 'primary')
        self._ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._ok_btn)
        root.addLayout(btn_row)

    def _specs_for_kind(self):
        # (key, label, default, min, max, slider_scale, decimals)
        if self.filter_kind == 'hsl':
            return [
                ('hue_deg', '色相 (°)', 0, -180, 180, 1, 0),
                ('sat_pct', '饱和度 (%)', 0, -100, 100, 1, 0),
                ('lum_pct', '明度 (%)', 0, -100, 100, 1, 0),
            ]
        if self.filter_kind == 'bc':
            return [
                ('brightness', '亮度', 0, -100, 100, 1, 0),
                ('contrast', '对比度', 0, -100, 100, 1, 0),
            ]
        if self.filter_kind == 'levels':
            return [
                ('in_black', '黑场输入', 0, 0, 245, 1, 0),
                ('gamma', '灰场 (γ)', 1.0, 0.2, 3.0, 100, 2),
                ('in_white', '白场输入', 255, 10, 255, 1, 0),
            ]
        if self.filter_kind == 'blur':
            return [
                ('radius', '模糊半径 (px)', 3.0, 0.5, 30.0, 10, 1),
            ]
        if self.filter_kind == 'sharpen':
            return [
                ('amount', '锐化强度 (%)', 100, 0, 300, 1, 0),
                ('radius', '作用半径 (px)', 1.5, 0.5, 10.0, 10, 1),
            ]
        if self.filter_kind == 'luma_white':
            return [
                ('threshold', '提纯阈值', 215, 100, 254, 1, 0),
                ('softness', '过渡柔和度', 24, 1, 64, 1, 0),
            ]
        return []

    def params(self) -> dict:
        result = {'filter': self.filter_kind}
        for key, _slider, spin, _default, _scale in self._controls:
            result[key] = spin.value()
        return result

    def set_param(self, key: str, value: float) -> None:
        for ctrl_key, slider, spin, _default, scale in self._controls:
            if ctrl_key == key:
                self._syncing = True
                spin.setValue(value)
                slider.setValue(round(value * scale))
                self._syncing = False
                self._schedule_preview()
                break

    def reset_defaults(self) -> None:
        self._syncing = True
        try:
            for _key, slider, spin, default, scale in self._controls:
                spin.setValue(default)
                slider.setValue(round(default * scale))
        finally:
            self._syncing = False
        self._schedule_preview()

    def _on_live_toggled(self, checked: bool):
        if checked:
            self._emit_preview()
        else:
            self._preview_timer.stop()
            self.preview_canceled.emit()

    def _schedule_preview(self):
        if self._live_check.isChecked():
            self._preview_timer.start()

    def _emit_preview(self):
        if self._live_check.isChecked():
            self.preview_requested.emit(self.params())

    def showEvent(self, event):
        super().showEvent(event)
        if self._live_check.isChecked():
            self._preview_timer.start()

    def done(self, result):
        self._preview_timer.stop()
        if result != QDialog.Accepted:
            self.preview_canceled.emit()
        super().done(result)
