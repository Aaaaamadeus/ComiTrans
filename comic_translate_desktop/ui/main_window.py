from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QSize,
    Qt,
    QSettings,
    QElapsedTimer,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImageReader,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QSizePolicy,
    QStackedWidget,
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import config as app_config
from ..config import config_fingerprint, missing_models, save_ai_config
from comic_translate_core.languages import SOURCE_LANGUAGES, validate_ocr_config
from ..diagnostics import Diagnostics
from ..pdf_utils import render_pdf_preview
from ..worker import BatchWorker
from .api_config_page import ApiConfigPage
from .editor_page import EditorPage
from .error_log_page import ErrorLogPage
from .step_panel import StepPanel
from .theme import APP_STYLESHEET, brand_font, refresh_style
from .preview import ImagePreview
from .log_panel import LogPanel
from .manga_components import ChapterBanner, PanelHeading, StageFocus
from .step_panel import STAGE_LABELS, STAGE_ORDER


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DOCUMENT_EXTS = IMAGE_EXTS | {".pdf"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComiTrans 本地漫画翻译")
        self.setWindowIcon(QIcon(str(app_config.ICON_PATH)))
        self._ui_settings = QSettings()
        self._stop_requested = False
        self._active_task_id = None
        self._warmup_task_id = None
        self._task_clock = QElapsedTimer()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self.resize(1440, 900)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1440, int(screen.width() * .94)), min(900, int(screen.height() * .94)))
        self.setAcceptDrops(True)

        self.config = app_config.load_ai_config()
        self.pipeline = None
        self.pipeline_fingerprint = None
        self.worker = None
        self.warmup_worker = None
        self.results = {}
        self.diagnostics = Diagnostics()
        self._prompt_refresh_timer = QTimer(self)
        self._prompt_refresh_timer.setSingleShot(True)
        self._prompt_refresh_timer.setInterval(300)
        self._prompt_refresh_timer.timeout.connect(self._refresh_error_page)

        self._build_ui()
        self._append_log("本地客户端已就绪。")
        if self.config["api_key"] and self.config["api_key"] == self.config["translation_model"]:
            self._append_log("警告：API Key 与模型名相同，看起来把模型名填到了密钥栏。")
        self._update_actions()
        self._start_warmup()

    def _build_ui(self) -> None:
        self.setStyleSheet(APP_STYLESHEET)
        central = QWidget()
        central.setObjectName("appRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSizeConstraint(QLayout.SetNoConstraint)
        self.layout().setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumSize(820, 480)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        header = QHBoxLayout(top_bar)
        header.setContentsMargins(24, 8, 24, 8)
        header.setSpacing(8)
        title = QLabel("ComiTrans")
        title.setObjectName("brandTitle")
        self._brand_title = title
        title.setFont(brand_font(48))
        title.setContentsMargins(0, 0, 12, 0)
        header.addWidget(title)
        header.addSpacing(20)
        self._nav_auto = QPushButton("自动处理")
        self._nav_editor = QPushButton("嵌字精修")
        for button in (self._nav_auto, self._nav_editor):
            button.setCheckable(True)
            button.setProperty("role", "nav")
            header.addWidget(button)
        header.addStretch()
        self.status_label = QLabel("○ 就绪")
        self.status_label.setObjectName("statusPill")
        self.status_label.setAlignment(Qt.AlignCenter)
        header.addWidget(self.status_label)
        self._stop_btn = QPushButton("□ 停止任务")
        self._stop_btn.setToolTip("请求停止，等待后台安全收尾")
        header.addWidget(self._stop_btn)
        self._settings_btn = QPushButton("设置")
        self._logs_btn = QPushButton("诊断")
        self._output_btn = QPushButton("输出目录")
        self._issue_btn = QPushButton("反馈")
        for button, tooltip in ((self._settings_btn, "翻译服务、OCR、模型与默认输出"), (self._logs_btn, "日志文件与 AI 诊断"), (self._output_btn, "打开输出目录"), (self._issue_btn, "打开反馈页面")):
            button.setProperty("role", "quiet")
            button.setProperty("compact", True)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            header.addWidget(button)
        self._more_btn = QToolButton()
        self._more_btn.setText("更多")
        self._more_btn.setProperty("role", "quiet")
        self._more_btn.setPopupMode(QToolButton.InstantPopup)
        more_menu = QMenu(self._more_btn)
        more_menu.addAction("设置", self._show_api_config)
        more_menu.addAction("诊断", self._show_error_log)
        more_menu.addAction("打开输出目录", self._open_output_dir)
        more_menu.addAction("反馈问题", self._open_issue)
        self._more_btn.setMenu(more_menu)
        header.addWidget(self._more_btn)
        root.addWidget(top_bar)
        self.tabs = QStackedWidget()
        self.translate_tab = QWidget()
        auto_layout = QVBoxLayout(self.translate_tab)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(0)
        self._chapter_banner = ChapterBanner("01", "自动翻译工作台", "批量处理 · 逐页检查 · 精准嵌字")
        self._work_title = self._chapter_banner
        auto_layout.addWidget(self._chapter_banner)
        self.queue_splitter = QSplitter(Qt.Horizontal)
        self.queue_splitter.setHandleWidth(8)
        self.queue_splitter.setChildrenCollapsible(False)
        self.queue_splitter.addWidget(self._build_file_panel())
        self.queue_splitter.addWidget(self._build_work_panel())
        self.queue_splitter.setStretchFactor(0, 0)
        self.queue_splitter.setStretchFactor(1, 1)
        self.queue_splitter.setSizes([264, 1128])
        auto_layout.addWidget(self.queue_splitter, 1)
        self.tabs.addWidget(self.translate_tab)
        self.api_config_page = ApiConfigPage(self.config)
        self.api_config_page.save_requested.connect(self._save_api_config)
        self.tabs.addWidget(self.api_config_page)
        self.error_log_page = ErrorLogPage(self.diagnostics)
        self.tabs.addWidget(self.error_log_page)
        self.editor_page = EditorPage()
        self.tabs.addWidget(self.editor_page)
        root.addWidget(self.tabs, 1)
        self._apply_compact_layout()
        self._nav_auto.clicked.connect(lambda: self.tabs.setCurrentWidget(self.translate_tab))
        self._nav_editor.clicked.connect(lambda: self.tabs.setCurrentWidget(self.editor_page))
        self._nav_auto.setChecked(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._add_btn.clicked.connect(self._choose_files)
        self._folder_btn.clicked.connect(self._choose_folder)
        self._settings_btn.clicked.connect(self._show_api_config)
        self._logs_btn.clicked.connect(self._show_error_log)
        self._output_btn.clicked.connect(self._open_output_dir)
        self._issue_btn.clicked.connect(self._open_issue)
        self._start_btn.clicked.connect(self._start_translation)
        self._stop_btn.clicked.connect(self._stop_translation)
        for key, splitter in (("queue", self.queue_splitter), ("previewLog", self.work_splitter)):
            state = self._ui_settings.value(f"ui/{key}")
            if state is not None:
                splitter.restoreState(state)
        self._log_toggle.setChecked(self._ui_settings.value("ui/logVisible", True, type=bool))
        self._pref_toggle.setChecked(self._ui_settings.value("ui/preferencesVisible", False, type=bool))

    def _build_file_panel(self) -> QWidget:
        group = QFrame()
        group.setObjectName("queuePanel")
        group.setMinimumWidth(200)
        group.setMaximumWidth(320)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(10)
        self._queue_layout = layout
        heading = PanelHeading("01", "漫画队列", sidebar=True)
        layout.addWidget(heading)
        self._file_count_label = QLabel("0 个文件")
        self._file_selection_label = QLabel("支持图片与 PDF")
        self._file_selection_label.setProperty("muted", True)
        layout.addWidget(self._file_count_label)
        layout.addWidget(self._file_selection_label)
        self._drop_zone = QFrame()
        self._drop_zone.setObjectName("dropZone")
        self._drop_zone.setProperty("dragActive", False)
        drop = QVBoxLayout(self._drop_zone)
        drop.setContentsMargins(8, 12, 8, 12)
        label = QLabel("拖入漫画或文件夹")
        self._drop_title = label
        label.setObjectName("dropTitle")
        label.setAlignment(Qt.AlignCenter)
        drop.addWidget(label)
        self._add_btn = QPushButton("＋ 添加文件")
        self._folder_btn = QPushButton("添加文件夹")
        self._folder_btn.setProperty("role", "quiet")
        drop.addWidget(self._add_btn)
        drop.addWidget(self._folder_btn)
        hint = QLabel("PNG / JPG / WEBP / BMP / PDF")
        hint.setObjectName("dropHint")
        hint.setWordWrap(True)
        self._drop_hint = hint
        drop.addWidget(hint)
        layout.addWidget(self._drop_zone)
        self.file_list = QListWidget()
        self.file_list.setIconSize(QSize(48, 64))
        self.file_list.setWordWrap(True)
        self.file_list.setTextElideMode(Qt.ElideMiddle)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setAccessibleName("漫画文件队列")
        self.file_list.itemSelectionChanged.connect(self._on_file_selection)
        layout.addWidget(self.file_list, 1)
        buttons = QHBoxLayout()
        self._remove_btn = QPushButton("移除选中")
        self._clear_btn = QPushButton("清空")
        for button in (self._remove_btn, self._clear_btn):
            button.setProperty("compact", True)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._remove_btn.clicked.connect(self._remove_selected)
        self._clear_btn.clicked.connect(self._clear_files)
        return group

    def _build_work_panel(self) -> QWidget:
        group = QFrame()
        group.setObjectName("workPanel")
        group.setMinimumWidth(580)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)
        self._work_layout = layout
        self._elapsed_label = QLabel("批量翻译 · 输出简体中文")
        self._elapsed_label.setProperty("muted", True)
        control_card = QFrame()
        control_card.setObjectName("controlCard")
        control_layout = QVBoxLayout(control_card)
        control_layout.setContentsMargins(0, 0, 0, 6)
        control_layout.setSpacing(4)
        self._control_grid = QGridLayout()
        self._control_grid.setContentsMargins(0, 0, 0, 0)
        self._control_grid.setHorizontalSpacing(10)
        self._control_grid.setVerticalSpacing(4)
        self._controls_inline = None
        self._language_controls = QWidget()
        control_row = QHBoxLayout(self._language_controls)
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(6)
        control_row.addWidget(QLabel("原文语言"))
        self._source_language = QComboBox()
        self._source_language.setMinimumWidth(100)
        self._source_language.setMaximumWidth(130)
        for code, label in SOURCE_LANGUAGES:
            self._source_language.addItem(label, code)
        self._source_language.setCurrentIndex(max(0, self._source_language.findData(self.config.get("source_language", "ja"))))
        self._source_language.setToolTip("其它语言可在设置中接入自定义 OCR")
        self._source_language.currentIndexChanged.connect(self._change_source_language)
        control_row.addWidget(self._source_language)
        self._pref_toggle = QToolButton()
        self._pref_toggle.setText("翻译偏好")
        self._pref_toggle.setCheckable(True)
        self._pref_toggle.setArrowType(Qt.RightArrow)
        self._pref_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._pref_toggle.setProperty("role", "quiet")
        control_row.addWidget(self._pref_toggle)
        control_row.addStretch()
        self._start_btn = QPushButton("开始翻译")
        self._start_btn.setProperty("role", "primary")
        self._output_controls = QWidget()
        output_row = QHBoxLayout(self._output_controls)
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(6)
        self._output_label = QLabel("输出目录")
        output_row.addWidget(self._output_label)
        self._output_dir_input = QLineEdit(str(self.config.get("page_output_dir", "")))
        self._output_dir_input.setMinimumWidth(100)
        self._output_dir_input.setCursorPosition(len(self._output_dir_input.text()))
        self._output_dir_input.setToolTip(self._output_dir_input.text())
        self._output_dir_input.textChanged.connect(self._output_dir_input.setToolTip)
        self._browse_output_btn = QPushButton("浏览")
        self._browse_output_btn.setProperty("compact", True)
        self._browse_output_btn.clicked.connect(self._browse_output_dir)
        output_row.addWidget(self._output_dir_input, 1)
        output_row.addWidget(self._browse_output_btn)
        control_layout.addLayout(self._control_grid)
        self._pref_container = QWidget()
        self._pref_container.setVisible(False)
        pref_layout = QHBoxLayout(self._pref_container)
        pref_layout.setContentsMargins(0, 0, 0, 0)
        pref_layout.setSpacing(10)

        prompt_panel = QVBoxLayout()
        prompt_panel.setSpacing(4)
        prompt_label = QLabel("背景提示词")
        prompt_label.setProperty("muted", True)
        self._prompt_input = QPlainTextEdit()
        self._prompt_input.setPlaceholderText(
            "可填写故事背景、世界观、人物关系、语气风格等，翻译时会自动附加到提示词中"
        )
        self._prompt_input.setMinimumHeight(68)
        self._prompt_input.setMaximumHeight(78)
        prompt_panel.addWidget(prompt_label)
        prompt_panel.addWidget(self._prompt_input)

        names_panel = QVBoxLayout()
        names_panel.setSpacing(4)
        names_label = QLabel("中文人名（每行一个，AI 会自动对照）")
        names_label.setProperty("muted", True)
        self._names_input = QPlainTextEdit()
        self._names_input.setPlaceholderText("例如：\n路飞\n娜美\n索隆")
        self._names_input.setMinimumHeight(68)
        self._names_input.setMaximumHeight(78)
        names_panel.addWidget(names_label)
        names_panel.addWidget(self._names_input)

        pref_layout.addLayout(prompt_panel, 1)
        pref_layout.addLayout(names_panel, 1)

        self._prompt_input.setPlainText(self.config.get("translation_prompt", ""))
        self._names_input.setPlainText(self.config.get("chinese_names", ""))
        self._pref_toggle.toggled.connect(self._toggle_preferences)
        self._pref_save_timer = QTimer(self)
        self._pref_save_timer.setSingleShot(True)
        self._pref_save_timer.setInterval(400)
        self._pref_save_timer.timeout.connect(self._save_translation_preferences)
        self._prompt_input.textChanged.connect(self._schedule_save_preferences)
        self._names_input.textChanged.connect(self._schedule_save_preferences)


        control_layout.addWidget(self._pref_container)
        layout.addWidget(control_card)
        self._output_dir_input.editingFinished.connect(self._apply_output_dir)
        self.stage_focus = StageFocus()
        self.stage_label = self.stage_focus._detail
        self._progress_label = QLabel("0 / 0 个文件")
        self._progress_label.setProperty("muted", True)
        self._page_progress_label = QLabel("页数待确定")
        self._page_progress_label.setProperty("muted", True)
        progress_header = QHBoxLayout()
        progress_header.addWidget(self.stage_focus, 1)
        progress_header.addWidget(self._page_progress_label)
        progress_header.addWidget(self._progress_label)
        layout.addLayout(progress_header)
        self.step_panel = StepPanel()
        layout.addWidget(self.step_panel)
        content_header = QHBoxLayout()
        preview_label = PanelHeading("02", "检查结果")
        content_header.addWidget(preview_label, 1)
        content_header.addWidget(self._elapsed_label)
        self._edit_result_btn = QPushButton("进入精修 →")
        self._edit_result_btn.setProperty("compact", True)
        self._edit_result_btn.clicked.connect(lambda: self.tabs.setCurrentWidget(self.editor_page))
        content_header.addWidget(self._edit_result_btn)
        self._log_toggle = QToolButton()
        self._log_toggle.setText("详细日志")
        self._log_toggle.setCheckable(True)
        self._log_toggle.setChecked(True)
        self._log_toggle.setArrowType(Qt.DownArrow)
        self._log_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._log_toggle.setProperty("role", "quiet")
        self._log_toggle.toggled.connect(self._toggle_log_panel)
        content_header.addWidget(self._log_toggle)
        layout.addLayout(content_header)
        self.preview_tabs = QTabWidget()
        self.preview_tabs.setDocumentMode(True)
        self.original_view = ImagePreview(import_action=True)
        self.original_view.import_requested.connect(self._choose_files)
        self.result_view = ImagePreview()
        self.preview_tabs.addTab(self.original_view, "原图")
        self.preview_tabs.addTab(self.result_view, "译图")
        self._log_panel = LogPanel(self.diagnostics.log_path)
        self.log_view = self._log_panel.view
        self.work_splitter = QSplitter(Qt.Vertical)
        self.work_splitter.setHandleWidth(8)
        self.work_splitter.setChildrenCollapsible(False)
        self.work_splitter.addWidget(self.preview_tabs)
        self.work_splitter.addWidget(self._log_panel)
        self.work_splitter.setStretchFactor(0, 1)
        self.work_splitter.setStretchFactor(1, 0)
        self.work_splitter.setSizes([420, 220])
        layout.addWidget(self.work_splitter, 1)
        return group

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self._output_dir_input.text())
        if path:
            self._output_dir_input.setText(path)
            self._apply_output_dir()

    def _apply_output_dir(self) -> None:
        value = self._output_dir_input.text().strip()
        if not value:
            return
        if value == str(self.config.get("page_output_dir", "")):
            return
        self.config["page_output_dir"] = value
        try:
            app_config.save_ai_config({"page_output_dir": value})
        except Exception:
            return
        if hasattr(self, "api_config_page"):
            self.api_config_page._output_input.setText(value)
        self._append_log(f"输出目录已更新: {value}")

    def _change_source_language(self) -> None:
        language = self._source_language.currentData()
        # Each built-in language has its own automatic model route.
        self.config = save_ai_config({"source_language": language, "ocr_backend": "custom" if language == "custom" else "auto"})
        self.pipeline = None
        self.pipeline_fingerprint = None
        self.api_config_page.load_config(self.config)
        self._append_log(f"被翻译语言已切换为 {self._source_language.currentText()}，将在下次翻译时加载对应 OCR。")
        if language == "custom":
            self.tabs.setCurrentWidget(self.api_config_page)

    def _expand_document_paths(self, paths) -> tuple[list[Path], int]:
        documents: list[Path] = []
        skipped = 0
        for raw in paths:
            if not raw:
                continue
            path = Path(raw)
            if path.is_dir():
                try:
                    children = sorted(
                        child
                        for child in path.rglob("*")
                        if child.is_file() and child.suffix.lower() in DOCUMENT_EXTS
                    )
                except OSError:
                    skipped += 1
                    continue
                documents.extend(children)
            elif path.is_file() and path.suffix.lower() in DOCUMENT_EXTS:
                documents.append(path)
            else:
                skipped += 1
        return documents, skipped

    def _add_paths(self, paths) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        documents, skipped = self._expand_document_paths(paths)
        existing = {
            self.file_list.item(i).data(Qt.UserRole)
            for i in range(self.file_list.count())
        }
        added = 0
        duplicates = 0
        first_added = None
        for path in documents:
            key = str(path.resolve())
            if key in existing:
                duplicates += 1
                continue
            icon = self._thumbnail_icon(path)
            item = QListWidgetItem(icon, path.name)
            item.setData(Qt.UserRole, key)
            item.setData(Qt.UserRole + 1, path.name)
            item.setToolTip(str(path))
            item.setText(f"○ 等待\n{path.name}")
            item.setSizeHint(QSize(180, 92))
            self.file_list.addItem(item)
            if first_added is None:
                first_added = item
            existing.add(key)
            added += 1
        if added:
            self._append_log(f"已添加 {added} 个文件。")
            self.file_list.setCurrentItem(first_added)
            self.tabs.setCurrentWidget(self.translate_tab)
        if duplicates or skipped:
            details = []
            if duplicates:
                details.append(f"{duplicates} 个重复项")
            if skipped:
                details.append(f"{skipped} 个不支持的项目")
            self._append_log(f"已跳过{'、'.join(details)}。")
        self._update_actions()

    def _thumbnail_icon(self, path: Path) -> QIcon:
        if path.suffix.lower() == ".pdf":
            try:
                return QIcon(QPixmap.fromImage(render_pdf_preview(path, QSize(96, 96))))
            except Exception:
                return QIcon()
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        reader.setScaledSize(QSize(96, 96))
        image = reader.read()
        if not image.isNull():
            return QIcon(QPixmap.fromImage(image))
        return QIcon()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择漫画图片或 PDF",
            "",
            "漫画文件 (*.png *.jpg *.jpeg *.webp *.bmp *.pdf);;图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;PDF 文件 (*.pdf)",
        )
        self._add_paths(paths)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择漫画文件夹", "")
        if not folder:
            return
        self._add_paths([folder])

    def _all_files(self) -> list[Path]:
        return [
            Path(self.file_list.item(i).data(Qt.UserRole))
            for i in range(self.file_list.count())
        ]

    def _on_file_selection(self) -> None:
        items = self.file_list.selectedItems()
        if not items:
            self.original_view.clear("选择文件后显示原图")
            self.result_view.clear("处理完成后显示译文")
            self._update_actions()
            return
        key = items[-1].data(Qt.UserRole)
        self.original_view.set_image(key)
        output = self.results.get(key)
        if output:
            self.result_view.set_image(output)
        else:
            self.result_view.clear("处理完成后显示译文")
        self._update_actions()

    def _remove_selected(self) -> None:
        items = list(self.file_list.selectedItems())
        if not items:
            return
        next_row = min(self.file_list.row(items[0]), self.file_list.count() - len(items) - 1)
        for item in items:
            key = item.data(Qt.UserRole)
            self.results.pop(key, None)
            self.file_list.takeItem(self.file_list.row(item))
        if self.file_list.count():
            self.file_list.setCurrentRow(max(0, next_row))
        else:
            self.original_view.clear("选择文件后显示原图")
            self.result_view.clear("处理完成后显示译文")
        self._update_actions()

    def _clear_files(self) -> None:
        self.file_list.clear()
        self.results.clear()
        self.original_view.clear("选择文件后显示原图")
        self.result_view.clear("处理完成后显示译文")
        self.stage_label.setText("尚未开始")
        self._progress_label.setText("0 / 0 个文件")
        self._page_progress_label.setText("页数待确定")
        self.step_panel.reset()
        if self.warmup_worker is None:
            self._set_status("等待任务", "idle")
        self._update_actions()

    def _set_status(self, text: str, state: str = "idle") -> None:
        symbol = {"idle": "○", "warming": "◉", "running": "◉", "ready": "✓", "success": "✓", "error": "⊠", "warning": "△", "stopping": "□", "cancelled": "—"}.get(state, "○")
        self.status_label.setText(f"{symbol} {text}")
        self.status_label.setProperty("state", state)
        refresh_style(self.status_label)
        self.status_label.setAccessibleName(text)
        if state not in ('running', 'stopping'):
            self.stage_focus.set_stage('—', text, self.stage_label.text())

    def _update_elapsed(self):
        if self._task_clock.isValid():
            seconds = self._task_clock.elapsed() // 1000
            self._elapsed_label.setText(f"耗时 {seconds // 60:02d}:{seconds % 60:02d}")

    def _start_warmup(self) -> None:
        if self.pipeline is not None or self.warmup_worker is not None:
            return
        self.warmup_worker = BatchWorker(
            [],
            Path(self.config["page_output_dir"]),
            self.config,
            parent=self,
        )
        self._warmup_task_id = self.warmup_worker.task_id
        self.warmup_worker.log.connect(self._append_log)
        self.warmup_worker.log.connect(self._on_warmup_log)
        self.warmup_worker.pipeline_ready.connect(self._on_pipeline_ready)
        self.warmup_worker.finished.connect(self._on_warmup_finished)
        self.warmup_worker.start()
        self.stage_label.setText("正在加载本地模型，可先添加待处理文件")
        self._progress_label.setText("模型预热")
        self._set_status("模型准备中", "warming")
        self._update_actions()
        self._append_log("正在预热 AI 管线...")

    def _on_warmup_log(self, message: str) -> None:
        if message and not message.startswith("["):
            self.stage_label.setText(message)

    def _on_warmup_finished(self, success: int, failed: int) -> None:
        if self.warmup_worker is not None:
            self.warmup_worker.wait()
            self.warmup_worker.deleteLater()
        self.warmup_worker = None
        self._progress_label.setText("0 / 0 个文件")
        self._page_progress_label.setText("页数待确定")
        if self.pipeline is None:
            self.stage_label.setText("模型初始化未完成，请在报错日志中查看原因")
            self._set_status("模型准备失败", "error")
        else:
            self.stage_label.setText("模型已就绪，添加文件后即可开始")
            self._set_status("模型已就绪", "ready")
        self._update_actions()

    def _start_translation(self) -> None:
        if self.worker is not None or self.warmup_worker is not None:
            return
        self._stop_requested = False
        files = self._all_files()
        if not files:
            self._set_status("请先添加文件", "warning")
            return

        self._apply_output_dir()
        self.step_panel.reset()
        self._save_translation_preferences()
        missing = missing_models(self.config)
        if missing:
            detail = "\n".join(missing)
            QMessageBox.warning(
                self,
                "OCR 或模型尚未就绪",
                f"请先完成以下配置再开始翻译：\n\n{detail}",
            )
            return

        if (
            not self.config["api_key"]
            or not self.config["api_base_url"]
            or not self.config["translation_model"]
        ):
            QMessageBox.warning(
                self,
                "翻译 API 未配置",
                "请先填写 API Key、Base URL 和翻译模型。\n"
                "未连接翻译 API 时不会生成伪装成译文的输出文件。",
            )
            self._set_status("需要配置翻译 API", "warning")
            self._show_api_config()
            return

        output_dir = Path(self.config["page_output_dir"])
        fingerprint = config_fingerprint(self.config)
        if self.pipeline is None or self.pipeline_fingerprint != fingerprint:
            self.pipeline = None

        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            key = item.data(Qt.UserRole)
            item.setText(f"○ 等待\n{item.data(Qt.UserRole + 1) or Path(key).name}")
            self.results.pop(key, None)

        self.worker = BatchWorker(
            files,
            output_dir,
            self.config,
            pipeline=self.pipeline,
            parent=self,
        )
        self._active_task_id = self.worker.task_id
        self._warmup_task_id = None
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._append_log)
        self.worker.stage_event.connect(self._on_stage_event)
        self.worker.page_progress.connect(self._on_page_progress)
        self.worker.pipeline_ready.connect(self._on_pipeline_ready)
        self.worker.image_done.connect(self._on_image_done)
        self.worker.image_failed.connect(self._on_image_failed)
        self.worker.finished.connect(self._on_finished)
        self._task_clock.start()
        self._elapsed_timer.start()
        self.worker.start()

        self._progress_label.setText(f"0 / {len(files)}")
        self._page_progress_label.setText("页数待确定")
        self.stage_label.setText("任务已创建，正在准备第一份文件")
        self._set_running(True)

    def _stop_translation(self) -> None:
        if self.worker and self.worker.isRunning():
            self._stop_requested = True
            self.worker.stop()
            self._stop_btn.setEnabled(False)
            self._set_status("正在停止", "stopping")
            self.stage_label.setText("正在安全停止当前任务…")

    def _set_running(self, running: bool) -> None:
        if running:
            self._set_status("正在翻译", "running")
            self.stage_focus.set_stage('—', '准备处理', self.stage_label.text())
        self._update_actions()

    def _update_actions(self) -> None:
        running = self.worker is not None
        warming = self.warmup_worker is not None and self.warmup_worker.isRunning()
        count = self.file_list.count()
        selected_count = len(self.file_list.selectedItems())
        self._start_btn.setText(f"开始翻译（{count}）" if count else "开始翻译")
        self._start_btn.setEnabled(not running and not warming and count > 0)
        self._stop_btn.setVisible(running)
        self._stop_btn.setEnabled(running and not self._stop_requested)
        self._add_btn.setEnabled(not running)
        self._folder_btn.setEnabled(not running)
        self.original_view.import_button.setEnabled(not running)
        self._output_dir_input.setEnabled(not running)
        self._browse_output_btn.setEnabled(not running)
        self._pref_container.setEnabled(not running)
        self._settings_btn.setEnabled(not running)
        self._remove_btn.setEnabled(not running and selected_count > 0)
        self._clear_btn.setEnabled(not running and count > 0)
        self.api_config_page.setEnabled(not running and not warming)
        self._source_language.setEnabled(not running and not warming)
        self._file_count_label.setText(f"{count} 个文件")
        self._file_selection_label.setText(
            f"已选 {selected_count} 个" if selected_count else "支持图片与 PDF"
        )
        selected = self.file_list.selectedItems()
        output = self.results.get(selected[-1].data(Qt.UserRole)) if selected else None
        self._edit_result_btn.setEnabled(bool(output and Path(output).suffix.lower() != ".pdf"))
        self._edit_result_btn.setToolTip("精修已生成的图片" if self._edit_result_btn.isEnabled() else "请选择已完成的图片；PDF 暂无持久化精修数据")
        if warming:
            self._start_btn.setToolTip("本地模型正在准备，完成后即可开始")
        elif not count:
            self._start_btn.setToolTip("请先添加漫画图片或 PDF")
        else:
            self._start_btn.setToolTip(f"开始处理当前列表中的 {count} 个文件")

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self._progress_label.setText(f"{done} / {total} 个文件")
        self.stage_label.setText(message)

    def _on_stage_event(self, event) -> None:
        if self.worker is None or event['task_id'] != self.worker.task_id:
            return
        self.step_panel.consume_event(event)
        number = f"{STAGE_ORDER.index(event['stage']) + 1:02d}" if event['stage'] in STAGE_ORDER else '×'
        state_label = {'running': '运行中', 'done': '完成', 'failed': '失败', 'skipped': '已跳过', 'cancelled': '已取消'}[event['state']]
        self.stage_focus.set_stage(number, STAGE_LABELS.get(event['stage'], '当前页面') + ' · ' + state_label, event['page_label'])
        self.stage_label.setText(event['message'])
        self.stage_label.setToolTip(event['message'])
        index = event['document_index']
        if 0 < index <= self.file_list.count():
            item = self.file_list.item(index - 1)
            state = {'failed': '⊠ 失败', 'cancelled': '— 已取消'}.get(event['state'], '◉ 处理中')
            item.setText(f"{state}\n{item.data(Qt.UserRole + 1)}")

    def _on_page_progress(self, done, total):
        self._page_progress_label.setText(f"已处理 {done} / {total} 页")

    def _on_pipeline_ready(self, pipeline) -> None:
        self.pipeline = pipeline
        self.pipeline_fingerprint = config_fingerprint(self.config)
        self._append_log("AI 模型初始化完成。")

    def _on_image_done(self, input_path: str, output_path: str) -> None:
        key = str(Path(input_path).resolve())
        self.results[key] = output_path
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) == key:
                item.setText(f"✓ 完成\n{item.data(Qt.UserRole + 1) or Path(key).name}")
                break

        selected = self.file_list.selectedItems()
        if selected and selected[-1].data(Qt.UserRole) == key:
            self.result_view.set_image(output_path)
            self.preview_tabs.setCurrentWidget(self.result_view)

    def _on_image_failed(self, name: str, message: str) -> None:
        self.step_panel.mark_failed()
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            original_name = item.data(Qt.UserRole + 1) or Path(item.data(Qt.UserRole)).name
            if original_name == name:
                item.setText(f"⊠ 失败\n{original_name}")
                item.setToolTip(f"{item.data(Qt.UserRole)}\n{message}")
                break
        self._append_log(f"[失败] {name}: {message}")

    def _on_finished(self, success: int, failed: int) -> None:
        # The terminal signal is emitted as run() returns. Keep the worker until it exits.
        if self.worker is not None:
            self._stop_requested = self._stop_requested or self.worker._is_stopped()
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None
        self._elapsed_timer.stop()
        self._update_elapsed()
        self._set_running(False)
        total_done = success + failed
        if self._stop_requested and total_done < self.file_list.count():
            summary = f"已停止，完成 {success} 个文件，失败 {failed} 个文件。"
            self.step_panel.mark_cancelled()
            state = "cancelled"
            status = "任务已取消"
            for index in range(self.file_list.count()):
                item = self.file_list.item(index)
                if item.data(Qt.UserRole) not in self.results and not item.text().startswith("⊠"):
                    item.setText(f"— 已取消\n{item.data(Qt.UserRole + 1)}")
        elif failed or total_done < self.file_list.count():
            summary = f"处理结束：成功 {success} 个文件，失败 {failed} 个文件。"
            self.step_panel.mark_failed()
            state = "error"
            status = "部分文件失败"
        else:
            summary = f"全部完成，共 {success} 个文件。"
            state = "success"
            status = "全部完成"
        self._set_status(status, state)
        self.stage_label.setText(summary)
        self._append_log(summary)
        self._log_panel.flush_all()
        self._update_actions()
        if failed and total_done == self.file_list.count():
            self._show_issue_prompt()

    def _open_output_dir(self) -> None:
        path = Path(self.config["page_output_dir"])
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_issue(self) -> None:
        url = self.config.get("issue_url", "").strip()
        if not url:
            QMessageBox.information(
                self,
                "Issue 链接未配置",
                "请先在 API 配置页填写 Issue 链接，例如：\nhttps://github.com/你的用户名/ComiTrans/issues",
            )
            return
        QDesktopServices.openUrl(QUrl(url))

    def _show_issue_prompt(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("翻译失败")
        box.setText(
            "本次翻译有图片失败。\n"
            "建议到 GitHub 提交 Issue，并附带报错日志页生成的诊断提示词。"
        )
        copy_btn = box.addButton("复制诊断提示词", QMessageBox.ActionRole)
        issue_btn = box.addButton("打开 Issue 页面", QMessageBox.ActionRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is copy_btn:
            self.error_log_page.copy_prompt()
        elif clicked is issue_btn:
            self._open_issue()

    def _show_api_config(self) -> None:
        self.api_config_page.load_config(self.config)
        self.tabs.setCurrentWidget(self.api_config_page)

    def _on_tab_changed(self, index: int) -> None:
        page = self.tabs.widget(index)
        self._nav_auto.setChecked(page is self.translate_tab)
        self._nav_editor.setChecked(page is self.editor_page)
        if page is self.error_log_page:
            self.error_log_page.refresh()
        if page is self.editor_page:
            selected = self.file_list.selectedItems()
            if selected:
                output = self.results.get(selected[-1].data(Qt.UserRole))
                if output and Path(output).suffix.lower() != ".pdf":
                    self.editor_page.load_page(output)

    def _show_error_log(self) -> None:
        self.error_log_page.refresh()
        self.tabs.setCurrentWidget(self.error_log_page)

    def _refresh_error_page(self) -> None:
        self.error_log_page.refresh()

    def _toggle_preferences(self, checked: bool) -> None:
        self._pref_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self._pref_container.setVisible(checked)

    def _toggle_log_panel(self, visible: bool) -> None:
        self._log_panel.setVisible(visible)
        self._log_toggle.setText("详细日志" if visible else "展开日志")
        self._log_toggle.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)
        self._apply_compact_layout()

    def _apply_compact_layout(self):
        if not hasattr(self, 'preview_tabs'):
            return
        compact = self.height() < 680
        self._brand_title.setFont(brand_font(32 if self.width() < 1120 else 48))
        narrow = self.width() < 1120
        self._more_btn.setVisible(narrow)
        self._output_btn.setVisible(not narrow)
        self._issue_btn.setVisible(not narrow)
        self._settings_btn.setVisible(self.width() >= 960)
        self._logs_btn.setVisible(self.width() >= 960)
        inline = self.width() >= 1180
        if inline != self._controls_inline:
            self._controls_inline = inline
            for widget in (self._language_controls, self._output_controls, self._start_btn):
                self._control_grid.removeWidget(widget)
            self._control_grid.addWidget(self._language_controls, 0, 0, 1, 1 if inline else 2)
            self._control_grid.addWidget(self._output_controls, 0 if inline else 1, 1 if inline else 0, 1, 1 if inline else 3)
            self._control_grid.addWidget(self._start_btn, 0, 2)
            self._control_grid.setColumnStretch(1, 1)
        self._output_controls.setVisible(self.height() >= 580)
        self._chapter_banner.set_compact(self.height() < 780, tight=self.height() < 580)
        self._elapsed_label.setVisible(not compact)
        self.step_panel.set_compact(compact)
        self.preview_tabs.setVisible(not compact or not self._log_toggle.isChecked())
        self._log_toggle.setToolTip('小窗口下，收起日志可查看图像' if compact else '独立展开或收起详细日志')
        self._work_layout.setContentsMargins(12, 8 if compact else 12, 12, 12)
        self._work_layout.setSpacing(4 if compact else 6)
        self._queue_layout.setContentsMargins(16, 8, 16, 16)
        self._queue_layout.setSpacing(8 if compact else 12)
        self._file_selection_label.setVisible(not compact)
        self._drop_hint.setVisible(not compact)
        self._drop_title.setVisible(self.height() >= 580)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_compact_layout()

    def _schedule_save_preferences(self) -> None:
        self._pref_save_timer.start()

    def _save_translation_preferences(self) -> None:
        self.config["translation_prompt"] = self._prompt_input.toPlainText().strip()
        self.config["chinese_names"] = self._names_input.toPlainText().strip()
        self.config = save_ai_config(
            {
                "translation_prompt": self.config["translation_prompt"],
                "chinese_names": self.config["chinese_names"],
            }
        )
        if self.pipeline is not None:
            self.pipeline.translation_prompt = self.config["translation_prompt"]
            self.pipeline.chinese_names = self.config["chinese_names"]

    def _save_api_config(self) -> None:
        updates = self.api_config_page.values()
        errors = validate_ocr_config({**self.config, **updates})
        if errors:
            QMessageBox.warning(self, "OCR 配置不完整", "\n".join(errors))
            return
        if updates.get("api_key") and updates["api_key"] == updates.get("translation_model"):
            QMessageBox.warning(
                self,
                "API 配置提示",
                "API Key 与模型名相同，看起来把模型名填到了密钥栏。"
                "DeepSeek / OpenAI 等平台的密钥通常以 sk- 开头。",
            )
            return
        self.config = save_ai_config(updates)
        self.api_config_page.load_config(self.config)
        self._source_language.blockSignals(True)
        self._source_language.setCurrentIndex(max(0, self._source_language.findData(self.config.get("source_language", "ja"))))
        self._source_language.blockSignals(False)
        self._output_dir_input.setText(self.config.get("page_output_dir", ""))
        self.api_config_page.mark_saved()
        fingerprint = config_fingerprint(self.config)
        if self.pipeline and self.pipeline_fingerprint == fingerprint:
            self.pipeline.api_key = self.config["api_key"]
            self.pipeline.api_base_url = self.config["api_base_url"]
            self.pipeline.translation_model = self.config["translation_model"]
            self.pipeline.translation_prompt = self.config.get("translation_prompt", "")
            self.pipeline.chinese_names = self.config.get("chinese_names", "")
            self.pipeline.multimodal = bool(self.config.get("multimodal", False))
        else:
            self.pipeline = None
        self._set_status("配置已保存", "success")
        self._append_log("API 配置已保存，将在下次翻译时生效。")

    def _append_log(self, message: str) -> None:
        sender = self.sender()
        if isinstance(sender, BatchWorker) and sender.task_id not in (self._active_task_id, self._warmup_task_id):
            return
        self._log_panel.append(message)
        if message.startswith(("[失败]", "[严重错误]", "[失败堆栈]")):
            self.diagnostics.add_error(message)
        else:
            self.diagnostics.append(message)
        if self.tabs.currentWidget() is self.error_log_page:
            self._prompt_refresh_timer.start()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
            return
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        accepted = any(
            path.is_dir() or (path.is_file() and path.suffix.lower() in DOCUMENT_EXTS)
            for path in paths
        )
        if accepted:
            self._drop_zone.setProperty("dragActive", True)
            refresh_style(self._drop_zone)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drop_zone.setProperty("dragActive", False)
        refresh_style(self._drop_zone)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_zone.setProperty("dragActive", False)
        refresh_style(self._drop_zone)
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self._add_paths(paths)
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        if not self.editor_page.confirm_discard():
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "退出确认",
                "翻译仍在进行中，退出会中断当前任务。确定退出吗？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.stop()
            self.worker.wait()
        if self.warmup_worker is not None and self.warmup_worker.isRunning():
            self.warmup_worker.wait()
        self.error_log_page.shutdown()
        self._log_panel.flush_all()
        self.editor_page.save_ui_state()
        for key, splitter in (("queue", self.queue_splitter), ("previewLog", self.work_splitter)):
            self._ui_settings.setValue(f"ui/{key}", splitter.saveState())
        self._ui_settings.setValue("ui/logVisible", self._log_toggle.isChecked())
        self._ui_settings.setValue("ui/preferencesVisible", self._pref_toggle.isChecked())
        event.accept()
