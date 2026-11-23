"""Edit OCR, request a candidate, and compare both readings before applying."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from ..editor_jobs import LatestJobQueue
from ..i18n import tr
from .window_chrome import apply_window_chrome


class RetranslateDialog(QDialog):
    def __init__(self, source, current, translate, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('重译当前气泡'))
        self.resize(720, 500)
        self._translate = translate
        self._preview = preview
        self._jobs = LatestJobQueue(self)
        self.result_text = None
        self._busy = False

        root = QVBoxLayout(self)
        inputs = QGridLayout()
        inputs.addWidget(QLabel(tr('校正 OCR 原文')), 0, 0, 1, 2)
        self.source = QPlainTextEdit(source)
        self.source.setAccessibleName(tr('校正 OCR 原文'))
        self.source.setMaximumHeight(70)
        inputs.addWidget(self.source, 1, 0, 1, 2)
        self.instruction = QLineEdit()
        self.instruction.setPlaceholderText(tr('重译要求，如缩短对白或保留反讽'))
        self.instruction.setAccessibleName(tr('重译要求，如缩短对白或保留反讽'))
        inputs.addWidget(self.instruction, 2, 0)
        self.request_button = QPushButton(tr('请求重译'))
        self.request_button.clicked.connect(self._request)
        inputs.addWidget(self.request_button, 2, 1)
        root.addLayout(inputs)

        comparison = QGridLayout()
        comparison.setColumnStretch(0, 1)
        comparison.setColumnStretch(1, 1)
        comparison.addWidget(QLabel(tr('当前译文')), 0, 0)
        comparison.addWidget(QLabel(tr('候选译文')), 0, 1)
        self.current_image = QLabel()
        self.candidate_image = QLabel()
        for column, label in enumerate((self.current_image, self.candidate_image)):
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(105)
            comparison.addWidget(label, 1, column)
        current_text = QPlainTextEdit(current)
        current_text.setReadOnly(True)
        current_text.setAccessibleName(tr('当前译文'))
        self.candidate = QPlainTextEdit()
        self.candidate.setReadOnly(True)
        self.candidate.setAccessibleName(tr('候选译文'))
        comparison.addWidget(current_text, 2, 0)
        comparison.addWidget(self.candidate, 2, 1)
        root.addLayout(comparison, 1)

        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.apply_button = QPushButton(tr('应用候选译文'))
        self.apply_button.setProperty('role', 'primary')
        self.apply_button.clicked.connect(self.accept)
        close = QPushButton(tr('关闭'))
        close.clicked.connect(self.reject)
        for button in (self.apply_button, close):
            button.setAutoDefault(False)
            footer.addWidget(button)
        root.addLayout(footer)
        self.source.textChanged.connect(self._reset_candidate)
        self.instruction.textChanged.connect(self._reset_candidate)
        self._reset_candidate()
        current_preview, _ = self._preview(None)
        self._show_image(self.current_image, current_preview)

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self)

    def done(self, result):
        self._jobs.close()
        super().done(result)

    @staticmethod
    def _show_image(label, image):
        label.setPixmap(QPixmap.fromImage(image).scaled(300, 140, Qt.KeepAspectRatio,
                                                         Qt.SmoothTransformation))

    def _reset_candidate(self):
        self.result_text = None
        self.candidate.clear()
        self.candidate_image.clear()
        self.status.clear()
        self.request_button.setEnabled(not self._busy and bool(self.source.toPlainText().strip()))
        self.apply_button.setEnabled(False)

    def _request(self):
        source, instruction = self.source.toPlainText().strip(), self.instruction.text()
        if not source or self._busy:
            return
        self._reset_candidate()
        self._set_busy(True)
        self.status.setText(tr('正在请求单气泡重译…'))
        self._jobs.submit(lambda cancelled: self._translate(source, instruction, cancelled),
                          self._ready, self._error, cancellable=True)

    def _set_busy(self, busy):
        self._busy = busy
        self.request_button.setEnabled(not busy and bool(self.source.toPlainText().strip()))
        self.source.setReadOnly(busy)
        self.instruction.setReadOnly(busy)

    def _ready(self, candidate):
        try:
            current, revised = self._preview(candidate)
            self._show_image(self.current_image, current)
            self._show_image(self.candidate_image, revised)
        except Exception as exc:
            self._error(str(exc))
            return
        self._set_busy(False)
        self.status.clear()
        self.candidate.setPlainText(candidate)
        self.result_text = candidate
        self.apply_button.setEnabled(True)

    def _error(self, message):
        self._set_busy(False)
        self.status.setText(tr('重译失败：{_0}', _0=message))
