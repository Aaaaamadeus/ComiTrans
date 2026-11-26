from __future__ import annotations
from ..i18n import tr
import json
import sys
import time
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import numpy as np
from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QRect, QSize, QSettings, QTimer, QEvent, QPoint, QVariantAnimation, QItemSelectionModel, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QColor, QFont, QImage, QPainter, QPixmap, QIcon, QImageReader, QShortcut, QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea, QSplitter, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QFileDialog, QMessageBox, QSizePolicy, QTabWidget, QCheckBox, QToolButton, QApplication, QLineEdit, QTextEdit, QAbstractSpinBox, QAbstractButton, QAbstractItemView, QStyledItemDelegate, QStyle, QDialog)
from ..config import load_ai_config, MAIN_DIR
from ..font_library import available_fonts, font_description, font_display_name, font_reference, import_font, inspect_font, resolve_font_reference
from comic_translate_core.page_compositor import compose_page, intersection, layer_bounds
from comic_translate_core.paint_engine import (
    BrushEngine,
    BrushSettings,
    BrushTool,
    ImageFilters,
    SelectionEngine,
    sample_color,
)
from comic_translate_core.restoration import (
    find_original, save_original, original_snapshot_path, legacy_region, protected_region,
    intersects_restored_region,
)
from comic_translate_core.layout_options import VERTICAL_ALIGNMENTS, normalize_text_color
from ..background_repair import BackgroundRepair, RepairWorker, save_editor_files
from ..cbz import PROJECT_EXTS
from ..pdf_export import PdfExportWorker
from ..pdf_utils import PdfProcessingError
from ..editor_jobs import LatestJobQueue, read_page, read_project_pages, read_transcript, SaveRequest
from ..lettering_transform import text_transform, transform_layer, outline_width
from ..productivity import STYLE_DEFAULTS, lettering_style, apply_lettering_style
from .color_picker import TextColorPicker
from .paint_filter_dialog import PaintFilterDialog
from .paint_studio_panel import PaintStudioPanel
from .strip_preview import StripPreview
from .thumbnail_loader import ThumbnailLoader
from .theme import color, set_themed_icon, ui_font
from .manga_components import PanelHeading
from .motion import (
    STANDARD,
    fade_in,
    fade_out,
    install_list_motion,
    install_tab_motion,
    play_reveal_overlay,
    play_slide_overlay,
    reduced_motion,
)
from .searchable_combo import SearchableFontCombo
from .favorite_fonts import FavoriteFontBar
from .tool_flow import ToolFlowLayout
from PySide6.QtWidgets import QColorDialog

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


