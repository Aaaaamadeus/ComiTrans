from __future__ import annotations
from ..i18n import tr
import json
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QSettings, QTimer
from PySide6.QtGui import QPixmap, QIcon, QShortcut, QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QGroupBox, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter, QComboBox, QSpinBox, QPlainTextEdit, QFileDialog, QMessageBox, QSizePolicy, QTabWidget, QCheckBox)
from ..config import load_ai_config, MAIN_DIR
from ..font_library import available_fonts, font_description, font_display_name, font_reference, inspect_font, resolve_font_reference
from comic_translate_core.watermark import apply_watermark
from comic_translate_core.layout_options import VERTICAL_ALIGNMENTS
from .preview import ImagePreview
from .theme import ui_font
from .manga_components import PanelHeading
from .searchable_combo import SearchableFontCombo

STYLE_LABELS = {
    "dialogue": "普通对话",
    "bold_dialogue": "粗体对话",
    "radiating": "强调/放射",
    "handwriting": "手写注记",
    "seto": "濑户字体",
    "tegaki_851": "851手写杂书体",
    "thought": "内心独白",
    "whisper": "轻声/低语",
    "serious": "严肃/正式",
    "narration": "旁白",
    "sfx": "拟声/音效",
    "lxgw_marker": "霞鹜漫黑",
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
        self._font_choice_dirty = False
        self._cleaned_image = None
        self._preview_dirty = False
        self._layer_cache = {}
        self._font_typesetters = {}
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(40)
        self._preview_timer.timeout.connect(self.apply_changes)
        self._init_typesetter()
        self._build_ui()

    def _init_typesetter(self):
        self._layer_cache.clear()
        self._font_typesetters.clear()
        if str(MAIN_DIR) not in sys.path:
            sys.path.insert(0, str(MAIN_DIR))
        from vertical_typesetter import VerticalTypesetter
        self.typesetter = VerticalTypesetter(self.config['font_map'], 16,
                                             fallback_fonts=self.config.get('font_fallbacks'))

    def _typesetter_for_item(self, item):
        reference = item.get('font_reference')
        if not reference:
            return self.typesetter
        try:
            path = str(inspect_font(resolve_font_reference(reference)).path)
        except Exception:
            return self.typesetter
        if path not in self._font_typesetters:
            from vertical_typesetter import VerticalTypesetter
            # Keep the chosen face for supported glyphs; only missing glyphs fall back.
            self._font_typesetters[path] = VerticalTypesetter(
                {style: path for style in self.config['font_map']}, 16,
                fallback_fonts=self.config.get('font_fallbacks'))
            if len(self._font_typesetters) > 32:
                self._font_typesetters.pop(next(iter(self._font_typesetters)))
        return self._font_typesetters[path]

    def _refresh_font_choices(self):
        self._style_combo.blockSignals(True)
        try:
            self._style_combo.clear()
            self._style_combo.addItem(tr('跟随翻译默认字体'), '')
            for style, label in STYLE_LABELS.items():
                self._style_combo.addItem(tr(label), style)
                path = self.config.get('style_font_map', self.config['font_map']).get(style)
                self._style_combo.setItemData(self._style_combo.count() - 1, path, Qt.ToolTipRole)
            for font in available_fonts(self.config):
                reference = font_reference(font.path)
                label = font_display_name(font) + (tr('（本地）') if reference.startswith('user_fonts/') else '')
                self._style_combo.addItem(tr(label), reference)
                self._style_combo.setItemData(self._style_combo.count() - 1, font_description(font), Qt.ToolTipRole)
            self._select_font_choice(self.items[self._loaded_row] if 0 <= self._loaded_row < len(self.items) else {})
        finally:
            self._style_combo.blockSignals(False)

    def _select_font_choice(self, item):
        reference = item.get('font_reference', '')
        style = item.get('style', 'dialogue')
        style_path = self.config.get('style_font_map', self.config['font_map']).get(style)
        missing = bool(reference) and not self._font_reference_available(reference)
        matching_style = reference and not missing and style_path and reference == font_reference(style_path)
        index = self._style_combo.findData(style if matching_style else reference)
        if index < 0:
            self._style_combo.addItem(tr('不可用：{_0}', _0=Path(reference).name), reference)
            index = self._style_combo.count() - 1
            self._style_combo.model().item(index).setEnabled(False)
        self._style_combo.setCurrentIndex(index)
        self._style_combo.setToolTip(tr('所选字体不可用，当前回退到翻译默认字体；请选择其它字体。') if missing else tr('仅修改当前文本块；手动选择优先于翻译默认字体，缺字自动回退。'))
        self._update_font_name()

    def _update_font_name(self):
        choice = self._style_combo.currentData()
        item = self.items[self._loaded_row] if 0 <= self._loaded_row < len(self.items) else {}
        try:
            if choice in STYLE_LABELS:
                path = self.config.get('style_font_map', self.config['font_map'])[choice]
            elif choice:
                path = resolve_font_reference(choice)
            else:
                path = self.config['font_map'][item.get('style', 'dialogue')]
            font = inspect_font(path)
            name, description = font_display_name(font), font_description(font)
        except Exception:
            name = self._style_combo.itemText(self._style_combo.currentIndex())
            description = self._style_combo.toolTip()
        self._font_name_label.setText(tr(tr('当前字体：') + name))
        self._font_name_label.setToolTip(tr(description))
        self._style_combo.lineEdit().setToolTip(tr(description))
        self._style_combo.lineEdit().setCursorPosition(0)

    @staticmethod
    def _font_reference_available(reference):
        try:
            inspect_font(resolve_font_reference(reference))
            return True
        except Exception:
            return False

    def _font_selection_changed(self):
        self._update_font_name()
        if self._loading or self._loaded_row < 0:
            return
        self._font_choice_dirty = True
        self._style_combo.setToolTip(tr('仅修改当前文本块；手动选择优先于翻译默认字体，缺字自动回退。'))
        self._schedule_preview()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QFrame()
        body.setObjectName('pageBody')
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        outer.addWidget(body, 1)
        toolbar_frame = QFrame()
        toolbar_frame.setObjectName('editorToolbar')
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(0, 0, 0, 10)
        toolbar.setSpacing(8)
        self._pages_toggle = QPushButton(tr('页面'))
        self._properties_toggle = QPushButton(tr('编辑面板'))
        for button in (self._pages_toggle, self._properties_toggle):
            button.setCheckable(True)
            button.setChecked(True)
            button.setProperty('compact', True)
            button.setProperty('role', 'utility')
            toolbar.addWidget(button)
        self._focus_btn = QPushButton(tr('专注画布'))
        self._focus_btn.setCheckable(True)
        self._focus_btn.setProperty('role', 'utility')
        self._focus_btn.setProperty('compact', True)
        self._focus_btn.setToolTip(tr('收起侧栏与辅助信息，专注查看作品 · Ctrl+Shift+F'))
        toolbar.addWidget(self._focus_btn)
        self._zoom = QComboBox()
        for name, value in [(tr('适应页面'), None), ('50%', .5), ('100%', 1.), ('150%', 1.5), ('200%', 2.)]:
            self._zoom.addItem(tr(name), value)
        self._zoom.setToolTip(tr('缩放预览；放大后可使用滚动条浏览'))
        toolbar.addWidget(self._zoom)
        toolbar.addStretch()
        self._save_btn = QPushButton(tr('保存图片'))
        self._save_btn.setProperty('role', 'primary')
        toolbar.addWidget(self._save_btn)
        root.addWidget(toolbar_frame)
        self._status = QLabel(tr('导入带布局数据的已翻译图片，或从自动处理结果进入精修。'))
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._status.setObjectName('editorStatus')
        self._status.setMaximumHeight(56)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(8)
        self.splitter.setChildrenCollapsible(False)
        self._pages_panel = QFrame()
        self._pages_panel.setObjectName('editorPanel')
        self._pages_panel.setMinimumWidth(180)
        self._pages_panel.setMaximumWidth(320)
        left = QVBoxLayout(self._pages_panel)
        left.setContentsMargins(8, 0, 12, 0)
        left.setSpacing(12)
        heading = PanelHeading('01', tr('页面'), sidebar=True)
        left.addWidget(heading)
        add = QPushButton(tr('＋ 导入已翻译图片'))
        add.clicked.connect(self._import_pages)
        left.addWidget(add)
        self.page_list = QListWidget()
        self.page_list.setIconSize(QSize(56, 72))
        self.page_list.setWordWrap(True)
        self.page_list.setTextElideMode(Qt.ElideMiddle)
        self.page_list.currentItemChanged.connect(self._select_page)
        left.addWidget(self.page_list, 1)
        self.splitter.addWidget(self._pages_panel)
        canvas = QFrame()
        canvas.setObjectName('canvasPanel')
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(8)
        self._canvas_heading = PanelHeading('02', tr('页面预览'))
        canvas_layout.addWidget(self._canvas_heading)
        self.preview = ImagePreview(import_action=True, illustration='studio-editor-v1.png')
        self.preview.clear(tr('选择一页，开始精修'))
        self.preview._hint.setText(tr('从自动处理结果进入，或导入已翻译图片'))
        self.preview.import_button.setText(tr('导入已翻译图片'))
        self.preview.import_requested.connect(self._import_pages)
        self.preview.region_edited.connect(self._resize_region_from_canvas)
        self.preview.region_edit_finished.connect(self.apply_changes)
        canvas_layout.addWidget(self.preview, 1)
        self.splitter.addWidget(canvas)
        self._properties_panel = QFrame()
        self._properties_panel.setObjectName('editorInspector')
        self._properties_panel.setMinimumWidth(280)
        self._properties_panel.setMaximumWidth(420)
        inspector_layout = QVBoxLayout(self._properties_panel)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(0)
        self._properties_scroll = QScrollArea()
        self._properties_scroll.setWidgetResizable(True)
        self._properties_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QFrame()
        content.setObjectName('editorPanel')
        self._properties_scroll.setWidget(content)
        inspector_layout.addWidget(self._properties_scroll, 1)
        props = QVBoxLayout(content)
        props.setContentsMargins(12, 12, 12, 12)
        heading = PanelHeading('03', tr('文本与排版'), sidebar=True)
        props.addWidget(heading)
        self.block_list = QListWidget()
        self.block_list.setFixedHeight(96)
        self.block_list.currentRowChanged.connect(self._load_properties)
        props.addWidget(self.block_list)
        self._inspector_tabs = QTabWidget()
        self._inspector_tabs.setDocumentMode(True)
        props.addWidget(self._inspector_tabs, 1)
        text_panel = QWidget()
        text_props = QVBoxLayout(text_panel)
        text_props.setContentsMargins(0, 8, 0, 0)
        text_props.setSpacing(8)
        self._inspector_tabs.addTab(text_panel, tr('译文编辑'))
        layout_panel = QWidget()
        layout_props = QVBoxLayout(layout_panel)
        layout_props.setContentsMargins(0, 8, 0, 0)
        layout_props.setSpacing(12)
        self._inspector_tabs.addTab(layout_panel, tr('排版与位置'))
        props = text_props
        source_label = QLabel(tr('原文'))
        source_label.setObjectName('fieldCaption')
        props.addWidget(source_label)
        self._source_text = QPlainTextEdit()
        self._source_text.setReadOnly(True)
        self._source_text.setFixedHeight(76)
        self._source_text.setFont(ui_font(japanese=True))
        props.addWidget(self._source_text)
        target_label = QLabel(tr('译文'))
        target_label.setObjectName('fieldCaption')
        break_row = QHBoxLayout()
        break_row.addWidget(target_label, 1)
        self._line_break_btn = QPushButton(tr('插入换行'))
        self._line_break_btn.setProperty('compact', True)
        self._line_break_btn.setToolTip(tr('在光标处插入换行，与 Enter 相同'))
        self._line_break_btn.clicked.connect(self._insert_line_break)
        break_row.addWidget(self._line_break_btn)
        props.addLayout(break_row)
        break_hint = QLabel(tr('Enter 换行 · 竖排时换到左列'))
        break_hint.setWordWrap(True)
        break_hint.setProperty('muted', True)
        props.addWidget(break_hint)
        self._text_input = QPlainTextEdit()
        self._text_input.setMinimumHeight(96)
        self._text_input.setMaximumHeight(180)
        self._text_input.setAccessibleName(tr('译文与手动换行'))
        self._text_input.setPlaceholderText(tr('输入译文，按 Enter 手动换行'))
        self._text_input.setToolTip(tr('Enter 插入硬换行：横排换到下一行，竖排换到左侧下一列；连续回车保留空行或空列。'))
        props.addWidget(self._text_input)
        props.addStretch(1)
        props = layout_props
        group = QGroupBox(tr('字体与排版'))
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._style_combo = SearchableFontCombo()
        self._style_combo.setAccessibleName(tr('当前文本块字体'))
        self._style_combo.setFont(ui_font(13))
        self._font_name_label = QLabel()
        self._font_name_label.setObjectName('fontChoiceName')
        self._font_name_label.setAccessibleName(tr('当前字体完整名称'))
        self._font_name_label.setWordWrap(True)
        self._font_name_label.setTextFormat(Qt.PlainText)
        self._font_name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._font_name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._refresh_font_choices()
        self._size_spin = QSpinBox()
        self._size_spin.setRange(0, 200)
        self._size_spin.setSpecialValueText(tr('自动'))
        self._size_spin.setToolTip(tr('手动字号按实际像素绘制；0 为自动适配蒙版'))
        self._direction_combo = QComboBox()
        for label, value in [(tr('自动判断'), -1), (tr('竖排'), 1), (tr('横排'), 0)]:
            self._direction_combo.addItem(tr(label), value)
        self._vertical_alignment_combo = QComboBox()
        self._vertical_alignment_combo.setAccessibleName(tr('竖排各列对齐方式'))
        for value, label in VERTICAL_ALIGNMENTS:
            self._vertical_alignment_combo.addItem(tr(label), value)
        self._vertical_alignment_combo.setCurrentIndex(1)
        self._vertical_alignment_combo.setToolTip(tr('竖排各列按最长列的顶部或底部对齐，整组文字仍在蒙版中居中。横排时不生效。'))
        self._effect_combo = QComboBox()
        self._effect_combo.setAccessibleName(tr('文字描边效果'))
        for label, value in [(tr('默认效果'), 'auto'), (tr('黑字白边'), 'outlined'), (tr('白字黑边（空心）'), 'hollow')]:
            self._effect_combo.addItem(tr(label), value)
        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        font_row.addWidget(QLabel(tr('字体')))
        font_row.addStretch(1)
        self._font_library_btn = QPushButton(tr('字体库'))
        self._font_library_btn.setProperty('compact', True)
        self._font_library_btn.setProperty('role', 'quiet')
        self._font_library_btn.clicked.connect(self._open_font_library)
        font_row.addWidget(self._font_library_btn)
        form.addRow(tr(font_row))
        form.addRow(tr(self._style_combo))
        form.addRow(tr(self._font_name_label))
        form.addRow(tr('字号'), self._size_spin)
        form.addRow(tr('排版方向'), self._direction_combo)
        form.addRow(tr('竖排列对齐'), self._vertical_alignment_combo)
        form.addRow(tr('文字效果'), self._effect_combo)
        props.addWidget(group)
        group = QGroupBox(tr('位置与蒙版'))
        form = QFormLayout(group)
        self._offset_x, self._offset_y = QSpinBox(), QSpinBox()
        for spin in (self._offset_x, self._offset_y):
            spin.setRange(-100000, 100000)
            spin.setSuffix(' px')
        self._mask_width, self._mask_height = QSpinBox(), QSpinBox()
        for spin in (self._mask_width, self._mask_height):
            spin.setRange(1, 100000)
            spin.setSuffix(' px')
            spin.setToolTip(tr('调整译文排版蒙版，以当前中心向两侧改变大小'))
        self._show_mask = QCheckBox(tr('显示蒙版范围'))
        self._show_mask.setChecked(True)
        self._show_mask.setToolTip(tr('画布辅助线仅用于精修，不写入导出图片'))
        self._box_label = QLabel(tr('选择文本块后显示坐标'))
        self._box_label.setWordWrap(True)
        self._box_label.setProperty('muted', True)
        form.addRow(tr('X 偏移'), self._offset_x)
        form.addRow(tr('Y 偏移'), self._offset_y)
        form.addRow(tr('蒙版宽度'), self._mask_width)
        form.addRow(tr('蒙版高度'), self._mask_height)
        form.addRow(tr(self._show_mask))
        form.addRow(tr(self._box_label))
        drag_hint = QLabel(tr('拖动蒙版边角调整大小，框内拖动位置'))
        drag_hint.setWordWrap(True)
        drag_hint.setProperty('muted', True)
        form.addRow(tr(drag_hint))
        props.addWidget(group)
        self._apply_btn = QPushButton(tr('刷新预览'))
        props.addStretch()
        inspector_actions = QFrame()
        inspector_actions.setObjectName('inspectorActions')
        actions_layout = QVBoxLayout(inspector_actions)
        actions_layout.setContentsMargins(12, 10, 12, 10)
        actions_layout.addWidget(self._apply_btn)
        hint = QLabel(tr('修改实时预览 · Ctrl+S 保存图片'))
        hint.setProperty('muted', True)
        actions_layout.addWidget(hint)
        inspector_layout.addWidget(inspector_actions)
        self.splitter.addWidget(self._properties_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([220, 820, 320])
        root.addWidget(self.splitter, 1)
        root.addWidget(self._status)
        self._pages_toggle.toggled.connect(self._pages_panel.setVisible)
        self._properties_toggle.toggled.connect(self._properties_panel.setVisible)
        self._focus_btn.toggled.connect(self._toggle_canvas_focus)
        self._zoom.currentIndexChanged.connect(lambda: self.preview.set_zoom(self._zoom.currentData()))
        self._apply_btn.clicked.connect(self.apply_changes)
        self._save_btn.clicked.connect(self.save_image)
        self._text_input.textChanged.connect(self._schedule_preview)
        self._style_combo.currentIndexChanged.connect(self._font_selection_changed)
        self._direction_combo.currentIndexChanged.connect(self._schedule_preview)
        self._direction_combo.currentIndexChanged.connect(self._update_vertical_alignment_enabled)
        self._vertical_alignment_combo.currentIndexChanged.connect(self._schedule_preview)
        self._effect_combo.currentIndexChanged.connect(self._schedule_preview)
        for spin in self._layout_spins():
            spin.valueChanged.connect(self._schedule_preview)
        self._show_mask.toggled.connect(self._update_region_guide)
        self._save_shortcut = QShortcut(QKeySequence.Save, self)
        self._save_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self.save_image)
        self._focus_shortcut = QShortcut(QKeySequence('Ctrl+Shift+F'), self)
        self._focus_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._focus_shortcut.activated.connect(self._focus_btn.toggle)
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
        settings.setValue('ui/editorSplitter', self._focus_splitter_state if self._focus_btn.isChecked() else self.splitter.saveState())
        panels = self._focus_panels if self._focus_btn.isChecked() else (self._pages_toggle.isChecked(), self._properties_toggle.isChecked())
        settings.setValue('ui/editorPages', panels[0])
        settings.setValue('ui/editorProperties', panels[1])
        settings.setValue('ui/editorZoom', self._zoom.currentIndex())

    def _toggle_canvas_focus(self, focused):
        if focused:
            self._focus_splitter_state = self.splitter.saveState()
            self._focus_panels = (self._pages_toggle.isChecked(), self._properties_toggle.isChecked())
            self._pages_toggle.setChecked(False)
            self._properties_toggle.setChecked(False)
        else:
            self._pages_toggle.setChecked(self._focus_panels[0])
            self._properties_toggle.setChecked(self._focus_panels[1])
            self.splitter.restoreState(self._focus_splitter_state)
        for widget in (self._canvas_heading, self._status, self._pages_toggle, self._properties_toggle):
            widget.setVisible(not focused)
        self._focus_btn.setText(tr('退出专注') if focused else tr('专注画布'))

    def _set_editable(self, enabled):
        for widget in (self._text_input, self._line_break_btn, self._style_combo, self._font_library_btn, self._direction_combo, self._vertical_alignment_combo, self._effect_combo, *self._layout_spins(), self._show_mask, self._apply_btn, self._save_btn):
            widget.setEnabled(enabled)
        self._update_vertical_alignment_enabled()

    def _update_vertical_alignment_enabled(self):
        self._vertical_alignment_combo.setEnabled(self._text_input.isEnabled()
                                                 and self._direction_combo.currentData() != 0)

    def _open_font_library(self):
        from .font_library_dialog import FontLibraryDialog
        try:
            self._store_properties()
            dialog = FontLibraryDialog(self.config, self)
            if dialog.exec() and dialog.reference:
                self._refresh_font_choices()
                self._style_combo.setCurrentIndex(self._style_combo.findData(dialog.reference))
        except Exception as exc:
            self._status.setText(tr('字体库未能打开：{_0}', _0=exc))

    def _import_pages(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr('导入已翻译图片'), str(self.config.get('page_output_dir', '')), tr('图片 (*.png *.jpg *.jpeg *.webp *.bmp)'))
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
        choice = QMessageBox.question(self, tr('页面有未保存修改'), tr('保存当前页面的修改后继续？'), QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
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
        self._preview_timer.stop()
        self._loading = True
        self._loaded_row = -1
        self._row_dirty = False
        self._font_choice_dirty = False
        self.items = []
        self._rendered = None
        self._cleaned_image = None
        self._preview_dirty = False
        self.preview.set_region(None)
        self._layer_cache.clear()
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
                raise ValueError(tr('缺少配套清理底图或布局 JSON，请在自动处理中重新生成。'))
            data = json.loads(self.layout_path.read_text(encoding='utf-8'))
            if not isinstance(data, list) or any(not isinstance(item, dict) or len(item.get('box', [])) < 4 for item in data):
                raise ValueError(tr('布局数据格式不正确。'))
            self.items = data
            from PIL import Image
            with Image.open(self.cleaned_path) as cleaned:
                self._cleaned_image = cleaned.convert('RGB')
            self._prepare_regions()
            for index, item in enumerate(self.items):
                block = QListWidgetItem(f"{index + 1:02d}  {str(item.get('text', ''))[:28]}")
                block.setToolTip(str(item.get('text', '')))
                self.block_list.addItem(tr(block))
            self._status.setText(tr('{_0} · {_1} 个文本块', _0=path.name, _1=len(self.items)))
            if self.items:
                self.block_list.setCurrentRow(0)
            else:
                self._status.setText(tr('{_0} · 没有可编辑文本块', _0=path.name))
        except (OSError, ValueError, TypeError) as exc:
            self._status.setText(tr('无法精修：{_0}', _0=exc))
            page_item.setText(tr('⊠ 无布局数据\n{_0}', _0=path.name))
        finally:
            self._loading = False
        self._dirty = False
        return True

    def _mark_dirty(self):
        if self._loading or not self.items:
            return
        self._dirty = True
        self._row_dirty = True
        self._preview_dirty = True
        self._status.setText(tr('● 未保存修改 · {_0}', _0=self.output_path.name))
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            if item.data(Qt.UserRole) == str(self.output_path):
                item.setText(tr('● 未保存\n{_0}', _0=self.output_path.name))

    def _insert_line_break(self):
        if self._loaded_row < 0:
            return
        self._text_input.insertPlainText('\n')
        self._text_input.setFocus()

    def _layout_spins(self):
        return (self._size_spin, self._offset_x, self._offset_y, self._mask_width, self._mask_height)

    def _schedule_preview(self):
        if self._loading or self._loaded_row < 0:
            return
        self._mark_dirty()
        self._update_region_guide()
        if not self._preview_timer.isActive():
            self._preview_timer.start()

    def _prepare_regions(self):
        """Recover old layouts once; new outputs already contain the actual region."""
        scratch = None
        for item in self.items:
            if item.get('mask_box'):
                continue
            if scratch is None:
                scratch = self._cleaned_image.copy()
            typesetter = self._typesetter_for_item(item)
            typesetter.draw_text(scratch, item['box'], str(item.get('text', '')),
                                 item.get('style', 'dialogue'), direction=int(item.get('direction', 1)),
                                 target_font_size=item.get('font_size'), non_bubble=bool(item.get('non_bubble', False)))
            item['mask_box'] = typesetter.last_layout_box or list(item['box'][:4])
            if not item.get('rendered_font_size'):
                item['rendered_font_size'] = typesetter.last_font_size

    @staticmethod
    def _mask_box(item, *, width=None, height=None, offset_x=None, offset_y=None):
        x1, y1, x2, y2 = item.get('mask_box') or item['box'][:4]
        width = max(1, int(width if width is not None else item.get('mask_width', round(x2 - x1))))
        height = max(1, int(height if height is not None else item.get('mask_height', round(y2 - y1))))
        center_x = (x1 + x2) / 2 + (item.get('offset_x', 0) if offset_x is None else offset_x)
        center_y = (y1 + y2) / 2 + (item.get('offset_y', 0) if offset_y is None else offset_y)
        left, top = round(center_x) - width // 2, round(center_y) - height // 2
        return [left, top, left + width, top + height]

    def _update_region_guide(self):
        box = None
        if 0 <= self._loaded_row < len(self.items):
            box = self._mask_box(self.items[self._loaded_row], width=self._mask_width.value(),
                                 height=self._mask_height.value(), offset_x=self._offset_x.value(),
                                 offset_y=self._offset_y.value())
            self._box_label.setText(tr(tr('蒙版区域：') + ', '.join(map(str, box))))
        self.preview.set_region(box if self._show_mask.isChecked() else None, editable=box is not None)

    def _resize_region_from_canvas(self, box):
        if self._loading or not 0 <= self._loaded_row < len(self.items):
            return
        item = self.items[self._loaded_row]
        base = item.get('mask_box') or item['box'][:4]
        x1, y1, x2, y2 = map(int, box)
        width, height = x2 - x1, y2 - y1
        self._loading = True
        try:
            self._mask_width.setValue(width)
            self._mask_height.setValue(height)
            self._offset_x.setValue(x1 + width // 2 - round((base[0] + base[2]) / 2))
            self._offset_y.setValue(y1 + height // 2 - round((base[1] + base[3]) / 2))
        finally:
            self._loading = False
        self._schedule_preview()

    def _store_properties(self):
        if not self._row_dirty or self._loaded_row < 0 or self._loaded_row >= len(self.items):
            return
        item = self.items[self._loaded_row]
        if self._font_choice_dirty:
            choice = self._style_combo.currentData()
            if choice in STYLE_LABELS:
                item['style'] = choice
                path = self.config.get('style_font_map', self.config['font_map'])[choice]
                item['font_reference'] = font_reference(path)
            elif choice:
                item['font_reference'] = choice
            else:
                item.pop('font_reference', None)
            self._font_choice_dirty = False
        item.update(text=self._text_input.toPlainText(), font_size=self._size_spin.value(), direction=int(self._direction_combo.currentData()), offset_x=self._offset_x.value(), offset_y=self._offset_y.value(), mask_width=self._mask_width.value(), mask_height=self._mask_height.value(), manual_layout=True)
        item['text_effect'] = self._effect_combo.currentData()
        item['vertical_alignment'] = self._vertical_alignment_combo.currentData()
        summary = item['text'].replace('\n', ' ↵ ')[:28]
        self.block_list.item(self._loaded_row).setText(f'{self._loaded_row + 1:02d}  {summary}')
        self._row_dirty = False

    def _load_properties(self, row):
        self.preview.cancel_region_drag()
        if row < 0 or row >= len(self.items):
            self._loaded_row = -1
            self._font_choice_dirty = False
            self._set_editable(False)
            self.preview.set_region(None)
            return
        if not self._loading:
            self._store_properties()
        self._loading = True
        self._loaded_row = row
        item = self.items[row]
        self._source_text.setFont(ui_font(japanese=item.get('source_language', 'ja') == 'ja'))
        self._source_text.setPlainText(str(item.get('source_text', '')))
        self._text_input.setPlainText(str(item.get('text', '')))
        self._select_font_choice(item)
        self._font_choice_dirty = False
        size = item.get('font_size') if item.get('manual_layout') else item.get('rendered_font_size') or item.get('font_size')
        self._size_spin.setValue(int(size or 0))
        self._direction_combo.setCurrentIndex(max(0, self._direction_combo.findData(int(item.get('direction', -1)))))
        self._effect_combo.setCurrentIndex(max(0, self._effect_combo.findData(item.get('text_effect', 'auto'))))
        alignment_index = self._vertical_alignment_combo.findData(item.get('vertical_alignment', 'center'))
        self._vertical_alignment_combo.setCurrentIndex(alignment_index if alignment_index >= 0 else 1)
        self._offset_x.setValue(int(item.get('offset_x', 0)))
        self._offset_y.setValue(int(item.get('offset_y', 0)))
        box = self._mask_box(item)
        self._mask_width.setValue(box[2] - box[0])
        self._mask_height.setValue(box[3] - box[1])
        self._update_region_guide()
        self._set_editable(True)
        self._loading = False
        self._row_dirty = False

    def apply_changes(self):
        if not self.items:
            return False
        self._preview_timer.stop()
        self._store_properties()
        if not self._preview_dirty and self._rendered is not None:
            return True
        try:
            self.render()
        except Exception as exc:
            self._status.setText(tr('预览失败：{_0}', _0=exc))
            return False
        self._preview_dirty = False
        return True

    def set_watermark_enabled(self, enabled: bool) -> None:
        if bool(self.config.get('watermark_enabled', True)) == enabled:
            return
        self.config['watermark_enabled'] = enabled
        if self.items and self.cleaned_path is not None and self.cleaned_path.is_file():
            self._mark_dirty()
            self.apply_changes()

    def set_translation_fonts(self, settings: dict) -> None:
        changed = any(self.config.get(key) != settings.get(key) for key in
                      ('font_map', 'style_font_map', 'font_fallbacks'))
        self._store_properties()
        for key in ('font_map', 'style_font_map', 'font_fallbacks', 'translation_font', 'translation_font_active'):
            if key in settings:
                self.config[key] = settings[key]
        self._refresh_font_choices()
        if not changed:
            return
        self._init_typesetter()
        if self.items:
            self._mark_dirty()
            self.apply_changes()

    def render(self) -> None:
        if self._cleaned_image is None:
            raise ValueError(tr('缺少配套清理底图，请重新导入页面'))
        image = self._cleaned_image.copy()
        for index, item in enumerate(self.items):
            text = item.get("text", "")
            if not text:
                self._layer_cache.pop(index, None)
                continue
            box = self._mask_box(item)
            size = item.get('font_size') if item.get('manual_layout') else item.get('rendered_font_size') or item.get('font_size')
            size = int(size or 0)
            typesetter = self._typesetter_for_item(item)
            key = (tuple(box), text, item.get('style', 'dialogue'), int(item.get('direction', 1)),
                   size, bool(item.get('non_bubble', False)),
                   typesetter.font_map.get(item.get('style', 'dialogue')), item.get('text_effect', 'auto'),
                   item.get('vertical_alignment', 'center'))
            cached = self._layer_cache.get(index)
            if cached is not None and cached[0] == key:
                _, surface, left, top, actual_size = cached
                image.paste(surface, (left, top), surface)
                item['rendered_font_size'] = actual_size
                continue
            image = typesetter.draw_text(
                image,
                box,
                text,
                item.get("style", "dialogue"),
                direction=int(item.get("direction", 1)),
                target_font_size=size if size > 0 else None,
                non_bubble=bool(item.get("non_bubble", False)),
                manual_layout=True,
                text_effect=item.get('text_effect', 'auto'),
                vertical_alignment=item.get('vertical_alignment', 'center'),
            )
            item['rendered_font_size'] = typesetter.last_font_size
            layer = typesetter.last_render_layer
            if layer is not None:
                surface, left, top = layer
                self._layer_cache.pop(index, None)
                self._layer_cache[index] = (key, surface, left, top, typesetter.last_font_size)
                # Bound the cached RGBA layers to about 64 MB even on very large pages.
                while sum(entry[1].width * entry[1].height for entry in self._layer_cache.values()) > 16_000_000:
                    self._layer_cache.pop(next(iter(self._layer_cache)))
        image = apply_watermark(image, enabled=bool(self.config.get('watermark_enabled', True)))
        self._rendered = image
        from PIL.ImageQt import ImageQt
        self.preview.set_pixmap(QPixmap.fromImage(ImageQt(image)))

    def save_image(self):
        if self.output_path is None or not self.items:
            return False
        for spin in self._layout_spins():
            spin.interpretText()
        if not self._dirty:
            return True
        if not self.apply_changes() or self._rendered is None:
            return False
        try:
            self._rendered.save(self.output_path)
            self.layout_path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            self._status.setText(tr('保存失败：{_0}。修改仍保留，请检查输出目录后重试。', _0=exc))
            return False
        self._dirty = False
        self._status.setText(tr('✓ 已保存图片与布局 · {_0}', _0=self.output_path.name))
        for index in range(self.page_list.count()):
            item = self.page_list.item(index)
            if item.data(Qt.UserRole) == str(self.output_path):
                item.setText(tr(self.output_path.name))
        return True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._adapt_width()

    def closeEvent(self, event):
        self._preview_timer.stop()
        self.preview.cancel_region_drag()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._store_properties()
        self._refresh_font_choices()
        QTimer.singleShot(0, self._adapt_width)

    def _adapt_width(self):
        if not self.isVisible():
            return
        if self._focus_btn.isChecked():
            return
        previous = self._last_available_width
        self._last_available_width = self.width()
        if self.width() < 1180 and (previous is None or previous >= 1180):
            self._pages_toggle.setChecked(False)
        if self.width() < 900 and (previous is None or previous >= 900):
            self._properties_toggle.setChecked(False)
