"""Bounded logical records, incremental rendering, and explicit follow control."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
import unicodedata
from PySide6.QtCore import QTimer, Qt, QSettings
from PySide6.QtGui import QTextCursor, QTextBlockFormat, QTextOption, QTextBlockUserData, QFontMetricsF, QTextCharFormat
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout, QPlainTextEdit, QComboBox, QLineEdit, QPushButton, QSpinBox, QMenu, QMessageBox, QFileDialog
from .theme import log_font, ui_font
from .manga_components import PanelHeading


class _RecordData(QTextBlockUserData):
    def __init__(self, sequence):
        super().__init__()
        self.sequence = sequence


@dataclass
class _Reveal:
    record: tuple
    text: str
    offset: int = 0


class LogPanel(QFrame):
    LIMIT = 5000
    FRAME_MS = 16
    CHARS_PER_FRAME = 4

    def __init__(self, log_path, parent=None):
        super().__init__(parent)
        self.setObjectName('logPanel')
        self.log_path = Path(log_path)
        self.records = deque(maxlen=self.LIMIT)
        self.pending = deque()
        self._reveal_queue = deque()
        self._remaining_chars = 0
        self.following = True
        self.unseen = 0
        self._updating = False
        self._sequence = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)
        bar = QHBoxLayout()
        self.heading = PanelHeading('03', '详细日志')
        self.heading.setFixedWidth(320)
        bar.addWidget(self.heading)
        self.level = QComboBox()
        self.level.addItems(['全部级别', 'INFO', 'WARN', 'ERROR'])
        self.level.setAccessibleName('日志级别筛选')
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索日志')
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(80)
        self.search.setAccessibleName('搜索日志')
        self.follow = QPushButton('暂停跟随')
        self.follow.setProperty('compact', True)
        self.follow.clicked.connect(self.toggle_follow)
        more = QPushButton('更多')
        more.setProperty('compact', True)
        menu = QMenu(more)
        menu.addAction('复制选中 / 当前筛选日志', self.copy_logs)
        menu.addAction('导出当前筛选日志（最多 5,000 条）', self.export_view)
        menu.addAction('导出磁盘完整日志', self.export_file)
        more.setMenu(menu)
        self.font_size = QSpinBox()
        self.font_size.setRange(12, 20)
        self.font_size.setSuffix(' px')
        self.font_size.setFixedWidth(86)
        self.font_size.setValue(int(QSettings().value('ui/logFontSize', 18)))
        self.font_size.setToolTip('日志字号 · 正文使用 Aa今日花晴 春懒猫困')
        self.font_size.setAccessibleName('日志字号')
        level_menu = menu.addMenu('日志级别')
        for index, name in enumerate(('全部级别', 'INFO', 'WARN', 'ERROR')):
            level_menu.addAction(name, lambda checked=False, value=index: self.level.setCurrentIndex(value))
        font_menu = menu.addMenu('日志字号')
        for size in range(12, 21):
            font_menu.addAction(f'{size} px', lambda checked=False, value=size: self.font_size.setValue(value))
        for widget in (self.level, self.search, self.follow, more, self.font_size):
            bar.addWidget(widget, 1 if widget is self.search else 0)
        layout.addLayout(bar)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        # Each event is one Qt block; embedded newlines use Unicode line separators.
        self.view.setMaximumBlockCount(self.LIMIT)
        self.view.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.view.setPlaceholderText('详细日志 · 等待后台输出')
        self.view.setMinimumHeight(70)
        self.view.setAccessibleName('实时详细日志')
        layout.addWidget(self.view, 1)
        self._set_font(self.font_size.value())
        self.font_size.valueChanged.connect(self._set_font)
        self.level.currentIndexChanged.connect(self._refilter)
        self.search.textChanged.connect(self._schedule_filter)
        self.view.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.view.selectionChanged.connect(self._selection_changed)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(self.FRAME_MS)
        self.timer.timeout.connect(self.flush)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(180)
        self.filter_timer.timeout.connect(self._refilter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.heading.setFixedWidth(180 if self.width() < 920 else 320)
        self.font_size.setVisible(self.width() >= 920)
        self.level.setVisible(self.width() >= 750)
        self.search.setPlaceholderText('搜索日志' if self.width() >= 750 else '搜索')

    def _set_font(self, size):
        self._metadata_font = ui_font(size, mono=True)
        self.view.setFont(log_font(size))
        QSettings().setValue('ui/logFontSize', size)
        if self.records:
            self._refilter()

    @staticmethod
    def level_for(message):
        upper = message.upper()
        if any(tag in upper for tag in ('[失败', '[严重错误]', '[ERROR]', 'TRACEBACK')):
            return 'ERROR'
        if any(tag in upper for tag in ('警告', '[WARN', '[WARNING]')):
            return 'WARN'
        return 'INFO'

    def append(self, message):
        self._sequence += 1
        record = (datetime.now().strftime('%H:%M:%S.%f')[:-3], self.level_for(message), message, self._sequence)
        self.pending.append(record)
        if not self.timer.isActive():
            self.timer.start()

    def _matches(self, record):
        return (self.level.currentIndex() == 0 or record[1] == self.level.currentText()) and self.search.text().casefold() in record[2].casefold()

    @staticmethod
    def _text(record):
        return f'{record[0]}\t{record[1]}\t{record[2]}'

    @staticmethod
    def _display_text(message):
        return message.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\u2028')

    def flush(self, *, force=False):
        incoming = 0
        has_error = False
        for _ in range(min(len(self.pending), 1000)):
            record = self.pending.popleft()
            self.records.append(record)
            has_error = has_error or record[1] == 'ERROR'
            if self._matches(record):
                text = self._display_text(record[2])
                self._reveal_queue.append(_Reveal(record, text))
                self._remaining_chars += len(text)
                incoming += 1
        # Full records are retained independently of their on-screen reveal.
        if self.records:
            oldest = self.records[0][3]
            while self._reveal_queue and self._reveal_queue[0].record[3] < oldest:
                expired = self._reveal_queue.popleft()
                self._remaining_chars -= len(expired.text) - expired.offset
        self._prune_view()
        if not self.following and incoming:
            self.unseen += incoming
            self.follow.setText(f'{self.unseen} 条新日志 · 回到最新')
        immediate = force or has_error or not self.following or not self.isVisible()
        # Normal pace is 250 code points/s; larger backlogs accelerate the reveal.
        # Callbacks stay bounded rather than running one timer per glyph.
        if immediate:
            budget = max(1, self._remaining_chars)
        elif self._remaining_chars > 512:
            budget = min(1024, max(self.CHARS_PER_FRAME, (self._remaining_chars + 23) // 24))
        else:
            budget = self.CHARS_PER_FRAME
        chunks = []
        while self._reveal_queue and budget > 0 and len(chunks) < 1000:
            current = self._reveal_queue[0]
            end = min(len(current.text), current.offset + budget)
            # Do not leave a combining mark, variation selector or joined emoji
            # detached from its base character at a frame boundary.
            while end < len(current.text) and (
                    unicodedata.combining(current.text[end]) or
                    current.text[end] in ('\ufe0e', '\ufe0f', '\u200d') or
                    '\U0001f3fb' <= current.text[end] <= '\U0001f3ff' or
                    (end > 0 and current.text[end - 1] == '\u200d')):
                end += 1
            count = end - current.offset
            chunks.append((current.record, current.text[current.offset:end], current.offset == 0))
            current.offset = end
            budget -= max(1, count)
            self._remaining_chars -= count
            if end == len(current.text):
                self._reveal_queue.popleft()
        if chunks:
            self._write_chunks(chunks)
        if not self.pending and not self._reveal_queue:
            self.timer.stop()

    def flush_all(self):
        while self.pending or self._reveal_queue:
            self.flush(force=True)

    def _insert(self, records):
        self._write_chunks([(record, self._display_text(record[2]), True) for record in records])

    def _write_chunks(self, chunks):
        self._updating = True
        bar = self.view.verticalScrollBar()
        old_scroll = bar.value()
        selection = self.view.textCursor()
        anchor, position = selection.anchor(), selection.position()
        cursor = QTextCursor(self.view.document())
        cursor.movePosition(QTextCursor.End)
        fmt = QTextBlockFormat()
        tabs = self._tabs()
        fmt.setLeftMargin(tabs[-1].position)
        fmt.setTextIndent(-tabs[-1].position)
        fmt.setTabPositions(tabs)
        fmt.setBottomMargin(4)
        mono_format = QTextCharFormat()
        mono_format.setFont(self._metadata_font)
        message_format = QTextCharFormat()
        message_format.setFont(self.view.font())
        cursor.beginEditBlock()
        for record, text, starts_record in chunks:
            if starts_record:
                if not self.view.document().isEmpty():
                    cursor.insertBlock(fmt)
                else:
                    cursor.setBlockFormat(fmt)
                cursor.insertText(f'{record[0]}\t{record[1]}\t', mono_format)
                cursor.block().setUserData(_RecordData(record[3]))
            cursor.insertText(text, message_format)
        cursor.endEditBlock()
        if anchor != position:
            # Inserting at the selection's right edge must not grow the selection.
            selection.setPosition(anchor)
            selection.setPosition(position, QTextCursor.KeepAnchor)
            self.view.setTextCursor(selection)
        if self.following:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(old_scroll)
        self._updating = False

    def _tabs(self):
        metrics = QFontMetricsF(self._metadata_font)
        first = metrics.horizontalAdvance('00:00:00.000') + 16
        second = first + metrics.horizontalAdvance('ERROR') + 16
        tabs = []
        for position in (first, second):
            tab = QTextOption.Tab()
            tab.position = position
            tabs.append(tab)
        return tabs

    def _prune_view(self):
        if not self.records:
            return
        self._updating = True
        oldest = self.records[0][3]
        block = self.view.document().firstBlock()
        while block.isValid() and block.userData() and block.userData().sequence < oldest:
            cursor = QTextCursor(block)
            if block.next().isValid():
                cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor)
            else:
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                block.setUserData(None)
            cursor.removeSelectedText()
            block = self.view.document().firstBlock()
        self._updating = False

    def pause_follow(self):
        self.following = False
        self.follow.setText('回到最新')

    def toggle_follow(self):
        if self.following:
            self.pause_follow()
        else:
            self.following = True
            self.unseen = 0
            self.follow.setText('暂停跟随')
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _scrolled(self, value):
        if not self._updating and value < self.view.verticalScrollBar().maximum():
            self.pause_follow()

    def _selection_changed(self):
        if not self._updating and self.view.textCursor().hasSelection():
            self.pause_follow()

    def _schedule_filter(self):
        self.pause_follow()
        self.filter_timer.start()

    def _refilter(self):
        self.flush_all()
        self.pause_follow()
        self.view.clear()
        self._insert([r for r in self.records if self._matches(r)])

    def filtered_text(self):
        return '\n'.join(self._text(r) for r in self.records if self._matches(r))

    def copy_logs(self):
        self.flush_all()
        selected = self.view.textCursor().selectedText().replace('\u2029', '\n').replace('\u2028', '\n')
        QApplication.clipboard().setText(selected or self.filtered_text())

    def export_view(self):
        self._export(False)

    def export_file(self):
        self._export(True)

    def _export(self, full):
        self.flush_all()
        path, _ = QFileDialog.getSaveFileName(self, '导出日志', 'ComiTrans.log', '文本日志 (*.log *.txt)')
        if not path:
            return
        try:
            if full:
                shutil.copyfile(self.log_path, path)
            else:
                Path(path).write_text(self.filtered_text(), encoding='utf-8')
        except OSError as exc:
            QMessageBox.warning(self, '日志导出失败', str(exc))
        else:
            QMessageBox.information(self, '日志已导出', path)
