"""Detailed settings that previously required editing config.yaml by hand."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config as app_config
from ..i18n import tr


class AdvancedConfigSection(QWidget):
    """Performance knobs and model locations, embedded in the settings page."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        performance = QGroupBox(tr('性能与渲染'))
        performance_grid = QGridLayout(performance)
        performance_grid.setContentsMargins(0, 0, 0, 0)
        performance_grid.setHorizontalSpacing(24)
        performance_grid.setVerticalSpacing(10)
        self._workers = self._spin('max_workers')
        self._workers.setToolTip(tr(
            '同时在途准备、翻译与修补的页数（1–16，默认 4）。数值越大吞吐越高，'
            '但更吃显存与内存；8 GB 显存建议 2–4。'))
        self._pdf_dpi = self._spin('pdf_dpi')
        self._pdf_dpi.setToolTip(tr(
            'PDF 页图的分辨率（96–400，默认 200）。越高越清晰，也越慢、越占内存；'
            '对图片输入没有影响。'))
        self._font_size = self._spin('font_size')
        self._font_size.setToolTip(tr(
            '新排版使用的基准字号（8–96，默认 16）。精修页可以逐块调整，'
            '这里只改变之后生成的译文。'))
        self._probe_samples = self._spin('font_probe_samples')
        self._probe_samples.setToolTip(tr(
            '启用「AI 字体判别」时，每块文本重复判定的次数（1–5，默认 3）。'
            '次数越多越稳定，但更耗 token。'))
        for row, (left_label, left_field, right_label, right_field) in enumerate((
            ('最大并行页数', self._workers, 'PDF 渲染 DPI', self._pdf_dpi),
            ('默认字号', self._font_size, '字体判别采样次数', self._probe_samples),
        )):
            performance_grid.addWidget(QLabel(tr(left_label)), row, 0)
            performance_grid.addWidget(left_field, row, 1, Qt.AlignLeft)
            performance_grid.addWidget(QLabel(tr(right_label)), row, 2)
            performance_grid.addWidget(right_field, row, 3, Qt.AlignLeft)
        performance_grid.setColumnStretch(1, 1)
        performance_grid.setColumnStretch(3, 1)
        performance_note = QLabel(tr(
            '并行与字号只影响之后生成的页面；修改 PDF DPI 会让断点续传重新渲染 PDF。'))
        performance_note.setWordWrap(True)
        performance_note.setProperty('muted', True)
        performance_grid.addWidget(performance_note, 2, 0, 1, 4)
        layout.addWidget(performance)

        models = QGroupBox(tr('模型文件'))
        models_form = QFormLayout(models)
        self._style_form(models_form)
        models_form.setVerticalSpacing(8)
        self._path_fields: dict[str, QLineEdit] = {}
        for key, label in (
            ('detector_model', '检测模型'),
            ('lama_model', '修复模型'),
            ('charspot_ocr_model', 'CharSpot OCR 目录'),
            ('ocr_model', 'manga-ocr 目录'),
            ('baberu_ocr_model', 'Baberu OCR 目录'),
        ):
            field = QLineEdit()
            field.setToolTip(tr('留空使用内置默认路径；更换文件后下一次任务会重新加载模型。'))
            field.setAccessibleName(tr(label))
            field.editingFinished.connect(self._refresh_model_status)
            button = QPushButton(tr('浏览...'))
            button.setProperty('compact', True)
            button.clicked.connect(
                lambda _checked=False, target=field, name=key: self._browse_model(target, name))
            row = QHBoxLayout()
            row.addWidget(field, 1)
            row.addWidget(button)
            models_form.addRow(tr(label), row)
            self._path_fields[key] = field
        self._model_status = QLabel()
        self._model_status.setWordWrap(True)
        self._model_status.setProperty('muted', True)
        self._model_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        models_form.addRow(tr('模型检查'), self._model_status)
        layout.addWidget(models)

        defaults_row = QHBoxLayout()
        defaults_row.setSpacing(12)
        self._reset_btn = QPushButton(tr('恢复推荐默认值'))
        self._reset_btn.setProperty('compact', True)
        self._reset_btn.setToolTip(tr('只恢复本页字段，点击「保存配置」后才会写入。'))
        self._reset_btn.clicked.connect(self.reset_to_defaults)
        defaults_row.addWidget(self._reset_btn)
        defaults_row.addStretch(1)
        location = QLabel(tr('配置文件：{_0}', _0=str(app_config.CONFIG_PATH)))
        location.setProperty('muted', True)
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        defaults_row.addWidget(location)
        layout.addLayout(defaults_row)
        layout.addStretch(1)
        self.load_config(config)

    @staticmethod
    def _style_form(form: QFormLayout) -> None:
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)

    @staticmethod
    def _spin(key: str) -> QSpinBox:
        low, high, _default = app_config.ADVANCED_LIMITS[key]
        box = QSpinBox()
        box.setRange(low, high)
        box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box.setMinimumWidth(96)
        box.setMaximumWidth(140)
        return box

    def _browse_model(self, field: QLineEdit, key: str) -> None:
        current = field.text().strip()
        if current and Path(current).is_file():
            start = str(Path(current).parent)
        elif current and Path(current).is_dir():
            start = current
        else:
            start = str(app_config.MODELS_ROOT)
        if key in ('ocr_model', 'baberu_ocr_model', 'charspot_ocr_model'):
            path = QFileDialog.getExistingDirectory(self, tr('选择模型目录'), start)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, tr('选择 ONNX 模型'), start, tr('ONNX 模型 (*.onnx)'))
        if path:
            field.setText(path)
            self._refresh_model_status()

    def load_config(self, config: dict) -> None:
        self._workers.setValue(int(config.get('max_workers') or 4))
        self._pdf_dpi.setValue(int(config.get('pdf_dpi') or 200))
        self._font_size.setValue(int(config.get('font_size') or 16))
        self._probe_samples.setValue(int(config.get('font_probe_samples') or 3))
        for key, field in self._path_fields.items():
            field.setText(str(config.get(key) or ''))
        self._refresh_model_status()

    def values(self) -> dict:
        data = {
            'max_workers': self._workers.value(),
            'pdf_dpi': self._pdf_dpi.value(),
            'font_size': self._font_size.value(),
            'font_probe_samples': self._probe_samples.value(),
        }
        for key, field in self._path_fields.items():
            data[key] = field.text().strip()
        return data

    def reset_to_defaults(self) -> None:
        defaults = app_config.model_defaults()
        self._workers.setValue(app_config.ADVANCED_LIMITS['max_workers'][2])
        self._pdf_dpi.setValue(app_config.ADVANCED_LIMITS['pdf_dpi'][2])
        self._font_size.setValue(app_config.ADVANCED_LIMITS['font_size'][2])
        self._probe_samples.setValue(app_config.ADVANCED_LIMITS['font_probe_samples'][2])
        for key, field in self._path_fields.items():
            field.setText(defaults.get(key, ''))
        self._refresh_model_status()

    def _refresh_model_status(self) -> None:
        existing = sum(1 for field in self._path_fields.values()
                       if field.text().strip() and Path(field.text().strip()).exists())
        total = len(self._path_fields)
        if existing == total:
            self._model_status.setText(tr('全部 {_0} 个路径存在', _0=total))
        else:
            self._model_status.setText(
                tr('{_0}/{_1} 个路径存在，缺失项会在开始翻译前提示', _0=existing, _1=total))
