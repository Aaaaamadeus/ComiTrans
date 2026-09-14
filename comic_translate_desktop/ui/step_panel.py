from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import refresh_style


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
STATUS_NAMES = {
    PENDING: "pending",
    RUNNING: "running",
    DONE: "done",
    FAILED: "failed",
    CANCELLED: "cancelled",
}


class StepPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._states = {stage: PENDING for stage in STAGE_ORDER}
        self._cards: dict[str, tuple[QFrame, QLabel]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        self._file_label = QLabel("等待任务")
        self._file_label.setObjectName("sectionTitle")
        layout.addWidget(self._file_label)

        stage_row = QHBoxLayout()
        stage_row.setSpacing(7)
        for index, stage in enumerate(STAGE_ORDER, start=1):
            card = QFrame()
            card.setObjectName("stageCard")
            card.setProperty("stageState", "pending")

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(9, 7, 9, 7)
            card_layout.setSpacing(1)

            number_label = QLabel(f"{index:02d}")
            number_label.setObjectName("stageNumber")
            name_label = QLabel(STAGE_LABELS[stage])
            name_label.setObjectName("stageName")
            status_label = QLabel(STATUS_TEXT[PENDING])
            status_label.setObjectName("stageStatus")

            card_layout.addWidget(number_label)
            card_layout.addWidget(name_label)
            card_layout.addWidget(status_label)
            stage_row.addWidget(card, 1)
            self._cards[stage] = (card, status_label)

        layout.addLayout(stage_row)
        self._refresh()

    def reset(self) -> None:
        self._file_label.setText("等待任务")
        self._states = {stage: PENDING for stage in STAGE_ORDER}
        self._refresh()

    def start_file(self, name: str) -> None:
        self._file_label.setText(f"正在处理 · {name}")
        self._file_label.setToolTip(name)
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
        for stage in STAGE_ORDER:
            state = self._states[stage]
            card, status_label = self._cards[stage]
            status_label.setText(STATUS_TEXT[state])
            card.setProperty("stageState", STATUS_NAMES[state])
            refresh_style(card)
