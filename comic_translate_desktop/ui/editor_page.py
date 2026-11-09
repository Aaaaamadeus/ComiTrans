from __future__ import annotations
from ..i18n import tr
import json
import sys
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import Qt, QSize, QSettings, QTimer, QEvent, QPoint
from PySide6.QtGui import QPixmap, QIcon, QImageReader, QShortcut, QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame, QGroupBox, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter, QComboBox, QSpinBox, QPlainTextEdit, QFileDialog, QMessageBox, QSizePolicy, QTabWidget, QCheckBox, QToolButton, QApplication, QLineEdit, QTextEdit, QAbstractSpinBox, QAbstractButton, QAbstractItemView)
from ..config import load_ai_config, MAIN_DIR
from ..font_library import available_fonts, font_description, font_display_name, font_reference, inspect_font, resolve_font_reference
from comic_translate_core.page_compositor import compose_page, layer_bounds
from comic_translate_core.restoration import (
    find_original, save_original, original_snapshot_path, legacy_region, protected_region,
    intersects_restored_region,
)
from comic_translate_core.layout_options import VERTICAL_ALIGNMENTS, normalize_text_color
from ..background_repair import BackgroundRepair, RepairWorker, save_editor_files
from ..pdf_export import PdfExportWorker
from ..editor_jobs import LatestJobQueue, read_page, read_project_pages, SaveRequest
from .color_picker import TextColorPicker
from .strip_preview import StripPreview
from .thumbnail_loader import ThumbnailLoader
from .theme import set_themed_icon, ui_font
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
        self._source_expanded = QSettings().value('ui/editorSourceExpanded', True, type=bool)
        self._source_compact_override = False
        self._desired_panels = [True, True]
        self._panel_priority = 1
        self._wide_splitter_state = None
        self._was_compact = False
        self._page_items = {}
        self._thumbnail_lru = OrderedDict()
        self._page_jobs = LatestJobQueue(self)
        self._import_jobs = LatestJobQueue(self)
        self._save_jobs = LatestJobQueue(self)
        self._after_save = None
        self._save_again = False
        self._requesting_page = False
        self._indexing = False
        self._pdf_sources = {}
        self._pdf_projects = {}
        self._export_worker = None
        self._thumbnail_loader = ThumbnailLoader(self)
        self._thumbnail_loader.ready.connect(self._accept_page_thumbnail)
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.timeout.connect(self._load_page_thumbnails)
        self._dirty = False
        self._loading = False
        self._rendered = None
        self._loaded_row = -1
        self._last_available_width = None
        self._row_dirty = False
        self._font_choice_dirty = False
        self._cleaned_image = None
        self._original_image = None
        self._repair_history = []
        self._repair_box = None
        self._repair_worker = None
        self._repair_engine = BackgroundRepair(
            self.config['lama_model'], device='cuda' if self.config.get('use_gpu') else 'cpu')
        self._edit_revision = 0
        self._text_dialog = None
        self._preview_dirty = False
        self._layer_cache = {}
        self._font_typesetters = {}
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(40)
        self._preview_timer.timeout.connect(self.apply_changes)
        # Owned timers instead of QTimer.singleShot(bound method): a queued
        # callback must not outlive the widget while another window pumps events.
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.timeout.connect(self._reveal_text_editor)
        self._adapt_timer = QTimer(self)
        self._adapt_timer.setSingleShot(True)
        self._adapt_timer.timeout.connect(self._adapt_width)
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
        self._zoom_tool_btn = QPushButton(tr('缩放工具'))
        self._zoom_tool_btn.setCheckable(True)
        self._zoom_tool_btn.setProperty('role', 'utility')
        self._zoom_tool_btn.setProperty('compact', True)
        self._zoom_tool_btn.setToolTip(tr('点击放大，Alt+点击缩小 · Z'))
        toolbar.addWidget(self._zoom_tool_btn)
        self._zoom = QComboBox()
        for name, value in [(tr('适应页面'), None), ('50%', .5), ('100%', 1.), ('150%', 1.5),
                            ('200%', 2.), (tr('适应宽度'), 'width')]:
            self._zoom.addItem(tr(name), value)
        self._zoom.setEditable(True)
        self._zoom.setInsertPolicy(QComboBox.NoInsert)
        self._zoom.lineEdit().setReadOnly(True)
        self._zoom.lineEdit().setAlignment(Qt.AlignCenter)
        self._zoom.setMinimumWidth(92)
        self._zoom.setToolTip(tr('缩放：Alt+滚轮以光标为中心，空格+拖动平移；Ctrl+0/1/2 适应页面/100%/适应宽度'))
        toolbar.addWidget(self._zoom)
        self._strip_toggle = QPushButton(tr('连续长条'))
        self._strip_toggle.setCheckable(True)
        self._strip_toggle.setProperty('compact', True)
        self._strip_toggle.setToolTip(tr('纵向滚动浏览所有页面，点击页面后原位精修。'))
        toolbar.addWidget(self._strip_toggle)
        toolbar.addStretch()
        self._export_pdf_btn = QPushButton(tr('导出 PDF'))
        self._export_pdf_btn.setToolTip(tr('将已保存的图片按页面顺序导出为 PDF；编辑时不会合成 PDF。'))
        self._export_pdf_btn.setEnabled(False)
        self._export_pdf_btn.clicked.connect(self._export_action)
        toolbar.addWidget(self._export_pdf_btn)
        self._save_btn = QPushButton(tr('保存图片'))
        self._save_btn.setProperty('role', 'primary')
        toolbar.addWidget(self._save_btn)
        root.addWidget(toolbar_frame)
        self._status = QLabel(tr('导入带布局数据的已翻译图片或 PDF，或从自动处理结果进入精修。'))
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
        add = QPushButton(tr('导入译图 / PDF'))
        set_themed_icon(add, 'plus')
        add.clicked.connect(self._import_pages)
        left.addWidget(add)
        self.page_list = QListWidget()
        self.page_list.viewport().installEventFilter(self)
        self.page_list.verticalScrollBar().valueChanged.connect(lambda: self._thumbnail_timer.start(25))
        self.page_list.setUniformItemSizes(True)
        self.page_list.setIconSize(QSize(56, 72))
        self.page_list.setWordWrap(True)
        self.page_list.setTextElideMode(Qt.ElideMiddle)
        self.page_list.currentItemChanged.connect(self._select_page)
        left.addWidget(self.page_list, 1)
        self.splitter.addWidget(self._pages_panel)
        canvas = QFrame()
        canvas.setObjectName('canvasPanel')
        # Let the responsive sidebars collapse before long translated actions widen the window.
        canvas.setMinimumWidth(280)
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(8)
        self._canvas_heading = PanelHeading('02', tr('页面预览'))
        canvas_layout.addWidget(self._canvas_heading)
        self.preview = StripPreview(import_action=True, illustration='studio-editor-v1.png')
        self._strip_toggle.toggled.connect(self.preview.set_continuous)
        self.preview.page_requested.connect(self.request_page)
        self.preview.clear(tr('选择一页，开始精修'))
        self.preview._hint.setText(tr('导入带布局数据的已翻译图片或 PDF，或从自动处理结果进入精修。'))
        self.preview.import_button.setText(tr('导入已翻译图片或 PDF'))
        self.preview.import_requested.connect(self._import_pages)
        self.preview.region_edited.connect(self._resize_region_from_canvas)
        self.preview.region_edit_finished.connect(self.apply_changes)
        self.preview.region_clicked.connect(self._select_block)
        self.preview.installEventFilter(self)
        self._zoom_tool_btn.toggled.connect(self.preview.set_zoom_tool)
        self._canvas_frame = canvas
        self._zoom_hud = QLabel(canvas)
        self._zoom_hud.setObjectName('zoomHud')
        self._zoom_hud.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._zoom_hud.hide()
        self._zoom_hud_timer = QTimer(self)
        self._zoom_hud_timer.setSingleShot(True)
        self._zoom_hud_timer.setInterval(900)
        self._zoom_hud_timer.timeout.connect(self._zoom_hud.hide)
        repair_toolbar = QHBoxLayout()
        self._repair_mode = QPushButton(tr('框选背景'))
        self._repair_mode.setCheckable(True)
        self._repair_mode.setToolTip(tr('拖动框选修补范围，拖动边角调整；Esc 取消本次拖动。'))
        self._repair_btn = QPushButton(tr('修补选区'))
        self._fill_white_btn = QPushButton(tr('填白'))
        self._fill_white_btn.setToolTip(tr('把框选区域整块填成白色（可撤回）。'))
        self._fill_black_btn = QPushButton(tr('填黑'))
        self._fill_black_btn.setToolTip(tr('把框选区域整块填成黑色（可撤回）。'))
        self._repair_undo = QPushButton(tr('撤回修补'))
        self._repair_undo.setToolTip(tr('使用处理前的图片逐步撤回；保存成功后清空缓存。'))
        for button in (self._repair_mode, self._repair_btn, self._fill_white_btn,
                       self._fill_black_btn, self._repair_undo):
            button.setProperty('compact', True)
            button.setProperty('role', 'utility')
            repair_toolbar.addWidget(button)
        repair_toolbar.addStretch()
        self._repair_mode.toggled.connect(self._toggle_repair_mode)
        self._repair_btn.clicked.connect(self._start_background_repair)
        self._fill_white_btn.clicked.connect(
            lambda: self._fill_repair_region((255, 255, 255)))
        self._fill_black_btn.clicked.connect(
            lambda: self._fill_repair_region((0, 0, 0)))
        self._repair_undo.clicked.connect(self.undo_background_repair)
        canvas_layout.addLayout(repair_toolbar)
        canvas_layout.addWidget(self.preview, 1)
        self.splitter.addWidget(canvas)
        self._properties_panel = QFrame()
        self._properties_panel.setObjectName('editorInspector')
        self._properties_panel.setMinimumWidth(300)
        self._properties_panel.setMaximumWidth(560)
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
        self.block_list.setMinimumHeight(160)
        self.block_list.currentRowChanged.connect(self._load_properties)
        self._restore_bubble_btn = QPushButton(tr('还原此气泡'))
        self._restore_bubble_btn.setToolTip(tr('撤销所选气泡的修补与嵌字，恢复处理前的原始像素；可再次恢复处理结果。'))
        self._restore_bubble_btn.clicked.connect(self.toggle_bubble_original)
        original_actions = QHBoxLayout()
        self._restore_bubble_btn.setProperty('compact', True)
        original_actions.addWidget(self._restore_bubble_btn)
        self._link_original_btn = QPushButton(tr('关联原图'))
        self._link_original_btn.setToolTip(tr('旧结果缺少原图时，选择该页处理前的同尺寸原图。'))
        self._link_original_btn.clicked.connect(self.link_original)
        self._link_original_btn.setProperty('compact', True)
        original_actions.addWidget(self._link_original_btn)
        props.addLayout(original_actions)
        self._inspector_tabs = QTabWidget()
        self._inspector_tabs.setDocumentMode(True)
        self._inspector_splitter = QSplitter(Qt.Vertical)
        self._inspector_splitter.setObjectName('inspectorSplitter')
        self._inspector_splitter.setChildrenCollapsible(False)
        self._inspector_splitter.setHandleWidth(6)
        self._inspector_splitter.addWidget(self.block_list)
        self._inspector_splitter.addWidget(self._inspector_tabs)
        self._inspector_splitter.setSizes([200, 420])
        props.addWidget(self._inspector_splitter, 1)
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
        self._source_toggle = QToolButton()
        self._source_toggle.setText(tr('原文'))
        self._source_toggle.setCheckable(True)
        self._source_toggle.setChecked(self._source_expanded)
        self._source_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._source_toggle.setProperty('role', 'quiet')
        self._source_toggle.setProperty('compact', True)
        props.addWidget(self._source_toggle)
        self._source_text = QPlainTextEdit()
        self._source_text.setReadOnly(True)
        self._source_text.setFixedHeight(110)
        self._source_text.setFont(ui_font(japanese=True))
        props.addWidget(self._source_text)
        self._source_toggle.toggled.connect(self._toggle_source_text)
        target_label = QLabel(tr('译文'))
        target_label.setObjectName('fieldCaption')
        break_row = QHBoxLayout()
        break_row.addWidget(target_label, 1)
        self._line_break_btn = QPushButton(tr('插入换行'))
        self._line_break_btn.setProperty('compact', True)
        self._line_break_btn.setToolTip(tr('在光标处插入换行，与 Enter 相同'))
        self._line_break_btn.clicked.connect(self._insert_line_break)
        break_row.addWidget(self._line_break_btn)
        self._expand_btn = QPushButton(tr('全屏编辑'))
        self._expand_btn.setProperty('compact', True)
        self._expand_btn.setToolTip(tr('在独立窗口中编辑当前气泡的译文 · F2'))
        self._expand_btn.clicked.connect(self.open_text_editor)
        break_row.addWidget(self._expand_btn)
        props.addLayout(break_row)
        break_hint = QLabel(tr('Enter 换行 · 竖排时换到左列'))
        break_hint.setWordWrap(True)
        break_hint.setProperty('muted', True)
        props.addWidget(break_hint)
        self._text_input = QPlainTextEdit()
        self._text_input.setObjectName('textInput')
        self._text_input.setMinimumHeight(140)
        self._text_input.setMaximumHeight(16777215)
        self._text_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._text_input.setAccessibleName(tr('译文与手动换行'))
        self._text_input.setPlaceholderText(tr('输入译文，按 Enter 手动换行'))
        self._text_input.setToolTip(tr('Enter 插入硬换行：横排换到下一行，竖排换到左侧下一列；连续回车保留空行或空列。'))
        props.addWidget(self._text_input, 1)
        props = layout_props
        group = QGroupBox(tr('字体与排版'))
        form = QFormLayout(group)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
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
        for label, value in [(tr('默认效果'), 'auto'), (tr('白色描边'), 'outlined'), (tr('黑色描边（空心）'), 'hollow')]:
            self._effect_combo.addItem(tr(label), value)
        self._text_color = TextColorPicker()
        self._text_color.setAccessibleName(tr('当前文本块文字颜色'))
        self._text_color.setToolTip(tr('只修改当前文本块；默认黑字，空心效果默认白字。自选颜色保留描边效果。'))
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
        form.addRow(tr('文字颜色'), self._text_color)
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
        self._apply_btn.setProperty('compact', True)
        self._apply_btn.setProperty('role', 'quiet')
        props.addStretch()
        inspector_actions = QFrame()
        inspector_actions.setObjectName('inspectorActions')
        actions_layout = QHBoxLayout(inspector_actions)
        actions_layout.setContentsMargins(12, 10, 12, 10)
        hint = QLabel(tr('修改实时预览 · Ctrl+S 保存图片'))
        hint.setProperty('muted', True)
        actions_layout.addWidget(hint, 1)
        actions_layout.addWidget(self._apply_btn)
        inspector_layout.addWidget(inspector_actions)
        self.splitter.addWidget(self._properties_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([220, 720, 440])
        root.addWidget(self.splitter, 1)
        root.addWidget(self._status)
        self._pages_toggle.toggled.connect(lambda checked: self._choose_panel(0, checked))
        self._properties_toggle.toggled.connect(lambda checked: self._choose_panel(1, checked))
        self._focus_btn.toggled.connect(self._toggle_canvas_focus)
        self._zoom.currentIndexChanged.connect(self._zoom_selected)
        self.preview.zoom_changed.connect(self._sync_zoom_display)
        self._apply_btn.clicked.connect(self.apply_changes)
        self._save_btn.clicked.connect(self.request_save)
        self._text_input.textChanged.connect(self._schedule_preview)
        self._style_combo.currentIndexChanged.connect(self._font_selection_changed)
        self._direction_combo.currentIndexChanged.connect(self._schedule_preview)
        self._direction_combo.currentIndexChanged.connect(self._update_vertical_alignment_enabled)
        self._vertical_alignment_combo.currentIndexChanged.connect(self._schedule_preview)
        self._effect_combo.currentIndexChanged.connect(self._schedule_preview)
        self._effect_combo.currentIndexChanged.connect(self._update_color_default)
        self._text_color.color_changed.connect(self._schedule_preview)
        for spin in self._layout_spins():
            spin.valueChanged.connect(self._schedule_preview)
        self._show_mask.toggled.connect(self._update_region_guide)
        self._save_shortcut = QShortcut(QKeySequence.Save, self)
        self._save_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self.request_save)
        self._focus_shortcut = QShortcut(QKeySequence('Ctrl+Shift+F'), self)
        self._focus_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._focus_shortcut.activated.connect(self._focus_btn.toggle)
        self._zoom_shortcuts = []
        for keys, action in (
            ('Ctrl+0', lambda: self.preview.set_zoom(None)),
            ('Ctrl+1', lambda: self.preview.set_zoom(1.0)),
            ('Ctrl+2', self.preview.set_fit_width),
            ('Ctrl+=', lambda: self.preview.zoom_by(1.25)),
            ('Ctrl+-', lambda: self.preview.zoom_by(1 / 1.25)),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
            self._zoom_shortcuts.append(shortcut)
        self._text_editor_shortcut = QShortcut(QKeySequence('F2'), self)
        self._text_editor_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._text_editor_shortcut.activated.connect(self.open_text_editor)
        self._zoom_tool_shortcut = QShortcut(QKeySequence('Z'), self)
        self._zoom_tool_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._zoom_tool_shortcut.activated.connect(self._toggle_zoom_tool)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._set_editable(False)
        settings = QSettings()
        state = settings.value('ui/editorSplitter')
        if state is not None:
            self.splitter.restoreState(state)
        self._desired_panels = [settings.value('ui/editorPages', True, type=bool),
                                settings.value('ui/editorProperties', True, type=bool)]
        self._apply_panel_layout()
        self._zoom.setCurrentIndex(max(0, min(self._zoom.count() - 1, int(settings.value('ui/editorZoom', 0)))))
        self._strip_toggle.setChecked(settings.value('ui/editorContinuous', False, type=bool))

    def _zoom_selected(self):
        value = self._zoom.currentData()
        if value == 'width':
            self.preview.set_fit_width()
        else:
            self.preview.set_zoom(value)

    def _sync_zoom_display(self, value):
        if value is None:
            text = tr('适应页面')
        elif value == 'width':
            text = tr('适应宽度')
        else:
            text = f'{round(float(value) * 100)}%'
        self._zoom.blockSignals(True)
        self._zoom.setCurrentIndex(-1)
        self._zoom.setEditText(text)
        self._zoom.blockSignals(False)
        if hasattr(self, '_zoom_hud'):
            self._zoom_hud.setText(text)
            self._zoom_hud.adjustSize()
            self._place_zoom_hud()
            self._zoom_hud.show()
            self._zoom_hud.raise_()
            self._zoom_hud_timer.start()

    def _place_zoom_hud(self):
        if not hasattr(self, '_zoom_hud') or not self._zoom_hud.isVisible():
            return
        rect = self.preview.geometry()
        self._zoom_hud.move(max(8, rect.right() - self._zoom_hud.width() - 16),
                            max(8, rect.bottom() - self._zoom_hud.height() - 16))

    def _toggle_zoom_tool(self):
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
            return
        self._zoom_tool_btn.toggle()

    def save_ui_state(self):
        settings = QSettings()
        settings.setValue('ui/editorSplitter', self._wide_splitter_state or (self._focus_splitter_state if self._focus_btn.isChecked() else self.splitter.saveState()))
        panels = self._desired_panels
        settings.setValue('ui/editorPages', panels[0])
        settings.setValue('ui/editorProperties', panels[1])
        settings.setValue('ui/editorZoom', self._zoom.currentIndex())
        settings.setValue('ui/editorContinuous', self._strip_toggle.isChecked())

    def _choose_panel(self, index, checked):
        self._desired_panels[index] = checked
        if checked:
            self._panel_priority = index
        settings = QSettings()
        settings.setValue('ui/editorPages' if index == 0 else 'ui/editorProperties', checked)
        self._apply_panel_layout()

    def _apply_panel_layout(self):
        focused = self._focus_btn.isChecked()
        compact = self.isVisible() and self.width() < 1120
        if compact and not self._was_compact and not focused:
            self._wide_splitter_state = self.splitter.saveState()
        effective = list(self._desired_panels)
        if focused:
            effective = [False, False]
        elif compact and all(effective):
            effective[1 - self._panel_priority] = False
        for index, (button, panel) in enumerate(((self._pages_toggle, self._pages_panel),
                                                (self._properties_toggle, self._properties_panel))):
            button.blockSignals(True)
            button.setChecked(effective[index])
            button.blockSignals(False)
            panel.setVisible(effective[index])
            button.setToolTip(tr('窗口较窄时暂时收起；展开此栏会让出另一个侧栏的位置。')
                              if self._desired_panels[index] and not effective[index] and not focused else '')
        if not compact and self._was_compact and not focused and self._wide_splitter_state is not None:
            self.splitter.restoreState(self._wide_splitter_state)
            self._wide_splitter_state = None
        self._was_compact = compact

    def _toggle_canvas_focus(self, focused):
        if focused:
            self._focus_splitter_state = self.splitter.saveState()
        self._apply_panel_layout()
        if not focused:
            self.splitter.restoreState(self._focus_splitter_state)
            self._apply_panel_layout()
        for widget in (self._canvas_heading, self._status, self._pages_toggle, self._properties_toggle):
            widget.setVisible(not focused)
        self._focus_btn.setText(tr('退出专注') if focused else tr('专注画布'))

    def _toggle_source_text(self, expanded):
        self._source_expanded = expanded
        self._source_compact_override = expanded and self.height() < 700
        QSettings().setValue('ui/editorSourceExpanded', expanded)
        self._apply_source_layout()

    def _reveal_text_editor(self):
        if not self.isVisible() or self._loaded_row < 0 or self._inspector_tabs.currentIndex() != 0:
            return
        if self.height() >= 760:
            return
        panel = self._properties_scroll
        point = self._text_input.mapTo(panel.widget(), QPoint(0, 0))
        if panel.viewport().height() - point.y() < 120:
            # Only ~a line of the editor is visible: align the tab header instead of a blank field.
            tabs_top = self._inspector_tabs.mapTo(panel.widget(), QPoint(0, 0)).y()
            panel.verticalScrollBar().setValue(max(0, tabs_top - 8))

    def _apply_source_layout(self):
        expanded = self._source_expanded and (not self.isVisible() or self.height() >= 700 or self._source_compact_override)
        self._source_toggle.blockSignals(True)
        self._source_toggle.setChecked(expanded)
        self._source_toggle.blockSignals(False)
        self._source_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._source_text.setVisible(expanded)

    def _set_editable(self, enabled):
        restored = 0 <= self._loaded_row < len(self.items) and self.items[self._loaded_row].get('restore_original', False)
        for widget in (self._text_input, self._line_break_btn, self._style_combo, self._font_library_btn, self._direction_combo, self._vertical_alignment_combo, self._effect_combo, self._text_color, *self._layout_spins(), self._show_mask, self._apply_btn, self._save_btn):
            widget.setEnabled(enabled and not restored)
        self._show_mask.setEnabled(enabled)
        self._update_vertical_alignment_enabled()
        self._update_repair_controls()

    def _update_vertical_alignment_enabled(self):
        self._vertical_alignment_combo.setEnabled(self._text_input.isEnabled()
                                                 and self._direction_combo.currentData() != 0)

    def _update_color_default(self):
        self._text_color.set_default_color('#ffffff' if self._effect_combo.currentData() == 'hollow' else '#000000')

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
        paths, _ = QFileDialog.getOpenFileNames(self, tr('导入已翻译图片或 PDF'),
            str(self.config.get('page_output_dir', '')), tr('漫画文件 (*.png *.jpg *.jpeg *.webp *.bmp *.pdf *.json)'))
        if paths:
            self.request_import(paths)

    @property
    def page_io_busy(self):
        return self._indexing or self._import_jobs.busy or self._page_jobs.busy

    def request_import(self, paths):
        self._import_jobs.invalidate()
        self._indexing = False
        if not self._allow_navigation(lambda: self.request_import(paths)):
            return False
        self._page_jobs.invalidate()
        revision, previous = self._edit_revision, self.output_path
        def read(cancelled):
            result = []
            for raw in paths:
                if cancelled():
                    raise RuntimeError('页面索引已取消')
                path = Path(raw).resolve()
                if path.suffix.lower() == '.pdf' or path.name == 'project.json':
                    result.append((path, read_project_pages(path, cancelled)))
                else:
                    reader = QImageReader(str(path))
                    size = reader.size()
                    if reader.transformation().value & 4:
                        size.transpose()
                    result.append((path, size))
            return result
        def accept(result):
            rows, imported = [], []
            for path, data in result:
                if isinstance(data, tuple):
                    project, sizes = data
                    imported.extend(project.images)
                    rows.extend((path, project, number, image, sizes.get(str(image)))
                                for number, image in enumerate(project.images, 1))
                else:
                    imported.append(path)
                    rows.append((None, None, 0, path, data))
            self._indexing = True
            generation = self._import_jobs.generation
            cursor = 0
            def append_batch():
                nonlocal cursor
                if generation != self._import_jobs.generation:
                    return
                self.page_list.blockSignals(True)
                self.page_list.setUpdatesEnabled(False)
                try:
                    for source, project, number, image, size in rows[cursor:cursor + 32]:
                        if project is None:
                            self._add_page(image, size)
                        else:
                            self._add_project_page(source, project, number, image, size)
                    cursor += 32
                finally:
                    self.page_list.blockSignals(False)
                    self.page_list.setUpdatesEnabled(True)
                if cursor < len(rows):
                    self._status.setText(tr('正在建立页面列表：{_0}/{_1}', _0=cursor, _1=len(rows)))
                    QTimer.singleShot(0, append_batch)
                    return
                self._indexing = False
                if imported and self.output_path == previous and self._edit_revision == revision:
                    self._begin_page_load(imported[0])
                else:
                    self._update_repair_controls()
                    self._status.setText(tr('页面索引已读取，当前修改保留。'))
            append_batch()
        self._status.setText(tr('正在后台读取页面索引…'))
        self._import_jobs.submit(read, accept, self._page_load_failed, cancellable=True)
        return True

    def _register_pdf(self, path):
        project, sizes = read_project_pages(path)
        return self._register_project(path, project, sizes)

    def _register_project(self, path, project, sizes):
        self.page_list.blockSignals(True)
        self.page_list.setUpdatesEnabled(False)
        try:
            for number, image in enumerate(project.images, 1):
                self._add_project_page(path, project, number, image, sizes.get(str(image)))
        finally:
            self.page_list.blockSignals(False)
            self.page_list.setUpdatesEnabled(True)
        return project.images

    def _add_project_page(self, source, project, number, image, size):
        self._pdf_sources[str(image)] = source
        self._pdf_projects[str(image)] = project
        item = self._add_page(image, size)
        label = tr('{_0} · 第 {_1} 页', _0=source.name, _1=number)
        item.setData(Qt.UserRole + 1, label)
        item.setText(tr('● 未保存\n{_0}', _0=label) if image == self.output_path and self._dirty else label)

    def _add_page(self, path, size=None):
        path = Path(path).resolve()
        key = str(path)
        if key in self._page_items:
            return self._page_items[key]
        self.preview.add_page(path, size)
        item = QListWidgetItem(path.name)
        item.setData(Qt.UserRole, key)
        item.setData(Qt.UserRole + 1, path.name)
        item.setToolTip(key)
        item.setSizeHint(QSize(170, 100))
        self._page_items[key] = item
        self.page_list.addItem(item)
        self._thumbnail_timer.start(0)
        return item

    def eventFilter(self, watched, event):
        if watched is self.page_list.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
            self._thumbnail_timer.start(0)
        elif watched is getattr(self, 'preview', None) and event.type() == QEvent.Resize:
            self._place_zoom_hud()
        elif event.type() in (QEvent.KeyPress, QEvent.KeyRelease) and event.key() == Qt.Key_Space:
            if self._space_pans_canvas():
                if event.isAutoRepeat():
                    return True
                self.preview.set_space_pan(event.type() == QEvent.KeyPress)
                return True
        elif event.type() == QEvent.WindowDeactivate:
            self.preview.set_space_pan(False)
        return super().eventFilter(watched, event)

    def _space_pans_canvas(self):
        """Space is the Hand tool, but never inside a text field or on a focused button."""
        if not self.isVisible() or self.preview._original.isNull():
            return False
        active = QApplication.activeWindow()
        if active is not None and active is not self.window() and QApplication.activeModalWidget() is None:
            return False
        focus = QApplication.focusWidget()
        return not isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox,
                                      QComboBox, QAbstractButton))

    def _load_page_thumbnails(self):
        requests = []
        if self.page_list.isVisible():
            viewport = self.page_list.viewport()
            top = self.page_list.indexAt(QPoint(4, 4)).row()
            top = max(0, top)
            count = viewport.height() // 100 + 3
            for index in range(top, min(self.page_list.count(), top + count)):
                item = self.page_list.item(index)
                key = item.data(Qt.UserRole)
                if item.icon().isNull():
                    requests.append((key, QSize(56, 72)))
                elif key in self._thumbnail_lru:
                    self._thumbnail_lru.move_to_end(key)
        self._thumbnail_loader.request(requests)

    def _accept_page_thumbnail(self, path, image):
        item = self._page_items.get(path)
        if item is None:
            return
        item.setIcon(QIcon(QPixmap.fromImage(image)))
        self._thumbnail_lru[path] = True
        self._thumbnail_lru.move_to_end(path)
        while len(self._thumbnail_lru) > 128:
            old, _ = self._thumbnail_lru.popitem(last=False)
            self._page_items[old].setIcon(QIcon())

    def _select_page(self, current, previous):
        if current:
            self.request_page(current.data(Qt.UserRole))

    def _restore_page_selection(self):
        self.page_list.blockSignals(True)
        self.page_list.setCurrentItem(self._page_items.get(str(self.output_path)))
        self.page_list.blockSignals(False)

    def _allow_navigation(self, action):
        if self._repair_worker is not None or self._export_worker is not None:
            self.confirm_discard()
            return False
        if self._save_jobs.busy:
            self._after_save = action
            return False
        if not self._dirty:
            return True
        choice = QMessageBox.question(self, tr('页面有未保存修改'), tr('保存当前页面的修改后继续？'),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if choice == QMessageBox.Save:
            self.request_save(after=action)
            return False
        if choice == QMessageBox.Discard:
            # Keep the current draft until the next page has actually loaded.
            return True
        return False

    def request_page(self, output_path):
        path = Path(output_path).resolve()
        self._import_jobs.invalidate()
        self._page_jobs.invalidate()
        self._indexing = self._requesting_page = False
        if path.suffix.lower() == '.pdf' or path.name == 'project.json':
            return self.request_import([path])
        if path == self.output_path:
            self._page_jobs.invalidate()
            self._requesting_page = False
            self._restore_page_selection()
            self._update_repair_controls()
            return True
        self._restore_page_selection()
        if not self._allow_navigation(lambda: self.request_page(path)):
            self._update_repair_controls()
            return False
        self._begin_page_load(path)
        return True

    def _begin_page_load(self, path):
        revision, previous = self._edit_revision, self.output_path
        settings = deepcopy(self.config)
        self._requesting_page = True
        self._loading_page = Path(path)
        self._status.setText(tr('正在后台加载页面：{_0}', _0=Path(path).name))
        self.preview.set_loading(tr('正在加载 {_0}', _0=Path(path).name))
        def accept(data):
            self._requesting_page = False
            if self.output_path != previous or self._edit_revision != revision:
                self._status.setText(tr('加载期间当前页有新修改，已保留当前页；请重新选择目标页。'))
                self._update_repair_controls()
                return
            self.load_page(path, _payload=data, _approved=True)
        self._page_jobs.submit(lambda cancelled: read_page(path, settings, cancelled), accept, self._page_load_failed, cancellable=True)
        self._update_repair_controls()

    def _page_load_failed(self, error):
        self._requesting_page = False
        self._restore_page_selection()
        self._status.setText(tr('页面加载失败：{_0}', _0=error))
        retry = None
        if getattr(self, '_loading_page', None) is not None:
            retry = lambda: self.request_page(self._loading_page)
        self.preview.set_error(tr('页面加载失败：{_0}', _0=error), retry=retry)
        self._update_repair_controls()

    def confirm_discard(self):
        if self._export_worker is not None:
            self._status.setText(tr('正在导出 PDF，请完成或取消导出后再切页或退出。'))
            return False
        if self._repair_worker is not None:
            self._status.setText(tr('正在修补背景，请稍候再保存或切换页面。'))
            return False
        if not self._dirty:
            return True
        choice = QMessageBox.question(self, tr('页面有未保存修改'), tr('保存当前页面的修改后继续？'), QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if choice == QMessageBox.Save:
            return self.save_image()
        if choice == QMessageBox.Discard:
            self._dirty = False
            return True
        return False

    def load_page(self, output_path, *, _payload=None, _approved=False):
        path = Path(output_path).resolve()
        if path.suffix.lower() == '.pdf' or path.name == 'project.json':
            try:
                pages = self._register_pdf(path)
            except Exception as exc:
                self._status.setText(tr('无法精修：{_0}', _0=exc))
                return False
            path = self.output_path if self.output_path in pages else pages[0]
        if self.output_path == path:
            self._export_pdf_btn.setEnabled(True)
            return True
        if not _approved and not self.confirm_discard():
            return False
        if _payload is None:
            try:
                _payload = read_page(path, self.config)
            except Exception as exc:
                self._page_load_failed(str(exc))
                return False
        self._page_jobs.invalidate()
        self._preview_timer.stop()
        self._repair_history.clear()
        self._repair_box = None
        self._repair_mode.setChecked(False)
        self._edit_revision = 0
        self._loading = True
        self._loaded_row = -1
        self._row_dirty = False
        self._font_choice_dirty = False
        self.items = []
        self._rendered = None
        self._cleaned_image = None
        self._original_image = None
        self._preview_dirty = False
        self.preview.set_region(None)
        self._layer_cache.clear()
        self.block_list.clear()
        self._source_text.clear()
        self._text_input.clear()
        self._set_editable(False)
        self.output_path = path
        self._export_pdf_btn.setEnabled(self._export_worker is None)
        self.cleaned_path = path.parent.parent / f'{path.parent.name}_cleaned' / f'{path.stem}_cleaned.png'
        self.layout_path = path.parent.parent / f'{path.parent.name}_layout' / f'{path.stem}_layout.json'
        page_item = self._add_page(path, _payload.preview.size())
        self.page_list.blockSignals(True)
        self.page_list.setCurrentItem(page_item)
        self.page_list.blockSignals(False)
        self.preview.set_page_pixmap(path, QPixmap.fromImage(_payload.preview))
        try:
            if _payload.error:
                raise ValueError(_payload.error)
            self.items = _payload.items
            self._cleaned_image = _payload.cleaned
            self._prepare_regions()
            for index, item in enumerate(self.items):
                block = QListWidgetItem(self._block_label(index))
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
        self._update_repair_controls()
        return True

    def _block_label(self, index):
        item = self.items[index]
        if item.get('restore_original'):
            return tr('{_0} · 已还原原图', _0=f'{index + 1:02d}')
        summary = str(item.get('text', '')).replace('\n', ' ↵ ')[:28]
        return f'{index + 1:02d}  {summary}'

    def _get_original_image(self):
        if self._original_image is None:
            path = find_original(self.output_path)
            if path is None:
                raise ValueError(tr('缺少处理前原图，请先关联原图。'))
            from PIL import Image
            with Image.open(path) as source:
                if source.size != self._cleaned_image.size:
                    raise ValueError(tr('原图与当前页面尺寸不一致，无法无损还原。'))
                self._original_image = source.convert('RGB')
        return self._original_image

    def link_original(self):
        if self._cleaned_image is None or self._repair_worker is not None or self._export_worker is not None:
            return False
        path, _ = QFileDialog.getOpenFileName(self, tr('选择处理前原图（尺寸必须一致）'),
            str(self.output_path.parent), tr('图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)'))
        if not path:
            return False
        try:
            selected = Path(path).resolve()
            if selected in (self.output_path.resolve(), self.cleaned_path.resolve()):
                raise ValueError(tr('请选择处理前的原图，不能使用译图或清理底图。'))
            from PIL import Image, ImageOps
            with Image.open(selected) as source:
                original = ImageOps.exif_transpose(source).convert('RGB')
            if original.size != self._cleaned_image.size:
                raise ValueError(tr('原图与当前页面尺寸不一致，无法无损还原。'))
            save_original(self.output_path, original)
            self._original_image = original
            self._layer_cache.clear()
            if any(item.get('restore_original') for item in self.items):
                self._dirty = self._preview_dirty = True
                self._edit_revision += 1
                self._refresh_page_dirty_label()
                if not self.apply_changes():
                    return False
            self._status.setText(tr('已关联原图，可还原选中的气泡。'))
            return True
        except Exception as exc:
            self._status.setText(tr('关联原图失败：{_0}', _0=exc))
            return False

    def toggle_bubble_original(self):
        if (self._cleaned_image is None or self._repair_worker is not None or self._export_worker is not None
                or not 0 <= self._loaded_row < len(self.items)):
            return False
        for spin in self._layout_spins():
            spin.interpretText()
        self._store_properties()
        item = self.items[self._loaded_row]
        restored = bool(item.get('restore_original'))
        if not restored:
            if find_original(self.output_path) is None and self._original_image is None:
                if not self.link_original():
                    return False
            try:
                original = self._get_original_image()
                if not item.get('original_region'):
                    item['original_region'] = legacy_region(item, original, self._cleaned_image)
                protected_region(item, self.items, original.size)
            except Exception as exc:
                self._status.setText(tr('还原失败：{_0}', _0=exc))
                return False
        item['restore_original'] = not restored
        self._layer_cache.pop(self._loaded_row, None)
        self._dirty = self._preview_dirty = True
        self._edit_revision += 1
        self.block_list.item(self._loaded_row).setText(self._block_label(self._loaded_row))
        self._refresh_page_dirty_label()
        self._set_editable(True)
        self._update_region_guide()
        if not self.apply_changes():
            return False
        self._status.setText(tr('已恢复此气泡的处理结果 · 未保存。') if restored
                             else tr('此气泡已还原为原图 · 未保存，点击保存图片后保留。'))
        return True

    def _mark_dirty(self):
        if self._loading or not self.items:
            return
        self._edit_revision += 1
        self._dirty = True
        self._row_dirty = True
        self._preview_dirty = True
        self._status.setText(tr('● 未保存修改 · {_0}', _0=self.output_path.name))
        self._refresh_page_dirty_label()

    def _insert_line_break(self):
        if self._loaded_row < 0:
            return
        self._text_input.insertPlainText('\n')
        self._text_input.setFocus()

    def open_text_editor(self):
        """F2 / 全屏编辑: one bubble, a roomy source and target side by side."""
        if not 0 <= self._loaded_row < len(self.items):
            return None
        from .text_editor_dialog import TextEditorDialog
        if self._text_dialog is None:
            self._text_dialog = TextEditorDialog(self)
            self._text_dialog.text_changed.connect(self._apply_dialog_text)
        item = self.items[self._loaded_row]
        self._text_dialog.set_block(self._loaded_row + 1, item.get('source_text', ''),
                                    self._text_input.toPlainText())
        self._text_dialog.show()
        self._text_dialog.raise_()
        self._text_dialog.activateWindow()
        return self._text_dialog

    def _apply_dialog_text(self, text):
        if self._loading or self._text_input.toPlainText() == text:
            return
        self._text_input.setPlainText(text)

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
        self.preview.set_regions(
            [(index, tuple(self._mask_box(item))) for index, item in enumerate(self.items)],
            visible=self._show_mask.isChecked() and not self._repair_mode.isChecked())
        if self._repair_mode.isChecked():
            self.preview.set_region(self._repair_box, editable=self._repair_box is not None)
            return
        box = None
        if 0 <= self._loaded_row < len(self.items):
            box = self._mask_box(self.items[self._loaded_row], width=self._mask_width.value(),
                                 height=self._mask_height.value(), offset_x=self._offset_x.value(),
                                 offset_y=self._offset_y.value())
            self._box_label.setText(tr(tr('蒙版区域：') + ', '.join(map(str, box))))
        restored = 0 <= self._loaded_row < len(self.items) and self.items[self._loaded_row].get('restore_original')
        if restored:
            box = list(self.items[self._loaded_row]['box'][:4])
            self._box_label.setText(tr('原图区域：{_0}', _0=', '.join(map(str, box))))
        self.preview.set_region(box if self._show_mask.isChecked() else None, editable=box is not None and not restored)

    def _select_block(self, index):
        """A click on a box in the canvas is the same as picking it in the list."""
        if not 0 <= index < len(self.items) or index == self._loaded_row:
            return
        self.block_list.setCurrentRow(index)
        item = self.block_list.item(index)
        if item is not None:
            self.block_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def _resize_region_from_canvas(self, box):
        if self._repair_mode.isChecked():
            self._repair_box = tuple(box) if box is not None else None
            self._update_region_guide()
            self._update_repair_controls()
            return
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
        item['text_color'] = self._text_color.color
        item['vertical_alignment'] = self._vertical_alignment_combo.currentData()
        self.block_list.item(self._loaded_row).setText(self._block_label(self._loaded_row))
        self._row_dirty = False

    def _load_properties(self, row):
        self.preview.cancel_region_drag()
        if row < 0 or row >= len(self.items):
            self._loaded_row = -1
            self._font_choice_dirty = False
            self._set_editable(False)
            self.preview.set_region(None)
            self.preview.set_regions([])
            if self._text_dialog is not None:
                self._text_dialog.close()
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
        self._text_color.set_color(item.get('text_color'))
        self._update_color_default()
        alignment_index = self._vertical_alignment_combo.findData(item.get('vertical_alignment', 'center'))
        self._vertical_alignment_combo.setCurrentIndex(alignment_index if alignment_index >= 0 else 1)
        self._offset_x.setValue(int(item.get('offset_x', 0)))
        self._offset_y.setValue(int(item.get('offset_y', 0)))
        box = self._mask_box(item)
        self._mask_width.setValue(box[2] - box[0])
        self._mask_height.setValue(box[3] - box[1])
        self._update_region_guide()
        self._set_editable(True)
        if self._text_dialog is not None and self._text_dialog.isVisible():
            self._text_dialog.set_block(row + 1, item.get('source_text', ''),
                                        self._text_input.toPlainText())
        self._loading = False
        self._row_dirty = False
        if self.height() >= 700:
            self._properties_scroll.verticalScrollBar().setValue(0)
        self._reveal_timer.start(0)

    def apply_changes(self):
        if self._cleaned_image is None:
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

    def set_repair_config(self, settings: dict) -> None:
        device = 'cuda' if settings.get('use_gpu') else 'cpu'
        model_path = settings['lama_model']
        if (model_path, device) != (self._repair_engine.model_path, self._repair_engine.device):
            # A running worker retains its own engine until the repair finishes.
            self._repair_engine = BackgroundRepair(model_path, device=device)
        self.config.update(lama_model=model_path, use_gpu=bool(settings.get('use_gpu')))

    def _update_repair_controls(self):
        busy = self._repair_worker is not None
        ready = (self._cleaned_image is not None and not busy and self._export_worker is None
                 and not self._save_jobs.busy and not self._requesting_page
                 and not self._indexing and not self._import_jobs.busy)
        self._repair_mode.setEnabled(ready)
        protected = False
        if ready and self._repair_box is not None:
            try:
                protected = intersects_restored_region(self._repair_box, self.items, self._cleaned_image.size)
            except (ValueError, KeyError, TypeError, OSError):
                protected = True
        self._repair_btn.setEnabled(ready and self._repair_box is not None and not protected)
        self._repair_btn.setToolTip(tr('选区包含已还原气泡，请先恢复该气泡的处理结果再修补。') if protected else '')
        fills_enabled = ready and self._repair_box is not None and not protected
        self._fill_white_btn.setEnabled(fills_enabled)
        self._fill_black_btn.setEnabled(fills_enabled)
        fill_tip = tr('选区包含已还原气泡，请先恢复该气泡的处理结果再填色。') if protected else ''
        self._fill_white_btn.setToolTip(fill_tip or tr('把框选区域整块填成白色（可撤回）。'))
        self._fill_black_btn.setToolTip(fill_tip or tr('把框选区域整块填成黑色（可撤回）。'))
        selected = 0 <= self._loaded_row < len(self.items)
        self._restore_bubble_btn.setEnabled(ready and selected)
        self._restore_bubble_btn.setText(tr('恢复处理结果') if selected and self.items[self._loaded_row].get('restore_original') else tr('还原此气泡'))
        self._link_original_btn.setEnabled(ready)
        self._repair_undo.setEnabled(ready and bool(self._repair_history))
        self._save_btn.setEnabled(ready)
        self.page_list.setEnabled(not busy and self._export_worker is None)
        self.preview.setEnabled(not busy)

    def _toggle_repair_mode(self, enabled):
        self.preview.set_region_creation(enabled)
        self._repair_box = None
        self._update_region_guide()
        self._update_repair_controls()
        if enabled:
            self._status.setText(tr('在画布拖动框选背景，再点击“修补选区”或“填白 / 填黑”；译文保持独立。'))

    def _start_background_repair(self):
        if self._requesting_page or self._indexing or self._save_jobs.busy or self._repair_worker is not None or self._cleaned_image is None or self._repair_box is None:
            return
        if self._export_worker is not None:
            return
        try:
            protected = intersects_restored_region(self._repair_box, self.items, self._cleaned_image.size)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self._status.setText(tr('还原失败：{_0}', _0=exc))
            return
        if protected:
            self._status.setText(tr('选区包含已还原气泡，请先恢复该气泡的处理结果再修补。'))
            return
        if not self.apply_changes():
            return
        worker = RepairWorker(self._repair_engine, self._cleaned_image, self._repair_box, self)
        self._repair_worker = worker
        worker.succeeded.connect(self._accept_background_repair)
        worker.failed.connect(self._background_repair_failed)
        worker.finished.connect(self._background_repair_finished)
        self._update_repair_controls()
        self._status.setText(tr('正在修补背景，请稍候再保存或切换页面。'))
        worker.start()

    def _fill_repair_region(self, color) -> None:
        """Paint the selected rectangle with a flat colour on the cleaned base."""
        if (self._requesting_page or self._indexing or self._save_jobs.busy
                or self._repair_worker is not None or self._cleaned_image is None
                or self._repair_box is None or self._export_worker is not None):
            return
        try:
            box = tuple(map(int, self._repair_box))
        except (TypeError, ValueError):
            self._status.setText(tr('选区超出图片范围。'))
            return
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= self._cleaned_image.width
                and 0 <= y1 < y2 <= self._cleaned_image.height):
            self._status.setText(tr('选区超出图片范围。'))
            return
        try:
            protected = intersects_restored_region(box, self.items, self._cleaned_image.size)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self._status.setText(tr('还原失败：{_0}', _0=exc))
            return
        if protected:
            self._status.setText(tr('选区包含已还原气泡，请先恢复该气泡的处理结果再填色。'))
            return
        if not self.apply_changes():
            return
        before = self._cleaned_image.crop(box)
        self._cleaned_image.paste(tuple(color), box)
        self._repair_history.append((box, before, self._dirty, self._edit_revision))
        self._layer_cache.clear()
        self._dirty = self._preview_dirty = True
        self._refresh_page_dirty_label()
        if self.apply_changes():
            self._status.setText(
                tr('已把选区填为白色 · 未保存，可撤回修补。') if color == (255, 255, 255)
                else tr('已把选区填为黑色 · 未保存，可撤回修补。'))

    def _accept_background_repair(self, box, patch):
        before = self._cleaned_image.crop(box)
        self._cleaned_image.paste(patch, box)
        self._repair_history.append((box, before, self._dirty, self._edit_revision))
        self._layer_cache.clear()
        self._dirty = self._preview_dirty = True
        self._refresh_page_dirty_label()
        if self.apply_changes():
            self._status.setText(tr('背景已修补 · 未保存，可撤回修补。'))

    def _background_repair_failed(self, message):
        self._status.setText(tr('背景修补失败：{_0}。图片未修改，可重试。', _0=message))

    def _background_repair_finished(self):
        worker = self._repair_worker
        self._repair_worker = None
        if worker is not None:
            worker.deleteLater()
        self._update_repair_controls()

    def undo_background_repair(self):
        if self._requesting_page or self._indexing or self._save_jobs.busy or self._repair_worker is not None or not self._repair_history:
            return False
        self._store_properties()
        box, before, was_dirty, revision = self._repair_history.pop()
        self._cleaned_image.paste(before, box)
        self._layer_cache.clear()
        self._dirty = was_dirty or revision != self._edit_revision
        self._preview_dirty = True
        self._refresh_page_dirty_label()
        self._update_repair_controls()
        if self.apply_changes():
            self._status.setText(tr('已从缓存恢复修补前的背景，文字修改保留。'))
        return True

    def _refresh_page_dirty_label(self):
        item = self._page_items.get(str(self.output_path))
        if item is not None:
            label = item.data(Qt.UserRole + 1)
            item.setText(tr('● 未保存\n{_0}', _0=label) if self._dirty else label)

    def render(self) -> None:
        if self._cleaned_image is None:
            raise ValueError(tr('缺少配套清理底图，请重新导入页面'))
        image = self._cleaned_image
        prior = getattr(self, '_render_layers', {})
        signatures, layers, changed = {}, [], []
        full = self._rendered is None or not self._layer_cache
        mode = (bool(self.config.get('watermark_enabled', True)),
                tuple((i, bool(item.get('restore_original'))) for i, item in enumerate(self.items)))
        # Restored-region protection depends on neighboring bubble geometry as well as glyph bounds.
        full = full or mode != getattr(self, '_render_mode', None) or any(restored for _, restored in mode[1])
        for index, item in enumerate(self.items):
            text = item.get("text", "")
            if not text or item.get('restore_original'):
                self._layer_cache.pop(index, None)
                continue
            box = self._mask_box(item)
            size = item.get('font_size') if item.get('manual_layout') else item.get('rendered_font_size') or item.get('font_size')
            size = int(size or 0)
            typesetter = self._typesetter_for_item(item)
            key = (tuple(box), text, item.get('style', 'dialogue'), int(item.get('direction', 1)),
                   size, bool(item.get('non_bubble', False)),
                   typesetter.font_map.get(item.get('style', 'dialogue')), item.get('text_effect', 'auto'),
                   item.get('source_outline_ratio'),
                   item.get('vertical_alignment', 'center'), normalize_text_color(item.get('text_color')))
            cached = self._layer_cache.get(index)
            if cached is not None and cached[0] == key:
                _, surface, left, top, actual_size = cached
                item['rendered_font_size'] = actual_size
                layer = surface, left, top
                layers.append(layer)
                signatures[index] = (key, layer_bounds(layer))
                continue
            typesetter.draw_text(
                image,
                box,
                text,
                item.get("style", "dialogue"),
                direction=int(item.get("direction", 1)),
                target_font_size=size if size > 0 else None,
                non_bubble=bool(item.get("non_bubble", False)),
                manual_layout=True,
                text_effect=item.get('text_effect', 'auto'),
                source_outline_ratio=item.get('source_outline_ratio'),
                vertical_alignment=item.get('vertical_alignment', 'center'),
                text_color=item.get('text_color'),
                composite=False,
            )
            item['rendered_font_size'] = typesetter.last_font_size
            layer = typesetter.last_render_layer
            if layer is not None:
                surface, left, top = layer
                layers.append(layer)
                signatures[index] = (key, layer_bounds(layer))
                self._layer_cache.pop(index, None)
                self._layer_cache[index] = (key, surface, left, top, typesetter.last_font_size)
                # Bound the cached RGBA layers to about 64 MB even on very large pages.
                while sum(entry[1].width * entry[1].height for entry in self._layer_cache.values()) > 16_000_000:
                    self._layer_cache.pop(next(iter(self._layer_cache)))
        for index in prior.keys() | signatures.keys():
            if prior.get(index) != signatures.get(index):
                if index in prior:
                    changed.append(prior[index][1])
                if index in signatures:
                    changed.append(signatures[index][1])
        original = self._get_original_image() if any(item.get('restore_original') for item in self.items) else None
        image, regions = compose_page(self._cleaned_image, self._rendered, layers,
            None if full else changed, watermark=mode[0], original=original, items=self.items,
            copy_previous=self._save_jobs.busy and self._rendered is getattr(self, '_saving_image', None))
        self._rendered = image
        self._render_layers, self._render_mode = signatures, mode
        self._last_render_regions = regions
        if full or self.preview._original.isNull():
            from PIL.ImageQt import ImageQt
            self.preview.set_pixmap(QPixmap.fromImage(ImageQt(image)))
        else:
            self.preview.update_regions(image, regions)

    def _export_action(self):
        if self._export_worker is not None:
            self._cancel_pdf_export()
        else:
            self.export_pdf()

    def export_pdf(self, output_path=None):
        if self._export_worker is not None or self.output_path is None or self._repair_worker is not None:
            return False
        project = self._pdf_projects.get(str(self.output_path))
        if project is not None:
            images, sizes = project.images, project.page_sizes
            source = self._pdf_sources[str(self.output_path)]
            default = (source.parent / f'{source.stem}_edited.pdf') if source.suffix.lower() == '.pdf' else source.parent / 'edited.pdf'
        else:
            images = [Path(self.page_list.item(i).data(Qt.UserRole)) for i in range(self.page_list.count())]
            sizes = []
            for path in images:
                reader = QImageReader(str(path))
                size = reader.size()
                if reader.transformation().value & 4:
                    size.transpose()
                if not size.isValid():
                    self._status.setText(tr('无法读取译图：{_0}', _0=path.name))
                    return False
                sizes.append((size.width() * 72 / 200, size.height() * 72 / 200))
            default = self.output_path.with_name('edited.pdf')
        if output_path is None:
            chosen, _ = QFileDialog.getSaveFileName(self, tr('导出 PDF'), str(default), 'PDF (*.pdf)')
            if not chosen:
                return False
            output_path = Path(chosen)
        output_path = Path(output_path).with_suffix('.pdf')
        # Flush pending spin-box text even before it has marked the page dirty.
        # Plain images without editing metadata can be exported directly.
        for spin in self._layout_spins():
            spin.interpretText()
        if self._dirty or self._save_jobs.busy:
            return self.request_save(after=lambda: self.export_pdf(output_path))
        worker = PdfExportWorker(images, sizes, output_path, self)
        self._export_worker = worker
        worker.progress.connect(self._pdf_export_progress)
        worker.succeeded.connect(self._pdf_export_succeeded)
        worker.failed.connect(self._pdf_export_failed)
        worker.cancelled.connect(self._pdf_export_cancelled)
        worker.finished.connect(self._pdf_export_finished)
        self._update_repair_controls()
        self._export_pdf_btn.setText(tr('取消导出'))
        self._export_pdf_btn.setToolTip(tr('取消导出'))
        self._status.setText(tr('正在后台导出 PDF…'))
        worker.start()
        return True

    def _pdf_export_progress(self, done, total):
        self._status.setText(tr('正在导出 PDF：{_0}/{_1} 页', _0=done, _1=total))

    def _pdf_export_succeeded(self, path):
        self._status.setText(tr('已导出 PDF：{_0}', _0=path))

    def _pdf_export_failed(self, message):
        self._status.setText(tr('PDF 导出失败：{_0}。已保存的图片仍然保留。', _0=message))

    def _pdf_export_cancelled(self):
        self._status.setText(tr('已取消 PDF 导出，已保存的图片仍然保留。'))

    def _cancel_pdf_export(self):
        if self._export_worker is not None:
            self._export_worker.requestInterruption()

    def _pdf_export_finished(self):
        worker = self._export_worker
        self._export_worker = None
        if worker is not None:
            worker.deleteLater()
        self._export_pdf_btn.setEnabled(self.output_path is not None)
        self._export_pdf_btn.setText(tr('导出 PDF'))
        self._export_pdf_btn.setToolTip(tr('将已保存的图片按页面顺序导出为 PDF；编辑时不会合成 PDF。'))
        self._update_repair_controls()

    def _save_request(self):
        if self._export_worker is not None or self._repair_worker is not None:
            self._status.setText(tr('后台任务正在使用当前页，请稍候再保存。'))
            return None
        if self.output_path is None or self._cleaned_image is None:
            return None
        for spin in self._layout_spins():
            spin.interpretText()
        if not self.apply_changes() or self._rendered is None:
            return None
        output, layout, cleaned = self.output_path, self.layout_path, self.cleaned_path
        original = original_path = None
        if output.suffix.lower() != '.png' and any('restore_original' in item for item in self.items):
            number = 1
            while True:
                suffix = '' if number == 1 else f'_{number}'
                output = self.output_path.with_name(f'{self.output_path.stem}_restored{suffix}.png')
                layout = self.layout_path.with_name(f'{output.stem}_layout.json')
                cleaned = self.cleaned_path.with_name(f'{output.stem}_cleaned.png')
                original_path = original_snapshot_path(output)
                if not any(path.exists() for path in (output, layout, cleaned, original_path)):
                    break
                number += 1
            original = self._get_original_image()
        return SaveRequest(self._rendered, output, deepcopy(self.items), layout,
            self._cleaned_image if self._repair_history or original is not None else None,
            cleaned, original, original_path)

    def _saved(self, request, previous, revision):
        if self.output_path != previous:
            return
        if request.output != previous:
            self.output_path, self.layout_path, self.cleaned_path = request.output, request.layout, request.cleaned_path
            self.preview.replace_page_path(previous, request.output)
            item = self._page_items.pop(str(previous))
            self._page_items[str(request.output)] = item
            item.setData(Qt.UserRole, str(request.output))
            item.setData(Qt.UserRole + 1, request.output.name)
            item.setToolTip(str(request.output))
        # Edits made during PNG encoding stay dirty and are never cleared by an old save.
        self._dirty = revision != self._edit_revision
        self._repair_history.clear()
        self._refresh_page_dirty_label()
        self._update_repair_controls()
        self._status.setText(tr('已保存；后续修改仍未保存。') if self._dirty else
            tr('✓ 已保存图片与布局 · {_0}', _0=self.output_path.name))

    def _save_failed(self, message):
        self._saving_image = None
        self._after_save = None
        self._save_again = False
        self._update_repair_controls()
        self._status.setText(tr('保存失败：{_0}。修改仍保留，请检查输出目录后重试。', _0=message))

    def request_save(self, checked=False, *, after=None):
        if after is not None:
            self._after_save = after
        if self._save_jobs.busy:
            self._save_again = True
            return True
        for spin in self._layout_spins():
            spin.interpretText()
        if not self._dirty:
            action, self._after_save = self._after_save, None
            if action:
                action()
            return True
        try:
            request = self._save_request()
        except Exception as exc:
            self._save_failed(str(exc))
            return False
        if request is None:
            self._after_save = None
            return False
        previous, revision = self.output_path, self._edit_revision
        def saved(result):
            self._saving_image = None
            self._saved(result, previous, revision)
            again, self._save_again = self._save_again, False
            if self._dirty and (again or self._after_save is not None):
                self.request_save()
            else:
                action, self._after_save = self._after_save, None
                if action:
                    action()
        self._saving_image = request.rendered
        self._save_jobs.submit(lambda: request.write(save_editor_files), saved, self._save_failed)
        self._update_repair_controls()
        self._status.setText(tr('正在后台保存图片与布局…'))
        return True

    def save_image(self):
        """Synchronous entry for scripts; interactive actions use request_save."""
        if self._save_jobs.busy or self._export_worker is not None or self._repair_worker is not None:
            return False
        for spin in self._layout_spins():
            spin.interpretText()
        if not self._dirty:
            return self.output_path is not None and self._cleaned_image is not None
        try:
            request = self._save_request()
            if request is None:
                return False
            previous, revision = self.output_path, self._edit_revision
            request.write(save_editor_files)
            self._saved(request, previous, revision)
            return True
        except Exception as exc:
            self._save_failed(str(exc))
            return False

    def shutdown_jobs(self):
        self._indexing = False
        for timer in (self._reveal_timer, self._adapt_timer,
                      self._preview_timer, self._thumbnail_timer):
            timer.stop()
        self._page_jobs.close()
        self._import_jobs.close()
        self._save_jobs.close()
        self._thumbnail_loader.request([])
        self.preview._thumbnail_loader.request([])
        # Detach event filters before the window goes away; otherwise a deleted
        # EditorPage can still be called for application-wide events.
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        for watched in (self.page_list.viewport(), self.preview):
            watched.removeEventFilter(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._adapt_width()

    def closeEvent(self, event):
        if self._repair_worker is not None or self._save_jobs.busy:
            event.ignore()
            return
        self.shutdown_jobs()
        self._repair_history.clear()
        self._preview_timer.stop()
        self.preview.cancel_region_drag()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._store_properties()
        self._refresh_font_choices()
        self._adapt_timer.start(0)

    def hideEvent(self, event):
        self.preview.set_space_pan(False)
        super().hideEvent(event)

    def _adapt_width(self):
        if self.isVisible():
            self._source_text.setFixedHeight(64 if self.height() < 700 else 110)
            self._apply_source_layout()
            self._apply_panel_layout()
            self._reveal_timer.start(0)
