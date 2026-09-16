from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from .theme import ui_font


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
SKIPPED = 5

STATUS_TEXT = {
    PENDING: "○ 等待",
    RUNNING: "◉ 运行中",
    DONE: "✓ 完成",
    FAILED: "⊠ 失败",
    CANCELLED: "— 已取消",
    SKIPPED: "— 已跳过",
}
class StepPanel(QWidget):
    """One straight track; each seventh advances only on a confirmed outcome."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._states = {stage: PENDING for stage in STAGE_ORDER}
        self._pages = {}
        self._labels = {}
        self._compact = False
        self.setFixedHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._file_label = QLabel("等待任务", self)
        self._file_label.hide()
        for index, stage in enumerate(STAGE_ORDER, start=1):
            name = QLabel(f'{index:02d} {STAGE_LABELS[stage]}', self)
            status = QLabel(self)
            for label in (name, status):
                label.setAlignment(Qt.AlignCenter)
                label.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._labels[stage] = (name, status)
        self._refresh()

    @property
    def completed_nodes(self):
        """Out-of-order events cannot fill across a waiting or failed node."""
        completed = 0
        for stage in STAGE_ORDER:
            if self._states[stage] not in (DONE, SKIPPED):
                break
            completed += 1
        return completed

    @property
    def progress_fraction(self):
        return self.completed_nodes / len(STAGE_ORDER)

    def set_compact(self, compact):
        if compact != self._compact:
            self._compact = compact
            self.setFixedHeight(36 if compact else 54)
            self._refresh()

    def reset(self) -> None:
        self._pages.clear()
        self._file_label.setText("等待任务")
        self._states = {stage: PENDING for stage in STAGE_ORDER}
        self._refresh()

    def start_file(self, name: str) -> None:
        self._file_label.setText(f"正在处理 · {name}")
        self._file_label.setToolTip(name)
        self._states = {stage: PENDING for stage in STAGE_ORDER}
        self._states[STAGE_ORDER[0]] = RUNNING
        self._refresh()

    def consume_event(self, event):
        page_id, stage = event['page_id'], event['stage']
        self._states = self._pages.setdefault(page_id, {key: PENDING for key in STAGE_ORDER})
        self._file_label.setText(event['page_label'])
        self._file_label.setToolTip(event['page_label'])
        state = event['state']
        if stage == 'failure':
            self.mark_failed()
        elif stage == 'cancelled':
            self.mark_cancelled()
        elif stage in self._states:
            new_state = {'running': RUNNING, 'done': DONE, 'failed': FAILED, 'skipped': SKIPPED, 'cancelled': CANCELLED}[state]
            old_state = self._states[stage]
            # Duplicate callbacks cannot reopen a completed or skipped node.
            if not (old_state in (DONE, SKIPPED) and new_state == RUNNING):
                if old_state != SKIPPED or new_state != DONE:
                    self._states[stage] = new_state
            if state == 'done':
                self.complete_stage(stage)
        self._refresh()

    def update_stage(self, stage: str) -> None:
        if stage not in self._states:
            return
        if self._states[stage] == PENDING:
            self._states[stage] = RUNNING
        self._refresh()

    def complete_stage(self, stage: str) -> None:
        # Legacy pipeline callbacks detect/ocr/translate/inpaint/typeset/save are
        # completion events. Unknown events (e.g. initialization) stay separate.
        if stage not in self._states:
            return
        if self._states[stage] != SKIPPED:
            self._states[stage] = DONE
        following = {"detect": "ocr", "inpaint": "typeset", "typeset": "save"}.get(stage)
        if stage == "detect":
            self._states["start"] = DONE
        if following and self._states[following] == PENDING:
            self._states[following] = RUNNING
        self._refresh()

    def mark_done(self) -> None:
        for stage in STAGE_ORDER:
            if self._states[stage] != SKIPPED:
                self._states[stage] = DONE
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
        summary = []
        for stage in STAGE_ORDER:
            state = self._states[stage]
            name, status = self._labels[stage]
            name.setFont(ui_font(12 if self._compact or self.width() < 850 else 13,
                                 QFont.Bold if state in (RUNNING, DONE) else QFont.Medium))
            status.setFont(ui_font(11))
            name.setStyleSheet('color: #111111; background: transparent;')
            status.setStyleSheet('color: %s; background: transparent;' %
                                ('#111111' if state in (RUNNING, FAILED) else '#595959'))
            status.setText(STATUS_TEXT[state])
            status.setVisible(not self._compact)
            name.setAccessibleName(f'{STAGE_LABELS[stage]}，{STATUS_TEXT[state]}')
            summary.append(f'{STAGE_LABELS[stage]} {STATUS_TEXT[state]}')
        self.setAccessibleName(f'{self._file_label.text()}，已通过 {self.completed_nodes}/7 个节点；' + '；'.join(summary))
        self._place_labels()
        self.update()

    def _place_labels(self):
        cell = self.width() / len(STAGE_ORDER)
        for index, (name, status) in enumerate(self._labels.values()):
            left, right = round(index * cell), round((index + 1) * cell)
            name.setGeometry(left, 18 if self._compact else 24, right - left, 18)
            status.setGeometry(left, 40, right - left, 14)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        y = 8.0 if self._compact else 12.0
        radius = 5.5 if self._compact else 7.0
        cell = self.width() / len(STAGE_ORDER)
        left, right = 4.0, self.width() - 4.0
        painter.setPen(QPen(QColor('#D0D0D0'), 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        if self.completed_nodes:
            endpoint = right if self.completed_nodes == 7 else self.completed_nodes * cell
            painter.setPen(QPen(QColor('#111111'), 4, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(left, y), QPointF(endpoint, y))
        for index, stage in enumerate(STAGE_ORDER):
            state = self._states[stage]
            x = (index + .5) * cell
            ink = QColor('#777777' if state in (PENDING, CANCELLED) else '#111111')
            painter.setPen(QPen(ink, 2.5 if state in (RUNNING, FAILED) else 1.5))
            painter.setBrush(QColor('#111111' if state == DONE else '#FFFFFF'))
            painter.drawEllipse(QPointF(x, y), radius, radius)
            painter.setPen(QPen(QColor('#FFFFFF') if state == DONE else ink, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if state == DONE:
                tick = QPainterPath(QPointF(x - radius * .45, y))
                tick.lineTo(x - radius * .1, y + radius * .35)
                tick.lineTo(x + radius * .5, y - radius * .4)
                painter.drawPath(tick)
            elif state == RUNNING:
                painter.setBrush(ink)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(x, y), radius * .4, radius * .4)
            elif state == FAILED:
                delta = radius * .4
                painter.drawLine(QPointF(x - delta, y - delta), QPointF(x + delta, y + delta))
                painter.drawLine(QPointF(x - delta, y + delta), QPointF(x + delta, y - delta))
            elif state in (SKIPPED, CANCELLED):
                painter.drawLine(QPointF(x - radius * .45, y), QPointF(x + radius * .45, y))
