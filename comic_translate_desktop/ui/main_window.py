from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTime, QTimer, QUrl
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
    QGroupBox,
    QHBoxLayout,
    QLabel,
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
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import config as app_config
from ..config import config_fingerprint, missing_models, save_ai_config
from ..diagnostics import Diagnostics
from ..worker import BatchWorker
from .api_config_page import ApiConfigPage
from .editor_page import EditorPage
from .error_log_page import ErrorLogPage
from .step_panel import StepPanel


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class ImagePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._original = QPixmap()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("无预览")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("color: #888;")
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._label)
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.setStyleSheet("background: #1f1f24;")
        layout.addWidget(self._scroll)

    def set_image(self, path: str) -> None:
        self._original = QPixmap(path)
        if self._original.isNull():
            self._label.setPixmap(QPixmap())
            self._label.setText("无法读取图片")
            return
        self._update_scaled()

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
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("ComiTrans 本地漫画翻译")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #666;")
        self._add_btn = QPushButton("添加图片")
        self._folder_btn = QPushButton("添加文件夹")
        self._settings_btn = QPushButton("API 配置")
        self._logs_btn = QPushButton("报错日志")
        self._output_btn = QPushButton("打开输出目录")
        self._issue_btn = QPushButton("Issue")
        self._start_btn = QPushButton("开始翻译")
        self._start_btn.setStyleSheet(
            "background: #2f6fed; color: white; padding: 6px 18px; border-radius: 4px;"
        )
        self._stop_btn = QPushButton("停止")

        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_label)
        header.addWidget(self._add_btn)
        header.addWidget(self._folder_btn)
        header.addWidget(self._settings_btn)
        header.addWidget(self._logs_btn)
        header.addWidget(self._output_btn)
        header.addWidget(self._issue_btn)
        header.addWidget(self._start_btn)
        header.addWidget(self._stop_btn)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.translate_tab = QSplitter(Qt.Horizontal)
        self.translate_tab.addWidget(self._build_file_panel())
        self.translate_tab.addWidget(self._build_work_panel())
        self.translate_tab.setStretchFactor(0, 0)
        self.translate_tab.setStretchFactor(1, 1)
        self.translate_tab.setSizes([280, 900])
        self.tabs.addTab(self.translate_tab, "翻译工作台")

        self.api_config_page = ApiConfigPage(self.config)
        self.api_config_page.save_requested.connect(self._save_api_config)
        self.tabs.addTab(self.api_config_page, "API 配置")
        self.error_log_page = ErrorLogPage(self.diagnostics)
        self.tabs.addTab(self.error_log_page, "报错日志")
        self.editor_page = EditorPage()
        self.tabs.addTab(self.editor_page, "嵌字编辑")
        root.addWidget(self.tabs, 1)

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
        group = QGroupBox("待处理图片")
        group.setMinimumWidth(260)
        layout = QVBoxLayout(group)

        self.file_list = QListWidget()
        self.file_list.setViewMode(QListView.IconMode)
        self.file_list.setIconSize(QSize(96, 96))
        self.file_list.setResizeMode(QListView.Adjust)
        self.file_list.setSpacing(6)
        self.file_list.setMovement(QListView.Static)
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.itemSelectionChanged.connect(self._on_file_selection)
        layout.addWidget(self.file_list, 1)

        buttons = QHBoxLayout()
        self._remove_btn = QPushButton("移除选中")
        self._clear_btn = QPushButton("清空")
        buttons.addWidget(self._remove_btn)
        buttons.addWidget(self._clear_btn)
        layout.addLayout(buttons)

        self._remove_btn.clicked.connect(self._remove_selected)
        self._clear_btn.clicked.connect(self._clear_files)
        return group

    def _build_work_panel(self) -> QWidget:
        group = QGroupBox("翻译工作区")
        layout = QVBoxLayout(group)

        self._pref_toggle = QToolButton()
        self._pref_toggle.setText("偏好设置")
        self._pref_toggle.setCheckable(True)
        self._pref_toggle.setArrowType(Qt.RightArrow)
        self._pref_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._pref_container = QWidget()
        self._pref_container.setVisible(False)
        pref_layout = QVBoxLayout(self._pref_container)
        pref_layout.setContentsMargins(0, 0, 0, 0)

        prompt_label = QLabel("背景提示词")
        self._prompt_input = QPlainTextEdit()
        self._prompt_input.setPlaceholderText(
            "可填写故事背景、世界观、人物关系、语气风格等，翻译时会自动附加到提示词中"
        )
        self._prompt_input.setMaximumHeight(90)

        names_label = QLabel("中文人名（每行一个，AI 会自动对照）")
        self._names_input = QPlainTextEdit()
        self._names_input.setPlaceholderText("例如：\n路飞\n娜美\n索隆")
        self._names_input.setMaximumHeight(80)

        pref_layout.addWidget(prompt_label)
        pref_layout.addWidget(self._prompt_input)
        pref_layout.addWidget(names_label)
        pref_layout.addWidget(self._names_input)

        self._prompt_input.setPlainText(self.config.get("translation_prompt", ""))
        self._names_input.setPlainText(self.config.get("chinese_names", ""))
        self._pref_toggle.toggled.connect(self._toggle_preferences)
        self._pref_save_timer = QTimer(self)
        self._pref_save_timer.setSingleShot(True)
        self._pref_save_timer.setInterval(400)
        self._pref_save_timer.timeout.connect(self._save_translation_preferences)
        self._prompt_input.textChanged.connect(self._schedule_save_preferences)
        self._names_input.textChanged.connect(self._schedule_save_preferences)

        layout.addWidget(self._pref_toggle)
        layout.addWidget(self._pref_container)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.stage_label = QLabel("尚未开始")
        self.stage_label.setStyleSheet("color: #555;")

        self.step_panel = StepPanel()
        self.preview_tabs = QTabWidget()
        self.original_view = ImagePreview()
        self.result_view = ImagePreview()
        self.preview_tabs.addTab(self.original_view, "原图预览")
        self.preview_tabs.addTab(self.result_view, "译文预览")

        log_label = QLabel("运行日志")
        log_label.setStyleSheet("font-weight: 600;")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setStyleSheet("font-family: Consolas, monospace;")
        self.log_view.setMinimumHeight(150)

        self.work_splitter = QSplitter(Qt.Vertical)
        self.work_splitter.addWidget(self.preview_tabs)
        self.work_splitter.addWidget(self.log_view)
        self.work_splitter.setStretchFactor(0, 2)
        self.work_splitter.setStretchFactor(1, 1)
        self.work_splitter.setSizes([420, 180])

        layout.addWidget(self.progress_bar)
        layout.addWidget(self.stage_label)
        layout.addWidget(self.step_panel)
        layout.addWidget(log_label)
        layout.addWidget(self.work_splitter, 1)
        return group

    def _add_paths(self, paths) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        existing = {
            self.file_list.item(i).data(Qt.UserRole)
            for i in range(self.file_list.count())
        }
        added = 0
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                continue
            key = str(path.resolve())
            if key in existing:
                continue
            icon = self._thumbnail_icon(path)
            item = QListWidgetItem(icon, path.name)
            item.setData(Qt.UserRole, key)
            item.setToolTip(str(path))
            self.file_list.addItem(item)
            existing.add(key)
            added += 1
        if added:
            self._append_log(f"已添加 {added} 张图片。")
        self._update_actions()

    def _thumbnail_icon(self, path: Path) -> QIcon:
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
            "选择漫画图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        self._add_paths(paths)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择漫画文件夹", "")
        if not folder:
            return
        root = Path(folder)
        paths = [
            str(path)
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTS
        ]
        paths.sort()
        self._add_paths(paths)

    def _all_files(self) -> list[Path]:
        return [
            Path(self.file_list.item(i).data(Qt.UserRole))
            for i in range(self.file_list.count())
        ]

    def _on_file_selection(self) -> None:
        items = self.file_list.selectedItems()
        if not items:
            return
        key = items[-1].data(Qt.UserRole)
        self.original_view.set_image(key)
        output = self.results.get(key)
        if output:
            self.result_view.set_image(output)
        else:
            self.result_view.clear("处理完成后显示译文")

    def _remove_selected(self) -> None:
        items = list(self.file_list.selectedItems())
        for item in items:
            key = item.data(Qt.UserRole)
            self.results.pop(key, None)
            self.file_list.takeItem(self.file_list.row(item))
        self._update_actions()

    def _clear_files(self) -> None:
        self.file_list.clear()
        self.results.clear()
        self.original_view.clear()
        self.result_view.clear()
        self.progress_bar.setValue(0)
        self.stage_label.setText("尚未开始")
        self.step_panel.reset()
        self._update_actions()

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
        self.warmup_worker.pipeline_ready.connect(self._on_pipeline_ready)
        self.warmup_worker.finished.connect(self._on_warmup_finished)
        self.warmup_worker.start()
        self._append_log("正在预热 AI 管线...")

    def _on_warmup_finished(self, success: int, failed: int) -> None:
        self.warmup_worker = None

    def _start_translation(self) -> None:
        files = self._all_files()
        if not files:
            return
        if self.warmup_worker is not None and self.warmup_worker.isRunning():
            self._append_log("AI 管线正在预热，请稍候再开始翻译。")
            return

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

        if not self.config["api_key"] or not self.config["api_base_url"]:
            self._append_log("警告：未配置翻译 API，结果将保留 OCR 原文。")

        output_dir = Path(self.config["page_output_dir"])
        fingerprint = config_fingerprint(self.config)
        if self.pipeline is None or self.pipeline_fingerprint != fingerprint:
            self.pipeline = None

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
        self._set_running(True)

    def _stop_translation(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self._stop_btn.setEnabled(False)
            self.step_panel.mark_cancelled()
            self.status_label.setText("正在取消任务...")

    def _set_running(self, running: bool) -> None:
        self._start_btn.setEnabled(not running and self.file_list.count() > 0)
        self._stop_btn.setEnabled(running)
        self._add_btn.setEnabled(not running)
        self._folder_btn.setEnabled(not running)
        self._settings_btn.setEnabled(not running)
        self._remove_btn.setEnabled(not running)
        self._clear_btn.setEnabled(not running)
        self._output_btn.setEnabled(not running)
        self.api_config_page.setEnabled(not running)
        if running:
            self.status_label.setText("翻译中...")

    def _update_actions(self) -> None:
        running = self.worker is not None and self.worker.isRunning()
        self._start_btn.setEnabled(not running and self.file_list.count() > 0)
        self._stop_btn.setEnabled(running)
        self._add_btn.setEnabled(not running)
        self._folder_btn.setEnabled(not running)
        self._remove_btn.setEnabled(not running and self.file_list.count() > 0)
        self._clear_btn.setEnabled(not running and self.file_list.count() > 0)

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
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
                if "[完成]" not in item.text():
                    item.setText(f"{item.text()}  [完成]")
                break

        selected = self.file_list.selectedItems()
        if selected and selected[-1].data(Qt.UserRole) == key:
            self.result_view.set_image(output_path)

    def _on_image_failed(self, name: str, message: str) -> None:
        self.step_panel.mark_failed()
        self._append_log(f"[失败] {name}: {message}")

    def _on_finished(self, success: int, failed: int) -> None:
        self._set_running(False)
        total_done = success + failed
        if total_done < self.file_list.count():
            summary = f"已停止，完成 {success} 张，失败 {failed} 张。"
            self.step_panel.mark_cancelled()
        elif failed:
            summary = f"处理结束：成功 {success} 张，失败 {failed} 张。"
            self.step_panel.mark_failed()
        else:
            summary = f"全部完成，共 {success} 张。"
            self.step_panel.mark_done()
        self.diagnostics.add_error(summary) if failed else self.diagnostics.append(summary)
        self.status_label.setText(summary)
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
        if self.tabs.widget(index) is self.editor_page:
            selected = self.file_list.selectedItems()
            if selected:
                key = selected[-1].data(Qt.UserRole)
                output = self.results.get(key)
                if output:
                    self.editor_page.load_page(output)

    def _show_error_log(self) -> None:
        self.error_log_page.refresh()
        self.tabs.setCurrentWidget(self.error_log_page)

    def _refresh_error_page(self) -> None:
        self.error_log_page.refresh()

    def _toggle_preferences(self, checked: bool) -> None:
        self._pref_container.setVisible(checked)
        self._pref_toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

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
        self.status_label.setText("API 配置已保存")
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
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
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
