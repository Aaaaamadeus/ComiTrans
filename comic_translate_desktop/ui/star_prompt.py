"""A non-modal, idle-dismissed repository support prompt."""
from __future__ import annotations
from ..i18n import tr

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget


REPOSITORY_URL = 'https://github.com/Aaaaamadeus/ComiTrans'
STAR_PROMPT_PROBABILITY = 0.15
STAR_PROMPT_IDLE_MS = 8000


class StarPrompt(QFrame):
    def __init__(self, parent, *, idle_timeout_ms=STAR_PROMPT_IDLE_MS):
        super().__init__(parent)
        self.setObjectName('starPrompt')
        self.setAccessibleName(tr('支持 ComiTrans 仓库'))
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 14, 16)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        title = QLabel(tr('☆ 喜欢这次翻译？'))
        title.setObjectName('starPromptTitle')
        heading.addWidget(title, 1)
        self.close_button = QToolButton()
        self.close_button.setText('×')
        self.close_button.setAccessibleName(tr('关闭求 Star 提示'))
        self.close_button.setToolTip(tr('关闭'))
        self.close_button.setProperty('role', 'quiet')
        self.close_button.clicked.connect(self.dismiss)
        heading.addWidget(self.close_button)
        layout.addLayout(heading)
        body = QLabel(tr('如果 ComiTrans 帮到了你，欢迎给仓库点个 Star，支持后续更新。'))
        body.setWordWrap(True)
        layout.addWidget(body)
        actions = QHBoxLayout()
        self.star_button = QPushButton(tr('去 GitHub 点 Star ↗'))
        self.star_button.setProperty('role', 'primary')
        self.star_button.setAccessibleName(tr('打开 ComiTrans GitHub 仓库'))
        self.star_button.clicked.connect(self._open_repository)
        actions.addWidget(self.star_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        hint = QLabel(tr('8 秒无操作后自动收起'))
        hint.setProperty('muted', True)
        layout.addWidget(hint)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(idle_timeout_ms)
        self._idle_timer.timeout.connect(self.dismiss)
        for widget in (self, *self.findChildren(QWidget)):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        self.hide()

    def show_prompt(self):
        self.reposition()
        self.show()
        self.raise_()
        self._idle_timer.start()

    def reposition(self):
        parent = self.parentWidget()
        margin = 16
        self.setFixedWidth(min(344, max(1, parent.width() - 2 * margin)))
        self.adjustSize()
        self.move(max(margin, parent.width() - self.width() - margin),
                  max(margin, parent.height() - self.height() - margin))

    def dismiss(self):
        self._idle_timer.stop()
        self.hide()

    def _open_repository(self):
        QDesktopServices.openUrl(QUrl(REPOSITORY_URL))
        self.dismiss()

    def eventFilter(self, watched, event):
        if self.isVisible() and event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress,
                                                QEvent.KeyPress, QEvent.Wheel, QEvent.FocusIn):
            self._idle_timer.start()
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        self._idle_timer.stop()
        super().hideEvent(event)
