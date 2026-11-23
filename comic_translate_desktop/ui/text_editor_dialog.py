"""Full-window editor for one bubble's translation, synced live with the inspector."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..i18n import tr
from .theme import ui_font
from .window_chrome import apply_window_chrome


class TextEditorDialog(QDialog):
    text_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('全屏编辑'))
        self.resize(780, 560)
        self.setSizeGripEnabled(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self._title = QLabel(tr('全屏编辑'))
        self._title.setObjectName('sectionTitle')
        header.addWidget(self._title, 1)
        self._stats = QLabel()
        self._stats.setObjectName('badgePill')
        self._stats.setFont(ui_font(12, mono=True))
        header.addWidget(self._stats)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(18)

        source_panel = QWidget()
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(6)
        source_label = QLabel(tr('原文'))
        source_label.setProperty('muted', True)
        self.source = QPlainTextEdit()
        self.source.setObjectName('textSource')
        self.source.setReadOnly(True)
        self.source.setFont(ui_font(15, japanese=True))
        source_layout.addWidget(source_label)
        source_layout.addWidget(self.source, 1)

        target_panel = QWidget()
        target_layout = QVBoxLayout(target_panel)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.setSpacing(6)
        target_header = QHBoxLayout()
        target_label = QLabel(tr('译文'))
        target_label.setProperty('muted', True)
        target_header.addWidget(target_label, 1)
        insert_break = QPushButton(tr('插入换行'))
        insert_break.setProperty('compact', True)
        insert_break.setProperty('role', 'chip')
        insert_break.clicked.connect(self._insert_break)
        target_header.addWidget(insert_break)
        target_layout.addLayout(target_header)
        self.target = QPlainTextEdit()
        self.target.setObjectName('textInput')
        self.target.setFont(ui_font(16))
        self.target.setPlaceholderText(tr('输入译文，按 Enter 手动换行'))
        self.target.textChanged.connect(self._emit_text)
        target_layout.addWidget(self.target, 1)

        body.addWidget(source_panel, 1)
        body.addWidget(target_panel, 2)
        layout.addLayout(body, 1)

        footer = QHBoxLayout()
        hint = QLabel(tr('修改会实时同步到右侧面板；Ctrl+S 保存图片。'))
        hint.setProperty('muted', True)
        hint.setWordWrap(True)
        footer.addWidget(hint, 1)
        close_btn = QPushButton(tr('关闭'))
        close_btn.setProperty('role', 'utility')
        close_btn.clicked.connect(self.close)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

        self._done_shortcut = QShortcut(QKeySequence('Ctrl+Return'), self)
        self._done_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._done_shortcut.activated.connect(self.close)
        self._update_stats()

    def _insert_break(self):
        self.target.insertPlainText('\n')
        self.target.setFocus()

    def _update_stats(self):
        text = self.target.toPlainText()
        lines = text.count('\n') + 1 if text else 0
        self._stats.setText(f'{len(text)} · {lines}')

    def _emit_text(self):
        self._update_stats()
        self.text_changed.emit(self.target.toPlainText())

    def set_block(self, number, source_text, target_text):
        self._title.setText(tr('全屏编辑 · 第 {_0} 块', _0=number))
        self.source.setPlainText(str(source_text or ''))
        if self.target.toPlainText() != str(target_text or ''):
            self.target.blockSignals(True)
            self.target.setPlainText(str(target_text or ''))
            self.target.blockSignals(False)
        self._update_stats()

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self)
        self.target.setFocus()
