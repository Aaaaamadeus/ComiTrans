from __future__ import annotations

from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..ai_diagnosis import AiDiagnosis


class DiagnosisWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, ai, user_text, parent=None):
        super().__init__(parent)
        self._ai = ai
        self._user_text = user_text

    def run(self) -> None:
        try:
            answer = self._ai.diagnose(self._user_text)
            self.finished.emit(answer)
        except Exception as exc:
            self.failed.emit(str(exc))


class ErrorLogPage(QWidget):
    def __init__(self, diagnostics, parent=None):
        super().__init__(parent)
        self._diagnostics = diagnostics
        self._ai = AiDiagnosis(diagnostics)
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(10)

        header = QLabel("报错日志与 AI 诊断")
        header.setObjectName("brandTitle")
        root.addWidget(header)

        self._file_label = QLabel(f"日志文件: {self._diagnostics.log_path}")
        self._file_label.setProperty("muted", True)
        root.addWidget(self._file_label)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._build_prompt_panel())
        splitter.addWidget(self._build_ai_panel())
        splitter.setSizes([360, 320])
        root.addWidget(splitter, 1)

        self.refresh()

    def _build_prompt_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setPlaceholderText("暂无报错日志")
        self.prompt_view.setProperty("code", True)
        layout.addWidget(self.prompt_view, 1)

        buttons = QHBoxLayout()
        self._copy_prompt_btn = QPushButton("复制诊断提示词")
        self._copy_raw_btn = QPushButton("复制原始日志")
        self._open_log_btn = QPushButton("打开日志文件")
        self._clear_btn = QPushButton("清空日志")
        self._clear_btn.setProperty("role", "danger")
        self._status_label = QLabel("")
        self._status_label.setProperty("muted", True)

        buttons.addWidget(self._copy_prompt_btn)
        buttons.addWidget(self._copy_raw_btn)
        buttons.addWidget(self._open_log_btn)
        buttons.addWidget(self._clear_btn)
        buttons.addWidget(self._status_label)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._copy_prompt_btn.clicked.connect(self.copy_prompt)
        self._copy_raw_btn.clicked.connect(self.copy_raw_logs)
        self._open_log_btn.clicked.connect(self.open_log_file)
        self._clear_btn.clicked.connect(self.clear_logs)
        return panel

    def _build_ai_panel(self) -> QWidget:
        group = QGroupBox("AI 诊断（支持上下文，不会自动重置）")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self.history_view = QPlainTextEdit()
        self.history_view.setReadOnly(True)
        self.history_view.setPlaceholderText("在这里发起 AI 诊断，后续问题会保留上下文。")
        layout.addWidget(self.history_view, 1)

        self._input_view = QPlainTextEdit()
        self._input_view.setPlaceholderText("描述报错现象，或直接问：帮我分析当前日志")
        self._input_view.setMaximumHeight(80)
        layout.addWidget(self._input_view)

        buttons = QHBoxLayout()
        self._send_btn = QPushButton("发送诊断")
        self._send_btn.setProperty("role", "primary")
        self._copy_result_btn = QPushButton("复制诊断结果")
        self._clear_context_btn = QPushButton("清空上下文")
        self._ai_status = QLabel("")
        self._ai_status.setProperty("muted", True)

        buttons.addWidget(self._send_btn)
        buttons.addWidget(self._copy_result_btn)
        buttons.addWidget(self._clear_context_btn)
        buttons.addWidget(self._ai_status)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._send_btn.clicked.connect(self._send_diagnosis)
        self._copy_result_btn.clicked.connect(self.copy_diagnosis_result)
        self._clear_context_btn.clicked.connect(self.clear_context)
        return group

    def refresh(self) -> None:
        self._file_label.setText(f"日志文件: {self._diagnostics.log_path}")
        self.prompt_view.setPlainText(self._diagnostics.build_prompt())

    def copy_prompt(self) -> None:
        QApplication.clipboard().setText(self.prompt_view.toPlainText())
        self._status_label.setText("诊断提示词已复制")

    def copy_raw_logs(self) -> None:
        QApplication.clipboard().setText(self._diagnostics.raw_text())
        self._status_label.setText("原始日志已复制")

    def copy_diagnosis_result(self) -> None:
        QApplication.clipboard().setText(self.history_view.toPlainText())
        self._ai_status.setText("诊断结果已复制")

    def open_log_file(self) -> None:
        path = self._diagnostics.log_path
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def clear_logs(self) -> None:
        self._diagnostics.clear()
        self.refresh()
        self._status_label.setText("日志已清空")

    def clear_context(self) -> None:
        self._ai.clear_context()
        self.history_view.clear()
        self._ai_status.setText("上下文已清空")

    def _send_diagnosis(self) -> None:
        text = self._input_view.toPlainText().strip()
        if not text:
            return
        if self._worker is not None and self._worker.isRunning():
            return

        self._append_history("你", text)
        self._input_view.clear()
        self._send_btn.setEnabled(False)
        self._ai_status.setText("AI 诊断中...")

        self._worker = DiagnosisWorker(self._ai, text, parent=self)
        self._worker.finished.connect(self._on_diagnosis_finished)
        self._worker.failed.connect(self._on_diagnosis_failed)
        self._worker.start()

    def _on_diagnosis_finished(self, answer: str) -> None:
        self._append_history("AI", answer)
        self._send_btn.setEnabled(True)
        self._ai_status.setText("诊断完成，上下文已保留")

    def _on_diagnosis_failed(self, message: str) -> None:
        self._append_history("系统", f"诊断失败: {message}")
        self._send_btn.setEnabled(True)
        self._ai_status.setText("诊断失败")

    def _append_history(self, role: str, content: str) -> None:
        self.history_view.appendPlainText(f"【{role}】\n{content}\n")

    def shutdown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5000)
