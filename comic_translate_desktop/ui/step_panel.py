from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


STAGE_ORDER = ["start", "detect", "ocr", "translate", "inpaint", "typeset", "save"]
STAGE_LABELS = {
    "start": "读取图片",
    "detect": "气泡检测",
    "ocr": "OCR 识别",
    "translate": "AI 翻译",
    "inpaint": "背景修复",
    "typeset": "中文排版",
    "save": "保存输出",
}

PENDING = 0
RUNNING = 1
DONE = 2
FAILED = 3
CANCELLED = 4

STATUS_TEXT = {
    PENDING: "等待",
    RUNNING: "进行中",
    DONE: "完成",
    FAILED: "失败",
    CANCELLED: "已取消",
}
STATUS_COLOR = {
    PENDING: QColor("#999999"),
    RUNNING: QColor("#2f6fed"),
    DONE: QColor("#2e7d32"),
    FAILED: QColor("#c62828"),
    CANCELLED: QColor("#ef6c00"),
}


class StepPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._states = {stage: PENDING for stage in STAGE_ORDER}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._file_label = QLabel("等待任务")
        self._file_label.setStyleSheet("font-weight: 600; color: #333;")
        layout.addWidget(self._file_label)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.NoSelection)
        self._list.setFocusPolicy(Qt.NoFocus)
        self._list.setMinimumHeight(170)
        self._list.setMaximumHeight(420)
        self._list.setStyleSheet(
            "QListWidget { border: 1px solid #d9d9d9; border-radius: 4px; padding: 4px; }"
        )
        for stage in STAGE_ORDER:
            QListWidgetItem(STAGE_LABELS[stage], self._list)
        layout.addWidget(self._list)
        self._refresh()

    def reset(self) -> None:
        self._file_label.setText("等待任务")
        self._states = {stage: PENDING for stage in STAGE_ORDER}
        self._refresh()

    def start_file(self, name: str) -> None:
        self._file_label.setText(f"正在处理: {name}")
        self._states = {stage: PENDING for stage in STAGE_ORDER}
        self._states[STAGE_ORDER[0]] = RUNNING
        self._refresh()

    def update_stage(self, stage: str) -> None:
        if stage not in self._states:
            return
        reached = False
        for key in STAGE_ORDER:
            if key == stage:
                self._states[key] = RUNNING
                reached = True
            elif not reached:
                self._states[key] = DONE
            else:
                self._states[key] = PENDING
        self._refresh()

    def mark_done(self) -> None:
        self._states = {stage: DONE for stage in STAGE_ORDER}
        self._refresh()

    def mark_failed(self) -> None:
        for stage in STAGE_ORDER:
            if self._states[stage] == RUNNING:
                self._states[stage] = FAILED
                break
        self._refresh()

    def mark_cancelled(self) -> None:
        for stage in STAGE_ORDER:
            if self._states[stage] in (PENDING, RUNNING):
                self._states[stage] = CANCELLED
        self._refresh()

    def _refresh(self) -> None:
        bold = QFont()
        bold.setBold(True)
        for index, stage in enumerate(STAGE_ORDER):
            item = self._list.item(index)
            state = self._states[stage]
            item.setText(f"{index + 1:02d}  {STAGE_LABELS[stage]}  {STATUS_TEXT[state]}")
            item.setForeground(STATUS_COLOR[state])
            item.setFont(bold if state == RUNNING else QFont())
