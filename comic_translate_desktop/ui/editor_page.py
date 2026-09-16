from __future__ import annotations
import json
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QSettings, QTimer
from PySide6.QtGui import QPixmap, QIcon, QShortcut, QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QGroupBox, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter, QComboBox, QSpinBox, QPlainTextEdit, QFileDialog, QMessageBox, QSizePolicy)
from ..config import load_ai_config, MAIN_DIR
from .preview import ImagePreview
from .theme import ui_font
from .manga_components import ChapterBanner, PanelHeading

STYLE_LABELS = {
    "dialogue": "普通对话",
    "bold_dialogue": "粗体对话",
    "radiating": "强调/放射",
    "handwriting": "手写注记",
    "thought": "内心独白",
    "whisper": "轻声/低语",
    "serious": "严肃/正式",
    "narration": "旁白",
    "sfx": "拟声/音效",
    "cute": "可爱/活泼",
    "next_preview": "下回预告",
    "title": "标题",
}


class EditorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = load_ai_config()
        self.items = []
        self.cleaned_path = self.output_path = None
        self._dirty = False
        self._loading = False
        self._rendered = None
        self._loaded_row = -1
        self._last_available_width = None
        self._row_dirty = False
        self._init_typesetter()
        self._build_ui()

    def _init_typesetter(self):
        if str(MAIN_DIR) not in sys.path:
            sys.path.insert(0, str(MAIN_DIR))
        from vertical_typesetter import VerticalTypesetter
        self.typesetter = VerticalTypesetter(self.config['font_map'], 16)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        self._chapter_banner = ChapterBanner('02', '嵌字精修', '检查原文 / 调整译文 / 完成排版')
        root.addWidget(self._chapter_banner)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._pages_toggle = QPushButton('页面')
        self._properties_toggle = QPushButton('编辑面板')
        for button in (self._pages_toggle, self._properties_toggle):
            button.setCheckable(True)
            button.setChecked(True)
            button.setProperty('compact', True)
            toolbar.addWidget(button)
        self._zoom = QComboBox()
        for name, value in [('适应页面', None), ('50%', .5), ('100%', 1.), ('150%', 1.5), ('200%', 2.)]:
            self._zoom.addItem(name, value)
        self._zoom.setToolTip('缩放预览；放大后可使用滚动条浏览')
        toolbar.addWidget(self._zoom)
        toolbar.addStretch()
        self._save_btn = QPushButton('保存图片')
        self._save_btn.setProperty('role', 'primary')
        toolbar.addWidget(self._save_btn)
        root.addLayout(toolbar)
        self._status = QLabel('导入带布局数据的已翻译图片，或从自动处理结果进入精修。')
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self._status)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(8)
        self.splitter.setChildrenCollapsible(False)
        self._pages_panel = QFrame()
        self._pages_panel.setObjectName('editorPanel')
        self._pages_panel.setMinimumWidth(150)
        left = QVBoxLayout(self._pages_panel)
        heading = PanelHeading('01', '页面', sidebar=True)
        left.addWidget(heading)
        add = QPushButton('＋ 导入已翻译图片')
        add.clicked.connect(self._import_pages)
        left.addWidget(add)
        self.page_list = QListWidget()
        self.page_list.setIconSize(QSize(56, 72))
        self.page_list.setWordWrap(True)
        self.page_list.setTextElideMode(Qt.ElideMiddle)
        self.page_list.currentItemChanged.connect(self._select_page)
        left.addWidget(self.page_list, 1)
        self.splitter.addWidget(self._pages_panel)
        self.preview = ImagePreview()
        self.preview.clear('选择一页，开始精修')
        self.preview._hint.setText('保留原图色彩 · 独立控制漫画输出字体')
        self.splitter.addWidget(self.preview)
        self._properties_panel = QScrollArea()
        self._properties_panel.setMinimumWidth(270)
        self._properties_panel.setWidgetResizable(True)
        content = QFrame()
        content.setObjectName('editorPanel')
        self._properties_panel.setWidget(content)
        props = QVBoxLayout(content)
        props.setContentsMargins(12, 12, 12, 12)
        heading = PanelHeading('02', '文本与排版', sidebar=True)
        props.addWidget(heading)
        self.block_list = QListWidget()
        self.block_list.setMinimumHeight(90)
        self.block_list.setMaximumHeight(132)
        self.block_list.currentRowChanged.connect(self._load_properties)
        props.addWidget(self.block_list)
        props.addWidget(QLabel('原文'))
        self._source_text = QPlainTextEdit()
        self._source_text.setReadOnly(True)
        self._source_text.setMaximumHeight(90)
        self._source_text.setFont(ui_font(japanese=True))
        props.addWidget(self._source_text)
        props.addWidget(QLabel('译文'))
        self._text_input = QPlainTextEdit()
        self._text_input.setMinimumHeight(80)
        self._text_input.setMaximumHeight(120)
        props.addWidget(self._text_input)
        group = QGroupBox('字体与排版')
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._style_combo = QComboBox()
        for style, label in STYLE_LABELS.items():
            self._style_combo.addItem(label, style)
        self._size_spin = QSpinBox()
        self._size_spin.setRange(0, 200)
        self._size_spin.setSpecialValueText('自动')
        self._direction_combo = QComboBox()
        for label, value in [('自动判断', -1), ('竖排', 1), ('横排', 0)]:
            self._direction_combo.addItem(label, value)
        form.addRow('字体风格', self._style_combo)
        form.addRow('字号', self._size_spin)
        form.addRow('排版方向', self._direction_combo)
        props.addWidget(group)
        group = QGroupBox('位置与区域')
        form = QFormLayout(group)
        self._offset_x, self._offset_y = QSpinBox(), QSpinBox()
        for spin in (self._offset_x, self._offset_y):
            spin.setRange(-300, 300)
        self._box_label = QLabel('选择文本块后显示坐标')
        self._box_label.setWordWrap(True)
        self._box_label.setProperty('muted', True)
        form.addRow('X 偏移', self._offset_x)
        form.addRow('Y 偏移', self._offset_y)
        form.addRow(self._box_label)
        props.addWidget(group)
        self._apply_btn = QPushButton('应用修改并预览')
        props.addWidget(self._apply_btn)
        props.addStretch()
        self.splitter.addWidget(self._properties_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([220, 820, 320])
        root.addWidget(self.splitter, 1)
        self._pages_toggle.toggled.connect(self._pages_panel.setVisible)
        self._properties_toggle.toggled.connect(self._properties_panel.setVisible)
        self._zoom.currentIndexChanged.connect(lambda: self.preview.set_zoom(self._zoom.currentData()))
        self._apply_btn.clicked.connect(self.apply_changes)
        self._save_btn.clicked.connect(self.save_image)
        self._text_input.textChanged.connect(self._mark_dirty)
        for combo in (self._style_combo, self._direction_combo):
            combo.currentIndexChanged.connect(self._mark_dirty)
        for spin in (self._size_spin, self._offset_x, self._offset_y):
            spin.valueChanged.connect(self._mark_dirty)
        self._save_shortcut = QShortcut(QKeySequence.Save, self)
        self._save_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self.save_image)
        self._set_editable(False)
        settings = QSettings()
        state = settings.value('ui/editorSplitter')
        if state is not None:
            self.splitter.restoreState(state)
        self._pages_toggle.setChecked(settings.value('ui/editorPages', True, type=bool))
        self._properties_toggle.setChecked(settings.value('ui/editorProperties', True, type=bool))
        self._zoom.setCurrentIndex(max(0, min(4, int(settings.value('ui/editorZoom', 0)))))

    def save_ui_state(self):
        settings = QSettings()
        settings.setValue('ui/editorSplitter', self.splitter.saveState())
        settings.setValue('ui/editorPages', self._pages_toggle.isChecked())
        settings.setValue('ui/editorProperties', self._properties_toggle.isChecked())
        settings.setValue('ui/editorZoom', self._zoom.currentIndex())

    def _set_editable(self, enabled):
        for widget in (self._text_input, self._style_combo, self._direction_combo, self._size_spin, self._offset_x, self._offset_y, self._apply_btn, self._save_btn):
            widget.setEnabled(enabled)
            widget.setToolTip('' if enabled else '请先导入含可编辑布局数据的图片并选择文本块')

    def _import_pages(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '导入已翻译图片', str(self.config.get('page_output_dir', '')), '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        for path in paths:
            self._add_page(Path(path).resolve())
        if paths:
            self.load_page(paths[0])

    def _add_page(self, path):
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            if item.data(Qt.UserRole) == str(path):
                return item
        item = QListWidgetItem(QIcon(QPixmap(str(path)).scaled(56, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)), path.name)
        item.setData(Qt.UserRole, str(path))
        item.setToolTip(str(path))
        item.setSizeHint(QSize(170, 100))
        self.page_list.addItem(item)
        return item

    def _select_page(self, current, previous):
        if current and not self.load_page(current.data(Qt.UserRole)):
            self.page_list.blockSignals(True)
            self.page_list.setCurrentItem(previous)
            self.page_list.blockSignals(False)

    def confirm_discard(self):
        if not self._dirty:
            return True
        choice = QMessageBox.question(self, '页面有未保存修改', '保存当前页面的修改后继续？', QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if choice == QMessageBox.Save:
            return self.save_image()
        if choice == QMessageBox.Discard:
            self._dirty = False
            return True
        return False

    def load_page(self, output_path):
        path = Path(output_path).resolve()
        if self.output_path == path:
            return True
        if not self.confirm_discard():
            return False
        self._loading = True
        self._loaded_row = -1
        self._row_dirty = False
        self.items = []
        self._rendered = None
        self.block_list.clear()
        self._source_text.clear()
        self._text_input.clear()
        self._set_editable(False)
        self.output_path = path
        self.cleaned_path = path.parent.parent / f'{path.parent.name}_cleaned' / f'{path.stem}_cleaned.png'
        self.layout_path = path.parent.parent / f'{path.parent.name}_layout' / f'{path.stem}_layout.json'
        page_item = self._add_page(path)
        self.page_list.blockSignals(True)
        self.page_list.setCurrentItem(page_item)
        self.page_list.blockSignals(False)
        self.preview.set_image(path)
        try:
            if not self.cleaned_path.is_file() or not self.layout_path.is_file():
                raise ValueError('缺少配套清理底图或布局 JSON，请在自动处理中重新生成。')
            data = json.loads(self.layout_path.read_text(encoding='utf-8'))
            if not isinstance(data, list) or any(not isinstance(item, dict) or len(item.get('box', [])) < 4 for item in data):
                raise ValueError('布局数据格式不正确。')
            self.items = data
            for index, item in enumerate(self.items):
                block = QListWidgetItem(f"{index + 1:02d}  {str(item.get('text', ''))[:28]}")
                block.setToolTip(str(item.get('text', '')))
                self.block_list.addItem(block)
            self._status.setText(f'{path.name} · {len(self.items)} 个文本块')
            if self.items:
                self.block_list.setCurrentRow(0)
            else:
                self._status.setText(f'{path.name} · 没有可编辑文本块')
        except (OSError, ValueError, TypeError) as exc:
            self._status.setText(f'无法精修：{exc}')
            page_item.setText(f'⊠ 无布局数据\n{path.name}')
        finally:
            self._loading = False
        self._dirty = False
        return True

    def _mark_dirty(self):
        if self._loading or not self.items:
            return
        self._dirty = True
        self._row_dirty = True
        self._status.setText(f'● 未保存修改 · {self.output_path.name}')
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            if item.data(Qt.UserRole) == str(self.output_path):
                item.setText(f'● 未保存\n{self.output_path.name}')

    def _store_properties(self):
        if not self._row_dirty or self._loaded_row < 0 or self._loaded_row >= len(self.items):
            return
        item = self.items[self._loaded_row]
        item.update(text=self._text_input.toPlainText(), style=self._style_combo.currentData(), font_size=self._size_spin.value(), direction=int(self._direction_combo.currentData()), offset_x=self._offset_x.value(), offset_y=self._offset_y.value())
        self.block_list.item(self._loaded_row).setText(f"{self._loaded_row + 1:02d}  {item['text'][:28]}")
        self._row_dirty = False

    def _load_properties(self, row):
        if row < 0 or row >= len(self.items):
            self._loaded_row = -1
            self._set_editable(False)
            return
        if not self._loading:
            self._store_properties()
        self._loading = True
        self._loaded_row = row
        item = self.items[row]
        self._source_text.setFont(ui_font(japanese=item.get('source_language', 'ja') == 'ja'))
        self._source_text.setPlainText(str(item.get('source_text', '')))
        self._text_input.setPlainText(str(item.get('text', '')))
        style = item.get('style', 'dialogue')
        index = self._style_combo.findData(style)
        if index < 0:
            self._style_combo.addItem(style, style)
            index = self._style_combo.count() - 1
        self._style_combo.setCurrentIndex(index)
        self._size_spin.setValue(int(item.get('font_size') or 0))
        self._direction_combo.setCurrentIndex(max(0, self._direction_combo.findData(int(item.get('direction', -1)))))
        self._offset_x.setValue(int(item.get('offset_x', 0)))
        self._offset_y.setValue(int(item.get('offset_y', 0)))
        self._box_label.setText('区域：' + ', '.join(map(str, item['box'][:4])))
        self._set_editable(True)
        self._loading = False

    def apply_changes(self):
        if not self.items:
            return False
        self._store_properties()
        try:
            self.render()
        except Exception as exc:
            self._status.setText(f'预览失败：{exc}')
            return False
        return True

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
        from PIL.ImageQt import ImageQt
        self.preview.set_pixmap(QPixmap.fromImage(ImageQt(image)))

    def save_image(self):
        if self.output_path is None or not self.items:
            return False
        if not self._dirty:
            return True
        if not self.apply_changes() or self._rendered is None:
            return False
        try:
            self._rendered.save(self.output_path)
            self.layout_path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            self._status.setText(f'保存失败：{exc}。修改仍保留，请检查输出目录后重试。')
            return False
        self._dirty = False
        self._status.setText(f'✓ 已保存图片与布局 · {self.output_path.name}')
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            if item.data(Qt.UserRole) == str(self.output_path):
                item.setText(self.output_path.name)
        return True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._adapt_width()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._adapt_width)

    def _adapt_width(self):
        if not self.isVisible():
            return
        previous = self._last_available_width
        self._last_available_width = self.width()
        self._chapter_banner.set_compact(self.height() < 700)
        if self.width() < 1180 and (previous is None or previous >= 1180):
            self._pages_toggle.setChecked(False)
        if self.width() < 900 and (previous is None or previous >= 900):
            self._properties_toggle.setChecked(False)
