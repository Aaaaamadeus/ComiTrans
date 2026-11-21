"""Fork-join workflow visualizer for the batch translation pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from math import pi, sin

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..i18n import tr, ui_language
from .motion import reduced_motion
from .theme import color, theme_changed, ui_font


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
STAGE_COMPACT_LABELS = dict(zip(STAGE_ORDER, ('读取', '检测', '识别', '翻译', '修复', '排版', '保存')))
STAGE_DESCRIPTIONS = {
    "start": "读取图片，或按页准备 PDF、CBZ 的原分辨率页图",
    "detect": "检测漫画气泡与文字框范围",
    "ocr": "识别框内原文并测量字号与排向",
    "translate": "按阅读顺序调用翻译模型，结合前文上下文并缓存译文",
    "inpaint": "与翻译并行在独立线程生成擦字掩膜并修补背景",
    "typeset": "翻译与修补汇合后，校对空译文并完成横竖排嵌字",
    "save": "写入译图、底图和布局，全部完成后生成译文 PDF 或 CBZ",
}

PENDING = 0
RUNNING = 1
DONE = 2
FAILED = 3
CANCELLED = 4
SKIPPED = 5
READY = 6

STATUS_TEXT = {
    PENDING: "○ 等待",
    RUNNING: "◉ 运行中",
    DONE: "✓ 完成",
    FAILED: "⊠ 失败",
    CANCELLED: "— 已取消",
    SKIPPED: "— 已跳过",
    READY: "✓ 待汇合",
}

_NORMAL_HEIGHT = 112
_COMPACT_HEIGHT = 66
_PULSE_INTERVAL_MS = 16
_PULSE_PERIOD_TICKS = 75


@dataclass(frozen=True)
class _StageView:
    stage: str
    state: int
    badge: str = ""
    sublabel: str = ""
    tooltip: str = ""


def _new_page_states() -> dict[str, int]:
    return {stage: PENDING for stage in STAGE_ORDER}


def _page_completed_nodes(states: dict[str, int]) -> int:
    """Count completed stages along the true fork-join dependency graph."""
    prep = 0
    for stage in ("start", "detect", "ocr"):
        if states[stage] not in (DONE, SKIPPED):
            return prep
        prep += 1
    translate_done = int(states["translate"] in (DONE, SKIPPED))
    inpaint_done = int(states["inpaint"] in (DONE, SKIPPED))
    completed = prep + translate_done + inpaint_done
    if translate_done and inpaint_done:
        for stage in ("typeset", "save"):
            if states[stage] not in (DONE, SKIPPED):
                break
            completed += 1
    return completed


def _is_active_branch(state: int) -> bool:
    return state in (RUNNING, READY, DONE, SKIPPED, FAILED)


class StepPanel(QWidget):
    """Real-time fork-join workflow visualizer for ComiTrans's parallel pipeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._states = _new_page_states()
        self._pages: dict[str, dict[str, int]] = {}
        self._page_order: list[str] = []
        self._page_meta: dict[str, dict] = {}
        self._active_page_id: str | None = None
        self._labels: dict[str, tuple[QLabel, QLabel]] = {}
        self._compact = False
        self._task_phase = "idle"
        self._queued_count = 0
        self._queued_names: list[str] = []
        self._max_workers = 4
        self._retain_context = False
        self._resume_enabled = True
        self._context_entries = 0
        self._publishing_pdf: dict | None = None
        self._node_rects: dict[str, QRectF] = {}
        self._tile_rects: list[tuple[QRectF, str, str]] = []
        self._hover_target: tuple[str, str] | None = None
        self._pulse_tick = 0
        self._pulse_clock = QElapsedTimer()
        self._pulse_clock.start()
        self._prev_stage_states: dict[str, int] = {}
        self._done_flash_until: dict[str, int] = {}

        self.setFixedHeight(_NORMAL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        theme_changed.changed.connect(self._refresh)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(_PULSE_INTERVAL_MS)
        self._pulse_timer.timeout.connect(self._advance_pulse)

        self._file_label = QLabel(tr('等待任务'), self)
        self._file_label.hide()
        for index, stage in enumerate(STAGE_ORDER, start=1):
            name = QLabel(f'{index:02d} {tr(STAGE_LABELS[stage])}', self)
            status = QLabel(self)
            name.hide()
            status.hide()
            self._labels[stage] = (name, status)
        self._refresh()

    @property
    def completed_nodes(self) -> int:
        """Out-of-order events cannot cross a waiting or failed fork/join gate."""
        return _page_completed_nodes(self._states)

    @property
    def progress_fraction(self) -> float:
        return self.completed_nodes / len(STAGE_ORDER)

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact != self._compact:
            self._compact = compact
            self.setFixedHeight(_COMPACT_HEIGHT if compact else _NORMAL_HEIGHT)
            self._refresh()

    def set_queued_files(self, count: int, names: list[str] | None = None) -> None:
        self._queued_count = max(0, int(count))
        self._queued_names = list(names or [])
        if self._task_phase == "idle":
            self._refresh()

    def set_pipeline_config(
        self,
        *,
        max_workers: int | None = None,
        retain_context: bool | None = None,
        resume_enabled: bool | None = None,
        context_entries: int | None = None,
    ) -> None:
        if max_workers is not None:
            self._max_workers = max(1, int(max_workers))
        if retain_context is not None:
            self._retain_context = bool(retain_context)
        if resume_enabled is not None:
            self._resume_enabled = bool(resume_enabled)
        if context_entries is not None:
            self._context_entries = max(0, int(context_entries))
        self._refresh()

    def reset(self) -> None:
        self._pages.clear()
        self._page_order.clear()
        self._page_meta.clear()
        self._active_page_id = None
        self._task_phase = "idle"
        self._publishing_pdf = None
        self._context_entries = 0
        self._hover_target = None
        self._file_label.setText(tr('等待任务'))
        self._states = _new_page_states()
        self._refresh()

    def start_file(self, name: str) -> None:
        self._pages.clear()
        self._page_order.clear()
        self._page_meta.clear()
        self._active_page_id = None
        self._task_phase = "running"
        self._publishing_pdf = None
        self._file_label.setText(tr('正在处理 · {_0}', _0=name))
        self._file_label.setToolTip(tr(name))
        self._states = _new_page_states()
        self._states[STAGE_ORDER[0]] = RUNNING
        self._refresh()

    def _ensure_page(self, page_id: str, page_label: str = "") -> dict[str, int]:
        if page_id not in self._pages:
            self._pages[page_id] = _new_page_states()
            self._page_order.append(page_id)
            self._page_meta[page_id] = {
                "label": page_label or page_id,
                "resumed": False,
                "message": "",
                "last_stage": "",
                "cached_translation": False,
            }
        elif page_label:
            self._page_meta[page_id]["label"] = page_label
        return self._pages[page_id]

    def consume_event(self, event: dict) -> None:
        page_id, stage = event['page_id'], event['stage']
        page_label = event.get('page_label', page_id)
        self._states = self._ensure_page(page_id, page_label)
        self._active_page_id = page_id
        if self._task_phase == "idle":
            self._task_phase = "running"
        self._file_label.setText(tr(page_label))
        self._file_label.setToolTip(tr(page_label))
        meta = self._page_meta[page_id]
        state = event['state']
        message = str(event.get('message') or '')
        if message:
            meta["message"] = message
        meta["last_stage"] = stage
        if stage == 'translate' and '复用已保存译文' in message:
            meta["cached_translation"] = True

        if stage == 'failure':
            self.mark_failed()
        elif stage == 'cancelled':
            self.mark_cancelled()
        elif stage in self._states:
            state_map = {
                'running': RUNNING,
                'done': DONE,
                'failed': FAILED,
                'skipped': SKIPPED,
                'cancelled': CANCELLED,
                'ready': READY,
            }
            new_state = state_map[state]
            old_state = self._states[stage]
            # Sequential lane transitions advance the preceding intra-lane step cleanly.
            if new_state == RUNNING:
                if stage == 'detect' and self._states['start'] == RUNNING:
                    self._states['start'] = DONE
                elif stage == 'ocr' and self._states['detect'] == RUNNING:
                    self._states['start'] = DONE
                    self._states['detect'] = DONE
                elif stage == 'save' and self._states['typeset'] == RUNNING:
                    self._states['typeset'] = DONE
            # Duplicate callbacks cannot reopen a completed or skipped node.
            if not (old_state in (DONE, SKIPPED) and new_state == RUNNING):
                if old_state != SKIPPED or new_state != DONE:
                    self._states[stage] = new_state
            if state == 'done':
                self.complete_stage(stage)
        self._refresh()

    def consume_workflow_event(self, event: dict) -> None:
        kind = event.get('type')
        if kind == 'plan':
            self._pages.clear()
            self._page_order.clear()
            self._page_meta.clear()
            self._active_page_id = None
            self._task_phase = "running"
            self._publishing_pdf = None
            self._max_workers = max(1, int(event.get('max_workers') or self._max_workers))
            self._retain_context = bool(event.get('retain_context', self._retain_context))
            self._context_entries = max(0, int(event.get('context_entries') or 0))
            for item in event.get('pages') or ():
                pid = item['page_id']
                states = self._ensure_page(pid, item.get('page_label', pid))
                resumed = bool(item.get('resumed', False))
                self._page_meta[pid]["resumed"] = resumed
                self._page_meta[pid]["document_name"] = item.get('document_name', '')
                self._page_meta[pid]["is_pdf"] = bool(item.get('is_pdf', False))
                if resumed:
                    for stage in STAGE_ORDER:
                        states[stage] = SKIPPED
            self._refresh()
        elif kind == 'repair_ready':
            pid = event.get('page_id')
            if pid:
                states = self._ensure_page(pid, event.get('page_label', pid))
                if states['inpaint'] in (PENDING, RUNNING):
                    states['inpaint'] = READY
                self._page_meta[pid]["message"] = '并行修补完成，等待汇合'
                self._refresh()
        elif kind == 'join':
            pid = event.get('page_id')
            if pid:
                states = self._ensure_page(pid, event.get('page_label', pid))
                if states['inpaint'] == READY:
                    states['inpaint'] = DONE
                if states['typeset'] == PENDING:
                    states['typeset'] = RUNNING
                self._page_meta[pid]["message"] = '翻译与修补已汇合，正在嵌字'
                self._refresh()
        elif kind == 'context':
            self._context_entries = max(0, int(event.get('context_entries') or 0))
            self._refresh()
        elif kind == 'publish':
            state = event.get('state')
            if state == 'running':
                self._publishing_pdf = {
                    'name': event.get('document_name', ''),
                    'format': event.get('output_format') or 'PDF',
                    'state': 'running',
                }
            elif state == 'failed':
                self._publishing_pdf = {
                    'name': event.get('document_name', ''),
                    'format': event.get('output_format') or 'PDF',
                    'state': 'failed',
                }
                self._task_phase = 'failed'
            else:
                self._publishing_pdf = None
            self._refresh()

    def update_stage(self, stage: str) -> None:
        if stage not in self._states:
            return
        if self._states[stage] == PENDING:
            self._states[stage] = RUNNING
        self._refresh()

    def complete_stage(self, stage: str) -> None:
        if stage not in self._states:
            return
        if self._states[stage] != SKIPPED:
            self._states[stage] = DONE
        if stage == "detect":
            self._states["start"] = DONE
            if self._states["ocr"] == PENDING:
                self._states["ocr"] = RUNNING
        elif stage == "inpaint":
            if (self._states["translate"] in (DONE, SKIPPED)
                    and self._states["typeset"] == PENDING):
                self._states["typeset"] = RUNNING
        elif stage == "typeset":
            if self._states["save"] == PENDING:
                self._states["save"] = RUNNING
        self._refresh()

    def mark_done(self) -> None:
        self._task_phase = "done"
        self._publishing_pdf = None
        for stage in STAGE_ORDER:
            if self._states[stage] != SKIPPED:
                self._states[stage] = DONE
        for pid, states in self._pages.items():
            if self._page_meta.get(pid, {}).get("resumed"):
                continue
            for stage in STAGE_ORDER:
                if states[stage] != SKIPPED:
                    states[stage] = DONE
        self._refresh()

    def mark_failed(self) -> None:
        self._task_phase = "failed"
        if any(v == FAILED for v in self._states.values()):
            self._refresh()
            return
        for target_state in (RUNNING, READY):
            for stage in STAGE_ORDER:
                if self._states[stage] == target_state:
                    self._states[stage] = FAILED
                    self._refresh()
                    return
        for pid, states in self._pages.items():
            if self._page_meta.get(pid, {}).get("resumed") or any(v == FAILED for v in states.values()):
                continue
            for target_state in (RUNNING, READY):
                for stage in STAGE_ORDER:
                    if states[stage] == target_state:
                        states[stage] = FAILED
                        self._refresh()
                        return
        self._refresh()

    def mark_cancelled(self) -> None:
        self._task_phase = "cancelled"
        self._publishing_pdf = None
        for stage in STAGE_ORDER:
            if self._states[stage] in (PENDING, RUNNING, READY):
                self._states[stage] = CANCELLED
        for pid, states in self._pages.items():
            if self._page_meta.get(pid, {}).get("resumed"):
                continue
            if states['save'] in (DONE, SKIPPED):
                continue
            for stage in STAGE_ORDER:
                if states[stage] in (PENDING, RUNNING, READY):
                    states[stage] = CANCELLED
        self._refresh()

    def _work_page_ids(self) -> list[str]:
        return [pid for pid in self._page_order if not self._page_meta.get(pid, {}).get("resumed")]

    def _resumed_count(self) -> int:
        return sum(1 for pid in self._page_order if self._page_meta.get(pid, {}).get("resumed"))

    def _in_flight_page_ids(self) -> list[str]:
        active = []
        for pid in self._work_page_ids():
            states = self._pages[pid]
            if states["save"] in (DONE, SKIPPED):
                continue
            if any(v == RUNNING or v == READY for v in states.values()):
                active.append(pid)
            elif any(v in (DONE, SKIPPED) for v in states.values()) and not any(
                v in (FAILED, CANCELLED) for v in states.values()
            ):
                active.append(pid)
        return active

    def _page_badge(self, page_id: str) -> str:
        if len(self._page_order) <= 1:
            return ""
        if page_id in self._page_order:
            return f"P{self._page_order.index(page_id) + 1}"
        return ""

    def _frontier_page_id(self, work_ids: list[str]) -> str | None:
        started = [
            pid for pid in work_ids
            if any(state != PENDING for state in self._pages[pid].values())
        ]
        for pid in started:
            states = self._pages[pid]
            if states["save"] not in (DONE, SKIPPED) and not any(
                v in (FAILED, CANCELLED) for v in states.values()
            ):
                return pid
        if started:
            return started[-1]
        return self._active_page_id

    def _compute_stage_views(self) -> dict[str, _StageView]:
        work_ids = self._work_page_ids()
        frontier_id = self._frontier_page_id(work_ids)
        views: dict[str, _StageView] = {}

        for stage in STAGE_ORDER:
            running = [pid for pid in work_ids if self._pages[pid][stage] == RUNNING]
            ready = [pid for pid in work_ids if self._pages[pid][stage] == READY]
            failed = [pid for pid in work_ids if self._pages[pid][stage] == FAILED]

            state = PENDING
            badge = ""
            sublabel = ""
            detail_line = tr(STAGE_DESCRIPTIONS[stage])

            if stage == "save" and self._publishing_pdf:
                badge = self._publishing_pdf['format']
                sublabel = tr('CBZ 打包') if badge == 'CBZ' else tr('PDF 合成')
                if self._publishing_pdf.get('state') == 'failed':
                    state = FAILED
                else:
                    state = RUNNING
                    detail_line = self._publish_status()
            elif failed:
                pid = failed[0]
                state = FAILED
                badge = self._page_badge(pid)
                msg = self._page_meta.get(pid, {}).get("message", "")
                detail_line = f"{self._page_meta.get(pid, {}).get('label', pid)} · {msg}" if msg else detail_line
            elif running:
                pid = running[0]
                state = RUNNING
                badge = self._page_badge(pid)
                if len(running) > 1:
                    badge = f"{badge}+{len(running) - 1}" if badge else f"×{len(running)}"
                if stage == "translate":
                    if self._context_entries > 0:
                        sublabel = tr('前文 {_0} 页', _0=self._context_entries)
                    else:
                        sublabel = tr('按序上下文')
                elif stage == "inpaint":
                    sublabel = tr('独立并行')
                msg = self._page_meta.get(pid, {}).get("message", "")
                label = self._page_meta.get(pid, {}).get("label", pid)
                detail_line = f"{label} · {tr(msg) if msg else tr(STATUS_TEXT[RUNNING])}"
            elif ready:
                pid = ready[0]
                state = READY
                badge = self._page_badge(pid)
                sublabel = tr('待汇合')
                label = self._page_meta.get(pid, {}).get("label", pid)
                detail_line = tr('{_0} · 并行修补就绪，等待翻译汇合', _0=label)
            elif self._task_phase == "done":
                if not work_ids:
                    state = SKIPPED if self._resumed_count() else DONE
                    if state == SKIPPED:
                        sublabel = tr('续传跳过')
                elif all(self._pages[pid][stage] == SKIPPED for pid in work_ids):
                    state = SKIPPED
                    if stage == "translate":
                        sublabel = tr('无文本跳过')
                else:
                    state = DONE
            elif frontier_id and frontier_id in self._pages:
                state = self._pages[frontier_id][stage]
                if state == CANCELLED:
                    pass
                elif stage == "translate":
                    if state == SKIPPED:
                        sublabel = tr('无文本跳过')
                    elif state == DONE and self._page_meta.get(frontier_id, {}).get("cached_translation"):
                        sublabel = tr('复用译文')
            elif self._task_phase == "cancelled":
                state = CANCELLED

            if stage == "translate" and state == PENDING and not sublabel:
                sublabel = tr('前文 {_0} 页', _0=self._context_entries) if self._context_entries else tr('按序上下文')
            elif stage == "inpaint" and state == PENDING and not sublabel:
                sublabel = tr('独立并行')

            tip = f"{tr(STAGE_LABELS[stage])} · {tr(STATUS_TEXT[state])}\n{detail_line}"
            views[stage] = _StageView(stage=stage, state=state, badge=badge, sublabel=sublabel, tooltip=tip)
        return views

    def _sync_pulse_timer(self, views: dict[str, _StageView]) -> None:
        now = int(self._pulse_clock.elapsed())
        self._done_flash_until = {k: v for k, v in self._done_flash_until.items() if v > now}
        any_running = any(view.state == RUNNING for view in views.values())
        any_flashing = bool(self._done_flash_until)
        should_pulse = (any_running or any_flashing) and not reduced_motion() and self.isVisible()
        if should_pulse:
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
        elif self._pulse_timer.isActive():
            self._pulse_timer.stop()

    def _advance_pulse(self) -> None:
        self._pulse_tick = (self._pulse_tick + 1) % _PULSE_PERIOD_TICKS
        if self._done_flash_until:
            self._sync_pulse_timer(self._compute_stage_views())
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_pulse_timer(self._compute_stage_views())

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._pulse_timer.isActive():
            self._pulse_timer.stop()

    def _refresh(self) -> None:
        views = self._compute_stage_views()
        now = int(self._pulse_clock.elapsed())
        can_flash = self.isVisible() and not reduced_motion()
        summary = []
        for index, stage in enumerate(STAGE_ORDER, start=1):
            view = views[stage]
            old_state = self._prev_stage_states.get(stage)
            if can_flash and old_state == RUNNING and view.state == DONE:
                self._done_flash_until[stage] = now + 440
            self._prev_stage_states[stage] = view.state
            name, status = self._labels[stage]
            name.setText(f'{index:02d} {tr(STAGE_LABELS[stage])}')
            status.setText(tr(STATUS_TEXT[view.state]))
            name.setAccessibleName(f'{tr(STAGE_LABELS[stage])}, {tr(STATUS_TEXT[view.state])}')
            summary.append(f'{tr(STAGE_LABELS[stage])} {tr(STATUS_TEXT[view.state])}')
        self.setAccessibleName(
            tr('流水线：{_0}；{_1}', _0=self._file_label.text(), _1='；'.join(summary))
        )
        self._sync_pulse_timer(views)
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        for stage, rect in self._node_rects.items():
            if rect.contains(pos):
                views = self._compute_stage_views()
                tip = views[stage].tooltip
                if self._hover_target != ('node', stage):
                    self._hover_target = ('node', stage)
                    self.update()
                if self.toolTip() != tip:
                    self.setToolTip(tip)
                return
        for rect, pid, tip in self._tile_rects:
            if rect.contains(pos):
                if self._hover_target != ('tile', pid) or self.toolTip() != tip:
                    self._hover_target = ('tile', pid)
                    self.setToolTip(tip)
                    self.update()
                return
        if self._hover_target is not None:
            self._hover_target = None
            self.update()
        self.setToolTip(tr('工作流视图 · OCR 后翻译与修补分叉并行'))

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._hover_target is not None:
            self._hover_target = None
            self.update()

    def _compute_dag_geometry(self, bounds: QRectF) -> tuple[dict[str, QRectF], QPointF, QPointF]:
        avail_w = max(240.0, bounds.width())
        normal_gap = max(6.0, min(18.0, avail_w * 0.017))
        fork_gap = max(15.0, min(34.0, avail_w * 0.032))
        nodes_w = max(160.0, avail_w - 3 * normal_gap - 2 * fork_gap)
        fork_ratio = 1.6 if self._compact or avail_w < 640.0 else 1.8
        unit = nodes_w / (5.0 + fork_ratio)
        fork_w = unit * fork_ratio

        single_h = 24.0 if self._compact else 29.0
        fork_h = 21.0 if self._compact else 25.5
        cy = bounds.center().y()
        fork_gap_y = 6.0 if self._compact else 7.0
        top_y = cy - fork_gap_y / 2.0 - fork_h
        bot_y = cy + fork_gap_y / 2.0
        single_y = cy - single_h / 2.0

        x = bounds.left()
        rects: dict[str, QRectF] = {}
        for stage in ("start", "detect", "ocr"):
            rects[stage] = QRectF(x, single_y, unit, single_h)
            x += unit + (fork_gap if stage == "ocr" else normal_gap)
        rects["translate"] = QRectF(x, top_y, fork_w, fork_h)
        rects["inpaint"] = QRectF(x, bot_y, fork_w, fork_h)
        x += fork_w + fork_gap
        rects["typeset"] = QRectF(x, single_y, unit, single_h)
        x += unit + normal_gap
        rects["save"] = QRectF(x, single_y, unit, single_h)

        fork_pt = QPointF(rects["ocr"].right() + fork_gap * 0.34, cy)
        join_pt = QPointF(rects["typeset"].left() - fork_gap * 0.34, cy)
        return rects, fork_pt, join_pt

    def _publish_status(self):
        name = self._publishing_pdf['name']
        if self._publishing_pdf['format'] == 'CBZ':
            return tr('正在打包译文 CBZ · {_0}', _0=name)
        return tr('正在合成译文 PDF · {_0}', _0=name)

    def _header_texts(self, views: dict[str, _StageView]) -> tuple[str, list[str]]:
        work_ids = self._work_page_ids()
        total_pages = len(self._page_order)
        in_flight = len(self._in_flight_page_ids())
        resumed = self._resumed_count()

        if self._publishing_pdf and self._publishing_pdf.get('state') == 'running':
            headline = self._publish_status()
        elif self._task_phase == 'failed' or any(v.state == FAILED for v in views.values()):
            headline = tr('流程中断 · 请查看报错日志')
        elif self._task_phase == 'cancelled':
            headline = tr('流水线已取消')
        elif self._task_phase == 'done':
            if total_pages > 0:
                headline = tr('流程已完成 · 共 {_0} 页', _0=total_pages)
            else:
                headline = tr('流程已完成 · {_0} 个文件', _0=self._queued_count)
        elif self._task_phase == 'running' and total_pages > 0:
            active_slots = max(in_flight, 1 if any(v.state == RUNNING for v in views.values()) else 0)
            headline = tr('并行流水线 · 在途 {_0}/{_1} 页', _0=active_slots, _1=self._max_workers)
        else:
            headline = tr('工作流视图 · OCR 后翻译与修补分叉并行')

        pills: list[str] = []
        if self._context_entries > 0:
            key = '沿用前文 {_0} 页' if self._retain_context else '前文 {_0} 页'
            pills.append(tr(key, _0=self._context_entries))
        elif self._retain_context:
            pills.append(tr('沿用前文 {_0} 页', _0=0))
        else:
            pills.append(tr('按序上下文'))
        if resumed > 0:
            pills.append(tr('续传 {_0} 页', _0=resumed))
        if self._task_phase == 'running' and total_pages > 0:
            pills.append(tr('并发 {_0}/{_1}', _0=min(in_flight or 1, self._max_workers), _1=self._max_workers))
        elif self.width() >= 680:
            pills.append(tr('并发上限 {_0}', _0=self._max_workers))
        return headline, pills

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = float(self.width())
        h = float(self.height())
        if w < 40 or h < 24:
            return

        # Outer architectural card
        card = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        painter.setPen(QPen(QColor(color('rule')), 1.0))
        painter.setBrush(QColor(color('workspace')))
        painter.drawRoundedRect(card, 10.0, 10.0)

        views = self._compute_stage_views()
        if not self._compact:
            self._draw_header(painter, QRectF(12.0, 5.0, w - 24.0, 18.0), views)
            dag_rect = QRectF(12.0, 26.0, w - 24.0, 60.0)
            matrix_rect = QRectF(12.0, 91.0, w - 24.0, 14.0)
        else:
            dag_rect = QRectF(10.0, 5.0, w - 20.0, 50.0)
            matrix_rect = QRectF(10.0, 58.0, w - 20.0, 4.0)

        rects, fork_pt, join_pt = self._compute_dag_geometry(dag_rect)
        self._node_rects = rects
        self._draw_wires(painter, rects, fork_pt, join_pt, views)
        for stage in STAGE_ORDER:
            self._draw_node(painter, rects[stage], views[stage])
        self._draw_page_matrix(painter, matrix_rect)

    def _draw_header(self, painter: QPainter, rect: QRectF, views: dict[str, _StageView]) -> None:
        headline, pills = self._header_texts(views)
        pill_font = ui_font(11, QFont.Medium)
        fm_pill = QFontMetrics(pill_font)
        right_x = rect.right()
        pill_rects: list[tuple[QRectF, str]] = []
        for text in reversed(pills):
            pw = float(fm_pill.horizontalAdvance(text)) + 14.0
            if right_x - pw < rect.left() + 180.0:
                break
            pill_rect = QRectF(right_x - pw, rect.top() + 1.0, pw, 16.0)
            pill_rects.append((pill_rect, text))
            right_x = pill_rect.left() - 6.0

        for pill_rect, text in pill_rects:
            painter.setPen(QPen(QColor(color('rule')), 1.0))
            painter.setBrush(QColor(color('paper')))
            painter.drawRoundedRect(pill_rect, 5.0, 5.0)
            painter.setFont(pill_font)
            painter.setPen(QColor(color('secondary')))
            painter.drawText(pill_rect, Qt.AlignCenter, text)

        # Status dot on the left of headline
        dot_center = QPointF(rect.left() + 4.0, rect.center().y())
        any_running = any(v.state == RUNNING for v in views.values())
        any_failed = self._task_phase == 'failed' or any(v.state == FAILED for v in views.values())
        if any_failed:
            painter.setPen(QPen(QColor(color('ink')), 1.8))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(dot_center, 3.5, 3.5)
        elif any_running or self._task_phase == 'done':
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('ink')))
            painter.drawEllipse(dot_center, 3.5, 3.5)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('secondary')))
            painter.drawEllipse(dot_center, 3.0, 3.0)

        head_font = ui_font(11, QFont.DemiBold if (any_running or any_failed) else QFont.Medium)
        painter.setFont(head_font)
        painter.setPen(QColor(color('ink') if (any_running or any_failed or self._task_phase == 'done') else color('secondary')))
        text_left = rect.left() + 14.0
        max_head_w = max(40.0, right_x - text_left - 8.0)
        elided = QFontMetrics(head_font).elidedText(headline, Qt.ElideRight, int(max_head_w))
        painter.drawText(QRectF(text_left, rect.top(), max_head_w, rect.height()),
                         Qt.AlignLeft | Qt.AlignVCenter, elided)

    def _draw_wire_path(
        self,
        painter: QPainter,
        path: QPainterPath,
        *,
        energized: bool,
        skipped: bool = False,
        travel: bool = False,
        arrow_at: QPointF | None = None,
    ) -> None:
        if skipped:
            pen = QPen(QColor(color('ruleStrong')), 1.3, Qt.DashLine, Qt.RoundCap)
        elif energized:
            pen = QPen(QColor(color('ink')), 1.9, Qt.SolidLine, Qt.RoundCap)
        else:
            pen = QPen(QColor(color('rule')), 1.4, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        if arrow_at is not None:
            arrow_color = QColor(color('ink') if energized else color('ruleStrong') if skipped else color('rule'))
            painter.setPen(QPen(arrow_color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            x, y = arrow_at.x(), arrow_at.y()
            chevron = QPainterPath(QPointF(x - 4.0, y - 3.0))
            chevron.lineTo(x, y)
            chevron.lineTo(x - 4.0, y + 3.0)
            painter.drawPath(chevron)

        if travel and energized and not reduced_motion() and self._pulse_timer.isActive():
            base_t = ((self._pulse_clock.elapsed() % 1350) / 1350.0) * 1.12 - 0.02
            painter.setPen(Qt.NoPen)
            ink = QColor(color('ink'))
            for offset, rad, alpha in ((0.0, 2.8, 255), (-0.055, 2.1, 150), (-0.11, 1.4, 70)):
                t = base_t + offset
                if 0.0 <= t <= 1.0:
                    pt = path.pointAtPercent(t)
                    c = QColor(ink)
                    c.setAlpha(alpha)
                    painter.setBrush(c)
                    painter.drawEllipse(pt, rad, rad)

    def _draw_wires(
        self,
        painter: QPainter,
        rects: dict[str, QRectF],
        fork_pt: QPointF,
        join_pt: QPointF,
        views: dict[str, _StageView],
    ) -> None:
        # 1. start -> detect -> ocr
        for src, dst in (("start", "detect"), ("detect", "ocr")):
            path = QPainterPath(QPointF(rects[src].right(), rects[src].center().y()))
            dst_pt = QPointF(rects[dst].left(), rects[dst].center().y())
            path.lineTo(dst_pt)
            src_passed = views[src].state in (DONE, SKIPPED, RUNNING)
            energized = src_passed and _is_active_branch(views[dst].state)
            self._draw_wire_path(
                painter, path, energized=energized,
                travel=views[src].state in (DONE, SKIPPED) and views[dst].state == RUNNING,
                arrow_at=dst_pt,
            )

        # 2. ocr -> fork point
        ocr_done = views["ocr"].state in (DONE, SKIPPED, RUNNING)
        tr_state = views["translate"].state
        in_state = views["inpaint"].state
        ocr_out = QPainterPath(QPointF(rects["ocr"].right(), rects["ocr"].center().y()))
        ocr_out.lineTo(fork_pt)
        self._draw_wire_path(
            painter, ocr_out,
            energized=ocr_done and (_is_active_branch(tr_state) or _is_active_branch(in_state)),
        )

        # 3. Fork S-curves -> translate (top) & inpaint (bottom)
        for target_stage, t_state in (("translate", tr_state), ("inpaint", in_state)):
            dst_pt = QPointF(rects[target_stage].left(), rects[target_stage].center().y())
            dx = dst_pt.x() - fork_pt.x()
            curve = QPainterPath(fork_pt)
            curve.cubicTo(
                QPointF(fork_pt.x() + dx * 0.55, fork_pt.y()),
                QPointF(dst_pt.x() - dx * 0.55, dst_pt.y()),
                dst_pt,
            )
            energized = ocr_done and _is_active_branch(t_state) and t_state != SKIPPED
            self._draw_wire_path(
                painter, curve,
                energized=energized,
                skipped=(t_state == SKIPPED and ocr_done),
                travel=views["ocr"].state in (DONE, SKIPPED) and t_state == RUNNING,
                arrow_at=dst_pt,
            )

        # Fork junction dot
        fork_active = ocr_done and (_is_active_branch(tr_state) or _is_active_branch(in_state))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color('ink') if fork_active else color('ruleStrong')))
        painter.drawEllipse(fork_pt, 2.5, 2.5)

        # 4. translate / inpaint -> join point
        tr_arrived = tr_state in (DONE, SKIPPED, READY)
        in_arrived = in_state in (DONE, SKIPPED, READY)
        for src_stage, s_state in (("translate", tr_state), ("inpaint", in_state)):
            src_pt = QPointF(rects[src_stage].right(), rects[src_stage].center().y())
            dx = join_pt.x() - src_pt.x()
            curve = QPainterPath(src_pt)
            curve.cubicTo(
                QPointF(src_pt.x() + dx * 0.55, src_pt.y()),
                QPointF(join_pt.x() - dx * 0.55, join_pt.y()),
                join_pt,
            )
            downstream = _is_active_branch(views["typeset"].state)
            self._draw_wire_path(
                painter, curve,
                energized=s_state in (DONE, READY) or (downstream and s_state != SKIPPED),
                skipped=(s_state == SKIPPED),
            )

        # 5. join point -> typeset -> save
        ty_state = views["typeset"].state
        sv_state = views["save"].state
        both_arrived = (tr_arrived and in_arrived) or _is_active_branch(ty_state)
        join_to_ty = QPainterPath(join_pt)
        ty_pt = QPointF(rects["typeset"].left(), rects["typeset"].center().y())
        join_to_ty.lineTo(ty_pt)
        self._draw_wire_path(
            painter, join_to_ty,
            energized=both_arrived and _is_active_branch(ty_state),
            travel=both_arrived and ty_state == RUNNING,
            arrow_at=ty_pt,
        )

        # Join gate indicator (hollow -> half-filled -> solid)
        gate_r = 3.8
        gate_rect = QRectF(join_pt.x() - gate_r, join_pt.y() - gate_r, gate_r * 2, gate_r * 2)
        if both_arrived:
            painter.setPen(QPen(QColor(color('ink')), 1.5))
            painter.setBrush(QColor(color('ink')))
            painter.drawEllipse(join_pt, gate_r, gate_r)
        elif tr_arrived or in_arrived:
            painter.setPen(QPen(QColor(color('ink')), 1.4))
            painter.setBrush(QColor(color('paper')))
            painter.drawEllipse(join_pt, gate_r, gate_r)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('ink')))
            # Top half when translate arrived first; bottom half when repair arrived first.
            start_angle = 0 if tr_arrived else 180 * 16
            painter.drawPie(gate_rect, start_angle, 180 * 16)
        else:
            painter.setPen(QPen(QColor(color('ruleStrong')), 1.3))
            painter.setBrush(QColor(color('paper')))
            painter.drawEllipse(join_pt, gate_r - 0.3, gate_r - 0.3)

        # 6. typeset -> save
        ty_to_sv = QPainterPath(QPointF(rects["typeset"].right(), rects["typeset"].center().y()))
        sv_pt = QPointF(rects["save"].left(), rects["save"].center().y())
        ty_to_sv.lineTo(sv_pt)
        ty_done = ty_state in (DONE, SKIPPED, RUNNING)
        self._draw_wire_path(
            painter, ty_to_sv,
            energized=ty_done and _is_active_branch(sv_state),
            travel=ty_state in (DONE, SKIPPED) and sv_state == RUNNING,
            arrow_at=sv_pt,
        )

    def _fit_node_label(
        self, stage: str, avail_w: float, base_size: int, weight: QFont.Weight
    ) -> tuple[QFont, str]:
        index = STAGE_ORDER.index(stage) + 1
        full = tr(STAGE_LABELS[stage])
        compact = tr(STAGE_COMPACT_LABELS[stage])
        if ui_language() == 'en' and stage == 'ocr':
            full = 'OCR'
        candidates = (
            f"{index:02d} {full}",
            full,
            f"{index:02d} {compact}",
            compact,
        )
        for size in (base_size, max(10, base_size - 1)):
            font = ui_font(size, weight)
            fm = QFontMetrics(font)
            for text in candidates:
                if fm.horizontalAdvance(text) <= avail_w:
                    return font, text
        fallback = ui_font(max(10, base_size - 1), weight)
        return fallback, QFontMetrics(fallback).elidedText(compact, Qt.ElideRight, max(16, int(avail_w)))

    def _draw_node(self, painter: QPainter, rect: QRectF, view: _StageView) -> None:
        state = view.state
        radius = 7.0 if self._compact else 8.0
        is_running = state == RUNNING
        is_done = state == DONE
        is_ready = state == READY
        is_failed = state == FAILED
        is_skipped = state == SKIPPED

        if is_running:
            fill = QColor(color('ink'))
            border_pen = QPen(QColor(color('ink')), 1.5)
            fg = QColor(color('paper'))
            sub_fg = QColor(color('paper'))
            sub_fg.setAlphaF(0.75)
        elif is_done:
            fill = QColor(color('muted'))
            border_pen = QPen(QColor(color('ink')), 1.25)
            fg = QColor(color('ink'))
            sub_fg = QColor(color('secondary'))
        elif is_ready:
            fill = QColor(color('muted'))
            border_pen = QPen(QColor(color('ink')), 1.5)
            fg = QColor(color('ink'))
            sub_fg = QColor(color('ink'))
        elif is_failed:
            fill = QColor(color('paper'))
            border_pen = QPen(QColor(color('ink')), 1.8, Qt.DashLine)
            fg = QColor(color('ink'))
            sub_fg = QColor(color('ink'))
        elif is_skipped:
            fill = QColor(color('paper'))
            border_pen = QPen(QColor(color('ruleStrong')), 1.1, Qt.DashLine)
            fg = QColor(color('secondary'))
            sub_fg = QColor(color('secondary'))
        elif state == CANCELLED:
            fill = QColor(color('paper'))
            border_pen = QPen(QColor(color('rule')), 1.0, Qt.DashLine)
            fg = QColor(color('disabled'))
            sub_fg = QColor(color('disabled'))
        else:
            fill = QColor(color('paper'))
            border_pen = QPen(QColor(color('rule')), 1.0)
            fg = QColor(color('secondary'))
            sub_fg = QColor(color('disabled'))

        painter.setPen(border_pen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)

        if self._hover_target == ('node', view.stage) and not is_running:
            hover_c = QColor(color('ink'))
            hover_c.setAlpha(18)
            painter.setPen(QPen(QColor(color('ink')), 1.1))
            painter.setBrush(hover_c)
            painter.drawRoundedRect(rect, radius, radius)

        if is_running and not reduced_motion() and self._pulse_timer.isActive():
            inner = rect.adjusted(2.0, 4.0, -2.0, -4.0)
            if inner.width() > 6.0 and inner.height() > 4.0:
                painter.save()
                clip = QPainterPath()
                clip.addRoundedRect(inner, max(2.0, radius - 2.0), max(2.0, radius - 2.0))
                painter.setClipPath(clip)
                phase = (self._pulse_clock.elapsed() % 1350) / 1350.0
                sweep = min(1.0, phase / 0.78)
                band_w = max(20.0, inner.width() * 0.44)
                cx = inner.left() - band_w * 0.6 + (inner.width() + band_w * 1.2) * sweep
                sheen = QColor(color('paper'))
                fade = 1.0 if phase <= 0.78 else max(0.0, 1.0 - (phase - 0.78) / 0.14)
                sheen_c = QColor(sheen)
                sheen_c.setAlpha(0)
                sheen_peak = QColor(sheen)
                sheen_peak.setAlpha(int(round(34 * fade)))
                grad = QLinearGradient(cx - band_w * 0.5, inner.top(), cx + band_w * 0.5, inner.bottom())
                grad.setColorAt(0.0, sheen_c)
                grad.setColorAt(0.5, sheen_peak)
                grad.setColorAt(1.0, sheen_c)
                painter.fillRect(inner, grad)
                painter.restore()

        flash_until = self._done_flash_until.get(view.stage)
        if flash_until is not None and not reduced_motion():
            rem = flash_until - int(self._pulse_clock.elapsed())
            if rem > 0:
                ft = 1.0 - max(0.0, min(1.0, rem / 440.0))
                spread = 1.5 + 5.5 * ft
                ring_c = QColor(color('ink'))
                ring_c.setAlpha(int(round(135 * (1.0 - ft) ** 2)))
                painter.setPen(QPen(ring_c, 1.3))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread), radius + spread * 0.4, radius + spread * 0.4)

        # Status glyph on the left inside the node
        pad_x = 6.0 if self._compact else 9.0
        glyph_r = 4.0 if self._compact else 5.2
        gx = rect.left() + pad_x + glyph_r
        gy = rect.center().y()
        self._draw_status_glyph(painter, QPointF(gx, gy), glyph_r, state, is_running)

        # Optional inline page badge (or sublabel on wide fork nodes)
        badge_font = ui_font(10 if self._compact else 11, QFont.Bold, mono=True)
        fm_badge = QFontMetrics(badge_font)
        right_cursor = rect.right() - (5.0 if self._compact else 8.0)

        badge_text = view.badge
        show_inline_badge = bool(badge_text) and rect.width() >= 96.0
        if show_inline_badge:
            bw = float(fm_badge.horizontalAdvance(badge_text)) + 10.0
            bh = 15.0 if self._compact else 16.0
            b_rect = QRectF(right_cursor - bw, rect.center().y() - bh / 2.0, bw, bh)
            painter.setPen(Qt.NoPen if is_running else QPen(QColor(color('ink')), 1.0))
            painter.setBrush(QColor(color('paper') if is_running else color('ink')))
            painter.drawRoundedRect(b_rect, 4.0, 4.0)
            painter.setFont(badge_font)
            painter.setPen(QColor(color('ink') if is_running else color('paper')))
            painter.drawText(b_rect, Qt.AlignCenter, badge_text)
            right_cursor = b_rect.left() - 6.0

        # Show concise sublabel inside wide fork nodes (or PDF build badge)
        sub_text = view.sublabel if (not self._compact and rect.width() >= 185.0) else ""
        if sub_text:
            sub_font = ui_font(10, QFont.Normal)
            fm_sub = QFontMetrics(sub_font)
            sw = float(fm_sub.horizontalAdvance(sub_text))
            if right_cursor - (gx + glyph_r + 6.0) - sw >= 82.0:
                s_rect = QRectF(right_cursor - sw, rect.top(), sw, rect.height())
                painter.setFont(sub_font)
                painter.setPen(sub_fg)
                painter.drawText(s_rect, Qt.AlignRight | Qt.AlignVCenter, sub_text)
                right_cursor = s_rect.left() - 8.0

        # Main label
        text_left = gx + glyph_r + (4.5 if self._compact else 6.0)
        avail_text_w = max(16.0, right_cursor - text_left)
        base_size = 11 if self._compact or self.width() < 860 else 12
        weight = QFont.Bold if state in (RUNNING, DONE, READY, FAILED) else QFont.Medium
        label_font, label_text = self._fit_node_label(view.stage, avail_text_w, base_size, weight)
        painter.setFont(label_font)
        painter.setPen(fg)
        painter.drawText(
            QRectF(text_left, rect.top(), avail_text_w, rect.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            label_text,
        )

        # Compact top-right corner page pill when node is too narrow for inline badge
        if badge_text and not show_inline_badge:
            bw = float(fm_badge.horizontalAdvance(badge_text)) + 8.0
            bh = 13.0
            b_rect = QRectF(rect.right() - bw + 2.0, rect.top() - 5.0, bw, bh)
            painter.setPen(QPen(QColor(color('paper') if is_running else color('ink')), 1.0))
            painter.setBrush(QColor(color('ink')))
            painter.drawRoundedRect(b_rect, 4.0, 4.0)
            painter.setFont(badge_font)
            painter.setPen(QColor(color('paper')))
            painter.drawText(b_rect, Qt.AlignCenter, badge_text)

    def _draw_status_glyph(
        self, painter: QPainter, center: QPointF, r: float, state: int, inverted: bool
    ) -> None:
        if state == RUNNING:
            fg = QColor(color('paper') if inverted else color('ink'))
            if not reduced_motion() and self._pulse_timer.isActive():
                ms = float(self._pulse_clock.elapsed())
                phase = 0.5 + 0.5 * sin(2 * pi * ms / 1100.0)
                ring = QColor(fg)
                ring.setAlphaF(0.28 + 0.48 * phase)
                painter.setPen(QPen(ring, 1.3))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(center, r * (0.86 + 0.24 * phase), r * (0.86 + 0.24 * phase))
                echo_t = (ms % 1100.0) / 1100.0
                echo_c = QColor(fg)
                echo_c.setAlphaF(0.45 * ((1.0 - echo_t) ** 2))
                painter.setPen(QPen(echo_c, 1.0))
                painter.drawEllipse(center, r * (0.95 + 0.85 * echo_t), r * (0.95 + 0.85 * echo_t))
            painter.setPen(Qt.NoPen)
            painter.setBrush(fg)
            painter.drawEllipse(center, r * 0.52, r * 0.52)
        elif state in (DONE, READY):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('ink')) if state == DONE else QColor(color('paper')))
            if state == READY:
                painter.setPen(QPen(QColor(color('ink')), 1.3))
            painter.drawEllipse(center, r, r)
            tick_pen = QPen(
                QColor(color('paper') if state == DONE else color('ink')),
                1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin,
            )
            painter.setPen(tick_pen)
            tick = QPainterPath(QPointF(center.x() - r * 0.42, center.y() + r * 0.02))
            tick.lineTo(QPointF(center.x() - r * 0.08, center.y() + r * 0.36))
            tick.lineTo(QPointF(center.x() + r * 0.46, center.y() - r * 0.34))
            painter.drawPath(tick)
        elif state == FAILED:
            painter.setPen(QPen(QColor(color('ink')), 1.5))
            painter.setBrush(QColor(color('paper')))
            painter.drawEllipse(center, r, r)
            d = r * 0.38
            painter.setPen(QPen(QColor(color('ink')), 1.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(center.x() - d, center.y() - d), QPointF(center.x() + d, center.y() + d))
            painter.drawLine(QPointF(center.x() - d, center.y() + d), QPointF(center.x() + d, center.y() - d))
        elif state in (SKIPPED, CANCELLED):
            pen_color = QColor(color('secondary') if state == SKIPPED else color('disabled'))
            painter.setPen(QPen(pen_color, 1.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(center.x() - r * 0.55, center.y()), QPointF(center.x() + r * 0.55, center.y()))
        else:
            painter.setPen(QPen(QColor(color('ruleStrong')), 1.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(center, r * 0.78, r * 0.78)

    def _draw_page_matrix(self, painter: QPainter, rect: QRectF) -> None:
        self._tile_rects = []
        if self._page_order:
            items = self._page_order
            from_plan = True
        elif self._queued_count > 0:
            items = [f"q:{idx + 1}" for idx in range(self._queued_count)]
            from_plan = False
        else:
            return

        count = len(items)
        if count <= 0:
            return
        gap = 2.0 if count <= 72 else 0.5
        total_gap = gap * max(0, count - 1)
        tile_w = (rect.width() - total_gap) / count
        if tile_w < 1.2:
            # Bucket huge page counts smoothly to crisp contiguous segments.
            buckets = max(1, int(rect.width() // 3))
            gap = 1.0
            tile_w = (rect.width() - gap * (buckets - 1)) / buckets
            for bucket in range(buckets):
                start = bucket * count // buckets
                end = max(start + 1, (bucket + 1) * count // buckets)
                slice_ids = items[start:end]
                x = rect.left() + bucket * (tile_w + gap)
                cell_h = 4.0 if self._compact else 6.0
                cell = QRectF(x, rect.center().y() - cell_h / 2.0, tile_w, cell_h)
                self._paint_bucket_tile(painter, cell, slice_ids, from_plan)
            return

        for idx, pid in enumerate(items):
            x = rect.left() + idx * (tile_w + gap)
            kind, tip = self._classify_page_tile(pid, idx, from_plan)
            if self._compact:
                cell_h = 4.0
            elif kind in ('active', 'failed'):
                cell_h = 9.0
            elif kind in ('done', 'resumed'):
                cell_h = 6.0
            else:
                cell_h = 4.5
            cell = QRectF(x, rect.center().y() - cell_h / 2.0, max(2.0, tile_w), cell_h)
            radius = min(2.5, cell.height() / 2.0, cell.width() / 2.0)
            self._paint_single_tile(painter, cell, radius, kind, hovered=(self._hover_target == ('tile', pid)))
            self._tile_rects.append((QRectF(x, rect.top() - 2.0, max(4.0, tile_w), rect.height() + 4.0), pid, tip))

    def _classify_page_tile(self, pid: str, idx: int, from_plan: bool) -> tuple[str, str]:
        if not from_plan:
            name = self._queued_names[idx] if idx < len(self._queued_names) else tr('第 {_0} 页', _0=idx + 1)
            if self._task_phase == 'done':
                return 'done', tr('{_0} · 已完成', _0=name)
            if self._task_phase == 'failed':
                return 'failed', tr('{_0} · 失败', _0=name)
            if self._task_phase == 'cancelled':
                return 'cancelled', tr('{_0} · 已取消', _0=name)
            return 'queued', tr('{_0} · 排队等待', _0=name)
        meta = self._page_meta.get(pid, {})
        label = meta.get('label', tr('第 {_0} 页', _0=idx + 1))
        if meta.get('resumed'):
            return 'resumed', tr('{_0} · 断点续传已跳过', _0=label)
        states = self._pages[pid]
        if any(v == FAILED for v in states.values()):
            return 'failed', tr('{_0} · 失败', _0=label)
        if states['save'] in (DONE, SKIPPED):
            return 'done', tr('{_0} · 已完成', _0=label)
        if any(v == CANCELLED for v in states.values()):
            return 'cancelled', tr('{_0} · 已取消', _0=label)
        if any(v in (RUNNING, READY, DONE, SKIPPED) for v in states.values()):
            active_names = [
                f"{tr(STAGE_LABELS[s])}({tr(STATUS_TEXT[states[s]])})"
                for s in STAGE_ORDER if states[s] in (RUNNING, READY)
            ]
            detail = ' · '.join(active_names) if active_names else tr('运行中')
            return 'active', f"{label} · {detail}"
        return 'queued', tr('{_0} · 排队等待', _0=label)

    def _paint_single_tile(
        self, painter: QPainter, cell: QRectF, radius: float, kind: str, *, hovered: bool
    ) -> None:
        if kind == 'done':
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('ink')))
        elif kind == 'active':
            painter.setPen(QPen(QColor(color('ink')), 1.2))
            painter.setBrush(QColor(color('ink')))
        elif kind == 'resumed':
            painter.setPen(QPen(QColor(color('ink')), 1.1))
            painter.setBrush(QColor(color('paper')))
        elif kind == 'failed':
            painter.setPen(QPen(QColor(color('ink')), 1.4, Qt.DashLine))
            painter.setBrush(QColor(color('paper')))
        elif kind == 'cancelled':
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('disabled')))
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('rule')))
        painter.drawRoundedRect(cell, radius, radius)

        if kind == 'active' and cell.width() >= 6.0 and cell.height() >= 6.0:
            # Tiny inner paper core distinguishes live in-flight pages from completed ones.
            core = QRectF(cell.center().x() - 1.5, cell.center().y() - 1.5, 3.0, 3.0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('paper')))
            painter.drawEllipse(core)
        elif kind == 'resumed' and cell.width() >= 6.0:
            # Small centered ink dot denotes checkpoint-resumed page.
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color('ink')))
            painter.drawEllipse(cell.center(), 1.3, 1.3)

        if hovered and not self._compact:
            painter.setPen(QPen(QColor(color('ink')), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(cell.adjusted(-1.0, -1.0, 1.0, 1.0), radius + 0.5, radius + 0.5)

    def _paint_bucket_tile(
        self, painter: QPainter, cell: QRectF, slice_ids: list[str], from_plan: bool
    ) -> None:
        if not from_plan:
            kind = 'queued'
        else:
            kinds = [self._classify_page_tile(pid, 0, True)[0] for pid in slice_ids]
            if 'failed' in kinds:
                kind = 'failed'
            elif 'active' in kinds:
                kind = 'active'
            elif all(k == 'done' for k in kinds):
                kind = 'done'
            elif all(k in ('done', 'resumed') for k in kinds):
                kind = 'resumed'
            elif any(k in ('done', 'resumed') for k in kinds):
                kind = 'active'
            elif 'cancelled' in kinds:
                kind = 'cancelled'
            else:
                kind = 'queued'
        self._paint_single_tile(painter, cell, min(2.0, cell.height() / 2.0), kind, hovered=False)