class _BlockItemDelegate(QStyledItemDelegate):
    """Crisp single-row block item with tabular index, elided summary, and right badge."""

    def sizeHint(self, option, index):
        return QSize(max(120, option.rect.width()), 34)

    def paint(self, painter, option, index):
        payload = index.data(Qt.UserRole + 2)
        if not payload:
            super().paint(painter, option, index)
            return
        number, summary, badge, restored = payload
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('muted')))
            painter.drawRoundedRect(rect, 6, 6)
            painter.setBrush(QColor(color('ink')))
            painter.drawRoundedRect(QRect(rect.left(), rect.top() + 5, 3, rect.height() - 10), 1, 1)
        elif hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('workspace')))
            painter.drawRoundedRect(rect, 6, 6)

        num_font = ui_font(12, QFont.Bold if selected else QFont.Normal, mono=True)
        painter.setFont(num_font)
        painter.setPen(QColor(color('ink' if selected else 'secondary')))
        num_rect = QRect(rect.left() + 10, rect.top(), 24, rect.height())
        painter.drawText(num_rect, Qt.AlignVCenter | Qt.AlignLeft, number)

        right_edge = rect.right() - 8
        if badge:
            badge_font = ui_font(11)
            painter.setFont(badge_font)
            fm = painter.fontMetrics()
            badge_w = fm.horizontalAdvance(badge) + (12 if restored else 4)
            badge_rect = QRect(right_edge - badge_w, rect.top() + (rect.height() - 20) // 2, badge_w, 20)
            if restored:
                painter.setPen(QColor(color('rule')))
                painter.setBrush(QColor(color('workspace')))
                painter.drawRoundedRect(badge_rect, 4, 4)
            painter.setPen(QColor(color('secondary')))
            painter.drawText(badge_rect, Qt.AlignCenter, badge)
            right_edge = badge_rect.left() - 6

        text_rect = QRect(num_rect.right() + 6, rect.top(), max(20, right_edge - (num_rect.right() + 6)), rect.height())
        body_font = ui_font(13, QFont.Medium if selected else QFont.Normal)
        painter.setFont(body_font)
        painter.setPen(QColor(color('ink' if not restored or selected else 'secondary')))
        elided = painter.fontMetrics().elidedText(summary, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
        painter.restore()


class EditorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = load_ai_config()
        self.items = []
        self.cleaned_path = self.output_path = None
        self._source_expanded = QSettings().value('ui/editorSourceExpanded', True, type=bool)
        self._source_compact_override = False
        raw_fav_pref = QSettings().value('ui/editorFavoriteBarVisible', None)
        if isinstance(raw_fav_pref, bool):
            self._favorite_bar_pref = raw_fav_pref
        elif isinstance(raw_fav_pref, str) and raw_fav_pref.lower() in ('true', 'false'):
            self._favorite_bar_pref = raw_fav_pref.lower() == 'true'
        else:
            self._favorite_bar_pref = None
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
        self._save_failure_callback = None
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
        self._pending_style_keys = set()
        self._pending_style_rows = []
        self._style_clipboard = None
        self._style_history = []
        self._cleaned_image = None
        self._original_image = None
        self._repair_history = []
        self._repair_redo = []
        self._repair_box = None
        self._fill_color = QColor('#ffffff')
        self._brush_engine = BrushEngine()
        self._selection_engine = SelectionEngine()
        self._paint_canvas_np = None
        self._stroke_session = None
        self._active_stroke_fps_ts = 0.0
        self._paint_shape_points = []
        self._paint_poly_lasso_points = []
        self._paint_curve_points = []
        self._paint_curve_dragging = False
        self._paint_move_start = None
        self._paint_move_base_np = None
        self._paint_move_base_mask = None
        self._clone_source = None
        self._tablet_prev_tool = None
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

    @staticmethod
    def _field_cell(caption, widget):
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(tr(caption))
        label.setProperty('muted', True)
        layout.addWidget(label)
        layout.addWidget(widget)
        return cell

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QFrame()
        body.setObjectName('pageBody')
        root = QVBoxLayout(body)
        root.setContentsMargins(14, 10, 14, 8)
        root.setSpacing(8)
        self._root_layout = root
        outer.addWidget(body, 1)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName('editorToolbar')
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(0, 0, 0, 8)
        toolbar.setSpacing(6)
        self._toolbar_layout = toolbar

        self._pages_toggle = QPushButton(tr('页面'), self)
        self._properties_toggle = QPushButton(tr('编辑面板'), self)
        for button in (self._pages_toggle, self._properties_toggle):
            button.setCheckable(True)
            button.setChecked(True)
            button.setProperty('compact', True)
            button.setProperty('role', 'utility')
            button.hide()

        self._zoom_tool_btn = QPushButton(tr('缩放工具'), self)
        self._zoom_tool_btn.setCheckable(True)
        self._zoom_tool_btn.setProperty('role', 'utility')
        self._zoom_tool_btn.setProperty('compact', True)
        self._zoom_tool_btn.hide()

        self._strip_toggle = QPushButton(tr('连续长条'), self)
        self._strip_toggle.setCheckable(True)
        self._strip_toggle.setProperty('role', 'utility')
        self._strip_toggle.setProperty('compact', True)
        self._strip_toggle.hide()

        self._view_menu_btn = QToolButton()
        self._view_menu_btn.setText(tr('视图'))
        self._view_menu_btn.setProperty('role', 'utility')
        self._view_menu_btn.setProperty('compact', True)
        self._view_menu_btn.setProperty('menuButton', True)
        self._view_menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._view_menu_btn.setToolTip(tr('视图与面板选项'))
        self._view_menu = QMenu(self._view_menu_btn)
        self._view_menu.setToolTipsVisible(True)
        self._pages_action = self._view_menu.addAction(tr('页面栏'))
        self._pages_action.setCheckable(True)
        self._pages_action.setChecked(True)
        self._properties_action = self._view_menu.addAction(tr('编辑面板'))
        self._properties_action.setCheckable(True)
        self._properties_action.setChecked(True)
        self._focus_action = self._view_menu.addAction(tr('专注画布') + '\tCtrl+Shift+F')
        self._focus_action.setCheckable(True)
        self._focus_action.setToolTip(tr('收起侧栏与辅助信息，专注查看作品 · Ctrl+Shift+F'))
        self._view_menu.addSeparator()
        self._strip_action = self._view_menu.addAction(tr('连续长条'))
        self._strip_action.setCheckable(True)
        self._strip_action.setToolTip(tr('纵向滚动浏览所有页面，点击页面后原位精修。'))
        self._zoom_tool_action = self._view_menu.addAction(tr('缩放工具') + '\tZ')
        self._zoom_tool_action.setCheckable(True)
        self._zoom_tool_action.setToolTip(tr('点击放大，Alt+点击缩小 · Z'))
        self._view_menu.addSeparator()
        self._favorite_bar_action = self._view_menu.addAction(tr('快捷字体栏'))
        self._favorite_bar_action.setCheckable(True)
        self._favorite_bar_action.setToolTip(tr('显示或隐藏画布上方的 1–9 快捷字体栏'))
        self._view_menu.addSeparator()
        self._view_menu.addAction(tr('适应页面') + '\tCtrl+0', lambda: self.preview.set_zoom(None))
        self._view_menu.addAction(tr('实际大小 (100%)') + '\tCtrl+1', lambda: self.preview.set_zoom(1.0))
        self._view_menu.addAction(tr('适应宽度') + '\tCtrl+2', lambda: self.preview.set_fit_width())
        self._view_menu_btn.setMenu(self._view_menu)
        toolbar.addWidget(self._view_menu_btn)

        self._focus_btn = QPushButton(tr('退出专注'))
        self._focus_btn.setCheckable(True)
        self._focus_btn.setProperty('role', 'utility')
        self._focus_btn.setProperty('compact', True)
        self._focus_btn.setAccessibleName(tr('专注画布'))
        self._focus_btn.setToolTip(tr('收起侧栏与辅助信息，专注查看作品 · Ctrl+Shift+F'))
        self._focus_btn.hide()
        toolbar.addWidget(self._focus_btn)

        toolbar_div = QFrame()
        toolbar_div.setObjectName('toolbarDivider')
        toolbar_div.setFrameShape(QFrame.VLine)
        toolbar_div.setFixedSize(1, 18)
        toolbar.addWidget(toolbar_div)
        self._zoom_out_btn = QPushButton()
        self._zoom_out_btn.setObjectName('zoomStepBtn')
        set_themed_icon(self._zoom_out_btn, 'minus', size=13)
        self._zoom_out_btn.setProperty('compact', True)
        self._zoom_out_btn.setProperty('role', 'chip')
        self._zoom_out_btn.setFixedWidth(26)
        self._zoom_out_btn.setAccessibleName(tr('缩小'))
        self._zoom_out_btn.setToolTip(tr('缩小 · Ctrl+-'))
        self._zoom_out_btn.clicked.connect(lambda: self.preview.zoom_by(1 / 1.25))
        toolbar.addWidget(self._zoom_out_btn)
        self._zoom = QComboBox()
        for name, value in [(tr('适应页面'), None), ('50%', .5), ('100%', 1.), ('150%', 1.5),
                            ('200%', 2.), (tr('适应宽度'), 'width')]:
            self._zoom.addItem(tr(name), value)
        self._zoom.setEditable(True)
        self._zoom.setInsertPolicy(QComboBox.NoInsert)
        self._zoom.lineEdit().setReadOnly(True)
        self._zoom.lineEdit().setAlignment(Qt.AlignCenter)
        self._zoom.setMinimumWidth(116)
        self._zoom.setToolTip(tr('缩放：Alt+滚轮以光标为中心，空格+拖动平移；Ctrl+0/1/2 适应页面/100%/适应宽度'))
        toolbar.addWidget(self._zoom)
        self._zoom_in_btn = QPushButton()
        self._zoom_in_btn.setObjectName('zoomStepBtn')
        set_themed_icon(self._zoom_in_btn, 'plus', size=13)
        self._zoom_in_btn.setProperty('compact', True)
        self._zoom_in_btn.setProperty('role', 'chip')
        self._zoom_in_btn.setFixedWidth(26)
        self._zoom_in_btn.setAccessibleName(tr('放大'))
        self._zoom_in_btn.setToolTip(tr('放大 · Ctrl+='))
        self._zoom_in_btn.clicked.connect(lambda: self.preview.zoom_by(1.25))
        toolbar.addWidget(self._zoom_in_btn)

        paint_div = QFrame()
        paint_div.setObjectName('toolbarDivider')
        paint_div.setFrameShape(QFrame.VLine)
        paint_div.setFixedSize(1, 18)
        toolbar.addWidget(paint_div)

        self._paint_mode_btn = QPushButton(tr('绘画修图'))
        self._paint_mode_btn.setCheckable(True)
        set_themed_icon(self._paint_mode_btn, 'paint-pen', size=14)
        self._paint_mode_btn.setProperty('compact', True)
        self._paint_mode_btn.setProperty('role', 'chip')
        self._paint_mode_btn.setToolTip(tr('切换画布绘画与选区修图模式（画笔、选区、填充、滤镜）'))
        self._paint_mode_btn.toggled.connect(self._toggle_paint_mode)
        toolbar.addWidget(self._paint_mode_btn)

        toolbar.addStretch()

        self._export_pdf_btn = QPushButton(tr('导出 PDF'), self)
        self._export_pdf_btn.setProperty('role', 'chip')
        self._export_pdf_btn.setProperty('compact', True)
        self._export_pdf_btn.setToolTip(tr('将已保存的图片按页面顺序导出为 PDF；编辑时不会合成 PDF。'))
        self._export_pdf_btn.setEnabled(False)
        self._export_pdf_btn.clicked.connect(self._export_action)
        self._export_pdf_btn.hide()

        self._file_menu_btn = QToolButton()
        self._file_menu_btn.setText(tr('文件'))
        self._file_menu_btn.setProperty('role', 'utility')
        self._file_menu_btn.setProperty('compact', True)
        self._file_menu_btn.setProperty('menuButton', True)
        self._file_menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._file_menu_btn.setToolTip(tr('文件与导出操作'))
        self._file_menu = QMenu(self._file_menu_btn)
        self._file_menu.setToolTipsVisible(True)
        self._import_pages_action = self._file_menu.addAction(tr('导入译图 / PDF'), self._import_pages)
        self._export_pdf_action = self._file_menu.addAction(tr('导出 PDF'), self._export_action)
        self._export_pdf_action.setToolTip(tr('将已保存的图片按页面顺序导出为 PDF；编辑时不会合成 PDF。'))
        self._export_pdf_action.setEnabled(False)
        self._export_cbz_action = self._file_menu.addAction(tr('导出 CBZ'), lambda: self._export_action('cbz'))
        self._export_cbz_action.setToolTip(tr('将已保存的图片按页面顺序打包为 CBZ。'))
        self._export_cbz_action.setEnabled(False)
        self._file_menu.addSeparator()
        self._open_output_action = self._file_menu.addAction(tr('打开输出目录'), self._open_output_dir)
        self._link_original_action = self._file_menu.addAction(tr('关联原图…'), self.link_original)
        self._link_original_action.setToolTip(tr('旧结果缺少原图时，选择该页处理前的同尺寸原图。'))
        self._link_original_action.setEnabled(False)
        self._file_menu_btn.setMenu(self._file_menu)
        toolbar.addWidget(self._file_menu_btn)

        self._save_btn = QPushButton(tr('保存图片'))
        self._save_btn.setProperty('role', 'primary')
        toolbar.addWidget(self._save_btn)
        root.addWidget(toolbar_frame)

        self._favorite_fonts = FavoriteFontBar(self.config)
        self._favorite_fonts.font_selected.connect(self._apply_favorite_font)
        self._favorite_fonts.add_current_requested.connect(self._add_favorite_font)
        self._favorite_fonts.hide_requested.connect(lambda: self._set_favorite_bar_visible(False))
        self._favorite_fonts.slots_changed.connect(self._on_favorite_slots_changed)
        root.addWidget(self._favorite_fonts)

        self._status = QLabel(tr('导入带布局数据的译稿，或从自动处理结果进入精修。'))
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._status.setObjectName('editorStatus')
        self._status.setMaximumHeight(44)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(8)
        self.splitter.setChildrenCollapsible(False)

        self._pages_panel = QFrame()
        self._pages_panel.setObjectName('editorSidebar')
        self._pages_panel.setMinimumWidth(196)
        self._pages_panel.setMaximumWidth(300)
        left = QVBoxLayout(self._pages_panel)
        left.setContentsMargins(10, 8, 10, 8)
        left.setSpacing(8)
        page_head = QHBoxLayout()
        page_head.setContentsMargins(0, 0, 0, 0)
        page_head.setSpacing(6)
        heading = PanelHeading('01', tr('页面'), sidebar=True)
        page_head.addWidget(heading, 1)
        self._page_count_label = QLabel(tr('{_0} 页', _0=0))
        self._page_count_label.setProperty('muted', True)
        self._page_count_label.setFont(ui_font(12, mono=True))
        page_head.addWidget(self._page_count_label)
        left.addLayout(page_head)
        add = QPushButton(tr('导入译图'))
        set_themed_icon(add, 'plus')
        add.setProperty('role', 'chip')
        add.clicked.connect(self._import_pages)
        left.addWidget(add)
        self._transcript_btn = QPushButton(tr('全书译稿'))
        self._transcript_btn.setProperty('role', 'chip')
        self._transcript_btn.setProperty('compact', True)
        self._transcript_btn.setEnabled(False)
        self._transcript_btn.clicked.connect(self.open_transcript)
        left.addWidget(self._transcript_btn)
        self.page_list = QListWidget()
        self.page_list.setObjectName('pageList')
        self.page_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.page_list.viewport().installEventFilter(self)
        self.page_list.verticalScrollBar().valueChanged.connect(lambda: self._thumbnail_timer.start(25))
        self.page_list.setUniformItemSizes(True)
        self.page_list.setIconSize(QSize(56, 72))
        self.page_list.setWordWrap(True)
        self.page_list.setTextElideMode(Qt.ElideMiddle)
        self.page_list.currentItemChanged.connect(self._select_page)
        self.page_list.itemSelectionChanged.connect(self._update_repair_controls)
        install_list_motion(self.page_list)
        left.addWidget(self.page_list, 1)
        sidebar_footer = QFrame()
        sidebar_footer.setObjectName('sidebarFooter')
        page_actions = QHBoxLayout(sidebar_footer)
        page_actions.setContentsMargins(0, 8, 0, 0)
        page_actions.setSpacing(6)
        self._remove_pages_btn = QPushButton(tr('移除选中'))
        self._clear_pages_btn = QPushButton(tr('清空'))
        for button in (self._remove_pages_btn, self._clear_pages_btn):
            button.setProperty('compact', True)
            button.setProperty('role', 'chip')
            page_actions.addWidget(button, 1)
        self._remove_pages_btn.clicked.connect(self._remove_selected_pages)
        self._clear_pages_btn.clicked.connect(self._clear_pages)
        left.addWidget(sidebar_footer)
        self.splitter.addWidget(self._pages_panel)

        canvas = QFrame()
        canvas.setObjectName('canvasPanel')
        # Let the responsive sidebars collapse before long translated actions widen the window.
        canvas.setMinimumWidth(280)
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(4, 0, 4, 0)
        canvas_layout.setSpacing(6)
        self._canvas_heading = PanelHeading('02', tr('页面预览'))
        canvas_layout.addWidget(self._canvas_heading)
        self.preview = StripPreview(import_action=True, illustration='studio-editor-v1.png')
        self._strip_toggle.toggled.connect(self.preview.set_continuous)
        self.preview.page_requested.connect(self._request_canvas_page)
        self.preview.clear(tr('选择一页，开始精修'))
        self.preview._hint.setText(tr('导入带布局数据的译稿，或从自动处理结果进入精修。'))
        self.preview.import_button.setText(tr('导入已翻译的漫画'))
        self.preview.import_requested.connect(self._import_pages)
        self.preview.region_edited.connect(self._resize_region_from_canvas)
        self.preview.region_edit_finished.connect(self.apply_changes)
        self.preview.region_clicked.connect(self._select_block)
        self.preview.region_context_menu.connect(self._show_canvas_bubble_context_menu)
        self.preview.bubble_created.connect(self._add_bubble_from_canvas)
        self.preview.color_picked.connect(self._accept_fill_color)
        self.preview.color_pick_canceled.connect(lambda: self._pick_fill_btn.setChecked(False))
        self.preview.paint_stroke_started.connect(self._on_paint_stroke_started)
        self.preview.paint_stroke_moved.connect(self._on_paint_stroke_moved)
        self.preview.paint_stroke_ended.connect(self._on_paint_stroke_ended)
        self.preview.paint_hover_moved.connect(self._on_paint_hover_moved)
        self.preview.paint_alt_clicked.connect(self._on_paint_alt_clicked)
        self.preview.paint_right_clicked.connect(self._on_paint_right_clicked)
        self.preview.paint_double_clicked.connect(self._on_paint_double_clicked)
        self.preview.paint_canceled.connect(self._on_paint_canceled)
        self.preview.tablet_eraser_changed.connect(self._on_tablet_eraser_changed)
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
        self._zoom_hud_timer.timeout.connect(lambda: fade_out(self._zoom_hud, 160))

        canvas_tools_frame = QFrame()
        canvas_tools_frame.setObjectName('canvasToolBar')
        canvas_tools = ToolFlowLayout(canvas_tools_frame)
        canvas_tools.setContentsMargins(8, 5, 8, 5)
        canvas_tools.setSpacing(5)
        self._repair_mode = QPushButton(tr('框选背景'))
        self._repair_mode.setCheckable(True)
        self._repair_mode.setToolTip(tr('拖动框选修补范围，拖动边角调整；Esc 取消本次拖动。'))
        self._add_bubble_btn = QPushButton(tr('添加气泡框'))
        self._add_bubble_btn.setCheckable(True)
        self._add_bubble_btn.setToolTip(tr('在画布上拖动一个矩形，添加可自由编辑的文字气泡框。'))
        self._repair_btn = QPushButton(tr('修补选区'))
        self._repair_undo = QPushButton(tr('撤回修补'))
        self._repair_undo.setToolTip(tr('优先撤回手动修补；没有手动记录时，还原选中气泡的自动修补与嵌字。旧结果请先关联原图。'))
        for button in (self._repair_mode, self._add_bubble_btn):
            button.setProperty('compact', True)
            button.setProperty('role', 'chip')
            canvas_tools.addWidget(button)
        self._repair_mode.toggled.connect(self._toggle_repair_mode)
        self._add_bubble_btn.toggled.connect(self._toggle_bubble_creation)
        self._repair_btn.clicked.connect(self._start_background_repair)
        self._repair_undo.clicked.connect(self.undo_background_repair)

        tools_div = QFrame()
        tools_div.setObjectName('toolbarDivider')
        tools_div.setProperty('toolDivider', True)
        tools_div.setFrameShape(QFrame.VLine)
        tools_div.setFixedSize(1, 18)
        canvas_tools.addWidget(tools_div)

        self._repair_btn.setProperty('compact', True)
        self._repair_btn.setProperty('role', 'chip')
        canvas_tools.addWidget(self._repair_btn)

        self._fill_menu_btn = QToolButton()
        self._fill_menu_btn.setText(tr('填色'))
        self._fill_menu_btn.setProperty('compact', True)
        self._fill_menu_btn.setProperty('role', 'chip')
        self._fill_menu_btn.setProperty('menuButton', True)
        self._fill_menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._fill_menu_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._fill_menu_btn.setToolTip(tr('背景填色与取色选项'))
        self._fill_menu = QMenu(self._fill_menu_btn)
        self._fill_menu.setToolTipsVisible(True)
        self._fill_white_action = self._fill_menu.addAction(
            tr('填白'), lambda: self._fill_repair_region((255, 255, 255)))
        self._fill_black_action = self._fill_menu.addAction(
            tr('填黑'), lambda: self._fill_repair_region((0, 0, 0)))
        self._fill_custom_action = self._fill_menu.addAction(
            tr('填色'), lambda: self._fill_repair_region(self._fill_color.getRgb()[:3]))
        self._fill_menu.addSeparator()
        self._fill_color_action = self._fill_menu.addAction(
            tr('选择填充颜色…'), self._choose_fill_color)
        self._fill_color_action.setToolTip(tr('点击选择颜色，支持 RGB 与十六进制色值。'))
        self._pick_fill_action = self._fill_menu.addAction(tr('图片取色'))
        self._pick_fill_action.setCheckable(True)
        self._pick_fill_action.setToolTip(tr('点击图片取色；Esc 或右键取消，不会修改图片。'))
        self._fill_menu_btn.setMenu(self._fill_menu)
        canvas_tools.addWidget(self._fill_menu_btn)

        self._pick_cancel_btn = QPushButton(tr('取色中 · 取消'))
        self._pick_cancel_btn.setProperty('compact', True)
        self._pick_cancel_btn.setProperty('role', 'utility')
        self._pick_cancel_btn.setToolTip(tr('点击退出图片取色，或按 Esc / 右键取消。'))
        self._pick_cancel_btn.clicked.connect(lambda: self._pick_fill_btn.setChecked(False))
        self._pick_cancel_btn.hide()
        canvas_tools.addWidget(self._pick_cancel_btn)

        self._repair_undo.setProperty('compact', True)
        self._repair_undo.setProperty('role', 'chip')
        canvas_tools.addWidget(self._repair_undo)

        self._fill_white_btn = QPushButton(tr('填白'), self)
        self._fill_white_btn.setToolTip(tr('把框选区域整块填成白色（可撤回）。'))
        self._fill_black_btn = QPushButton(tr('填黑'), self)
        self._fill_black_btn.setToolTip(tr('把框选区域整块填成黑色（可撤回）。'))
        self._fill_color_btn = QPushButton(self)
        self._fill_color_btn.setAccessibleName(tr('选择填充颜色'))
        self._fill_color_btn.setToolTip(tr('点击选择颜色，支持 RGB 与十六进制色值。'))
        self._fill_color_btn.clicked.connect(self._choose_fill_color)
        self._pick_fill_btn = QPushButton(tr('图片取色'), self)
        self._pick_fill_btn.setCheckable(True)
        self._pick_fill_btn.setToolTip(tr('点击图片取色；Esc 或右键取消，不会修改图片。'))
        self._pick_fill_btn.toggled.connect(self._toggle_fill_color_pick)
        self._fill_custom_btn = QPushButton(tr('填色'), self)
        self._fill_white_btn.clicked.connect(lambda: self._fill_repair_region((255, 255, 255)))
        self._fill_black_btn.clicked.connect(lambda: self._fill_repair_region((0, 0, 0)))
        self._fill_custom_btn.clicked.connect(lambda: self._fill_repair_region(self._fill_color.getRgb()[:3]))
        for button in (self._fill_white_btn, self._fill_black_btn, self._fill_color_btn,
                       self._pick_fill_btn, self._fill_custom_btn):
            button.setProperty('compact', True)
            button.setProperty('role', 'chip')
            button.hide()
        self._refresh_fill_color()
        canvas_layout.addWidget(canvas_tools_frame)
        canvas_layout.addWidget(self.preview, 1)
        self.splitter.addWidget(canvas)

        self._properties_panel = QFrame()
        self._properties_panel.setObjectName('editorInspector')
        self._properties_panel.setMinimumWidth(310)
        self._properties_panel.setMaximumWidth(560)
        inspector_layout = QVBoxLayout(self._properties_panel)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(0)

        inspector_header = QFrame()
        inspector_header.setObjectName('inspectorHeader')
        header_layout = QVBoxLayout(inspector_header)
        header_layout.setContentsMargins(12, 6, 12, 6)
        header_layout.setSpacing(4)
        self._header_layout = header_layout
        self._inspector_heading = PanelHeading('03', tr('文本与排版'), sidebar=True)
        header_layout.addWidget(self._inspector_heading)
        bubble_bar = QHBoxLayout()
        bubble_bar.setContentsMargins(0, 0, 0, 0)
        bubble_bar.setSpacing(5)
        self._block_counter = QLabel(tr('0 块'))
        self._block_counter.setProperty('muted', True)
        self._block_counter.setFont(ui_font(12, mono=True))
        bubble_bar.addWidget(self._block_counter)
        self._prev_block_btn = QToolButton()
        self._prev_block_btn.setObjectName('blockNavBtn')
        set_themed_icon(self._prev_block_btn, 'chevron-left', size=14)
        self._prev_block_btn.setProperty('compact', True)
        self._prev_block_btn.setProperty('role', 'chip')
        self._prev_block_btn.setFixedSize(26, 26)
        self._prev_block_btn.setAccessibleName(tr('上一个文本块 · Alt+↑'))
        self._prev_block_btn.setToolTip(tr('上一个文本块 · Alt+↑'))
        self._prev_block_btn.clicked.connect(lambda: self._step_block(-1))
        bubble_bar.addWidget(self._prev_block_btn)
        self._next_block_btn = QToolButton()
        self._next_block_btn.setObjectName('blockNavBtn')
        set_themed_icon(self._next_block_btn, 'chevron-right', size=14)
        self._next_block_btn.setProperty('compact', True)
        self._next_block_btn.setProperty('role', 'chip')
        self._next_block_btn.setFixedSize(26, 26)
        self._next_block_btn.setAccessibleName(tr('下一个文本块 · Alt+↓'))
        self._next_block_btn.setToolTip(tr('下一个文本块 · Alt+↓'))
        self._next_block_btn.clicked.connect(lambda: self._step_block(1))
        bubble_bar.addWidget(self._next_block_btn)
        bubble_bar.addStretch(1)
        self._restore_bubble_btn = QPushButton(tr('还原此气泡'))
        self._restore_bubble_btn.setProperty('compact', True)
        self._restore_bubble_btn.setProperty('role', 'chip')
        self._restore_bubble_btn.setToolTip(tr('撤销所选气泡的修补与嵌字，恢复处理前的原始像素；可再次恢复处理结果。'))
        self._restore_bubble_btn.clicked.connect(self.toggle_bubble_original)
        bubble_bar.addWidget(self._restore_bubble_btn)
        self._brush_cancel_btn = QPushButton(tr('退出样式刷'))
        self._brush_cancel_btn.setProperty('compact', True)
        self._brush_cancel_btn.setProperty('role', 'chip')
        self._brush_cancel_btn.clicked.connect(self._stop_style_brush)
        self._brush_cancel_btn.hide()
        bubble_bar.addWidget(self._brush_cancel_btn)
        self._bubble_menu_btn = QToolButton()
        self._bubble_menu_btn.setText('⋯')
        self._bubble_menu_btn.setProperty('compact', True)
        self._bubble_menu_btn.setProperty('role', 'chip')
        self._bubble_menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._bubble_menu_btn.setAccessibleName(tr('当前气泡更多操作'))
        self._bubble_menu_btn.setToolTip(tr('当前气泡更多操作'))
        self._bubble_menu = QMenu(self._bubble_menu_btn)
        self._bubble_menu.setToolTipsVisible(True)
        self._bubble_menu.aboutToShow.connect(lambda: self._populate_bubble_menu(self._bubble_menu))
        self._bubble_menu_btn.setMenu(self._bubble_menu)
        bubble_bar.addWidget(self._bubble_menu_btn)
        self._link_original_btn = QPushButton(tr('关联原图'), self)
        self._link_original_btn.setProperty('compact', True)
        self._link_original_btn.setProperty('role', 'chip')
        self._link_original_btn.setToolTip(tr('旧结果缺少原图时，选择该页处理前的同尺寸原图。'))
        self._link_original_btn.clicked.connect(self.link_original)
        self._link_original_btn.hide()
        header_layout.addLayout(bubble_bar)
        inspector_layout.addWidget(inspector_header)

        inspector_body = QWidget()
        body_layout = QVBoxLayout(inspector_body)
        body_layout.setContentsMargins(10, 6, 10, 6)
        body_layout.setSpacing(0)
        self._inspector_body_layout = body_layout
        self.block_list = QListWidget()
        self.block_list.setObjectName('blockList')
        self.block_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.block_list.setMinimumHeight(40)
        self.block_list.setUniformItemSizes(True)
        self.block_list.setMouseTracking(True)
        self.block_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.block_list.customContextMenuRequested.connect(self._show_block_list_context_menu)
        self.block_list.setItemDelegate(_BlockItemDelegate(self.block_list))
        self.block_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.block_list.currentRowChanged.connect(self._load_properties)
        self.block_list.itemSelectionChanged.connect(self._selection_changed)
        self.block_list.itemClicked.connect(self._brush_list_clicked)
        self.preview.regions_selected.connect(self._select_blocks)
        self._copy_style_btn = QPushButton(tr('取样式'), self)
        self._copy_style_btn.setToolTip(tr('复制当前气泡的字体与排版样式，然后点击或框选目标气泡。'))
        self._copy_style_btn.clicked.connect(self.copy_style)
        self._style_brush_btn = QPushButton(tr('样式刷'), self)
        self._style_brush_btn.setCheckable(True)
        self._style_brush_btn.setToolTip(tr('点击目标应用样式；Shift 拖动框选，Ctrl 点击多选；Esc 退出。不会复制译文或气泡位置。'))
        self._undo_style_btn = QPushButton(tr('撤销样式'), self)
        self._undo_style_btn.clicked.connect(self.undo_style)
        for button in (self._copy_style_btn, self._style_brush_btn, self._undo_style_btn):
            button.setProperty('compact', True)
            button.setProperty('role', 'chip')
            button.hide()
        self._brush_escape = QShortcut(QKeySequence('Escape'), self)
        self._brush_escape.setContext(Qt.WidgetWithChildrenShortcut)
        self._brush_escape.setEnabled(False)
        self._brush_escape.activated.connect(self._stop_style_brush)
        self._style_brush_btn.toggled.connect(self._brush_escape.setEnabled)
        self._style_brush_btn.toggled.connect(self._sync_style_brush_ui)
        for button in (self._repair_mode, self._add_bubble_btn, self._pick_fill_btn, self._paint_mode_btn):
            button.toggled.connect(self._stop_style_brush_for_tool)
        install_list_motion(self.block_list)
        self._inspector_tabs = QTabWidget()
        self._inspector_tabs.setDocumentMode(True)
        install_tab_motion(self._inspector_tabs)
        self._inspector_splitter = QSplitter(Qt.Vertical)
        self._inspector_splitter.setObjectName('inspectorSplitter')
        self._inspector_splitter.setChildrenCollapsible(False)
        self._inspector_splitter.setHandleWidth(6)
        self._inspector_splitter.addWidget(self.block_list)
        self._inspector_splitter.addWidget(self._inspector_tabs)
        self._inspector_splitter.setStretchFactor(0, 0)
        self._inspector_splitter.setStretchFactor(1, 1)
        self._inspector_splitter.setSizes([150, 440])
        body_layout.addWidget(self._inspector_splitter, 1)
        inspector_layout.addWidget(inspector_body, 1)

        text_panel = QWidget()
        text_props = QVBoxLayout(text_panel)
        text_props.setContentsMargins(0, 8, 0, 0)
        text_props.setSpacing(6)
        self._text_props_layout = text_props
        self._inspector_tabs.addTab(text_panel, tr('译文编辑'))

        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(6)
        self._source_toggle = QToolButton()
        self._source_toggle.setText(tr('原文'))
        self._source_toggle.setCheckable(True)
        self._source_toggle.setChecked(self._source_expanded)
        self._source_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._source_toggle.setProperty('role', 'quiet')
        self._source_toggle.setProperty('compact', True)
        source_row.addWidget(self._source_toggle)
        self._retranslate_btn = QPushButton(tr('重译气泡'))
        self._retranslate_btn.setProperty('compact', True)
        self._retranslate_btn.setProperty('role', 'chip')
        self._retranslate_btn.setEnabled(False)
        self._retranslate_btn.clicked.connect(self.open_retranslation)
        source_row.addWidget(self._retranslate_btn)
        source_row.addStretch(1)
        quick_size_label = QLabel(tr('字号'))
        quick_size_label.setProperty('muted', True)
        source_row.addWidget(quick_size_label)
        self._quick_size_spin = QSpinBox()
        self._quick_size_spin.setObjectName('quickSizeSpin')
        self._quick_size_spin.setRange(0, 200)
        self._quick_size_spin.setSpecialValueText(tr('自动'))
        self._quick_size_spin.setToolTip(tr('手动字号按实际像素绘制；0 为自动适配蒙版'))
        self._quick_size_spin.setAccessibleName(tr('字号'))
        self._quick_size_spin.setMinimumWidth(72)
        self._quick_size_spin.setMaximumWidth(86)
        source_row.addWidget(self._quick_size_spin)
        text_props.addLayout(source_row)
        self._source_text = QPlainTextEdit()
        self._source_text.setObjectName('textSource')
        self._source_text.setReadOnly(True)
        self._source_text.setFixedHeight(92)
        self._source_text.setFont(ui_font(japanese=True))
        self._source_anim = None
        self._source_anim_gen = 0
        text_props.addWidget(self._source_text)
        self._source_toggle.toggled.connect(self._toggle_source_text)
        target_label = QLabel(tr('译文'))
        target_label.setObjectName('fieldCaption')
        break_row = QHBoxLayout()
        break_row.addWidget(target_label, 1)
        self._line_break_btn = QPushButton(tr('插入换行'))
        self._line_break_btn.setProperty('compact', True)
        self._line_break_btn.setProperty('role', 'chip')
        self._line_break_btn.setToolTip(tr('在光标处插入换行，与 Enter 相同'))
        self._line_break_btn.clicked.connect(self._insert_line_break)
        break_row.addWidget(self._line_break_btn)
        self._expand_btn = QPushButton(tr('全屏编辑'))
        self._expand_btn.setProperty('compact', True)
        self._expand_btn.setProperty('role', 'chip')
        self._expand_btn.setToolTip(tr('在独立窗口中编辑当前气泡的译文 · F2'))
        self._expand_btn.clicked.connect(self.open_text_editor)
        break_row.addWidget(self._expand_btn)
        text_props.addLayout(break_row)
        break_hint = QLabel(tr('Enter 换行 · 竖排时换到左列'))
        break_hint.setWordWrap(True)
        break_hint.setProperty('muted', True)
        self._break_hint = break_hint
        text_props.addWidget(break_hint)
        self._text_input = QPlainTextEdit()
        self._text_input.setObjectName('textInput')
        self._text_input.setMinimumHeight(80)
        self._text_input.setMaximumHeight(16777215)
        self._text_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._text_input.setAccessibleName(tr('译文与手动换行'))
        self._text_input.setPlaceholderText(tr('输入译文，按 Enter 手动换行'))
        self._text_input.setToolTip(tr('Enter 插入硬换行：横排换到下一行，竖排换到左侧下一列；连续回车保留空行或空列。'))
        text_props.addWidget(self._text_input, 1)

        layout_panel = QWidget()
        layout_tab_root = QVBoxLayout(layout_panel)
        layout_tab_root.setContentsMargins(0, 6, 0, 0)
        layout_tab_root.setSpacing(0)
        self._layout_tab_root = layout_tab_root
        self._inspector_tabs.addTab(layout_panel, tr('排版与位置'))

        self._properties_scroll = QScrollArea()
        self._properties_scroll.setObjectName('inspectorScroll')
        self._properties_scroll.setWidgetResizable(True)
        self._properties_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_content = QFrame()
        scroll_content.setObjectName('inspectorScrollContent')
        self._properties_scroll.setWidget(scroll_content)
        layout_tab_root.addWidget(self._properties_scroll, 1)

        props = QVBoxLayout(scroll_content)
        props.setContentsMargins(0, 2, 2, 6)
        props.setSpacing(10)

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
        self._outline_width = QDoubleSpinBox()
        self._outline_width.setRange(-1, 30)
        self._outline_width.setDecimals(1)
        self._outline_width.setSingleStep(1)
        self._outline_width.setSuffix(' px')
        self._outline_width.setSpecialValueText(tr('自动'))
        self._outline_width.setValue(-1)
        self._outline_width.setToolTip(tr('描边宽度按原图像素计算；自动保留原效果，0 为无描边。白边和黑边均可调整。'))
        self._hollow_preset_btn = QPushButton(tr('白字黑边竖排'))
        self._hollow_preset_btn.setProperty('compact', True)
        self._hollow_preset_btn.setProperty('role', 'chip')
        self._hollow_preset_btn.setToolTip(tr('应用示例效果：竖排、白色字心、黑色描边；保留当前字体。'))
        self._hollow_preset_btn.clicked.connect(self._apply_hollow_preset)
        self._text_color = TextColorPicker()
        self._text_color.setAccessibleName(tr('当前文本块文字颜色'))
        self._text_color.setToolTip(tr('只修改当前文本块；默认黑字，空心效果默认白字。自选颜色保留描边效果。'))
        self._text_scale_x, self._text_scale_y = QSpinBox(), QSpinBox()
        for spin in (self._text_scale_x, self._text_scale_y):
            spin.setRange(10, 400)
            spin.setValue(100)
            spin.setSuffix(' %')
            spin.setToolTip(tr('以文字中心拉伸；100% 保持原样，不改变换行与蒙版。'))
        self._text_rotation = QDoubleSpinBox()
        self._text_rotation.setRange(-180, 180)
        self._text_rotation.setDecimals(1)
        self._text_rotation.setSuffix('°')
        self._text_rotation.setToolTip(tr('以文字中心旋转；正数顺时针，负数逆时针。'))
        self._reset_transform_btn = QPushButton(tr('重置文字变形'))
        self._reset_transform_btn.setProperty('compact', True)
        self._reset_transform_btn.setProperty('role', 'chip')
        self._reset_transform_btn.clicked.connect(self._reset_text_transform)

        type_card = QFrame()
        type_card.setObjectName('inspectorCard')
        type_layout = QVBoxLayout(type_card)
        type_layout.setContentsMargins(8, 8, 8, 8)
        type_layout.setSpacing(6)
        type_title = QLabel(tr('字体与排版'))
        type_title.setObjectName('cardTitle')
        type_layout.addWidget(type_title)
        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        font_label = QLabel(tr('字体'))
        font_label.setProperty('muted', True)
        font_row.addWidget(font_label)
        font_row.addStretch(1)
        self._font_menu_btn = QToolButton()
        self._font_menu_btn.setText(tr('字体管理'))
        self._font_menu_btn.setProperty('compact', True)
        self._font_menu_btn.setProperty('role', 'chip')
        self._font_menu_btn.setProperty('menuButton', True)
        self._font_menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._font_menu_btn.setToolTip(tr('字体库、导入与快捷字体管理'))
        self._font_menu = QMenu(self._font_menu_btn)
        self._font_menu.setToolTipsVisible(True)
        self._font_library_action = self._font_menu.addAction(tr('字体库…'), self._open_font_library)
        self._import_font_action = self._font_menu.addAction(tr('导入本地字体…'), self._import_local_fonts)
        self._font_menu.addSeparator()
        self._add_favorite_action = self._font_menu.addAction(tr('将当前字体加入快捷字体'), self._add_favorite_font)
        self._configure_favorites_action = self._font_menu.addAction(tr('设置快捷字体…'), self._favorite_fonts.configure)
        self._font_menu_show_bar_action = self._font_menu.addAction(tr('快捷字体栏'))
        self._font_menu_show_bar_action.setCheckable(True)
        self._font_menu_btn.setMenu(self._font_menu)
        font_row.addWidget(self._font_menu_btn)
        self._font_library_btn = QPushButton(tr('字体库'), self)
        self._font_library_btn.setProperty('compact', True)
        self._font_library_btn.setProperty('role', 'chip')
        self._font_library_btn.clicked.connect(self._open_font_library)
        self._font_library_btn.hide()
        type_layout.addLayout(font_row)
        type_layout.addWidget(self._style_combo)
        type_layout.addWidget(self._font_name_label)
        type_grid = QGridLayout()
        type_grid.setContentsMargins(0, 1, 0, 1)
        type_grid.setHorizontalSpacing(10)
        type_grid.setVerticalSpacing(5)
        type_grid.setColumnStretch(0, 1)
        type_grid.setColumnStretch(1, 1)
        type_grid.addWidget(self._field_cell('字号', self._size_spin), 0, 0)
        type_grid.addWidget(self._field_cell('排版方向', self._direction_combo), 0, 1)
        type_layout.addLayout(type_grid)
        type_layout.addWidget(self._field_cell('文字颜色', self._text_color))

        self._advanced_style_toggle = QToolButton()
        self._advanced_style_toggle.setText(tr('高级样式（描边 · 变形）'))
        self._advanced_style_toggle.setCheckable(True)
        self._advanced_style_toggle.setChecked(False)
        self._advanced_style_toggle.setArrowType(Qt.RightArrow)
        self._advanced_style_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._advanced_style_toggle.setProperty('role', 'quiet')
        self._advanced_style_toggle.setProperty('compact', True)
        self._advanced_style_toggle.toggled.connect(self._toggle_advanced_style)
        type_layout.addWidget(self._advanced_style_toggle)

        self._advanced_style_panel = QWidget()
        adv_layout = QVBoxLayout(self._advanced_style_panel)
        adv_layout.setContentsMargins(0, 2, 0, 0)
        adv_layout.setSpacing(6)
        adv_layout.addWidget(self._field_cell('文字效果', self._effect_combo))
        outline_grid = QGridLayout()
        outline_grid.setContentsMargins(0, 1, 0, 1)
        outline_grid.setHorizontalSpacing(10)
        outline_grid.setVerticalSpacing(5)
        outline_grid.setColumnStretch(0, 1)
        outline_grid.setColumnStretch(1, 1)
        outline_grid.addWidget(self._field_cell('竖排列对齐', self._vertical_alignment_combo), 0, 0)
        outline_grid.addWidget(self._field_cell('描边大小', self._outline_width), 0, 1)
        adv_layout.addLayout(outline_grid)
        preset_row = QHBoxLayout()
        preset_row.addWidget(self._hollow_preset_btn)
        preset_row.addStretch(1)
        adv_layout.addLayout(preset_row)
        transform_grid = QGridLayout()
        transform_grid.setContentsMargins(0, 1, 0, 1)
        transform_grid.setHorizontalSpacing(10)
        transform_grid.setVerticalSpacing(4)
        transform_grid.setColumnStretch(0, 1)
        transform_grid.setColumnStretch(1, 1)
        transform_grid.addWidget(self._field_cell('横向拉伸', self._text_scale_x), 0, 0)
        transform_grid.addWidget(self._field_cell('纵向拉伸', self._text_scale_y), 0, 1)
        transform_grid.addWidget(self._field_cell('文字旋转', self._text_rotation), 1, 0)
        reset_cell = QWidget()
        reset_cell_layout = QVBoxLayout(reset_cell)
        reset_cell_layout.setContentsMargins(0, 0, 0, 0)
        reset_cell_layout.setSpacing(3)
        reset_cell_layout.addStretch(1)
        reset_cell_layout.addWidget(self._reset_transform_btn)
        transform_grid.addWidget(reset_cell, 1, 1)
        adv_layout.addLayout(transform_grid)
        self._advanced_style_panel.setVisible(False)
        type_layout.addWidget(self._advanced_style_panel)
        props.addWidget(type_card)

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

        geo_card = QFrame()
        geo_card.setObjectName('inspectorCard')
        geo_layout = QVBoxLayout(geo_card)
        geo_layout.setContentsMargins(8, 8, 8, 8)
        geo_layout.setSpacing(5)
        geo_title = QLabel(tr('位置与蒙版'))
        geo_title.setObjectName('cardTitle')
        geo_layout.addWidget(geo_title)
        geo_grid = QGridLayout()
        geo_grid.setContentsMargins(0, 1, 0, 1)
        geo_grid.setHorizontalSpacing(10)
        geo_grid.setVerticalSpacing(4)
        geo_grid.setColumnStretch(0, 1)
        geo_grid.setColumnStretch(1, 1)
        geo_grid.addWidget(self._field_cell('X 偏移', self._offset_x), 0, 0)
        geo_grid.addWidget(self._field_cell('Y 偏移', self._offset_y), 0, 1)
        geo_grid.addWidget(self._field_cell('蒙版宽度', self._mask_width), 1, 0)
        geo_grid.addWidget(self._field_cell('蒙版高度', self._mask_height), 1, 1)
        for spin in (self._size_spin, self._offset_x, self._offset_y, self._mask_width, self._mask_height,
                     self._text_scale_x, self._text_scale_y, self._text_rotation, self._outline_width):
            spin.setMinimumWidth(64)
            spin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        for combo in (self._direction_combo, self._vertical_alignment_combo, self._effect_combo):
            combo.setMinimumWidth(64)
            combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        type_grid.setHorizontalSpacing(6)
        outline_grid.setHorizontalSpacing(6)
        transform_grid.setHorizontalSpacing(6)
        geo_grid.setHorizontalSpacing(6)
        geo_layout.addLayout(geo_grid)
        geo_layout.addWidget(self._show_mask)
        geo_layout.addWidget(self._box_label)
        drag_hint = QLabel(tr('拖动蒙版边角调整大小，框内拖动位置'))
        drag_hint.setWordWrap(True)
        drag_hint.setProperty('muted', True)
        geo_layout.addWidget(drag_hint)
        props.addWidget(geo_card)
        props.addStretch(1)

        paint_tab = QWidget()
        paint_tab_root = QVBoxLayout(paint_tab)
        paint_tab_root.setContentsMargins(0, 6, 0, 0)
        paint_tab_root.setSpacing(0)
        self._paint_tab_root = paint_tab_root
        self._paint_scroll = QScrollArea()
        self._paint_scroll.setObjectName('inspectorScroll')
        self._paint_scroll.setWidgetResizable(True)
        self._paint_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._paint_panel = PaintStudioPanel()
        self._paint_scroll.setWidget(self._paint_panel)
        paint_tab_root.addWidget(self._paint_scroll, 1)
        self._inspector_tabs.addTab(paint_tab, tr('绘画修图'))
        self._inspector_tabs.currentChanged.connect(self._on_inspector_tab_changed)
        self._paint_panel.tool_changed.connect(self._on_paint_tool_changed)
        self._paint_panel.settings_changed.connect(self._on_paint_settings_changed)
        self._paint_panel.selection_action.connect(self._on_paint_selection_action)
        self._paint_panel.view_changed.connect(self._on_paint_view_changed)
        self._paint_panel.filter_requested.connect(self._on_paint_filter_requested)
        self._paint_panel.status_message.connect(self._status.setText)

        self._apply_btn = QPushButton(tr('刷新预览'))
        self._apply_btn.setProperty('compact', True)
        self._apply_btn.setProperty('role', 'chip')
        inspector_actions = QFrame()
        inspector_actions.setObjectName('inspectorActions')
        actions_layout = QHBoxLayout(inspector_actions)
        actions_layout.setContentsMargins(12, 8, 12, 8)
        self._inspector_actions_layout = actions_layout
        hint = QLabel(tr('修改实时预览 · Ctrl+S 保存图片'))
        hint.setProperty('muted', True)
        hint.setWordWrap(True)
        self._inspector_hint = hint
        actions_layout.addWidget(hint, 1)
        self._inspector_spacer = QWidget()
        self._inspector_spacer.setVisible(False)
        actions_layout.addWidget(self._inspector_spacer, 1)
        actions_layout.addWidget(self._apply_btn)
        inspector_layout.addWidget(inspector_actions)

        self.splitter.addWidget(self._properties_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([216, 740, 420])
        root.addWidget(self.splitter, 1)
        root.addWidget(self._status)
        self._pages_toggle.toggled.connect(lambda checked: self._choose_panel(0, checked))
        self._properties_toggle.toggled.connect(lambda checked: self._choose_panel(1, checked))
        self._pages_action.toggled.connect(self._pages_toggle.setChecked)
        self._properties_action.toggled.connect(self._properties_toggle.setChecked)
        self._focus_btn.toggled.connect(self._toggle_canvas_focus)
        self._focus_action.toggled.connect(self._focus_btn.setChecked)
        self._strip_toggle.toggled.connect(self._sync_strip_action)
        self._strip_action.toggled.connect(self._strip_toggle.setChecked)
        self._zoom_tool_btn.toggled.connect(self._sync_zoom_tool_action)
        self._zoom_tool_action.toggled.connect(self._zoom_tool_btn.setChecked)
        self._favorite_bar_action.toggled.connect(self._set_favorite_bar_visible)
        self._font_menu_show_bar_action.toggled.connect(self._set_favorite_bar_visible)
        self._pick_fill_btn.toggled.connect(self._sync_pick_fill_ui)
        self._pick_fill_action.toggled.connect(self._pick_fill_btn.setChecked)
        self._zoom.currentIndexChanged.connect(self._zoom_selected)
        self.preview.zoom_changed.connect(self._sync_zoom_display)
        self._apply_btn.clicked.connect(self.apply_changes)
        self._save_btn.clicked.connect(self.request_save)
        self._text_input.textChanged.connect(self._schedule_preview)
        self._style_combo.currentIndexChanged.connect(self._font_selection_changed)
        self._size_spin.valueChanged.connect(self._sync_quick_size)
        self._quick_size_spin.valueChanged.connect(self._size_spin.setValue)
        self._direction_combo.currentIndexChanged.connect(self._schedule_preview)
        self._direction_combo.currentIndexChanged.connect(self._update_vertical_alignment_enabled)
        self._vertical_alignment_combo.currentIndexChanged.connect(self._schedule_preview)
        self._vertical_alignment_combo.currentIndexChanged.connect(self._update_advanced_style_badge)
        self._effect_combo.currentIndexChanged.connect(self._schedule_preview)
        self._effect_combo.currentIndexChanged.connect(self._update_color_default)
        self._effect_combo.currentIndexChanged.connect(self._update_advanced_style_badge)
        self._text_color.color_changed.connect(self._schedule_preview)
        for spin in self._layout_spins():
            spin.valueChanged.connect(self._schedule_preview)
        style_controls = (
            (self._style_combo, self._style_combo.currentIndexChanged, ('style', 'font_reference')),
            (self._size_spin, self._size_spin.valueChanged, ('font_size',)),
            (self._direction_combo, self._direction_combo.currentIndexChanged, ('direction',)),
            (self._effect_combo, self._effect_combo.currentIndexChanged, ('text_effect',)),
            (self._vertical_alignment_combo, self._vertical_alignment_combo.currentIndexChanged, ('vertical_alignment',)),
            (self._text_color, self._text_color.color_changed, ('text_color',)),
            (self._text_scale_x, self._text_scale_x.valueChanged, ('text_scale_x',)),
            (self._text_scale_y, self._text_scale_y.valueChanged, ('text_scale_y',)),
            (self._text_rotation, self._text_rotation.valueChanged, ('text_rotation',)),
            (self._outline_width, self._outline_width.valueChanged, ('outline_width',)),
        )
        self._style_control_fields = {widget: keys for widget, signal, keys in style_controls}
        for widget, signal, keys in style_controls:
            signal.connect(self._note_style_control_changed)
        for widget in (self._outline_width, self._text_scale_x, self._text_scale_y, self._text_rotation):
            widget.valueChanged.connect(self._update_advanced_style_badge)
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
        self._block_nav_shortcuts = []
        for keys, delta in (('Alt+Up', -1), ('Alt+Down', 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda d=delta: self._step_block(d))
            self._block_nav_shortcuts.append(shortcut)
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
        inspector_state = settings.value('ui/editorInspectorSplitter')
        if inspector_state is not None:
            self._inspector_splitter.restoreState(inspector_state)
        self._desired_panels = [settings.value('ui/editorPages', True, type=bool),
                                settings.value('ui/editorProperties', True, type=bool)]
        self._apply_panel_layout()
        self._sync_favorite_bar_visibility()
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
            was_visible = self._zoom_hud.isVisible()
            self._zoom_hud.show()
            if not was_visible:
                fade_in(self._zoom_hud, 110)
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

    def _sync_strip_action(self, checked):
        self._strip_action.blockSignals(True)
        self._strip_action.setChecked(checked)
        self._strip_action.blockSignals(False)

    def _sync_zoom_tool_action(self, checked):
        self._zoom_tool_action.blockSignals(True)
        self._zoom_tool_action.setChecked(checked)
        self._zoom_tool_action.blockSignals(False)

    def _sync_pick_fill_ui(self, checked):
        self._pick_fill_action.blockSignals(True)
        self._pick_fill_action.setChecked(checked)
        self._pick_fill_action.blockSignals(False)
        self._pick_cancel_btn.setVisible(bool(checked))

    def _sync_quick_size(self, value):
        self._quick_size_spin.blockSignals(True)
        self._quick_size_spin.setValue(value)
        self._quick_size_spin.blockSignals(False)

    def _set_favorite_bar_visible(self, visible):
        self._favorite_bar_pref = bool(visible)
        QSettings().setValue('ui/editorFavoriteBarVisible', self._favorite_bar_pref)
        self._sync_favorite_bar_visibility()

    def _on_favorite_slots_changed(self, has_active):
        if has_active and self._favorite_bar_pref is False:
            return
        self._sync_favorite_bar_visibility()

    def _sync_favorite_bar_visibility(self):
        focused = self._focus_btn.isChecked()
        preferred = (
            self._favorite_bar_pref
            if self._favorite_bar_pref is not None
            else self._favorite_fonts.has_active_slots()
        )
        self._favorite_fonts.setVisible(bool(preferred) and not focused)
        for action in (self._favorite_bar_action, self._font_menu_show_bar_action):
            action.blockSignals(True)
            action.setChecked(bool(preferred))
            action.blockSignals(False)

    def _toggle_advanced_style(self, expanded):
        self._advanced_style_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._advanced_style_panel.setVisible(bool(expanded))

    def _update_advanced_style_badge(self):
        customized = (
            self._effect_combo.currentData() not in (None, 'auto')
            or self._vertical_alignment_combo.currentData() not in (None, 'center')
            or self._outline_width.value() >= 0
            or self._text_scale_x.value() != 100
            or self._text_scale_y.value() != 100
            or abs(self._text_rotation.value()) > 1e-6
        )
        self._advanced_style_toggle.setText(
            tr('高级样式 · 已自定义') if customized else tr('高级样式（描边 · 变形）')
        )

    def _sync_export_pdf_state(self, *, enabled=None, text=None, tooltip=None):
        if enabled is not None:
            self._export_pdf_btn.setEnabled(enabled)
            self._export_pdf_action.setEnabled(enabled)
        if text is not None:
            self._export_pdf_btn.setText(text)
            self._export_pdf_action.setText(text)
        if tooltip is not None:
            self._export_pdf_btn.setToolTip(tooltip)
            self._export_pdf_action.setToolTip(tooltip)

    def _open_output_dir(self):
        target = None
        if self.output_path is not None and self.output_path.parent.is_dir():
            target = self.output_path.parent
        else:
            configured = Path(str(self.config.get('page_output_dir', '') or ''))
            if str(configured) and configured.is_dir():
                target = configured
        if target is None:
            self._status.setText(tr('输出目录不存在或尚未生成。'))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _show_block_list_context_menu(self, pos):
        item = self.block_list.itemAt(pos)
        if item is not None:
            row = self.block_list.row(item)
            self._focus_context_bubble(row)
        if 0 <= self._loaded_row < len(self.items):
            self._show_bubble_context_menu(self.block_list.viewport().mapToGlobal(pos))

    def _show_canvas_bubble_context_menu(self, index, global_pos):
        if not 0 <= index < len(self.items):
            return
        self._focus_context_bubble(index)
        self._show_bubble_context_menu(global_pos)

    def _focus_context_bubble(self, index):
        # Right-clicking an existing member keeps the batch selection and never paints.
        if index in self.selected_blocks():
            self.block_list.setCurrentRow(index, QItemSelectionModel.NoUpdate)
        else:
            self.block_list.setCurrentRow(index)

    def _show_bubble_context_menu(self, global_pos):
        if not 0 <= self._loaded_row < len(self.items):
            return
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        self._populate_bubble_menu(menu)
        menu.exec(global_pos)

    def _populate_bubble_menu(self, menu):
        menu.clear()
        busy = (self._repair_worker is not None or self._export_worker is not None
                or self._save_jobs.busy or self.page_io_busy)
        ready = self._cleaned_image is not None and not busy
        selected = 0 <= self._loaded_row < len(self.items)
        restored = selected and bool(self.items[self._loaded_row].get('restore_original'))
        editable = ready and selected and not restored

        edit_act = menu.addAction(tr('全屏编辑译文') + '\tF2', self.open_text_editor)
        edit_act.setEnabled(editable)
        restore_label = tr('恢复处理结果') if restored else tr('还原此气泡')
        restore_act = menu.addAction(restore_label, self.toggle_bubble_original)
        restore_act.setEnabled(ready and selected)
        menu.addSeparator()
        lib_act = menu.addAction(tr('字体库…'), self._open_font_library)
        lib_act.setEnabled(editable)
        fav_act = menu.addAction(tr('将当前字体加入快捷字体'), self._add_favorite_font)
        fav_act.setEnabled(editable)
        hollow_act = menu.addAction(tr('白字黑边竖排'), self._apply_hollow_preset)
        hollow_act.setEnabled(editable)
        reset_act = menu.addAction(tr('重置文字变形'), self._reset_text_transform)
        reset_act.setEnabled(editable)
        menu.addSeparator()
        style_copy = menu.addAction(tr('取样式'), self.copy_style)
        style_copy.setEnabled(editable)
        rows = self.selected_blocks() or ([self._loaded_row] if selected else [])
        paste_style = menu.addAction(tr('应用样式到所选气泡'), self._paste_selected_style)
        paste_style.setEnabled(ready and self._style_clipboard is not None
                               and any(not self.items[row].get('restore_original') for row in rows))
        paste_style.setToolTip(tr('仅应用字体与排版；保留译文和位置，跳过已还原原图的气泡。'))
        brush_style = menu.addAction(tr('样式刷'))
        brush_style.setCheckable(True)
        brush_style.setChecked(self._style_brush_btn.isChecked())
        brush_style.setEnabled(ready and self._style_clipboard is not None)
        brush_style.toggled.connect(self._style_brush_btn.setChecked)
        undo_style = menu.addAction(tr('撤销样式'), self.undo_style)
        undo_style.setEnabled(ready and bool(self._style_history))
        menu.addSeparator()
        link_act = menu.addAction(tr('关联原图…'), self.link_original)
        link_act.setEnabled(ready)

    def save_ui_state(self):
        settings = QSettings()
        focus_state = self._focus_splitter_state if (self._focus_btn.isChecked() and hasattr(self, '_focus_splitter_state')) else self.splitter.saveState()
        settings.setValue('ui/editorSplitter', self._wide_splitter_state or focus_state)
        settings.setValue('ui/editorInspectorSplitter', self._inspector_splitter.saveState())
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

    def _apply_panel_layout(self, *, animate=True):
        focused = self._focus_btn.isChecked()
        compact = self.isVisible() and self.width() < 1120
        if compact and not self._was_compact and not focused:
            self._wide_splitter_state = self.splitter.saveState()
        effective = list(self._desired_panels)
        if focused:
            effective = [False, False]
        elif compact and all(effective):
            effective[1 - self._panel_priority] = False
        for index, (button, action, panel) in enumerate((
            (self._pages_toggle, self._pages_action, self._pages_panel),
            (self._properties_toggle, self._properties_action, self._properties_panel),
        )):
            button.blockSignals(True)
            button.setChecked(effective[index])
            button.blockSignals(False)
            action.blockSignals(True)
            action.setChecked(effective[index])
            action.blockSignals(False)
            was_visible = panel.isVisible()
            want_visible = effective[index]
            if animate and self.isVisible() and was_visible != want_visible:
                edge = 'left' if index == 0 else 'right'
                if want_visible:
                    panel.setVisible(True)
                    play_reveal_overlay(panel, edge=edge, duration=190)
                else:
                    play_slide_overlay(panel, edge=edge, duration=160)
                    panel.setVisible(False)
            else:
                panel.setVisible(want_visible)
            tip = (tr('窗口较窄时暂时收起；展开此栏会让出另一个侧栏的位置。')
                   if self._desired_panels[index] and not effective[index] and not focused else '')
            button.setToolTip(tip)
            action.setToolTip(tip)
        if compact and not focused:
            avail = max(400, self.width() - 36)
            left_w = 210 if effective[0] else 0
            right_w = min(328, max(310, avail // 3)) if effective[1] else 0
            center_w = max(280, avail - left_w - right_w)
            self.splitter.setSizes([left_w, center_w, right_w])
        elif not compact and self._was_compact and not focused and self._wide_splitter_state is not None:
            self.splitter.restoreState(self._wide_splitter_state)
            self._wide_splitter_state = None
        self._was_compact = compact

    def _toggle_canvas_focus(self, focused):
        if focused:
            self._focus_splitter_state = self.splitter.saveState()
            self._apply_panel_layout()
        else:
            if hasattr(self, '_focus_splitter_state'):
                self.splitter.restoreState(self._focus_splitter_state)
            self._apply_panel_layout()
        self._focus_action.blockSignals(True)
        self._focus_action.setChecked(focused)
        self._focus_action.blockSignals(False)
        self._focus_btn.setVisible(focused)
        for widget, edge, slide_hide in (
            (self._canvas_heading, 'top', True),
            (self._status, 'bottom', True),
        ):
            want_visible = not focused and (widget is not self._canvas_heading or self.height() >= 680)
            was_visible = widget.isVisible()
            if self.isVisible() and was_visible != want_visible:
                if want_visible:
                    widget.setVisible(True)
                    play_reveal_overlay(widget, edge=edge, duration=155)
                else:
                    if slide_hide:
                        play_slide_overlay(widget, edge=edge, duration=135)
                    widget.setVisible(False)
            else:
                widget.setVisible(want_visible)
        self._sync_favorite_bar_visibility()
        self._update_toolbar_labels()

    def _update_toolbar_labels(self):
        narrow = self.width() < 920
        self._save_btn.setText(tr('保存') if narrow else tr('保存图片'))
        self._save_btn.setAccessibleName(tr('保存图片'))
        self._focus_btn.setText(tr('退出专注'))
        self._focus_btn.setAccessibleName(tr('专注画布'))

    def _toggle_source_text(self, expanded):
        self._source_expanded = expanded
        self._source_compact_override = expanded and self.height() < 680
        QSettings().setValue('ui/editorSourceExpanded', expanded)
        self._apply_source_layout()

    def _reveal_text_editor(self):
        # The block list sits in the upper splitter pane while the editor tabs
        # stay anchored below it; keep the inspector split balanced on short windows.
        if not self.isVisible() or self._loaded_row < 0:
            return
        self._sync_inspector_split()

    def _sync_inspector_split(self):
        compact_h = self.height() < 680
        very_short = self.height() < 500
        if hasattr(self, '_canvas_heading'):
            self._canvas_heading.setVisible(not compact_h and not self._focus_btn.isChecked())
        if hasattr(self, '_inspector_heading'):
            self._inspector_heading.setVisible(not compact_h)
        if hasattr(self, '_root_layout'):
            self._root_layout.setContentsMargins(10 if compact_h else 14, 4 if compact_h else 10, 10 if compact_h else 14, 4 if compact_h else 8)
            self._root_layout.setSpacing(4 if compact_h else 8)
            self._toolbar_layout.setContentsMargins(0, 0, 0, 4 if compact_h else 8)
            self._header_layout.setContentsMargins(10 if compact_h else 12, 3 if compact_h else 6, 10 if compact_h else 12, 3 if compact_h else 6)
            self._inspector_body_layout.setContentsMargins(8 if compact_h else 10, 2 if compact_h else 6, 8 if compact_h else 10, 2 if compact_h else 6)
            self._text_props_layout.setContentsMargins(0, 4 if compact_h else 8, 0, 0)
            self._text_props_layout.setSpacing(4 if compact_h else 6)
            self._layout_tab_root.setContentsMargins(0, 2 if compact_h else 6, 0, 0)
            if hasattr(self, '_paint_tab_root'):
                self._paint_tab_root.setContentsMargins(0, 2 if compact_h else 6, 0, 0)
            self._inspector_actions_layout.setContentsMargins(10 if compact_h else 12, 3 if compact_h else 8, 10 if compact_h else 12, 3 if compact_h else 8)
            self._break_hint.setVisible(not compact_h)
            self._inspector_hint.setVisible(not compact_h)
            self._inspector_spacer.setVisible(compact_h)
            self._text_input.setMinimumHeight(42 if very_short else 72 if compact_h else 88)
        self._inspector_splitter.setHandleWidth(4 if very_short else 6)
        self.block_list.setMinimumHeight(38 if very_short else 68 if compact_h else 104)
        total = sum(self._inspector_splitter.sizes())
        if total <= 0:
            return
        if very_short:
            list_h = 38 if self.height() < 460 else 42
            self._inspector_splitter.setSizes([list_h, max(120, total - list_h)])
        elif compact_h:
            list_h = min(92, max(68, total // 4))
            self._inspector_splitter.setSizes([list_h, max(180, total - list_h)])
        elif self._inspector_splitter.sizes()[0] < 104 or self._inspector_splitter.sizes()[0] > total // 2:
            list_h = min(148, max(104, total // 4))
            self._inspector_splitter.setSizes([list_h, max(200, total - list_h)])

    def _step_block(self, delta):
        if not self.items:
            return
        row = self._loaded_row if 0 <= self._loaded_row < len(self.items) else 0
        target = max(0, min(len(self.items) - 1, row + delta))
        if target != self.block_list.currentRow():
            self.block_list.setCurrentRow(target)
            item = self.block_list.item(target)
            if item is not None:
                self.block_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def _refresh_page_counter(self):
        if hasattr(self, '_page_count_label'):
            self._page_count_label.setText(tr('{_0} 页', _0=self.page_list.count()))

    def _refresh_block_counter(self):
        if not hasattr(self, '_block_counter'):
            return
        total = len(self.items)
        if len(self.selected_blocks()) > 1:
            self._block_counter.setText(tr('已选 {_0} / {_1}', _0=len(self.selected_blocks()), _1=total))
        elif total and 0 <= self._loaded_row < total:
            self._block_counter.setText(tr('{_0} / {_1}', _0=self._loaded_row + 1, _1=total))
        elif total:
            self._block_counter.setText(tr('{_0} 块', _0=total))
        else:
            self._block_counter.setText(tr('0 块'))
        self._prev_block_btn.setEnabled(total > 1 and self._loaded_row > 0)
        self._next_block_btn.setEnabled(total > 1 and 0 <= self._loaded_row < total - 1)

    def _apply_source_layout(self, *, animate=True):
        compact_h = self.isVisible() and self.height() < 680
        target_h = 52 if compact_h else 84
        expanded = self._source_expanded and (not compact_h or self._source_compact_override)
        self._source_toggle.blockSignals(True)
        self._source_toggle.setChecked(expanded)
        self._source_toggle.blockSignals(False)
        self._source_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        if getattr(self, '_source_anim', None) is not None:
            self._source_anim.stop()
            self._source_anim.deleteLater()
            self._source_anim = None
        self._source_anim_gen += 1
        gen = self._source_anim_gen

        if not animate or not self.isVisible() or reduced_motion():
            self._source_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self._source_text.setFixedHeight(target_h if expanded else 0)
            self._source_text.setVisible(expanded)
            return

        was_visible = self._source_text.isVisible()
        if was_visible == expanded and self._source_text.height() == (target_h if expanded else 0):
            return

        start_h = self._source_text.height() if was_visible else 0
        end_h = target_h if expanded else 0
        self._source_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._source_text.setVisible(True)
        self._source_text.setFixedHeight(start_h)

        anim = QVariantAnimation(self)
        anim.setDuration(195 if expanded else 160)
        anim.setStartValue(float(start_h))
        anim.setEndValue(float(end_h))
        anim.setEasingCurve(STANDARD)

        def _on_val(val):
            if gen != self._source_anim_gen:
                return
            self._source_text.setFixedHeight(max(0, int(round(float(val)))))

        def _on_done():
            if gen != self._source_anim_gen:
                return
            self._source_anim = None
            self._source_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            if expanded:
                self._source_text.setFixedHeight(target_h)
                self._source_text.setVisible(True)
            else:
                self._source_text.setFixedHeight(0)
                self._source_text.setVisible(False)

        anim.valueChanged.connect(_on_val)
        anim.finished.connect(_on_done)
        self._source_anim = anim
        anim.start()

    def _set_editable(self, enabled):
        restored = 0 <= self._loaded_row < len(self.items) and self.items[self._loaded_row].get('restore_original', False)
        active = enabled and not restored
        for widget in (self._text_input, self._line_break_btn, self._quick_size_spin, self._style_combo,
                       self._font_menu_btn, self._font_library_btn, self._direction_combo,
                       self._vertical_alignment_combo, self._effect_combo, self._text_color,
                       self._hollow_preset_btn, self._reset_transform_btn, *self._layout_spins(),
                       self._show_mask, self._apply_btn, self._save_btn):
            widget.setEnabled(active)
        for action in (self._font_library_action, self._import_font_action, self._add_favorite_action):
            action.setEnabled(active)
        self._show_mask.setEnabled(enabled)
        self._copy_style_btn.setEnabled(enabled and not restored)
        self._style_brush_btn.setEnabled(enabled and self._style_clipboard is not None)
        self._undo_style_btn.setEnabled(enabled and bool(self._style_history))
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

    def _import_local_fonts(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr('导入漫画译文字体'), '', tr('字体 (*.ttf *.otf *.ttc *.otc)'))
        if not paths:
            return []
        imported, failures = [], []
        for path in paths:
            try:
                imported.append(import_font(path))
            except Exception as exc:
                failures.append(f'{Path(path).name}：{exc}')
        if imported:
            reference = font_reference(imported[-1].path)
            self._refresh_font_choices()
            index = self._style_combo.findData(reference)
            if index >= 0:
                self._style_combo.setCurrentIndex(index)
            self._status.setText(tr('已导入或复用 {_0} 款字体。', _0=len({font.path for font in imported})))
        elif failures:
            self._status.setText(tr('未导入：{_0}', _0='；'.join(failures)))
        return imported

    def _import_pages(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr('导入已翻译的漫画'),
            str(self.config.get('page_output_dir', '')), tr('漫画文件 (*.png *.jpg *.jpeg *.webp *.bmp *.pdf *.cbz *.json *.comitrans)'))
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
            result, failures = [], []
            for raw in paths:
                if cancelled():
                    raise RuntimeError('页面索引已取消')
                try:
                    path = Path(raw).resolve()
                    if path.suffix.lower() == '.comitrans':
                        path = path.with_suffix('.pdf')
                    if path.suffix.lower() in PROJECT_EXTS or path.name == 'project.json':
                        result.append((path, read_project_pages(path, cancelled)))
                    else:
                        reader = QImageReader(str(path))
                        size = reader.size()
                        if not size.isValid():
                            raise OSError(reader.errorString())
                        if reader.transformation().value & 4:
                            size.transpose()
                        result.append((path, size))
                except (PdfProcessingError, OSError, ValueError) as exc:
                    failures.append((Path(raw).name, str(exc)))
            return result, failures
        def accept(payload):
            result, failures = payload
            notice = tr('跳过 {_0} 个无法导入的文件', _0=len(failures)) if failures else ''
            details = '\n'.join(f'{name}: {error}' for name, error in failures)
            self._status.setToolTip(details)
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
                    self._begin_page_load(imported[0], import_notice=notice)
                else:
                    self._update_repair_controls()
                    self._status.setText(notice or tr('页面索引已读取，当前修改保留。'))
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
        self._refresh_page_counter()
        self._thumbnail_timer.start(0)
        return item

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and self._paint_hotkeys_available():
            if self._handle_paint_key(event):
                return True
        if (event.type() == QEvent.KeyPress and Qt.Key_1 <= event.key() <= Qt.Key_9
                and event.modifiers() in (Qt.NoModifier, Qt.KeypadModifier)
                and not self._paint_mode_btn.isChecked()
                and self._font_hotkeys_available()):
            if not event.isAutoRepeat() and self._favorite_fonts.activate(event.key() - Qt.Key_1):
                return True
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

    def _font_hotkeys_available(self):
        focus = QApplication.focusWidget()
        return (self.isVisible() and QApplication.activeModalWidget() is None
                and QApplication.activeWindow() is self.window()
                and focus is not None and (focus is self or self.isAncestorOf(focus))
                and self._style_combo.isEnabled() and not self.page_io_busy
                and self._repair_worker is None and self._export_worker is None
                and not self._save_jobs.busy
                and not isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit,
                                           QAbstractSpinBox, QComboBox)))

    def _add_favorite_font(self):
        choice = self._style_combo.currentData()
        try:
            if choice in STYLE_LABELS:
                path = self.config.get('style_font_map', self.config['font_map'])[choice]
            elif choice:
                path = resolve_font_reference(choice)
            else:
                style = self.items[self._loaded_row].get('style', 'dialogue')
                path = self.config['font_map'][style]
            reference = font_reference(inspect_font(path).path)
        except (OSError, ValueError, KeyError, IndexError):
            return
        if not self._favorite_fonts.add_font(reference):
            self._status.setText(tr('常用字体已满（9 个），请在“设置快捷字体”中替换。'))
        elif self._favorite_bar_pref is False:
            self._set_favorite_bar_visible(True)

    def _apply_favorite_font(self, reference):
        if (not self._style_combo.isEnabled() or self.page_io_busy or self._save_jobs.busy
                or self._repair_worker is not None or self._export_worker is not None
                or not self._font_reference_available(reference)):
            return
        index = self._style_combo.findData(reference)
        if index < 0:
            font = inspect_font(resolve_font_reference(reference))
            self._style_combo.addItem(font_display_name(font), reference)
            index = self._style_combo.count() - 1
        self._style_combo.setCurrentIndex(index)
        self.apply_changes()

    def _request_canvas_page(self, path):
        if self._strip_toggle.isChecked() and self.preview._continuous:
            self.request_page(path)

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

    def _remove_selected_pages(self):
        selected = list(self.page_list.selectedItems())
        if not selected or self.page_io_busy or self._repair_worker is not None or self._export_worker is not None:
            return False
        keys = [str(Path(item.data(Qt.UserRole)).resolve()) for item in selected]
        current_key = str(self.output_path) if self.output_path is not None else None
        if current_key in keys and self._dirty:
            if not self._allow_navigation(lambda: self._remove_pages(keys)):
                return False
            return self._remove_pages(keys)
        return self._remove_pages(keys)

    def _remove_pages(self, keys):
        keys = {str(Path(key).resolve()) for key in keys}
        rows = [self.page_list.row(item) for item in self.page_list.selectedItems()
                if str(Path(item.data(Qt.UserRole)).resolve()) in keys]
        first_row = min(rows) if rows else 0
        current_key = str(self.output_path) if self.output_path is not None else None
        current_removed = current_key in keys
        remaining_items = [self.page_list.item(index) for index in range(self.page_list.count())
                           if str(Path(self.page_list.item(index).data(Qt.UserRole)).resolve()) not in keys]
        for key in keys:
            self.preview.remove_page(key)
            self._page_items.pop(key, None)
            self._pdf_sources.pop(key, None)
            self._pdf_projects.pop(key, None)
            self._thumbnail_lru.pop(key, None)
        self.page_list.blockSignals(True)
        for index in reversed(range(self.page_list.count())):
            item = self.page_list.item(index)
            if str(Path(item.data(Qt.UserRole)).resolve()) in keys:
                self.page_list.takeItem(index)
        self.page_list.blockSignals(False)
        self._refresh_page_counter()
        if not current_removed:
            self._restore_page_selection()
            self._update_repair_controls()
            return True
        self._dirty = False
        if remaining_items:
            next_index = min(first_row, len(remaining_items) - 1)
            next_key = remaining_items[next_index].data(Qt.UserRole)
            self.page_list.blockSignals(True)
            self.page_list.setCurrentRow(next_index)
            self.page_list.blockSignals(False)
            self.request_page(next_key)
        else:
            self._clear_loaded_page()
        self._update_repair_controls()
        return True

    def _clear_pages(self):
        if not self.page_list.count() or self.page_io_busy or self._repair_worker is not None or self._export_worker is not None:
            return False
        keys = [self.page_list.item(index).data(Qt.UserRole)
                for index in range(self.page_list.count())]
        if self._dirty:
            if not self._allow_navigation(lambda: self._remove_pages(keys)):
                return False
            return True
        return self._remove_pages(keys)

    def _clear_loaded_page(self):
        self._page_jobs.invalidate()
        self._preview_timer.stop()
        self._thumbnail_timer.stop()
        self._thumbnail_loader.request([])
        self._requesting_page = False
        self._repair_history.clear()
        self._repair_redo.clear()
        self._repair_box = None
        self._repair_mode.setChecked(False)
        self._add_bubble_btn.setChecked(False)
        self._paint_mode_btn.setChecked(False)
        self._reset_paint_state(clear_selection=True)
        self._style_history.clear()
        self._pending_style_keys.clear()
        self._style_brush_btn.setChecked(False)
        self.output_path = self.cleaned_path = self.layout_path = None
        self.items = []
        self._loaded_row = -1
        self._row_dirty = False
        self._font_choice_dirty = False
        self._rendered = None
        self._cleaned_image = None
        self._original_image = None
        self._preview_dirty = False
        self._layer_cache.clear()
        self.block_list.clear()
        self._refresh_block_counter()
        self._sync_export_pdf_state(enabled=False)
        self.preview.clear(tr('选择一页，开始精修'))
        self._set_editable(False)
        self._status.setText(tr('已清空页面列表。'))

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

    def request_page(self, output_path, *, block=None):
        path = Path(output_path).resolve()
        self._import_jobs.invalidate()
        self._page_jobs.invalidate()
        self._indexing = self._requesting_page = False
        if path.suffix.lower() in PROJECT_EXTS or path.suffix.lower() == '.comitrans' or path.name == 'project.json':
            return self.request_import([path])
        if path == self.output_path:
            self._page_jobs.invalidate()
            self._requesting_page = False
            self._restore_page_selection()
            self._update_repair_controls()
            if block is not None:
                self._jump_to_block(block)
            return True
        self._restore_page_selection()
        if not self._allow_navigation(lambda: self.request_page(path, block=block)):
            self._update_repair_controls()
            return False
        self._begin_page_load(path, after=None if block is None else lambda: self._jump_to_block(block))
        return True

    def _begin_page_load(self, path, *, import_notice='', after=None, failed=None):
        revision, previous = self._edit_revision, self.output_path
        settings = deepcopy(self.config)
        self._requesting_page = True
        self._loading_page = Path(path)
        self._status.setText(tr('正在后台加载页面：{_0}', _0=Path(path).name))
        self.preview.set_loading(tr('正在加载 {_0}', _0=Path(path).name))
        def accept(data):
            self._requesting_page = False
            if self.output_path != previous or self._edit_revision != revision:
                message = tr('加载期间当前页有新修改，已保留当前页；请重新选择目标页。')
                self._status.setText(message)
                self._update_repair_controls()
                if failed:
                    failed(message)
                return
            if self.load_page(path, _payload=data, _approved=True):
                if import_notice:
                    self._status.setText(f'{self._status.text()} · {import_notice}')
                if after:
                    after()
            elif failed:
                failed(self._status.text())
        def reject(message):
            self._page_load_failed(message)
            if failed:
                failed(message)
        self._page_jobs.submit(lambda cancelled: read_page(path, settings, cancelled), accept, reject, cancellable=True)
        self._update_repair_controls()

    def open_transcript(self):
        from .transcript_dialog import TranscriptDialog
        if not self._transcript_btn.isEnabled():
            return
        if self._text_dialog is not None:
            self._text_dialog.close()
        project = self._pdf_projects.get(str(self.output_path))
        dialog = TranscriptDialog(lambda jobs, loaded, failed: self._index_transcript(
            jobs, loaded, failed, project), self._replace_transcript, self)
        if dialog.exec() and dialog.selection is not None:
            self.request_page(dialog.selection.path, block=dialog.selection.index)
        dialog.deleteLater()

    def _index_transcript(self, jobs, loaded, failed, project):
        self._store_properties()
        keys = [str(path) for path in project.images] if project else [
            self.page_list.item(row).data(Qt.UserRole) for row in range(self.page_list.count())]
        pages = [(Path(key), self._page_items[key].data(Qt.UserRole + 1))
                 for key in keys if key in self._page_items]
        current = self.output_path if self._cleaned_image is not None else None
        items = deepcopy(self.items)
        jobs.submit(lambda cancelled: read_transcript(pages, current, items, cancelled),
                    loaded, failed, cancellable=True)

    def _replace_transcript(self, replacements, complete, progress):
        grouped = {}
        for entry, text in replacements:
            grouped.setdefault(entry.path, []).append((entry, text))
        pages = list(grouped.items())
        starting_page = self.output_path
        saved_start = starting_page
        completed = 0

        def finish(error=''):
            if error:
                complete(tr('已保存 {_0} 页。替换暂停（{_1}）', _0=completed, _1=error))
            else:
                complete(tr('已保存 {_0} 页的译文替换', _0=completed))

        def save_next():
            if completed == len(pages):
                finish()
                return
            path, changes = pages[completed]
            if path == starting_page:
                path = saved_start
            progress(completed + 1, len(pages))

            def apply():
                if any(entry.index >= len(self.items)
                       or self.items[entry.index].get('restore_original')
                       or str(self.items[entry.index].get('source_text') or '') != entry.source
                       or str(self.items[entry.index].get('text') or '') != entry.translation
                       for entry, _text in changes):
                    finish(tr('页面内容已更新，请重新预览替换'))
                    return
                for entry, text in changes:
                    self.items[entry.index]['text'] = text
                    self._refresh_block_item(entry.index)
                self._load_properties(self._loaded_row)
                self._mark_dirty(properties=False)
                self.request_save(after=saved, on_error=finish)

            if path == self.output_path:
                apply()
            else:
                self._begin_page_load(path, after=apply, failed=finish)

        def saved():
            nonlocal completed
            completed += 1
            save_next()

        def start():
            nonlocal saved_start
            saved_start = self.output_path
            save_next()

        self.request_save(after=start, on_error=finish)

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
            self._status.setText(tr('正在导出，请完成或取消后再切页或退出。'))
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
        if path.suffix.lower() in PROJECT_EXTS or path.name == 'project.json':
            try:
                pages = self._register_pdf(path)
            except Exception as exc:
                self._status.setText(tr('无法精修：{_0}', _0=exc))
                return False
            path = self.output_path if self.output_path in pages else pages[0]
        if self.output_path == path:
            self._sync_export_pdf_state(enabled=True)
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
        self._repair_redo.clear()
        self._repair_box = None
        self._repair_mode.setChecked(False)
        self._paint_mode_btn.setChecked(False)
        self._reset_paint_state(clear_selection=True)
        self._edit_revision = 0
        self._style_history.clear()
        self._pending_style_keys.clear()
        self._style_brush_btn.setChecked(False)
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
        self._sync_export_pdf_state(enabled=self._export_worker is None)
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
            if self._cleaned_image is not None:
                self._selection_engine.resize(*self._cleaned_image.size)
            self._prepare_regions()
            for index, item in enumerate(self.items):
                block = QListWidgetItem(self._block_label(index))
                block.setData(Qt.UserRole + 2, self._block_payload(index))
                block.setToolTip(str(item.get('text', '')))
                self.block_list.addItem(tr(block))
            self._status.setText(tr('{_0} · {_1} 个文本块', _0=path.name, _1=len(self.items)))
            if self.items:
                self.block_list.setCurrentRow(0)
            else:
                self._status.setText(tr('{_0} · 没有可编辑文本块', _0=path.name))
            self._refresh_block_counter()
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

    def _block_payload(self, index):
        item = self.items[index]
        number = f'{index + 1:02d}'
        if item.get('restore_original'):
            return (number, tr('已还原原图'), tr('已还原'), True)
        summary = ' '.join(str(item.get('text', '')).split()) or tr('（空）')
        direction = tr('横') if int(item.get('direction', 1)) == 0 else tr('竖')
        size = item.get('font_size') if item.get('manual_layout') else item.get('rendered_font_size') or item.get('font_size')
        badge = f'{direction} {int(size)}px' if size else direction
        return (number, summary, badge, False)

    def _refresh_block_item(self, index):
        row = self.block_list.item(index)
        if row is None or not 0 <= index < len(self.items):
            return
        row.setText(self._block_label(index))
        row.setData(Qt.UserRole + 2, self._block_payload(index))
        row.setToolTip(str(self.items[index].get('text', '')))

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
        self._refresh_block_item(self._loaded_row)
        self._refresh_page_dirty_label()
        self._set_editable(True)
        self._update_region_guide()
        if not self.apply_changes():
            return False
        self._status.setText(tr('已恢复此气泡的处理结果 · 未保存。') if restored
                             else tr('此气泡已还原为原图 · 未保存，点击保存图片后保留。'))
        return True

    def _mark_dirty(self, *, properties=True):
        if self._loading or not self.items:
            return
        self._edit_revision += 1
        self._dirty = True
        self._row_dirty = self._row_dirty or properties
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

    def open_retranslation(self):
        from ..bubble_translation import retranslate_bubble
        from .retranslate_dialog import RetranslateDialog

        if not self._retranslate_btn.isEnabled() or not self.apply_changes():
            return
        if self._text_dialog is not None:
            self._text_dialog.close()
        index = self._loaded_row
        item = self.items[index]
        config = load_ai_config()
        language = item.get('source_language') or config.get('source_language', 'ja')
        original = find_original(self.output_path)
        bounds = (0, 0, *self._cleaned_image.size)
        box = intersection(item['box'][:4], bounds)
        source = str(item.get('source_text') or '')
        current = str(item.get('text') or '')
        neighbors = [
            {'原文': row.get('source_text', ''), '译文': row.get('text', '')}
            for row in self.items[max(0, index - 2):index + 3] if row is not item]
        context = '相邻气泡，仅供参考：\n' + json.dumps(neighbors, ensure_ascii=False) if neighbors else ''
        def translate(text, instruction, cancelled):
            return retranslate_bubble(config, language, text, instruction, context,
                                      original if box else None, box, cancelled)
        dialog = RetranslateDialog(source, current, translate,
                                   lambda candidate: self._preview_retranslation(index, candidate), self)
        try:
            if dialog.exec() and dialog.result_text is not None:
                revised_source = dialog.source.toPlainText().strip()
                if revised_source != source:
                    item.setdefault('ocr_raw_text', source)
                    item['source_text'] = revised_source
                item['text'] = dialog.result_text
                self._load_properties(index)
                self._mark_dirty(properties=False)
                self._preview_timer.start()
                self._status.setText(tr('已应用候选译文，保存后写入图片'))
        finally:
            dialog.deleteLater()

    def _preview_retranslation(self, index, candidate):
        from PIL.ImageQt import ImageQt

        item = self.items[index]
        box = self._mask_box(item)
        rectangles = [box]
        cached = self._layer_cache.get(index)
        if cached:
            rectangles.append(layer_bounds(cached[1:4]))
        layer = None
        if candidate is not None:
            revised = {**item, 'text': candidate}
            typesetter = self._typesetter_for_item(item)
            size = item.get('font_size') if item.get('manual_layout') else item.get('rendered_font_size') or item.get('font_size')
            layer = self._draw_lettering(self._cleaned_image, revised, typesetter, box, int(size or 0))
            if layer is not None:
                rectangles.append(layer_bounds(layer))
        left = min(rect[0] for rect in rectangles)
        top = min(rect[1] for rect in rectangles)
        right = max(rect[2] for rect in rectangles)
        bottom = max(rect[3] for rect in rectangles)
        padding = max(12, round(max(right - left, bottom - top) * .12))
        bounds = (0, 0, *self._rendered.size)
        crop = intersection((left - padding, top - padding, right + padding, bottom + padding), bounds) or bounds

        def preview(image):
            sample = image.crop(crop)
            sample.thumbnail((600, 280))
            return ImageQt(sample).copy()

        current = preview(self._rendered)
        if candidate is None:
            return current, None
        layers = []
        for row in range(len(self.items)):
            if row == index:
                if layer is not None:
                    layers.append(layer)
            elif row in self._layer_cache:
                layers.append(self._layer_cache[row][1:4])
        original = self._get_original_image() if any(i.get('restore_original') for i in self.items) else None
        revised_image, _ = compose_page(self._cleaned_image, self._rendered, layers, [crop],
            watermark=bool(self.config.get('watermark_enabled', True)),
            original=original, items=self.items, copy_previous=True)
        return current, preview(revised_image)

    def _layout_spins(self):
        return (self._size_spin, self._offset_x, self._offset_y, self._mask_width, self._mask_height,
                self._text_scale_x, self._text_scale_y, self._text_rotation, self._outline_width)

    def _reset_text_transform(self):
        self._text_scale_x.setValue(100)
        self._text_scale_y.setValue(100)
        self._text_rotation.setValue(0)

    def _apply_hollow_preset(self):
        self._direction_combo.setCurrentIndex(self._direction_combo.findData(1))
        self._effect_combo.setCurrentIndex(self._effect_combo.findData('hollow'))
        self._text_color.set_color(None)
        self._outline_width.setValue(2)
        self._schedule_preview()

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
        self.preview.set_selected_regions(self.selected_blocks())
        self.preview.set_regions(
            [(index, tuple(self._mask_box(item))) for index, item in enumerate(self.items)],
            visible=self._show_mask.isChecked()
            and not self._repair_mode.isChecked()
            and not self._paint_mode_btn.isChecked())
        if self._paint_mode_btn.isChecked():
            self.preview.set_region(None)
            return
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
        self.preview.set_region(box if self._show_mask.isChecked() else None,
                                editable=box is not None and not restored and len(self.selected_blocks()) <= 1
                                and not self._style_brush_btn.isChecked())

    def _select_block(self, index):
        """A click on a box in the canvas is the same as picking it in the list."""
        if not 0 <= index < len(self.items):
            return
        if self._style_brush_btn.isChecked():
            self.block_list.setCurrentRow(index)
            self.paste_style([index])
            return
        self.block_list.setCurrentRow(index)
        item = self.block_list.item(index)
        if item is not None:
            self.block_list.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def selected_blocks(self):
        return sorted(self.block_list.row(item) for item in self.block_list.selectedItems())

    def _selection_changed(self):
        if self._loading or not hasattr(self, '_show_mask'):
            return
        rows = self.selected_blocks()
        if rows and self._loaded_row not in rows:
            self.block_list.setCurrentRow(rows[0], QItemSelectionModel.NoUpdate)
        self._refresh_block_counter()
        self._update_region_guide()
        if len(rows) > 1:
            self._status.setText(tr('已选 {_0} 个气泡：排版修改应用到所选，译文和位置单独保留。', _0=len(rows)))

    def _select_blocks(self, indices, mode='replace'):
        self._store_properties()
        rows = set(self.selected_blocks()) if mode in ('toggle', 'add') else set()
        targets = {int(index) for index in indices if 0 <= int(index) < len(self.items)}
        rows = rows ^ targets if mode == 'toggle' else rows | targets
        blocked = self.block_list.blockSignals(True)
        try:
            for row in range(self.block_list.count()):
                self.block_list.item(row).setSelected(row in rows)
            if rows:
                self.block_list.setCurrentRow(min(rows), QItemSelectionModel.NoUpdate)
        finally:
            self.block_list.blockSignals(blocked)
        if rows:
            self._load_properties(min(rows))
        self._selection_changed()
        if self._style_brush_btn.isChecked() and rows:
            self.paste_style(sorted(rows))

    def _note_style_change(self, keys):
        if self._loading or self._loaded_row < 0:
            return
        if not self._pending_style_keys:
            self._pending_style_rows = self.selected_blocks()
        self._pending_style_keys.update(keys)

    def _note_style_control_changed(self, *_args):
        self._note_style_change(self._style_control_fields.get(self.sender(), ()))

    def _stop_style_brush(self):
        self._style_brush_btn.setChecked(False)
        self.preview.cancel_region_drag()

    def _sync_style_brush_ui(self, enabled):
        self._brush_cancel_btn.setVisible(enabled)
        self._restore_bubble_btn.setVisible(not enabled)
        if enabled:
            self._repair_mode.setChecked(False)
            self._add_bubble_btn.setChecked(False)
            self._pick_fill_btn.setChecked(False)
            self._paint_mode_btn.setChecked(False)
        self._update_region_guide()

    def _stop_style_brush_for_tool(self, enabled):
        if enabled:
            self._stop_style_brush()

    def _paste_selected_style(self):
        return self.paste_style(self.selected_blocks() or [self._loaded_row])

    def _brush_list_clicked(self, *_args):
        if self._style_brush_btn.isChecked():
            self.paste_style()

    def _remember_style_change(self, before):
        changed = {row: item for row, item in before.items()
                   if lettering_style(item) != lettering_style(self.items[row])}
        if changed:
            self._style_history.append(changed)
            self._style_history = self._style_history[-20:]
            self._undo_style_btn.setEnabled(True)

    def copy_style(self):
        if not 0 <= self._loaded_row < len(self.items) or self.items[self._loaded_row].get('restore_original'):
            return False
        self._store_properties()
        self._style_clipboard = lettering_style(self.items[self._loaded_row])
        self._style_brush_btn.setEnabled(True)
        self._style_brush_btn.setChecked(True)
        self._status.setText(tr('已取样式，点击或框选目标气泡；Esc 退出样式刷。'))
        return True

    def paste_style(self, rows=None):
        if self._style_clipboard is None or self.page_io_busy or self._save_jobs.busy or self._repair_worker is not None or self._export_worker is not None:
            return False
        self._store_properties()
        rows = self.selected_blocks() if rows is None else rows
        before = {row: deepcopy(self.items[row]) for row in rows if 0 <= row < len(self.items)}
        for row in before:
            apply_lettering_style(self.items[row], self._style_clipboard)
        self._remember_style_change(before)
        if not any(lettering_style(self.items[row]) != lettering_style(item) for row, item in before.items()):
            return False
        self._finish_style_edit()
        return True

    def _finish_style_edit(self):
        self._edit_revision += 1
        self._dirty = self._preview_dirty = True
        self._row_dirty = False
        self._refresh_page_dirty_label()
        for row in self.selected_blocks():
            self._refresh_block_item(row)
        if self._loaded_row >= 0:
            self._load_properties(self._loaded_row)
        self.apply_changes()

    def undo_style(self):
        self._store_properties()
        if not self._style_history or self.page_io_busy or self._save_jobs.busy or self._repair_worker is not None or self._export_worker is not None:
            return False
        before = self._style_history.pop()
        for row, previous in before.items():
            if row >= len(self.items):
                continue
            for key in (*STYLE_DEFAULTS, 'manual_layout', 'rendered_font_size'):
                if key in previous:
                    self.items[row][key] = deepcopy(previous[key])
                else:
                    self.items[row].pop(key, None)
            self._refresh_block_item(row)
        self._finish_style_edit()
        self._undo_style_btn.setEnabled(bool(self._style_history))
        return True

    def _jump_to_block(self, index):
        if not 0 <= index < len(self.items):
            return
        self._select_block(index)
        self._inspector_tabs.setCurrentIndex(0)
        item = self.items[index]
        box = item['box'][:4] if item.get('restore_original') else self._mask_box(item)
        self.preview.reveal_region(box)

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

    def _toggle_bubble_creation(self, enabled):
        self._pick_fill_btn.setChecked(False)
        enabled = bool(enabled)
        if enabled and self._repair_mode.isChecked():
            self._repair_mode.blockSignals(True)
            self._repair_mode.setChecked(False)
            self._repair_mode.blockSignals(False)
            self._toggle_repair_mode(False)
        if enabled and self._paint_mode_btn.isChecked():
            self._paint_mode_btn.setChecked(False)
        self.preview.set_bubble_creation(enabled)
        if enabled:
            self._status.setText(tr('在画布拖动矩形添加气泡框，添加后可直接输入译文。'))
        self._update_repair_controls()

    def _add_bubble_from_canvas(self, box):
        if self._loading or self._cleaned_image is None or not box:
            return
        try:
            x1, y1, x2, y2 = map(int, box[:4])
        except (TypeError, ValueError):
            return
        width, height = x2 - x1, y2 - y1
        if width < 2 or height < 2:
            return
        image_width, image_height = self._cleaned_image.size
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image_width, x2), min(image_height, y2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            return
        self._store_properties()
        item = {
            'box': [x1, y1, x2, y2],
            'mask_box': [x1, y1, x2, y2],
            'source_text': tr('手动添加'),
            'source_language': self.config.get('source_language', 'ja'),
            'text': '',
            'style': 'dialogue',
            'direction': -1,
            'font_size': None,
            'rendered_font_size': None,
            'non_bubble': False,
            'manual_layout': True,
            'offset_x': 0,
            'offset_y': 0,
            'mask_width': x2 - x1,
            'mask_height': y2 - y1,
            'text_effect': 'auto',
            'text_color': None,
            'vertical_alignment': 'center',
        }
        self.items.append(item)
        index = len(self.items) - 1
        block = QListWidgetItem(self._block_label(index))
        block.setData(Qt.UserRole + 2, self._block_payload(index))
        block.setToolTip(tr('手动添加的气泡框，输入译文后即可嵌字。'))
        self.block_list.addItem(block)
        self._edit_revision += 1
        self._dirty = True
        self._preview_dirty = True
        self._refresh_page_dirty_label()
        self.block_list.setCurrentRow(index)
        self._text_input.setFocus()
        self._status.setText(tr('已添加气泡框 {_0}，请输入译文。', _0=index + 1))

    def _store_properties(self):
        if not self._row_dirty or self._loaded_row < 0 or self._loaded_row >= len(self.items):
            return
        item = self.items[self._loaded_row]
        keys = set(self._pending_style_keys)
        rows = list(self._pending_style_rows)
        before = {row: deepcopy(self.items[row]) for row in set(rows + [self._loaded_row])} if keys else {}
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
        # Store the same canonical RGB value used by the automatic pipeline.
        # Older layouts can contain mixed-case values, so normalize on every save.
        item['text_color'] = normalize_text_color(self._text_color.color)
        item['vertical_alignment'] = self._vertical_alignment_combo.currentData()
        item.update(text_scale_x=self._text_scale_x.value() / 100,
                    text_scale_y=self._text_scale_y.value() / 100,
                    text_rotation=self._text_rotation.value(),
                    outline_width=None if self._outline_width.value() < 0 else self._outline_width.value())
        if keys:
            old_style, new_style = lettering_style(before[self._loaded_row]), lettering_style(item)
            patch = {key: new_style[key] for key in keys if old_style[key] != new_style[key]}
            for row in rows:
                if row != self._loaded_row:
                    apply_lettering_style(self.items[row], patch)
                    self._refresh_block_item(row)
            self._remember_style_change(before)
        self._pending_style_keys.clear()
        self._pending_style_rows = []
        self._refresh_block_item(self._loaded_row)
        self._row_dirty = False

    def _load_properties(self, row):
        self.preview.cancel_region_drag()
        if row < 0 or row >= len(self.items):
            self._loaded_row = -1
            self._font_choice_dirty = False
            self._set_editable(False)
            self._refresh_block_counter()
            self.preview.set_region(None)
            self.preview.set_regions([])
            if self._text_dialog is not None:
                self._text_dialog.close()
            return
        if not self._loading:
            self._store_properties()
        self._loading = True
        self._loaded_row = row
        self._pending_style_keys.clear()
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
        scale_x, scale_y, rotation = text_transform(item)
        self._text_scale_x.setValue(round(scale_x * 100))
        self._text_scale_y.setValue(round(scale_y * 100))
        self._text_rotation.setValue(rotation)
        stroke = outline_width(item)
        self._outline_width.setValue(-1 if stroke is None else stroke)
        box = self._mask_box(item)
        self._mask_width.setValue(box[2] - box[0])
        self._mask_height.setValue(box[3] - box[1])
        self._update_region_guide()
        self._update_advanced_style_badge()
        self._set_editable(True)
        if self._text_dialog is not None and self._text_dialog.isVisible():
            self._text_dialog.set_block(row + 1, item.get('source_text', ''),
                                        self._text_input.toPlainText())
        self._loading = False
        self._row_dirty = False
        self._refresh_block_counter()
        if self.height() >= 700 and self._inspector_tabs.currentIndex() == 1:
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
        self._paint_mode_btn.setEnabled(ready)
        if hasattr(self, '_paint_panel'):
            self._paint_panel.setEnabled(ready)
        if not ready and self._paint_mode_btn.isChecked():
            self._paint_mode_btn.setChecked(False)
        self._favorite_fonts.set_apply_enabled(ready and self._style_combo.isEnabled())
        self._add_bubble_btn.setEnabled(ready)
        if not ready and self._add_bubble_btn.isChecked():
            self._add_bubble_btn.blockSignals(True)
            self._add_bubble_btn.setChecked(False)
            self._add_bubble_btn.blockSignals(False)
            self.preview.set_bubble_creation(False)
        has_paint_sel = ready and not self._selection_engine.is_empty()
        if hasattr(self, '_paint_panel'):
            self._paint_panel.set_selection_active(has_paint_sel)
        target_box = self._repair_box if self._repair_box is not None else (
            self._selection_engine.bbox() if has_paint_sel else None
        )
        protected = False
        if ready and target_box is not None:
            try:
                protected = intersects_restored_region(target_box, self.items, self._cleaned_image.size)
            except (ValueError, KeyError, TypeError, OSError):
                protected = True
        self._repair_btn.setEnabled(ready and target_box is not None and not protected)
        self._repair_btn.setToolTip(tr('选区包含已还原气泡，请先恢复该气泡的处理结果再修补。') if protected else '')
        fills_enabled = ready and target_box is not None and not protected
        self._fill_white_btn.setEnabled(fills_enabled)
        self._fill_black_btn.setEnabled(fills_enabled)
        self._fill_custom_btn.setEnabled(fills_enabled)
        self._fill_color_btn.setEnabled(ready)
        self._pick_fill_btn.setEnabled(ready)
        self._fill_menu_btn.setEnabled(ready)
        self._fill_white_action.setEnabled(fills_enabled)
        self._fill_black_action.setEnabled(fills_enabled)
        self._fill_custom_action.setEnabled(fills_enabled)
        self._fill_color_action.setEnabled(ready)
        self._pick_fill_action.setEnabled(ready)
        if not ready:
            self._pick_fill_btn.setChecked(False)
        fill_tip = tr('选区包含已还原气泡，请先恢复该气泡的处理结果再填色。') if protected else ''
        for target, default_tip in (
            (self._fill_white_btn, tr('把框选区域整块填成白色（可撤回）。')),
            (self._fill_white_action, tr('把框选区域整块填成白色（可撤回）。')),
            (self._fill_black_btn, tr('把框选区域整块填成黑色（可撤回）。')),
            (self._fill_black_action, tr('把框选区域整块填成黑色（可撤回）。')),
            (self._fill_custom_btn, tr('用当前颜色填充框选区域（可撤回）。')),
            (self._fill_custom_action, tr('用当前颜色填充框选区域（可撤回）。')),
        ):
            target.setToolTip(fill_tip or default_tip)
        selected = 0 <= self._loaded_row < len(self.items)
        self._retranslate_btn.setEnabled(ready and selected and not self.items[self._loaded_row].get('restore_original'))
        self._restore_bubble_btn.setEnabled(ready and selected)
        self._restore_bubble_btn.setText(tr('恢复处理结果') if selected and self.items[self._loaded_row].get('restore_original') else tr('还原此气泡'))
        self._bubble_menu_btn.setEnabled(ready and selected)
        self._link_original_btn.setEnabled(ready)
        self._link_original_action.setEnabled(ready)
        can_restore = (selected and not self.items[self._loaded_row].get('restore_original')
                       and (self._original_image is not None or find_original(self.output_path) is not None))
        self._repair_undo.setEnabled(ready and (bool(self._repair_history) or can_restore))
        self._save_btn.setEnabled(ready)
        if self._export_worker is None:
            can_export = self.output_path is not None and not busy and not self.page_io_busy
            self._sync_export_pdf_state(enabled=can_export)
            self._export_cbz_action.setEnabled(can_export)
        page_list_busy = (busy or self._export_worker is not None or self.page_io_busy)
        self._transcript_btn.setEnabled(not page_list_busy and not self._save_jobs.busy
                                        and self.page_list.count() > 0)
        self.page_list.setEnabled(not page_list_busy)
        self._remove_pages_btn.setEnabled(not page_list_busy and bool(self.page_list.selectedItems()))
        self._clear_pages_btn.setEnabled(not page_list_busy and self.page_list.count() > 0)
        self.preview.setEnabled(not busy)

    def _toggle_repair_mode(self, enabled):
        self._pick_fill_btn.setChecked(False)
        if enabled and self._paint_mode_btn.isChecked():
            self._paint_mode_btn.setChecked(False)
        if enabled and self._add_bubble_btn.isChecked():
            self._add_bubble_btn.blockSignals(True)
            self._add_bubble_btn.setChecked(False)
            self._add_bubble_btn.blockSignals(False)
            self._toggle_bubble_creation(False)
        self.preview.set_region_creation(enabled)
        self._repair_box = None
        self._update_region_guide()
        self._update_repair_controls()
        if enabled:
            self._status.setText(tr('在画布拖动框选背景，再修补或填色；可自选颜色或从图片取色。'))

    def _refresh_fill_color(self):
        swatch = QPixmap(18, 18)
        swatch.fill(Qt.transparent)
        painter = QPainter(swatch)
        painter.setPen(QColor(color('ruleStrong')))
        painter.setBrush(self._fill_color)
        painter.drawRoundedRect(1, 1, 16, 16, 3, 3)
        painter.end()
        icon = QIcon(swatch)
        hex_color = self._fill_color.name().upper()
        self._fill_color_btn.setIcon(icon)
        self._fill_color_btn.setText(hex_color)
        self._fill_menu_btn.setIcon(icon)
        self._fill_custom_action.setIcon(icon)
        self._fill_custom_action.setText(tr('用当前色填充 ({color})', color=hex_color))

    def _choose_fill_color(self):
        self._pick_fill_btn.setChecked(False)
        picked = QColorDialog.getColor(self._fill_color, self, tr('选择填充颜色'),
                                       QColorDialog.DontUseNativeDialog)
        if picked.isValid():
            self._accept_fill_color(picked)

    def _toggle_fill_color_pick(self, enabled):
        if enabled and not self.apply_changes():
            self._pick_fill_btn.setChecked(False)
            return
        self.preview.set_color_picking(enabled)
        self._status.setText(tr('点击图片选择填充颜色；Esc 或右键取消。') if enabled
                             else tr('已退出图片取色。'))

    def _accept_fill_color(self, picked):
        self._fill_color = QColor(picked.name())
        self._refresh_fill_color()
        self._pick_fill_btn.setChecked(False)
        self._status.setText(tr('填充颜色：{color} · 框选区域后点击“填色”。',
                                color=self._fill_color.name().upper()))

    def _start_background_repair(self):
        self._pick_fill_btn.setChecked(False)
        if self._requesting_page or self._indexing or self._save_jobs.busy or self._repair_worker is not None or self._cleaned_image is None:
            return
        if self._export_worker is not None:
            return
        repair_mask = None
        repair_box = self._repair_box
        if repair_box is None and not self._selection_engine.is_empty():
            repair_box = self._selection_engine.bbox()
            repair_mask = self._selection_engine.mask.copy() if self._selection_engine.mask is not None else None
        if repair_box is None:
            return
        try:
            protected = intersects_restored_region(repair_box, self.items, self._cleaned_image.size)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self._status.setText(tr('还原失败：{_0}', _0=exc))
            return
        if protected:
            self._status.setText(tr('选区包含已还原气泡，请先恢复该气泡的处理结果再修补。'))
            return
        if not self.apply_changes():
            return
        worker = RepairWorker(self._repair_engine, self._cleaned_image, repair_box, self, mask=repair_mask)
        self._repair_worker = worker
        worker.succeeded.connect(self._accept_background_repair)
        worker.failed.connect(self._background_repair_failed)
        worker.finished.connect(self._background_repair_finished)
        self._update_repair_controls()
        self._status.setText(tr('正在修补背景，请稍候再保存或切换页面。'))
        worker.start()

    def _fill_repair_region(self, color) -> None:
        """Paint the selected rectangle or paint selection with a flat colour on the cleaned base."""
        self._pick_fill_btn.setChecked(False)
        if (self._requesting_page or self._indexing or self._save_jobs.busy
                or self._repair_worker is not None or self._cleaned_image is None
                or self._export_worker is not None):
            return
        if self._repair_box is None and not self._selection_engine.is_empty():
            if not self.apply_changes():
                return
            canvas_np = self._ensure_paint_canvas_np()
            if canvas_np is None:
                return
            prot = self._build_protected_mask()
            res = SelectionEngine.fill_selection(canvas_np, tuple(color), self._selection_engine.mask, prot)
            if res is None:
                self._status.setText(tr('选区包含已还原气泡，请先恢复该气泡的处理结果再填色。'))
                return
            box, before_pil, after_pil = res
            self._commit_paint_result(
                box, before_pil, after_pil,
                status_text=tr('已把选区填为 {color} · 未保存，可撤回修补。', color=QColor(*color).name().upper()),
            )
            return
        if self._repair_box is None:
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
        self._paint_canvas_np = None
        self._repair_history.append((box, before, self._dirty, self._edit_revision))
        self._repair_redo.clear()
        self._layer_cache.clear()
        self._dirty = self._preview_dirty = True
        self._refresh_page_dirty_label()
        self._update_repair_controls()
        if self.apply_changes():
            self._status.setText(tr('已把选区填为 {color} · 未保存，可撤回修补。',
                                    color=QColor(*color).name().upper()))

    def _accept_background_repair(self, box, patch):
        before = self._cleaned_image.crop(box)
        self._cleaned_image.paste(patch, box)
        self._paint_canvas_np = None
        self._repair_history.append((box, before, self._dirty, self._edit_revision))
        self._repair_redo.clear()
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
        if (self._requesting_page or self._indexing or self._save_jobs.busy
                or self._repair_worker is not None or self._export_worker is not None
                or self._cleaned_image is None):
            return False
        if not self._repair_history:
            if not 0 <= self._loaded_row < len(self.items) or self.items[self._loaded_row].get('restore_original'):
                return False
            if self._original_image is None and find_original(self.output_path) is None:
                self._status.setText(tr('缺少处理前原图，请先关联原图。'))
                return False
            return self.toggle_bubble_original()
        self._store_properties()
        box, before, was_dirty, revision = self._repair_history.pop()
        after = self._cleaned_image.crop(box)
        self._repair_redo.append((box, after, self._dirty, self._edit_revision))
        self._cleaned_image.paste(before, box)
        self._paint_canvas_np = None
        self._rendered = None
        self._layer_cache.clear()
        self._dirty = was_dirty or revision != self._edit_revision
        self._preview_dirty = True
        self._refresh_page_dirty_label()
        self._update_repair_controls()
        if self.apply_changes():
            self._status.setText(tr('已从缓存恢复修补前的背景，文字修改保留。'))
        return True

    def redo_background_repair(self):
        if (self._requesting_page or self._indexing or self._save_jobs.busy
                or self._repair_worker is not None or self._export_worker is not None
                or self._cleaned_image is None or not self._repair_redo):
            return False
        self._store_properties()
        box, after, _was_dirty, _revision = self._repair_redo.pop()
        before = self._cleaned_image.crop(box)
        self._repair_history.append((box, before, self._dirty, self._edit_revision))
        self._cleaned_image.paste(after, box)
        self._paint_canvas_np = None
        self._rendered = None
        self._layer_cache.clear()
        self._dirty = True
        self._preview_dirty = True
        self._refresh_page_dirty_label()
        self._update_repair_controls()
        if self.apply_changes():
            self._status.setText(tr('已重做画布背景修改。'))
        return True

    def _refresh_page_dirty_label(self):
        item = self._page_items.get(str(self.output_path))
        if item is not None:
            label = item.data(Qt.UserRole + 1)
            item.setText(tr('● 未保存\n{_0}', _0=label) if self._dirty else label)

    @staticmethod
    def _draw_lettering(image, item, typesetter, box, size):
        typesetter.draw_text(
            image, box, item['text'], item.get('style', 'dialogue'),
            direction=int(item.get('direction', 1)),
            target_font_size=size if size > 0 else None,
            non_bubble=bool(item.get('non_bubble', False)), manual_layout=True,
            text_effect=item.get('text_effect', 'auto'),
            source_outline_ratio=item.get('source_outline_ratio'),
            vertical_alignment=item.get('vertical_alignment', 'center'),
            text_color=normalize_text_color(item.get('text_color')),
            outline_width=outline_width(item), composite=False)
        return transform_layer(typesetter.last_render_layer, text_transform(item))

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
                   item.get('vertical_alignment', 'center'), normalize_text_color(item.get('text_color')),
                   text_transform(item), outline_width(item))
            cached = self._layer_cache.get(index)
            if cached is not None and cached[0] == key:
                _, surface, left, top, actual_size = cached
                item['rendered_font_size'] = actual_size
                layer = surface, left, top
                layers.append(layer)
                signatures[index] = (key, layer_bounds(layer))
                continue
            layer = self._draw_lettering(image, item, typesetter, box, size)
            item['rendered_font_size'] = typesetter.last_font_size
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
        if self.preview._original.isNull():
            self.preview.set_pixmap(QPixmap.fromImage(ImageQt(image)))
        elif full and self._paint_mode_btn.isChecked() and self.preview._original.size() == QSize(*image.size):
            self.preview.set_original_image(ImageQt(image))
        elif full:
            self.preview.set_pixmap(QPixmap.fromImage(ImageQt(image)))
        else:
            self.preview.update_regions(image, regions)
        if 0 <= self._loaded_row < len(self.items):
            self._refresh_block_item(self._loaded_row)

    def _export_action(self, kind='pdf'):
        if self._export_worker is not None:
            self._cancel_pdf_export()
        else:
            self._export_comic(kind if isinstance(kind, str) else 'pdf')

    def export_pdf(self, output_path=None):
        return self._export_comic('pdf', output_path)

    def export_cbz(self, output_path=None):
        return self._export_comic('cbz', output_path)

    def _export_comic(self, kind, output_path=None):
        if self._export_worker is not None or self.output_path is None or self._repair_worker is not None:
            return False
        suffix = f'.{kind}'
        sizes = []
        project = self._pdf_projects.get(str(self.output_path))
        if project is not None:
            images, sizes = project.images, project.page_sizes
            source = self._pdf_sources[str(self.output_path)]
            filename = f'{source.stem}_edited{suffix}' if source.suffix.lower() in PROJECT_EXTS else f'edited{suffix}'
            default = source.parent / filename
        else:
            images = [Path(self.page_list.item(i).data(Qt.UserRole)) for i in range(self.page_list.count())]
            if kind == 'pdf':
                for path in images:
                    reader = QImageReader(str(path))
                    size = reader.size()
                    if reader.transformation().value & 4:
                        size.transpose()
                    if not size.isValid():
                        self._status.setText(tr('无法读取译图：{_0}', _0=path.name))
                        return False
                    sizes.append((size.width() * 72 / 200, size.height() * 72 / 200))
            default = self.output_path.with_name(f'edited{suffix}')
        format_name = kind.upper()
        if output_path is None:
            chosen, _ = QFileDialog.getSaveFileName(self, tr('导出 {_0}', _0=format_name),
                                                    str(default), f'{format_name} (*{suffix})')
            if not chosen:
                return False
            output_path = Path(chosen)
        output_path = Path(output_path).with_suffix(suffix)
        # Flush pending spin-box text even before it has marked the page dirty.
        # Plain images without editing metadata can be exported directly.
        self._commit_spin_inputs()
        if self._dirty or self._save_jobs.busy:
            return self.request_save(after=lambda: self._export_comic(kind, output_path))
        worker = PdfExportWorker(images, sizes, output_path, self)
        self._export_worker = worker
        worker.progress.connect(self._pdf_export_progress)
        worker.succeeded.connect(self._pdf_export_succeeded)
        worker.failed.connect(self._pdf_export_failed)
        worker.cancelled.connect(self._pdf_export_cancelled)
        worker.finished.connect(self._pdf_export_finished)
        self._update_repair_controls()
        self._sync_export_pdf_state(enabled=kind == 'pdf')
        self._export_cbz_action.setEnabled(kind == 'cbz')
        if kind == 'pdf':
            self._sync_export_pdf_state(text=tr('取消导出'), tooltip=tr('取消导出'))
        else:
            self._export_cbz_action.setText(tr('取消导出'))
            self._export_cbz_action.setToolTip(tr('取消导出'))
        self._status.setText(tr('正在后台导出 {_0}…', _0=format_name))
        worker.start()
        return True

    def _pdf_export_progress(self, done, total):
        self._status.setText(tr('正在导出 {_0}：{_1}/{_2} 页',
                                _0=self._export_worker.output.suffix[1:].upper(), _1=done, _2=total))

    def _pdf_export_succeeded(self, path):
        self._status.setText(tr('已导出 {_0}：{_1}', _0=Path(path).suffix[1:].upper(), _1=path))

    def _pdf_export_failed(self, message):
        self._status.setText(tr('导出失败：{_0}。已保存的图片仍然保留。', _0=message))

    def _pdf_export_cancelled(self):
        self._status.setText(tr('已取消导出，已保存的图片仍然保留。'))

    def _cancel_pdf_export(self):
        if self._export_worker is not None:
            self._export_worker.requestInterruption()

    def _commit_spin_inputs(self):
        if self._quick_size_spin.hasFocus():
            self._quick_size_spin.interpretText()
        for spin in self._layout_spins():
            spin.interpretText()

    def _pdf_export_finished(self):
        worker = self._export_worker
        self._export_worker = None
        if worker is not None:
            worker.deleteLater()
        self._sync_export_pdf_state(
            enabled=self.output_path is not None,
            text=tr('导出 PDF'),
            tooltip=tr('将已保存的图片按页面顺序导出为 PDF；编辑时不会合成 PDF。'),
        )
        self._export_cbz_action.setText(tr('导出 CBZ'))
        self._export_cbz_action.setToolTip(tr('将已保存的图片按页面顺序打包为 CBZ。'))
        self._update_repair_controls()

    def _save_request(self):
        if self._export_worker is not None or self._repair_worker is not None:
            self._status.setText(tr('后台任务正在使用当前页，请稍候再保存。'))
            return None
        if self.output_path is None or self._cleaned_image is None:
            return None
        self._commit_spin_inputs()
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
        self._repair_redo.clear()
        self._refresh_page_dirty_label()
        self._update_repair_controls()
        self._status.setText(tr('已保存；后续修改仍未保存。') if self._dirty else
            tr('✓ 已保存图片与布局 · {_0}', _0=self.output_path.name))

    def _save_failed(self, message):
        callback, self._save_failure_callback = self._save_failure_callback, None
        self._saving_image = None
        self._after_save = None
        self._save_again = False
        self._update_repair_controls()
        self._status.setText(tr('保存失败：{_0}。修改仍保留，请检查输出目录后重试。', _0=message))
        if callback:
            callback(message)

    def request_save(self, checked=False, *, after=None, on_error=None):
        if after is not None:
            self._after_save = after
            self._save_failure_callback = on_error
        if self._save_jobs.busy:
            self._save_again = True
            return True
        self._commit_spin_inputs()
        if not self._dirty:
            self._save_failure_callback = None
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
            self._save_failed(self._status.text())
            return False
        previous, revision = self.output_path, self._edit_revision
        def saved(result):
            self._saving_image = None
            self._saved(result, previous, revision)
            again, self._save_again = self._save_again, False
            if self._dirty and (again or self._after_save is not None):
                self.request_save()
            else:
                self._save_failure_callback = None
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
        self._commit_spin_inputs()
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
        self._repair_redo.clear()
        self._reset_paint_state(clear_selection=True)
        self._preview_timer.stop()
        self.preview.cancel_region_drag()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._store_properties()
        self._refresh_font_choices()
        if self.width() > 0:
            self._adapt_width(animate=False)
        self._adapt_timer.start(0)

    def hideEvent(self, event):
        self.preview.set_space_pan(False)
        super().hideEvent(event)

    def _adapt_width(self, *, animate=True):
        if self.isVisible():
            self._update_toolbar_labels()
            self._apply_source_layout(animate=False)
            self._apply_panel_layout(animate=animate)
            self._sync_inspector_split()
            self._reveal_timer.start(0)

    # ---- Paint & retouch studio ----

    def _on_inspector_tab_changed(self, index: int):
        if self._loading or not hasattr(self, '_paint_mode_btn'):
            return
        if index == 2:
            if self._paint_mode_btn.isEnabled() and not self._paint_mode_btn.isChecked():
                self._paint_mode_btn.setChecked(True)
        elif index in (0, 1) and self._paint_mode_btn.isChecked():
            self._paint_mode_btn.setChecked(False)

    def _toggle_paint_mode(self, enabled: bool):
        enabled = bool(enabled)
        if enabled and self._cleaned_image is None:
            self._paint_mode_btn.blockSignals(True)
            self._paint_mode_btn.setChecked(False)
            self._paint_mode_btn.blockSignals(False)
            return
        if enabled:
            if self._repair_mode.isChecked():
                self._repair_mode.setChecked(False)
            if self._add_bubble_btn.isChecked():
                self._add_bubble_btn.setChecked(False)
            if self._pick_fill_btn.isChecked():
                self._pick_fill_btn.setChecked(False)
            if self._style_brush_btn.isChecked():
                self._style_brush_btn.setChecked(False)
            if not self._properties_toggle.isChecked():
                self._properties_toggle.setChecked(True)
            if self._inspector_tabs.currentIndex() != 2:
                self._inspector_tabs.setCurrentIndex(2)
            if self._cleaned_image is not None:
                self._selection_engine.resize(*self._cleaned_image.size)
            self._sync_paint_preview_settings()
            self._sync_selection_overlay()
            self.preview.set_view_transform(
                self._paint_panel.rotation_deg(),
                self._paint_panel.flipped_h(),
                self._paint_panel.show_grid(),
            )
            self._status.setText(tr('绘画修图模式：可直接涂抹修复背景；右键吸色，[ / ] 调笔径，Ctrl+Z/Y 撤销重做。'))
        else:
            self._on_paint_canceled()
            self.preview.set_paint_mode(False)
            self.preview.set_view_transform(0.0, False, False)
        self._update_region_guide()
        self._update_repair_controls()

    def _reset_paint_state(self, *, clear_selection: bool = False):
        self._on_paint_canceled()
        self._paint_canvas_np = None
        self._clone_source = None
        self._tablet_prev_tool = None
        if hasattr(self, 'preview'):
            self.preview.set_clone_source_marker(None)
            self.preview.set_paint_preview_overlay(None)
            if clear_selection:
                self._selection_engine.resize(0, 0)
                self.preview.set_selection_overlay(None)

    def _ensure_paint_canvas_np(self) -> np.ndarray | None:
        if self._cleaned_image is None:
            return None
        if self._paint_canvas_np is None:
            img = self._cleaned_image.convert('RGB') if self._cleaned_image.mode != 'RGB' else self._cleaned_image
            self._paint_canvas_np = np.ascontiguousarray(np.array(img, dtype=np.uint8))
        return self._paint_canvas_np

    def _build_protected_mask(self) -> np.ndarray | None:
        if self._cleaned_image is None:
            return None
        restored = [item for item in self.items if item.get('restore_original')]
        if not restored:
            return None
        w, h = self._cleaned_image.size
        mask = np.zeros((h, w), dtype=np.uint8)
        for item in restored:
            try:
                bounds, region_mask = protected_region(item, self.items, (w, h))
            except (ValueError, KeyError, TypeError, OSError):
                box = item.get('box')
                if box and len(box) >= 4:
                    x1 = max(0, min(w, int(box[0])))
                    y1 = max(0, min(h, int(box[1])))
                    x2 = max(x1, min(w, int(box[2])))
                    y2 = max(y1, min(h, int(box[3])))
                    mask[y1:y2, x1:x2] = 255
                continue
            rx1, ry1, rx2, ry2 = bounds
            arr = np.asarray(region_mask, dtype=np.uint8)
            existing = mask[ry1:ry2, rx1:rx2]
            mask[ry1:ry2, rx1:rx2] = np.maximum(existing, np.where(arr > 0, 255, 0).astype(np.uint8))
        return mask if np.any(mask > 0) else None

    def _get_original_canvas_np(self) -> np.ndarray | None:
        if self._cleaned_image is None:
            return None
        orig = self._get_original_image()
        if orig is None or orig.size != self._cleaned_image.size:
            return None
        rgb = orig.convert('RGB') if orig.mode != 'RGB' else orig
        return np.ascontiguousarray(np.array(rgb, dtype=np.uint8))

    def _sync_paint_preview_settings(self):
        if not self._paint_mode_btn.isChecked():
            return
        settings = self._paint_panel.settings()
        show_cursor = settings.tool in (
            BrushTool.STROKE_TOOLS | BrushTool.SELECTION_STROKE_TOOLS
        )
        self.preview.set_paint_mode(
            True,
            brush_diameter=float(settings.size),
            show_cursor=show_cursor,
            right_click_pick=self._paint_panel.right_click_eyedropper_enabled(),
            symmetry=settings.symmetry,
        )

    def _sync_selection_overlay(self):
        if self._selection_engine.is_empty():
            self.preview.set_selection_overlay(None)
        else:
            self.preview.set_selection_overlay(
                self._selection_engine.mask,
                self._selection_engine.contours(),
            )

    def _patch_live_canvas(self, box):
        if box is None or self._paint_canvas_np is None or self.preview._original.isNull():
            return
        h, w = self._paint_canvas_np.shape[:2]
        x1 = max(0, min(w, int(box[0])))
        y1 = max(0, min(h, int(box[1])))
        x2 = max(x1, min(w, int(box[2])))
        y2 = max(y1, min(h, int(box[3])))
        if x2 <= x1 or y2 <= y1:
            return
        roi = np.ascontiguousarray(self._paint_canvas_np[y1:y2, x1:x2])
        rw, rh = x2 - x1, y2 - y1
        qimg = QImage(roi.data, rw, rh, rw * 3, QImage.Format_RGB888).copy()
        self.preview.update_canvas_patch((x1, y1, x2, y2), qimg)

    def _commit_paint_result(self, box, before_pil, after_pil, status_text=''):
        if self._cleaned_image is None:
            return
        self._store_properties()
        self._cleaned_image.paste(after_pil, box)
        self._repair_history.append((box, before_pil, self._dirty, self._edit_revision))
        self._repair_redo.clear()
        self._rendered = None
        self._layer_cache.clear()
        self._dirty = True
        self._preview_dirty = True
        self._refresh_page_dirty_label()
        self._update_repair_controls()
        if self.apply_changes() and status_text:
            self._status.setText(status_text)

    def _on_paint_tool_changed(self, tool_id: str):
        if self._paint_poly_lasso_points or self._paint_curve_dragging:
            self._paint_poly_lasso_points.clear()
            self._paint_curve_points.clear()
            self._paint_curve_dragging = False
            self.preview.set_paint_preview_overlay(None)
        self._sync_paint_preview_settings()
        if tool_id == BrushTool.CLONE and self._clone_source is None:
            self._status.setText(tr('仿制图章：请先按住 Alt + 点击画布设定取样源点。'))
        elif tool_id == BrushTool.POLY_LASSO:
            self._status.setText(tr('多边形套索：依次点击添加顶点，双击或按 Enter 闭合选区，Esc 取消。'))
        elif tool_id == BrushTool.CURVE:
            self._status.setText(tr('曲线工具：先拖动起点到终点，再移动并点击确定弯曲控制点。'))

    def _on_paint_settings_changed(self, settings: BrushSettings):
        if self._paint_mode_btn.isChecked():
            show_cursor = settings.tool in (
                BrushTool.STROKE_TOOLS | BrushTool.SELECTION_STROKE_TOOLS
            )
            self.preview.update_paint_cursor(
                float(settings.size), show=show_cursor, symmetry=settings.symmetry,
            )
            self.preview._label.paint_right_click_pick = self._paint_panel.right_click_eyedropper_enabled()

    def _on_paint_view_changed(self, rotation_deg: float, flipped_h: bool, show_grid: bool):
        if self._paint_mode_btn.isChecked():
            self.preview.set_view_transform(rotation_deg, flipped_h, show_grid)

    def _on_tablet_eraser_changed(self, is_eraser: bool):
        if not self._paint_mode_btn.isChecked():
            return
        if is_eraser:
            cur = self._paint_panel.current_tool()
            if cur != BrushTool.ERASER:
                self._tablet_prev_tool = cur
                self._paint_panel.select_tool(BrushTool.ERASER)
        elif self._tablet_prev_tool is not None:
            prev, self._tablet_prev_tool = self._tablet_prev_tool, None
            self._paint_panel.select_tool(prev)

    def _effective_select_mode(self, modifiers) -> str:
        if modifiers & Qt.ShiftModifier:
            return 'add'
        if modifiers & Qt.AltModifier:
            return 'subtract'
        return self._paint_panel.settings().select_mode

    def _sample_fg_at(self, x: float, y: float) -> bool:
        canvas_np = self._ensure_paint_canvas_np()
        if canvas_np is None:
            return False
        rgb = sample_color(canvas_np, int(x), int(y))
        if rgb is None:
            return False
        qcol = QColor(*rgb)
        self._paint_panel.set_fg_color(qcol, emit=True)
        self._status.setText(tr('已吸取颜色：{color}', color=qcol.name().upper()))
        return True

    def _on_paint_stroke_started(self, x: float, y: float, pressure: float, modifiers):
        if (self._cleaned_image is None or self.page_io_busy or self._repair_worker is not None
                or self._export_worker is not None or self._save_jobs.busy):
            return
        settings = self._paint_panel.settings()
        tool = settings.tool

        if tool == BrushTool.EYEDROPPER:
            self._sample_fg_at(x, y)
            return

        canvas_np = self._ensure_paint_canvas_np()
        if canvas_np is None:
            return
        h, w = canvas_np.shape[:2]
        self._selection_engine.resize(w, h)

        if tool in BrushTool.STROKE_TOOLS:
            if tool == BrushTool.CLONE and self._clone_source is None:
                self._status.setText(tr('仿制图章：请先按住 Alt + 点击画布设定取样源点。'))
                return
            orig_np = None
            if tool == BrushTool.ERASER and settings.eraser_mode == 'original':
                orig_np = self._get_original_canvas_np()
                if orig_np is None:
                    self._status.setText(tr('缺少同尺寸原图，橡皮擦已退回背景色擦除。'))
            self._stroke_session = self._brush_engine.start_stroke(
                canvas_np,
                settings,
                selection_mask=self._selection_engine.mask,
                original_canvas=orig_np,
                protected_mask=self._build_protected_mask(),
                clone_source=self._clone_source,
            )
            dirty = self._stroke_session.begin(x, y, pressure)
            self._active_stroke_fps_ts = time.monotonic()
            if dirty is not None:
                self._patch_live_canvas(dirty)
            return

        if tool in BrushTool.SELECTION_STROKE_TOOLS:
            self._paint_shape_points = [(x, y)]
            self._selection_engine.paint_mask_stroke(
                [(x, y)],
                max(0.5, settings.size / 2.0),
                erase=(tool == BrushTool.DESELECT_PEN),
                antialias=settings.antialias,
            )
            self._active_stroke_fps_ts = time.monotonic()
            self._sync_selection_overlay()
            self._update_repair_controls()
            return

        if tool == BrushTool.RECT_SELECT:
            self._paint_shape_points = [(x, y), (x, y)]
            self.preview.set_paint_preview_overlay({'kind': 'rect', 'rect': (x, y, x, y)})
            return

        if tool == BrushTool.LASSO_SELECT:
            self._paint_shape_points = [(x, y)]
            self.preview.set_paint_preview_overlay({'kind': 'lasso', 'points': self._paint_shape_points, 'closed': False})
            return

        if tool == BrushTool.POLY_LASSO:
            self._paint_poly_lasso_points.append((x, y))
            self.preview.set_paint_preview_overlay({
                'kind': 'poly',
                'points': list(self._paint_poly_lasso_points),
                'closed': False,
            })
            return

        if tool == BrushTool.MAGIC_WAND:
            mode = self._effective_select_mode(modifiers)
            self._selection_engine.apply_magic_wand(
                canvas_np,
                int(x),
                int(y),
                tolerance=settings.tolerance,
                contiguous=settings.contiguous,
                antialias=settings.antialias,
                mode=mode,
            )
            self._sync_selection_overlay()
            self._update_repair_controls()
            return

        if tool == BrushTool.MOVE_SELECTION:
            if self._selection_engine.is_empty():
                self._status.setText(tr('请先创建选区后再移动选区内容。'))
                return
            self._paint_move_start = (x, y)
            self._paint_move_base_np = canvas_np.copy()
            self._paint_move_base_mask = self._selection_engine.mask.copy()
            self._active_stroke_fps_ts = time.monotonic()
            return

        if tool == BrushTool.BUCKET:
            res = SelectionEngine.bucket_fill(
                canvas_np,
                int(x),
                int(y),
                settings.color,
                tolerance=settings.tolerance,
                contiguous=settings.contiguous,
                gap_close=settings.gap_close,
                expand_px=settings.fill_expand,
                selection_mask=self._selection_engine.mask,
                protected_mask=self._build_protected_mask(),
            )
            if res is not None:
                box, before_pil, after_pil = res
                self._commit_paint_result(box, before_pil, after_pil)
            else:
                self._status.setText(tr('油漆桶未填充区域（可能在选区外或处于已还原气泡保护区内）。'))
            return

        if tool == BrushTool.CURVE and self._paint_curve_dragging and len(self._paint_curve_points) == 2:
            self._finish_curve(x, y)
            return

        if tool in (BrushTool.GRADIENT, BrushTool.LINE, BrushTool.CURVE,
                    BrushTool.RECT_SHAPE, BrushTool.ELLIPSE_SHAPE):
            self._paint_shape_points = [(x, y), (x, y)]
            kind = 'line' if tool in (BrushTool.GRADIENT, BrushTool.LINE, BrushTool.CURVE) else (
                'rect' if tool == BrushTool.RECT_SHAPE else 'ellipse'
            )
            overlay = {'kind': kind, 'p0': (x, y), 'p1': (x, y)} if kind == 'line' else {'kind': kind, 'rect': (x, y, x, y)}
            self.preview.set_paint_preview_overlay(overlay)

    def _on_paint_stroke_moved(self, x: float, y: float, pressure: float, modifiers):
        settings = self._paint_panel.settings()
        tool = settings.tool

        if tool == BrushTool.EYEDROPPER:
            self._sample_fg_at(x, y)
            return

        if self._stroke_session is not None:
            dirty = self._stroke_session.add_point(x, y, pressure)
            now = time.monotonic()
            if dirty is not None and now - self._active_stroke_fps_ts >= 0.016:
                self._active_stroke_fps_ts = now
                self._patch_live_canvas(dirty)
            return

        if tool in BrushTool.SELECTION_STROKE_TOOLS and self._paint_shape_points:
            prev = self._paint_shape_points[-1]
            if (x - prev[0]) ** 2 + (y - prev[1]) ** 2 >= 1.0:
                self._paint_shape_points.append((x, y))
                self._selection_engine.paint_mask_stroke(
                    [prev, (x, y)],
                    max(0.5, settings.size / 2.0),
                    erase=(tool == BrushTool.DESELECT_PEN),
                    antialias=settings.antialias,
                )
                now = time.monotonic()
                if now - self._active_stroke_fps_ts >= 0.016:
                    self._active_stroke_fps_ts = now
                    self._sync_selection_overlay()
            return

        if tool == BrushTool.RECT_SELECT and len(self._paint_shape_points) >= 1:
            x0, y0 = self._paint_shape_points[0]
            self._paint_shape_points = [(x0, y0), (x, y)]
            self.preview.set_paint_preview_overlay({'kind': 'rect', 'rect': (x0, y0, x, y)})
            return

        if tool == BrushTool.LASSO_SELECT and self._paint_shape_points:
            prev = self._paint_shape_points[-1]
            if (x - prev[0]) ** 2 + (y - prev[1]) ** 2 >= 4.0:
                self._paint_shape_points.append((x, y))
                self.preview.set_paint_preview_overlay({'kind': 'lasso', 'points': self._paint_shape_points, 'closed': False})
            return

        if tool == BrushTool.MOVE_SELECTION and self._paint_move_start is not None:
            now = time.monotonic()
            if now - self._active_stroke_fps_ts < 0.016:
                return
            self._active_stroke_fps_ts = now
            dx = round(x - self._paint_move_start[0])
            dy = round(y - self._paint_move_start[1])
            work = self._paint_move_base_np.copy()
            res = SelectionEngine.move_selection(
                work,
                self._paint_move_base_mask,
                dx,
                dy,
                bg_color=settings.bg_color,
                protected_mask=self._build_protected_mask(),
            )
            self._paint_canvas_np = work
            if res is not None:
                box, _before, _after, new_mask = res
                self._selection_engine.mask = new_mask
                self._patch_live_canvas(box)
                self._sync_selection_overlay()
            return

        if tool in (BrushTool.GRADIENT, BrushTool.LINE, BrushTool.CURVE,
                    BrushTool.RECT_SHAPE, BrushTool.ELLIPSE_SHAPE) and self._paint_shape_points:
            p0 = self._paint_shape_points[0]
            self._paint_shape_points = [p0, (x, y)]
            if tool in (BrushTool.GRADIENT, BrushTool.LINE, BrushTool.CURVE):
                self.preview.set_paint_preview_overlay({'kind': 'line', 'p0': p0, 'p1': (x, y)})
            elif tool == BrushTool.RECT_SHAPE:
                self.preview.set_paint_preview_overlay({'kind': 'rect', 'rect': (p0[0], p0[1], x, y)})
            else:
                self.preview.set_paint_preview_overlay({'kind': 'ellipse', 'rect': (p0[0], p0[1], x, y)})

    def _on_paint_stroke_ended(self, x: float, y: float, pressure: float, modifiers):
        settings = self._paint_panel.settings()
        tool = settings.tool

        if self._stroke_session is not None:
            session, self._stroke_session = self._stroke_session, None
            res = session.end()
            if res is not None:
                box, before_pil, after_pil = res
                self._commit_paint_result(box, before_pil, after_pil)
            elif self._rendered is not None:
                self._paint_canvas_np = None
                self.preview.set_original_image(ImageQt(self._rendered))
            return

        if tool in BrushTool.SELECTION_STROKE_TOOLS and self._paint_shape_points:
            prev = self._paint_shape_points[-1]
            self._selection_engine.paint_mask_stroke(
                [prev, (x, y)],
                max(0.5, settings.size / 2.0),
                erase=(tool == BrushTool.DESELECT_PEN),
                antialias=settings.antialias,
            )
            self._paint_shape_points = []
            self._sync_selection_overlay()
            self._update_repair_controls()
            return

        if tool == BrushTool.RECT_SELECT and self._paint_shape_points:
            x0, y0 = self._paint_shape_points[0]
            self._paint_shape_points = []
            self.preview.set_paint_preview_overlay(None)
            box = (round(min(x0, x)), round(min(y0, y)), round(max(x0, x)), round(max(y0, y)))
            self._selection_engine.apply_rect(box, mode=self._effective_select_mode(modifiers))
            self._sync_selection_overlay()
            self._update_repair_controls()
            return

        if tool == BrushTool.LASSO_SELECT and self._paint_shape_points:
            pts = self._paint_shape_points + [(x, y)]
            self._paint_shape_points = []
            self.preview.set_paint_preview_overlay(None)
            self._selection_engine.apply_lasso(
                pts, mode=self._effective_select_mode(modifiers), antialias=settings.antialias,
            )
            self._sync_selection_overlay()
            self._update_repair_controls()
            return

        if tool == BrushTool.MOVE_SELECTION and self._paint_move_start is not None:
            dx = round(x - self._paint_move_start[0])
            dy = round(y - self._paint_move_start[1])
            work = self._paint_move_base_np.copy()
            base_mask = self._paint_move_base_mask
            self._paint_move_start = None
            self._paint_move_base_np = None
            self._paint_move_base_mask = None
            if dx == 0 and dy == 0:
                self._paint_canvas_np = None
                self._selection_engine.mask = base_mask
                self._sync_selection_overlay()
                if self._rendered is not None:
                    self.preview.set_original_image(ImageQt(self._rendered))
                return
            res = SelectionEngine.move_selection(
                work,
                base_mask,
                dx,
                dy,
                bg_color=settings.bg_color,
                protected_mask=self._build_protected_mask(),
            )
            if res is not None:
                box, before_pil, after_pil, new_mask = res
                self._selection_engine.mask = new_mask
                self._paint_canvas_np = work
                self._sync_selection_overlay()
                self._commit_paint_result(box, before_pil, after_pil)
            else:
                self._paint_canvas_np = None
                self._selection_engine.mask = base_mask
                self._sync_selection_overlay()
            return

        if tool == BrushTool.CURVE and self._paint_shape_points and not self._paint_curve_dragging:
            p0 = self._paint_shape_points[0]
            self._paint_shape_points = []
            if (x - p0[0]) ** 2 + (y - p0[1]) ** 2 >= 4.0:
                self._paint_curve_points = [p0, (x, y)]
                self._paint_curve_dragging = True
                self.preview.set_paint_preview_overlay({'kind': 'line', 'p0': p0, 'p1': (x, y)})
            else:
                self.preview.set_paint_preview_overlay(None)
            return

        if tool in (BrushTool.GRADIENT, BrushTool.LINE, BrushTool.RECT_SHAPE, BrushTool.ELLIPSE_SHAPE) and self._paint_shape_points:
            p0 = self._paint_shape_points[0]
            self._paint_shape_points = []
            self.preview.set_paint_preview_overlay(None)
            canvas_np = self._ensure_paint_canvas_np()
            if canvas_np is None:
                return
            prot = self._build_protected_mask()
            if tool == BrushTool.GRADIENT:
                res = BrushEngine.draw_gradient(
                    canvas_np, p0, (x, y), settings,
                    selection_mask=self._selection_engine.mask, protected_mask=prot,
                )
            else:
                res = BrushEngine.draw_shape(
                    canvas_np, tool, [p0, (x, y)], settings,
                    selection_mask=self._selection_engine.mask, protected_mask=prot,
                )
            if res is not None:
                box, before_pil, after_pil = res
                self._commit_paint_result(box, before_pil, after_pil)

    def _on_paint_hover_moved(self, x: float, y: float):
        if not self._paint_mode_btn.isChecked():
            return
        tool = self._paint_panel.current_tool()
        if tool == BrushTool.POLY_LASSO and self._paint_poly_lasso_points:
            self.preview.set_paint_preview_overlay({
                'kind': 'poly',
                'points': [*self._paint_poly_lasso_points, (x, y)],
                'closed': False,
            })
        elif tool == BrushTool.CURVE and self._paint_curve_dragging and len(self._paint_curve_points) == 2:
            p0, p1 = self._paint_curve_points
            self.preview.set_paint_preview_overlay({
                'kind': 'poly',
                'points': [p0, (x, y), p1],
                'closed': False,
            })

    def _on_paint_alt_clicked(self, x: float, y: float):
        if not self._paint_mode_btn.isChecked():
            return
        if self._paint_panel.current_tool() == BrushTool.CLONE:
            self._clone_source = (float(x), float(y))
            self.preview.set_clone_source_marker(self._clone_source)
            self._status.setText(tr('已设定图章源点：({x}, {y})', x=round(x), y=round(y)))
        else:
            self._sample_fg_at(x, y)

    def _on_paint_right_clicked(self, x: float, y: float):
        if not self._paint_mode_btn.isChecked():
            return
        if self._paint_panel.right_click_eyedropper_enabled():
            self._sample_fg_at(x, y)

    def _on_paint_double_clicked(self, x: float, y: float):
        if not self._paint_mode_btn.isChecked():
            return
        tool = self._paint_panel.current_tool()
        if tool == BrushTool.POLY_LASSO and len(self._paint_poly_lasso_points) >= 3:
            self._finish_poly_lasso()
        elif tool == BrushTool.CURVE and self._paint_curve_dragging and len(self._paint_curve_points) == 2:
            self._finish_curve(x, y)

    def _finish_poly_lasso(self):
        pts = list(self._paint_poly_lasso_points)
        self._paint_poly_lasso_points.clear()
        self.preview.set_paint_preview_overlay(None)
        if len(pts) < 3 or self._cleaned_image is None:
            return
        self._selection_engine.resize(*self._cleaned_image.size)
        settings = self._paint_panel.settings()
        self._selection_engine.apply_poly_lasso(
            pts, mode=settings.select_mode, antialias=settings.antialias,
        )
        self._sync_selection_overlay()
        self._update_repair_controls()

    def _finish_curve(self, ctrl_x: float, ctrl_y: float):
        pts = list(self._paint_curve_points)
        self._paint_curve_points.clear()
        self._paint_curve_dragging = False
        self.preview.set_paint_preview_overlay(None)
        if len(pts) != 2 or self._cleaned_image is None:
            return
        canvas_np = self._ensure_paint_canvas_np()
        if canvas_np is None:
            return
        settings = self._paint_panel.settings()
        res = BrushEngine.draw_shape(
            canvas_np,
            BrushTool.CURVE,
            [pts[0], (ctrl_x, ctrl_y), pts[1]],
            settings,
            selection_mask=self._selection_engine.mask,
            protected_mask=self._build_protected_mask(),
        )
        if res is not None:
            box, before_pil, after_pil = res
            self._commit_paint_result(box, before_pil, after_pil)

    def _on_paint_canceled(self):
        changed = False
        if self._stroke_session is not None:
            self._stroke_session = None
            changed = True
        if self._paint_move_base_mask is not None:
            self._selection_engine.mask = self._paint_move_base_mask
            self._paint_move_base_mask = None
            self._paint_move_base_np = None
            self._paint_move_start = None
            self._sync_selection_overlay()
            changed = True
        self._paint_shape_points.clear()
        self._paint_poly_lasso_points.clear()
        self._paint_curve_points.clear()
        self._paint_curve_dragging = False
        self.preview.set_paint_preview_overlay(None)
        if changed:
            self._paint_canvas_np = None
            if self._rendered is not None and not self.preview._original.isNull():
                self.preview.set_original_image(ImageQt(self._rendered))

    def _on_paint_selection_action(self, action: str):
        if self._cleaned_image is None or self.page_io_busy or self._repair_worker is not None:
            return
        w, h = self._cleaned_image.size
        self._selection_engine.resize(w, h)
        if action == 'select_all':
            self._selection_engine.select_all()
            self._sync_selection_overlay()
            self._update_repair_controls()
        elif action == 'invert':
            self._selection_engine.invert()
            self._sync_selection_overlay()
            self._update_repair_controls()
        elif action == 'clear':
            self._selection_engine.clear()
            self._sync_selection_overlay()
            self._update_repair_controls()
        elif action == 'expand':
            self._selection_engine.expand(2)
            self._sync_selection_overlay()
            self._update_repair_controls()
        elif action == 'contract':
            self._selection_engine.contract(2)
            self._sync_selection_overlay()
            self._update_repair_controls()
        elif action == 'feather':
            self._selection_engine.feather(3)
            self._sync_selection_overlay()
            self._update_repair_controls()
        elif action in ('fill', 'clear_pixels'):
            if self._selection_engine.is_empty():
                return
            if not self.apply_changes():
                return
            canvas_np = self._ensure_paint_canvas_np()
            if canvas_np is None:
                return
            settings = self._paint_panel.settings()
            col = settings.bg_color if action == 'clear_pixels' else settings.color
            res = SelectionEngine.fill_selection(
                canvas_np, col, self._selection_engine.mask, self._build_protected_mask(),
            )
            if res is not None:
                box, before_pil, after_pil = res
                self._commit_paint_result(box, before_pil, after_pil)
        elif action == 'ai_repair':
            if self._selection_engine.is_empty():
                return
            saved_box = self._repair_box
            self._repair_box = None
            try:
                self._start_background_repair()
            finally:
                self._repair_box = saved_box

    def _on_paint_filter_requested(self, kind: str):
        if (self._cleaned_image is None or self.page_io_busy or self._repair_worker is not None
                or self._export_worker is not None or self._save_jobs.busy):
            return
        if not self.apply_changes():
            return
        sel_mask = self._selection_engine.mask
        prot_mask = self._build_protected_mask()

        def _dispatch(src_np: np.ndarray, params: dict):
            if kind == 'hsl':
                return ImageFilters.adjust_hsl(
                    src_np, params.get('hue_deg', 0.0), params.get('sat_pct', 0.0), params.get('lum_pct', 0.0),
                    selection_mask=sel_mask, protected_mask=prot_mask,
                )
            if kind == 'bc':
                return ImageFilters.adjust_brightness_contrast(
                    src_np, params.get('brightness', 0.0), params.get('contrast', 0.0),
                    selection_mask=sel_mask, protected_mask=prot_mask,
                )
            if kind == 'levels':
                return ImageFilters.adjust_levels(
                    src_np,
                    int(params.get('in_black', 0)),
                    float(params.get('gamma', 1.0)),
                    int(params.get('in_white', 255)),
                    selection_mask=sel_mask,
                    protected_mask=prot_mask,
                )
            if kind == 'blur':
                return ImageFilters.gaussian_blur(
                    src_np, float(params.get('radius', 3.0)),
                    selection_mask=sel_mask, protected_mask=prot_mask,
                )
            if kind == 'sharpen':
                return ImageFilters.sharpen(
                    src_np, float(params.get('amount', 100.0)), float(params.get('radius', 1.5)),
                    selection_mask=sel_mask, protected_mask=prot_mask,
                )
            if kind == 'luma_white':
                return ImageFilters.luminance_to_white(
                    src_np, int(params.get('threshold', 215)), int(params.get('softness', 24)),
                    selection_mask=sel_mask, protected_mask=prot_mask,
                )
            if kind == 'invert':
                return ImageFilters.invert_colors(src_np, selection_mask=sel_mask, protected_mask=prot_mask)
            if kind == 'desaturate':
                return ImageFilters.desaturate(src_np, selection_mask=sel_mask, protected_mask=prot_mask)
            return None

        canvas_np = self._ensure_paint_canvas_np()
        if canvas_np is None:
            return
        if kind in ('invert', 'desaturate'):
            res = _dispatch(canvas_np, {})
            if res is not None:
                box, before_pil, after_pil = res
                self._paint_canvas_np = None
                self._commit_paint_result(box, before_pil, after_pil)
            return

        base_cleaned = self._cleaned_image.copy()
        base_np = np.ascontiguousarray(np.array(
            base_cleaned.convert('RGB') if base_cleaned.mode != 'RGB' else base_cleaned,
            dtype=np.uint8,
        ))
        was_dirty = self._dirty
        dialog = PaintFilterDialog(kind, self)

        def _apply_preview(params: dict):
            self._cleaned_image = base_cleaned.copy()
            res = _dispatch(base_np, params)
            if res is not None:
                box, _before, after_pil = res
                self._cleaned_image.paste(after_pil, box)
            self._paint_canvas_np = None
            self._rendered = None
            self._layer_cache.clear()
            self._preview_dirty = True
            self.apply_changes()

        def _cancel_preview():
            self._cleaned_image = base_cleaned.copy()
            self._paint_canvas_np = None
            self._rendered = None
            self._layer_cache.clear()
            self._preview_dirty = True
            self.apply_changes()

        dialog.preview_requested.connect(_apply_preview)
        dialog.preview_canceled.connect(_cancel_preview)
        accepted = dialog.exec()
        params = dialog.params()
        dialog.deleteLater()

        if accepted == QDialog.Accepted:
            self._cleaned_image = base_cleaned.copy()
            self._dirty = was_dirty
            res = _dispatch(base_np, params)
            self._paint_canvas_np = None
            if res is not None:
                box, before_pil, after_pil = res
                self._commit_paint_result(box, before_pil, after_pil, tr('已应用图像滤镜 · 可撤回修补。'))
            else:
                self._rendered = None
                self._layer_cache.clear()
                self._preview_dirty = True
                self.apply_changes()
        else:
            self._cleaned_image = base_cleaned
            self._paint_canvas_np = None
            self._dirty = was_dirty
            if self._cleaned_image is not None:
                self._rendered = None
                self._layer_cache.clear()
                self._preview_dirty = True
                self.apply_changes()
            self._refresh_page_dirty_label()
            self._update_repair_controls()

    def _paint_hotkeys_available(self) -> bool:
        focus = QApplication.focusWidget()
        return (
            self.isVisible()
            and self._cleaned_image is not None
            and QApplication.activeModalWidget() is None
            and QApplication.activeWindow() is self.window()
            and focus is not None
            and (focus is self or self.isAncestorOf(focus))
            and not self.page_io_busy
            and self._repair_worker is None
            and self._export_worker is None
            and not self._save_jobs.busy
            and not isinstance(focus, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QComboBox))
        )

    def _handle_paint_key(self, event) -> bool:
        mods = event.modifiers() & ~Qt.KeypadModifier
        key = event.key()
        in_paint = self._paint_mode_btn.isChecked()
        focus = QApplication.focusWidget()
        on_canvas = focus is self.preview._label

        if mods == Qt.ControlModifier and key == Qt.Key_Z:
            if in_paint or on_canvas:
                return self.undo_background_repair()
            return False
        if (mods == Qt.ControlModifier and key == Qt.Key_Y) or (
            mods == (Qt.ControlModifier | Qt.ShiftModifier) and key == Qt.Key_Z
        ):
            if in_paint or on_canvas:
                return self.redo_background_repair()
            return False

        if not in_paint:
            return False

        if mods == Qt.ControlModifier and key == Qt.Key_A:
            self._on_paint_selection_action('select_all')
            return True
        if mods == Qt.ControlModifier and key == Qt.Key_D:
            self._on_paint_selection_action('clear')
            return True
        if mods == (Qt.ControlModifier | Qt.ShiftModifier) and key == Qt.Key_I:
            self._on_paint_selection_action('invert')
            return True
        if mods == Qt.NoModifier and key in (Qt.Key_Delete, Qt.Key_Backspace):
            if not self._selection_engine.is_empty():
                self._on_paint_selection_action('clear_pixels')
                return True
            return False
        if mods == Qt.NoModifier and key in (Qt.Key_Return, Qt.Key_Enter):
            if self._paint_panel.current_tool() == BrushTool.POLY_LASSO and len(self._paint_poly_lasso_points) >= 3:
                self._finish_poly_lasso()
                return True
            return False
        if mods == Qt.NoModifier and key == Qt.Key_Escape:
            if (self._stroke_session is not None or self._paint_poly_lasso_points
                    or self._paint_curve_dragging or self._paint_shape_points
                    or self._paint_move_base_mask is not None):
                self._on_paint_canceled()
                return True
            if not self._selection_engine.is_empty():
                self._on_paint_selection_action('clear')
                return True
            return False

        if mods == Qt.NoModifier and not event.isAutoRepeat():
            tool_map = {
                Qt.Key_P: BrushTool.PENCIL,
                Qt.Key_B: BrushTool.PEN,
                Qt.Key_A: BrushTool.AIRBRUSH,
                Qt.Key_W: BrushTool.WATERCOLOR,
                Qt.Key_E: BrushTool.ERASER,
                Qt.Key_S: BrushTool.CLONE,
                Qt.Key_I: BrushTool.EYEDROPPER,
                Qt.Key_M: BrushTool.RECT_SELECT,
                Qt.Key_L: BrushTool.LASSO_SELECT,
                Qt.Key_K: BrushTool.SELECT_PEN,
                Qt.Key_G: BrushTool.BUCKET,
            }
            if key in tool_map:
                self._paint_panel.select_tool(tool_map[key])
                return True
            if key == Qt.Key_BracketLeft:
                self._paint_panel.step_size(-1)
                return True
            if key == Qt.Key_BracketRight:
                self._paint_panel.step_size(1)
                return True
            if key == Qt.Key_X:
                self._paint_panel.swap_colors()
                return True
            if key == Qt.Key_D:
                self._paint_panel.reset_colors()
                return True
            if key == Qt.Key_H:
                self._paint_panel.toggle_flip_h()
                return True
        elif mods == Qt.NoModifier and key in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            self._paint_panel.step_size(-1 if key == Qt.Key_BracketLeft else 1)
            return True
        return False
