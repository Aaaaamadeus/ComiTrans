from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSize,
    Qt,
    QTime,
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
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import config as app_config
from ..config import config_fingerprint, missing_models, save_ai_config
from ..diagnostics import Diagnostics
from ..pdf_utils import render_pdf_preview
from ..worker import BatchWorker
from .api_config_page import ApiConfigPage
from .editor_page import EditorPage
from .error_log_page import ErrorLogPage
from .step_panel import StepPanel
from .theme import APP_STYLESHEET, refresh_style


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
DOCUMENT_EXTS = IMAGE_EXTS | {".pdf"}


class ImagePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._original = QPixmap()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("无预览")
        self._label.setObjectName("previewLabel")
        self._label.setAlignment(Qt.AlignCenter)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("previewCanvas")
        self._scroll.setWidget(self._label)
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._scroll)

        self._fade_effect = QGraphicsOpacityEffect(self._label)
        self._fade_effect.setOpacity(1.0)
        self._label.setGraphicsEffect(self._fade_effect)
        self._fade_animation = QPropertyAnimation(self._fade_effect, b"opacity", self)
        self._fade_animation.setDuration(180)
        self._fade_animation.setEasingCurve(QEasingCurve.OutCubic)

    def set_image(self, path: str) -> None:
        if Path(path).suffix.lower() == ".pdf":
            try:
                self._original = QPixmap.fromImage(render_pdf_preview(path, QSize(1600, 1600)))
            except Exception as exc:
                self._original = QPixmap()
                self._label.setPixmap(QPixmap())
                self._label.setText(f"无法预览 PDF\n{exc}")
                return
        else:
            self._original = QPixmap(path)
        if self._original.isNull():
            self._label.setPixmap(QPixmap())
            self._label.setText("无法读取图片")
            return
        self._update_scaled()
        self._fade_animation.stop()
        self._fade_animation.setStartValue(0.35)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

    def clear(self, text: str = "无预览") -> None:
        self._original = QPixmap()
        self._label.setPixmap(QPixmap())
        self._label.setText(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self) -> None:
        if self._original.isNull():
            return
        size = self._scroll.viewport().size()
        if size.width() <= 0 or size.height() <= 0:
            return
        scaled = self._original.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._label.setPixmap(scaled)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ComiTrans 本地漫画翻译")
        self.setWindowIcon(QIcon(str(app_config.ICON_PATH)))
        self.resize(1240, 800)
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
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        header = QHBoxLayout(top_bar)
        header.setContentsMargins(15, 9, 12, 9)
        header.setSpacing(7)

        icon_label = QLabel()
        icon_label.setFixedSize(38, 38)
        icon_label.setPixmap(QIcon(str(app_config.ICON_PATH)).pixmap(34, 34))
        icon_label.setAlignment(Qt.AlignCenter)
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(0)
        title = QLabel("ComiTrans")
        title.setObjectName("brandTitle")
        subtitle = QLabel("本地漫画翻译工作台")
        subtitle.setObjectName("brandSubtitle")
        brand_layout.addWidget(title)
        brand_layout.addWidget(subtitle)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusPill")
        self.status_label.setProperty("state", "idle")
        self.status_label.setAlignment(Qt.AlignCenter)

        self._settings_btn = QPushButton("配置")
        self._logs_btn = QPushButton("诊断")
        self._output_btn = QPushButton("输出")
        self._issue_btn = QPushButton("反馈")
        for button in (
            self._settings_btn,
            self._logs_btn,
            self._output_btn,
            self._issue_btn,
        ):
            button.setProperty("role", "quiet")
            button.setProperty("compact", True)

        self._start_btn = QPushButton("开始翻译")
        self._start_btn.setProperty("role", "primary")
        self._stop_btn = QPushButton("停止")
        self._stop_btn.setProperty("role", "danger")
        self._stop_btn.setProperty("compact", True)

        self._settings_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self._logs_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning))
        self._output_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._issue_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion))
        self._start_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self._stop_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))

        self._settings_btn.setToolTip("翻译服务、OCR 与运行设置")
        self._logs_btn.setToolTip("查看运行日志与 AI 诊断")
        self._output_btn.setToolTip("打开译文输出目录")
        self._issue_btn.setToolTip("反馈问题")

        header.addWidget(icon_label)
        header.addLayout(brand_layout)
        header.addStretch(1)
        header.addWidget(self.status_label)
        header.addWidget(self._settings_btn)
        header.addWidget(self._logs_btn)
        header.addWidget(self._output_btn)
        header.addWidget(self._issue_btn)
        header.addWidget(self._start_btn)
        header.addWidget(self._stop_btn)
        root.addWidget(top_bar)

        self._status_opacity = QGraphicsOpacityEffect(self.status_label)
        self.status_label.setGraphicsEffect(self._status_opacity)
        self._status_pulse = QPropertyAnimation(self._status_opacity, b"opacity", self)
        self._status_pulse.setDuration(1400)
        self._status_pulse.setLoopCount(-1)
        self._status_pulse.setKeyValueAt(0.0, 1.0)
        self._status_pulse.setKeyValueAt(0.5, 0.68)
        self._status_pulse.setKeyValueAt(1.0, 1.0)
        self._status_pulse.setEasingCurve(QEasingCurve.InOutSine)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.translate_tab = QSplitter(Qt.Horizontal)
        self.translate_tab.setChildrenCollapsible(False)
        self.translate_tab.addWidget(self._build_file_panel())
        self.translate_tab.addWidget(self._build_work_panel())
        self.translate_tab.setStretchFactor(0, 0)
        self.translate_tab.setStretchFactor(1, 1)
        self.translate_tab.setSizes([280, 900])
        self.tabs.addTab(
            self.translate_tab,
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "翻译工作台",
        )

        self.api_config_page = ApiConfigPage(self.config)
        self.api_config_page.save_requested.connect(self._save_api_config)
        self.tabs.addTab(
            self.api_config_page,
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
            "API 配置",
        )
        self.error_log_page = ErrorLogPage(self.diagnostics)
        self.tabs.addTab(
            self.error_log_page,
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning),
            "报错日志",
        )
        self.editor_page = EditorPage()
        self.tabs.addTab(
            self.editor_page,
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
            "嵌字编辑",
        )
        root.addWidget(self.tabs, 1)

        self._progress_animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_animation.setDuration(220)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._tab_fade_animation = None
        self._tab_fade_effect = None

        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._add_btn.clicked.connect(self._choose_files)
        self._folder_btn.clicked.connect(self._choose_folder)
        self._settings_btn.clicked.connect(self._show_api_config)
        self._logs_btn.clicked.connect(self._show_error_log)
        self._output_btn.clicked.connect(self._open_output_dir)
        self._issue_btn.clicked.connect(self._open_issue)
        self._start_btn.clicked.connect(self._start_translation)
        self._stop_btn.clicked.connect(self._stop_translation)

    def _build_file_panel(self) -> QWidget:
        group = QGroupBox("待处理文件")
        group.setMinimumWidth(285)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        summary_row = QHBoxLayout()
        self._file_count_label = QLabel("0 个文件")
        self._file_count_label.setObjectName("sectionTitle")
        self._file_selection_label = QLabel("支持图片与 PDF")
        self._file_selection_label.setProperty("muted", True)
        summary_row.addWidget(self._file_count_label)
        summary_row.addStretch(1)
        summary_row.addWidget(self._file_selection_label)
        layout.addLayout(summary_row)

        self._drop_zone = QFrame()
        self._drop_zone.setObjectName("dropZone")
        self._drop_zone.setProperty("dragActive", False)
        drop_layout = QVBoxLayout(self._drop_zone)
        drop_layout.setContentsMargins(10, 8, 10, 8)
        drop_layout.setSpacing(3)
        drop_title = QLabel("拖放文件或文件夹到这里")
        drop_title.setObjectName("dropTitle")
        drop_title.setAlignment(Qt.AlignCenter)
        drop_hint = QLabel("PNG · JPG · WEBP · BMP · PDF")
        drop_hint.setObjectName("dropHint")
        drop_hint.setAlignment(Qt.AlignCenter)
        drop_actions = QHBoxLayout()
        drop_actions.addStretch(1)
        self._add_btn = QPushButton("选择文件")
        self._add_btn.setProperty("compact", True)
        self._folder_btn = QPushButton("选择文件夹")
        self._folder_btn.setProperty("role", "quiet")
        self._folder_btn.setProperty("compact", True)
        self._add_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self._folder_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        drop_actions.addWidget(self._add_btn)
        drop_actions.addWidget(self._folder_btn)
        drop_actions.addStretch(1)
        drop_layout.addWidget(drop_title)
        drop_layout.addWidget(drop_hint)
        drop_layout.addLayout(drop_actions)
        layout.addWidget(self._drop_zone)

        self.file_list = QListWidget()
        self.file_list.setViewMode(QListView.IconMode)
        self.file_list.setIconSize(QSize(88, 88))
        self.file_list.setResizeMode(QListView.Adjust)
        self.file_list.setSpacing(4)
        self.file_list.setMovement(QListView.Static)
        self.file_list.setWordWrap(True)
        self.file_list.setUniformItemSizes(True)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.itemSelectionChanged.connect(self._on_file_selection)
        layout.addWidget(self.file_list, 1)

        buttons = QHBoxLayout()
        self._remove_btn = QPushButton("移除选中")
        self._clear_btn = QPushButton("清空")
        self._remove_btn.setProperty("role", "quiet")
        self._clear_btn.setProperty("role", "quiet")
        self._remove_btn.setProperty("compact", True)
        self._clear_btn.setProperty("compact", True)
        buttons.addWidget(self._remove_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._clear_btn)
        layout.addLayout(buttons)

        self._remove_btn.clicked.connect(self._remove_selected)
        self._clear_btn.clicked.connect(self._clear_files)
        return group

    def _build_work_panel(self) -> QWidget:
        group = QGroupBox("翻译工作区")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(11, 12, 11, 10)
        layout.setSpacing(8)

        control_card = QFrame()
        control_card.setObjectName("controlCard")
        control_layout = QVBoxLayout(control_card)
        control_layout.setContentsMargins(10, 8, 10, 8)
        control_layout.setSpacing(6)

        control_row = QHBoxLayout()
        self._pref_toggle = QToolButton()
        self._pref_toggle.setText("偏好设置")
        self._pref_toggle.setCheckable(True)
        self._pref_toggle.setArrowType(Qt.RightArrow)
        self._pref_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._pref_toggle.setProperty("role", "quiet")
        self._pref_toggle.setProperty("compact", True)

        output_label = QLabel("输出目录")
        output_label.setProperty("muted", True)
        self._output_dir_input = QLineEdit(str(self.config.get("page_output_dir", "")))
        self._output_dir_input.setPlaceholderText("默认: page/output_page_output")
        self._output_dir_input.setToolTip("译文、清理底图与排版信息将保存到这里")
        browse_output_btn = QPushButton("浏览")
        browse_output_btn.setProperty("role", "quiet")
        browse_output_btn.setProperty("compact", True)
        browse_output_btn.clicked.connect(self._browse_output_dir)

        control_row.addWidget(self._pref_toggle)
        control_row.addStretch(1)
        control_row.addWidget(output_label)
        control_row.addWidget(self._output_dir_input, 1)
        control_row.addWidget(browse_output_btn)
        control_layout.addLayout(control_row)

        self._pref_container = QWidget()
        self._pref_container.setVisible(False)
        self._pref_container.setMaximumHeight(0)
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

        self._pref_opacity = QGraphicsOpacityEffect(self._pref_container)
        self._pref_opacity.setOpacity(0.0)
        self._pref_container.setGraphicsEffect(self._pref_opacity)
        self._pref_animation = QParallelAnimationGroup(self)
        self._pref_height_animation = QPropertyAnimation(
            self._pref_container, b"maximumHeight", self
        )
        self._pref_height_animation.setDuration(180)
        self._pref_height_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._pref_opacity_animation = QPropertyAnimation(
            self._pref_opacity, b"opacity", self
        )
        self._pref_opacity_animation.setDuration(150)
        self._pref_opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._pref_animation.addAnimation(self._pref_height_animation)
        self._pref_animation.addAnimation(self._pref_opacity_animation)
        self._pref_animation.finished.connect(self._finish_preference_animation)
        self._pref_expanding = False

        control_layout.addWidget(self._pref_container)
        layout.addWidget(control_card)
        self._output_dir_input.editingFinished.connect(self._apply_output_dir)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.stage_label = QLabel("尚未开始")
        self.stage_label.setObjectName("sectionTitle")
        self._progress_label = QLabel("0 / 0")
        self._progress_label.setProperty("muted", True)

        progress_header = QHBoxLayout()
        progress_header.addWidget(self.stage_label)
        progress_header.addStretch(1)
        progress_header.addWidget(self._progress_label)

        self.step_panel = StepPanel()
        self.preview_tabs = QTabWidget()
        self.preview_tabs.setDocumentMode(True)
        self.original_view = ImagePreview()
        self.result_view = ImagePreview()
        self.preview_tabs.addTab(self.original_view, "原图预览")
        self.preview_tabs.addTab(self.result_view, "译文预览")

        content_header = QHBoxLayout()
        preview_label = QLabel("图像预览")
        preview_label.setObjectName("sectionTitle")
        self._log_toggle = QToolButton()
        self._log_toggle.setText("收起运行日志")
        self._log_toggle.setCheckable(True)
        self._log_toggle.setChecked(True)
        self._log_toggle.setArrowType(Qt.DownArrow)
        self._log_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._log_toggle.setProperty("role", "quiet")
        self._log_toggle.setProperty("compact", True)
        self._log_toggle.toggled.connect(self._toggle_log_panel)
        content_header.addWidget(preview_label)
        content_header.addStretch(1)
        content_header.addWidget(self._log_toggle)

        self._log_panel = QFrame()
        self._log_panel.setObjectName("logPanel")
        log_layout = QVBoxLayout(self._log_panel)
        log_layout.setContentsMargins(7, 7, 7, 7)
        log_layout.setSpacing(4)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setProperty("code", True)
        self.log_view.setMinimumHeight(110)
        log_layout.addWidget(self.log_view)

        self.work_splitter = QSplitter(Qt.Vertical)
        self.work_splitter.setChildrenCollapsible(False)
        self.work_splitter.addWidget(self.preview_tabs)
        self.work_splitter.addWidget(self._log_panel)
        self.work_splitter.setStretchFactor(0, 3)
        self.work_splitter.setStretchFactor(1, 1)
        self.work_splitter.setSizes([420, 140])

        layout.addLayout(progress_header)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.step_panel)
        layout.addLayout(content_header)
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
            item.setTextAlignment(Qt.AlignHCenter)
            item.setSizeHint(QSize(124, 126))
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
                return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
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
        self._progress_animation.stop()
        self.file_list.clear()
        self.results.clear()
        self.original_view.clear("选择文件后显示原图")
        self.result_view.clear("处理完成后显示译文")
        self.progress_bar.setValue(0)
        self.stage_label.setText("尚未开始")
        self._progress_label.setText("0 / 0")
        self.step_panel.reset()
        self._update_actions()

    def _set_status(self, text: str, state: str = "idle") -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        refresh_style(self.status_label)
        if state in {"warming", "running", "stopping"}:
            if self._status_pulse.state() != QAbstractAnimation.Running:
                self._status_pulse.start()
        else:
            self._status_pulse.stop()
            self._status_opacity.setOpacity(1.0)

    def _start_warmup(self) -> None:
        if self.pipeline is not None or self.warmup_worker is not None:
            return
        self.warmup_worker = BatchWorker(
            [],
            Path(self.config["page_output_dir"]),
            self.config,
            parent=self,
        )
        self.warmup_worker.log.connect(self._append_log)
        self.warmup_worker.log.connect(self._on_warmup_log)
        self.warmup_worker.pipeline_ready.connect(self._on_pipeline_ready)
        self.warmup_worker.finished.connect(self._on_warmup_finished)
        self.progress_bar.setRange(0, 0)
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
        self.warmup_worker = None
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self._progress_label.setText("0 / 0")
        if self.pipeline is None:
            self.stage_label.setText("模型初始化未完成，请在报错日志中查看原因")
            self._set_status("模型准备失败", "error")
        else:
            self.stage_label.setText("模型已就绪，添加文件后即可开始")
            self._set_status("模型已就绪", "ready")
        self._update_actions()

    def _start_translation(self) -> None:
        files = self._all_files()
        if not files:
            self._set_status("请先添加文件", "warning")
            return
        if self.warmup_worker is not None and self.warmup_worker.isRunning():
            self._append_log("AI 管线正在预热，请稍候再开始翻译。")
            self._set_status("模型准备中", "warming")
            return

        self._apply_output_dir()
        self.step_panel.reset()
        self._save_translation_preferences()
        missing = missing_models(self.config)
        if missing:
            detail = "\n".join(missing)
            answer = QMessageBox.warning(
                self,
                "模型文件缺失",
                f"以下模型文件不存在，翻译可能失败：\n\n{detail}",
                QMessageBox.Yes | QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
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
            item.setText(item.data(Qt.UserRole + 1) or Path(key).name)
            self.results.pop(key, None)

        self.worker = BatchWorker(
            files,
            output_dir,
            self.config,
            pipeline=self.pipeline,
            parent=self,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._append_log)
        self.worker.stage_changed.connect(self._on_stage)
        self.worker.pipeline_ready.connect(self._on_pipeline_ready)
        self.worker.image_done.connect(self._on_image_done)
        self.worker.image_failed.connect(self._on_image_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

        self.progress_bar.setRange(0, len(files))
        self.progress_bar.setValue(0)
        self._progress_label.setText(f"0 / {len(files)}")
        self.stage_label.setText("任务已创建，正在准备第一份文件")
        self._set_running(True)

    def _stop_translation(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self._stop_btn.setEnabled(False)
            self.step_panel.mark_cancelled()
            self._set_status("正在停止", "stopping")
            self.stage_label.setText("正在安全停止当前任务…")

    def _set_running(self, running: bool) -> None:
        if running:
            self._set_status("正在翻译", "running")
        self._update_actions()

    def _update_actions(self) -> None:
        running = self.worker is not None and self.worker.isRunning()
        warming = self.warmup_worker is not None and self.warmup_worker.isRunning()
        count = self.file_list.count()
        selected_count = len(self.file_list.selectedItems())
        self._start_btn.setText(f"开始翻译（{count}）" if count else "开始翻译")
        self._start_btn.setEnabled(not running and not warming and count > 0)
        self._stop_btn.setEnabled(running)
        self._add_btn.setEnabled(not running)
        self._folder_btn.setEnabled(not running)
        self._settings_btn.setEnabled(not running)
        self._remove_btn.setEnabled(not running and selected_count > 0)
        self._clear_btn.setEnabled(not running and count > 0)
        self.api_config_page.setEnabled(not running)
        self._file_count_label.setText(f"{count} 个文件")
        self._file_selection_label.setText(
            f"已选 {selected_count} 个" if selected_count else "支持图片与 PDF"
        )
        if warming:
            self._start_btn.setToolTip("本地模型正在准备，完成后即可开始")
        elif not count:
            self._start_btn.setToolTip("请先添加漫画图片或 PDF")
        else:
            self._start_btn.setToolTip(f"开始处理当前列表中的 {count} 个文件")

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self._progress_animation.stop()
        self.progress_bar.setMaximum(total)
        self._progress_animation.setStartValue(self.progress_bar.value())
        self._progress_animation.setEndValue(done)
        self._progress_animation.start()
        self._progress_label.setText(f"{done} / {total}")
        self.stage_label.setText(message)

    def _on_stage(self, index: int, stage: str, message: str) -> None:
        self.stage_label.setText(message)
        if stage == "start":
            name = message.split(":", 1)[0] if ":" in message else message
            self.step_panel.start_file(name)
        elif stage == "cancelled":
            self.step_panel.mark_cancelled()
        else:
            self.step_panel.update_stage(stage)

    def _on_pipeline_ready(self, pipeline) -> None:
        self.pipeline = pipeline
        self.pipeline_fingerprint = config_fingerprint(self.config)
        self._append_log("AI 模型初始化完成。")

    def _on_image_done(self, input_path: str, output_path: str) -> None:
        self.step_panel.mark_done()
        key = str(Path(input_path).resolve())
        self.results[key] = output_path
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.UserRole) == key:
                item.setText(f"✓  {item.data(Qt.UserRole + 1) or Path(key).name}")
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
                item.setText(f"×  {original_name}")
                break
        self._append_log(f"[失败] {name}: {message}")

    def _on_finished(self, success: int, failed: int) -> None:
        self._set_running(False)
        total_done = success + failed
        if total_done < self.file_list.count():
            summary = f"已停止，完成 {success} 个文件，失败 {failed} 个文件。"
            self.step_panel.mark_cancelled()
            state = "warning"
            status = "任务已停止"
        elif failed:
            summary = f"处理结束：成功 {success} 个文件，失败 {failed} 个文件。"
            self.step_panel.mark_failed()
            state = "error"
            status = "部分文件失败"
        else:
            summary = f"全部完成，共 {success} 个文件。"
            self.step_panel.mark_done()
            state = "success"
            status = "全部完成"
        self.diagnostics.add_error(summary) if failed else self.diagnostics.append(summary)
        self._set_status(status, state)
        self.stage_label.setText(summary)
        self._append_log(summary)
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
        if page is not None:
            if self._tab_fade_animation is not None:
                self._tab_fade_animation.stop()
            self._tab_fade_effect = QGraphicsOpacityEffect(page)
            self._tab_fade_effect.setOpacity(0.45)
            page.setGraphicsEffect(self._tab_fade_effect)
            self._tab_fade_animation = QPropertyAnimation(
                self._tab_fade_effect, b"opacity", self
            )
            self._tab_fade_animation.setDuration(160)
            self._tab_fade_animation.setStartValue(0.45)
            self._tab_fade_animation.setEndValue(1.0)
            self._tab_fade_animation.setEasingCurve(QEasingCurve.OutCubic)
            self._tab_fade_animation.start()
        if self.tabs.widget(index) is self.editor_page:
            selected = self.file_list.selectedItems()
            if selected:
                key = selected[-1].data(Qt.UserRole)
                output = self.results.get(key)
                if output and Path(output).suffix.lower() != ".pdf":
                    self.editor_page.load_page(output)

    def _show_error_log(self) -> None:
        self.error_log_page.refresh()
        self.tabs.setCurrentWidget(self.error_log_page)

    def _refresh_error_page(self) -> None:
        self.error_log_page.refresh()

    def _toggle_preferences(self, checked: bool) -> None:
        self._pref_animation.stop()
        self._pref_expanding = checked
        self._pref_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        if checked:
            self._pref_container.setVisible(True)
        target_height = max(96, self._pref_container.layout().sizeHint().height())
        self._pref_height_animation.setStartValue(self._pref_container.maximumHeight())
        self._pref_height_animation.setEndValue(target_height if checked else 0)
        self._pref_opacity_animation.setStartValue(self._pref_opacity.opacity())
        self._pref_opacity_animation.setEndValue(1.0 if checked else 0.0)
        self._pref_animation.start()

    def _finish_preference_animation(self) -> None:
        if not self._pref_expanding:
            self._pref_container.setVisible(False)

    def _toggle_log_panel(self, visible: bool) -> None:
        self._log_panel.setVisible(visible)
        self._log_toggle.setText("收起运行日志" if visible else "展开运行日志")
        self._log_toggle.setArrowType(Qt.DownArrow if visible else Qt.RightArrow)
        if visible:
            available = max(400, self.work_splitter.height())
            self.work_splitter.setSizes([max(250, available - 140), 140])

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
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        self.log_view.appendPlainText(f"[{timestamp}] {message}")
        if message.startswith(("[失败]", "[严重错误]", "[失败堆栈]")):
            self.diagnostics.add_error(message)
        else:
            self.diagnostics.append(message)
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
        event.accept()
