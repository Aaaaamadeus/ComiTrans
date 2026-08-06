from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import load_ai_config


class _Preview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._original = QPixmap()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("选择已翻译图片后，在这里预览并编辑")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("color: #888;")
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._label)
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._scroll)

    def set_image(self, path) -> None:
        self._original = QPixmap(str(path))
        if self._original.isNull():
            self._label.setPixmap(QPixmap())
            self._label.setText("无法读取图片")
            return
        self._update_scaled()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self) -> None:
        if self._original.isNull():
            return
        size = self._scroll.viewport().size()
        if size.width() <= 0 or size.height() <= 0:
            return
        self._label.setPixmap(
            self._original.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )


class EditorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = load_ai_config()
        self.items = []
        self.cleaned_path = None
        self.output_path = None
        self._init_typesetter()
        self._build_ui()

    def _init_typesetter(self) -> None:
        main_dir = Path(__file__).resolve().parents[2] / "comic-translate-ai" / "main"
        if str(main_dir) not in sys.path:
            sys.path.insert(0, str(main_dir))
        from vertical_typesetter import VerticalTypesetter

        self.typesetter = VerticalTypesetter(self.config["font_map"], 16)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        left_group = QGroupBox("文本块")
        left = QVBoxLayout(left_group)
        self.block_list = QListWidget()
        self.block_list.currentRowChanged.connect(self._load_properties)
        left.addWidget(self.block_list, 1)
        self._apply_btn = QPushButton("应用修改")
        self._save_btn = QPushButton("保存图片")
        left.addWidget(self._apply_btn)
        left.addWidget(self._save_btn)
        root.addWidget(left_group, 0)

        right_group = QGroupBox("预览与属性")
        right = QVBoxLayout(right_group)
        self.preview = _Preview()
        right.addWidget(self.preview, 1)

        form = QFormLayout()
        self._style_combo = QComboBox()
        self._style_combo.addItems(["dialogue", "radiating", "handwriting", "serious"])
        self._size_spin = QSpinBox()
        self._size_spin.setRange(0, 200)
        self._size_spin.setSpecialValueText("自动")
        self._direction_combo = QComboBox()
        self._direction_combo.addItems(["竖排", "横排"])
        self._offset_x = QSpinBox()
        self._offset_x.setRange(-300, 300)
        self._offset_y = QSpinBox()
        self._offset_y.setRange(-300, 300)
        form.addRow("字体风格", self._style_combo)
        form.addRow("字号（0=自动）", self._size_spin)
        form.addRow("排版方向", self._direction_combo)
        form.addRow("X 偏移", self._offset_x)
        form.addRow("Y 偏移", self._offset_y)
        right.addLayout(form)
        root.addWidget(right_group, 1)

        self._apply_btn.clicked.connect(self.apply_changes)
        self._save_btn.clicked.connect(self.save_image)

    def load_page(self, output_path) -> None:
        self.output_path = Path(output_path)
        cleaned_dir = self.output_path.parent.parent / f"{self.output_path.parent.name}_cleaned"
        self.cleaned_path = cleaned_dir / f"{self.output_path.stem}_cleaned.png"
        layout_dir = self.output_path.parent.parent / f"{self.output_path.parent.name}_layout"
        layout_dir.mkdir(parents=True, exist_ok=True)
        layout_path = layout_dir / f"{self.output_path.stem}_layout.json"
        if not self.cleaned_path.exists() or not layout_path.exists():
            self.block_list.clear()
            self.items = []
            self.preview._label.setText("该图片没有可编辑布局数据")
            return
        with open(layout_path, "r", encoding="utf-8") as f:
            self.items = json.load(f)
        self.block_list.clear()
        for index, item in enumerate(self.items):
            text = str(item.get("text", ""))[:20]
            QListWidgetItem(f"{index + 1:02d}  {text}", self.block_list)
        self.preview.set_image(self.cleaned_path)
        self.render()
        if self.block_list.count() > 0:
            self.block_list.setCurrentRow(0)

    def _load_properties(self, row: int) -> None:
        if row < 0 or row >= len(self.items):
            return
        item = self.items[row]
        self._style_combo.setCurrentText(item.get("style", "dialogue"))
        size = int(item.get("font_size") or 0)
        self._size_spin.setValue(size)
        self._direction_combo.setCurrentIndex(0 if int(item.get("direction", 1)) == 1 else 1)
        self._offset_x.setValue(int(item.get("offset_x", 0)))
        self._offset_y.setValue(int(item.get("offset_y", 0)))

    def apply_changes(self) -> None:
        row = self.block_list.currentRow()
        if row < 0 or row >= len(self.items):
            return
        item = self.items[row]
        item["style"] = self._style_combo.currentText()
        item["font_size"] = self._size_spin.value()
        item["direction"] = 1 if self._direction_combo.currentIndex() == 0 else 0
        item["offset_x"] = self._offset_x.value()
        item["offset_y"] = self._offset_y.value()
        self.render()

    def render(self) -> None:
        if self.cleaned_path is None or not self.cleaned_path.exists():
            return
        from PIL import Image

        image = Image.open(self.cleaned_path).convert("RGB")
        for item in self.items:
            text = item.get("text", "")
            if not text:
                continue
            box = [int(v) for v in item["box"][:4]]
            box[0] += int(item.get("offset_x", 0))
            box[1] += int(item.get("offset_y", 0))
            box[2] += int(item.get("offset_x", 0))
            box[3] += int(item.get("offset_y", 0))
            size = int(item.get("font_size") or 0)
            image = self.typesetter.draw_text(
                image,
                box,
                text,
                item.get("style", "dialogue"),
                direction=int(item.get("direction", 1)),
                target_font_size=size if size > 0 else None,
                non_bubble=bool(item.get("non_bubble", False)),
            )
        self._rendered = image
        import tempfile

        temp_path = Path(tempfile.gettempdir()) / "comitrans_editor_preview.png"
        image.save(temp_path)
        self.preview.set_image(temp_path)

    def save_image(self) -> None:
        self.apply_changes()
        if self.output_path is None or not hasattr(self, "_rendered"):
            return
        self._rendered.save(self.output_path)
        layout_dir = self.output_path.parent.parent / f"{self.output_path.parent.name}_layout"
        layout_path = layout_dir / f"{self.output_path.stem}_layout.json"
        with open(layout_path, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)
