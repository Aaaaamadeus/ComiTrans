"""Search a book's saved and current dialogue, with a reviewable replacement."""
from html import escape
import re

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHeaderView, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableView, QVBoxLayout,
)

from ..editor_jobs import LatestJobQueue
from ..i18n import tr
from .window_chrome import apply_window_chrome


class TranscriptModel(QAbstractTableModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows = []
        self.preview = False

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 4 if self.preview else 3

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return (tr('页码与气泡'), tr('原文'), tr('译文'), tr('替换后'))[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        entry, replacement = self.rows[index.row()]
        values = (f'{entry.label}  ·  #{entry.index + 1}', entry.source, entry.translation, replacement)
        text = values[index.column()]
        if role == Qt.ToolTipRole and text:
            return '<qt>' + escape(text).replace('\n', '<br>') + '</qt>'
        return text

    def set_rows(self, rows, *, preview=False):
        self.beginResetModel()
        self.rows, self.preview = rows, preview
        self.endResetModel()


class TranscriptDialog(QDialog):
    def __init__(self, index_book, apply_replacements, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('全书译稿'))
        self.resize(760, 500)
        self._index_book = index_book
        self._apply_replacements = apply_replacements
        self._jobs = LatestJobQueue(self)
        self._entries = []
        self._skipped = 0
        self._busy = False
        self.selection = None

        root = QVBoxLayout(self)
        inputs = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('搜索原文或译文'))
        self.search.setAccessibleName(tr('搜索原文或译文'))
        self.replace = QLineEdit()
        self.replace.setPlaceholderText(tr('替换为（留空即删除）'))
        self.replace.setAccessibleName(tr('替换为（留空即删除）'))
        self.preview_button = QPushButton(tr('预览替换'))
        self.preview_button.clicked.connect(self._preview)
        for widget in (self.search, self.replace, self.preview_button):
            inputs.addWidget(widget)
        root.addLayout(inputs)

        self.model = TranscriptModel(self)
        self.table = QTableView()
        self.table.setObjectName('transcriptTable')
        self.table.setModel(self.model)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(3 * self.table.fontMetrics().lineSpacing() + 10)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._jump)
        self.table.selectionModel().selectionChanged.connect(self._refresh_actions)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.jump_button = QPushButton(tr('定位气泡'))
        self.jump_button.clicked.connect(lambda: self._jump(self.table.currentIndex()))
        self.apply_button = QPushButton(tr('替换并保存'))
        self.apply_button.clicked.connect(self._apply)
        self.close_button = QPushButton(tr('关闭'))
        self.close_button.clicked.connect(self.reject)
        for button in (self.jump_button, self.apply_button, self.close_button):
            button.setAutoDefault(False)
            footer.addWidget(button)
        root.addLayout(footer)
        self.search.textChanged.connect(self._filter)
        self.replace.textChanged.connect(self._filter)
        self._reload()

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self)

    def done(self, result):
        if not self._busy:
            self._jobs.close()
            super().done(result)

    def _reload(self, notice=''):
        self._set_busy(True)
        self.status.setText(tr('正在读取全书译稿…'))
        def loaded(entries):
            self._entries, self._skipped = entries
            self._set_busy(False)
            self._filter()
            if notice:
                self.status.setText(notice)
        def failed(message):
            loaded(([], 0))
            self.status.setText(message)
        self._index_book(self._jobs, loaded, failed)

    def _set_busy(self, busy):
        self._busy = busy
        for widget in (self.search, self.replace, self.table, self.close_button):
            widget.setEnabled(not busy)
        self._refresh_actions()

    def _refresh_actions(self):
        self.jump_button.setEnabled(not self._busy and self.table.currentIndex().isValid())
        self.preview_button.setEnabled(not self._busy and bool(self.search.text().strip()))
        self.apply_button.setEnabled(not self._busy and self.model.preview and bool(self.model.rows))

    def _filter(self):
        query = self.search.text().strip().casefold()
        rows = [(entry, None) for entry in self._entries
                if query in entry.source.casefold() or query in entry.translation.casefold()]
        self.model.set_rows(rows)
        message = tr('显示 {_0} 个气泡', _0=len(rows))
        if self._skipped:
            message += ' · ' + tr('{_0} 页缺少可读译稿', _0=self._skipped)
        self.status.setText(message)
        self._refresh_actions()

    def _preview(self):
        query, replacement = self.search.text().strip(), self.replace.text()
        if not query:
            return
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        rows = [(entry, after) for entry in self._entries if not entry.restored
                and (after := pattern.sub(lambda _: replacement, entry.translation)) != entry.translation]
        self.model.set_rows(rows, preview=True)
        self.status.setText(tr('将修改 {_0} 个气泡（仅匹配译文）', _0=len(rows)))
        self._refresh_actions()

    def _jump(self, index):
        if index.isValid() and not self._busy:
            self.selection = self.model.rows[index.row()][0]
            self.accept()

    def _apply(self):
        rows = list(self.model.rows)
        self._set_busy(True)
        self._apply_replacements(
            rows, self._reload,
            lambda done, total: self.status.setText(tr('正在保存第 {_0}/{_1} 页…', _0=done, _1=total)))
