"""A non-modal, idle-dismissed repository support prompt."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from ..i18n import tr
from .halftone import draw_tone
from .theme import apply_card_shadow, set_themed_icon, set_themed_pixmap, theme_changed, ui_font

from .motion import fade_in


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
        layout.setContentsMargins(16, 14, 14, 14)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        badge = QFrame()
        badge.setObjectName('starBadge')
        badge.setFixedSize(30, 30)
        badge_layout = QHBoxLayout(badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_icon = QLabel()
        badge_icon.setAlignment(Qt.AlignCenter)
        set_themed_pixmap(badge_icon, 'star', size=16)
        badge_layout.addWidget(badge_icon)
        heading.addWidget(badge, 0, Qt.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        title = QLabel(tr('喜欢这次翻译？'))
        title.setObjectName('starPromptTitle')
        title_col.addWidget(title)
        repo_tag = QLabel('GitHub · ComiTrans')
        repo_tag.setObjectName('starRepoTag')
        repo_tag.setFont(ui_font(11, mono=True))
        repo_tag.setFixedHeight(20)
        title_col.addWidget(repo_tag, 0, Qt.AlignLeft)
        heading.addLayout(title_col, 1)

        self.close_button = QToolButton()
        self.close_button.setObjectName('starCloseBtn')
        self.close_button.setAccessibleName(tr('关闭求 Star 提示'))
        self.close_button.setToolTip(tr('关闭'))
        self.close_button.setProperty('role', 'quiet')
        self.close_button.setFixedSize(26, 26)
        self.close_button.setCursor(Qt.PointingHandCursor)
        set_themed_icon(self.close_button, 'close', size=14)
        self.close_button.clicked.connect(self.dismiss)
        heading.addWidget(self.close_button, 0, Qt.AlignTop)
        layout.addLayout(heading)

        body = QLabel(tr('如果 ComiTrans 帮到了你，欢迎给仓库点个 Star，支持后续更新。'))
        body.setWordWrap(True)
        layout.addWidget(body)

        divider = QFrame()
        divider.setObjectName('hairlineRule')
        layout.addWidget(divider)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.star_button = QPushButton(tr('去 GitHub 点 Star ↗'))
        self.star_button.setProperty('role', 'primary')
        self.star_button.setCursor(Qt.PointingHandCursor)
        self.star_button.setAccessibleName(tr('打开 ComiTrans GitHub 仓库'))
        self.star_button.clicked.connect(self._open_repository)
        actions.addWidget(self.star_button)
        actions.addStretch(1)
        hint = QLabel(tr('8 秒无操作后自动收起'))
        hint.setProperty('muted', True)
        hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        actions.addWidget(hint)
        layout.addLayout(actions)

        apply_card_shadow(self, blur=20, y_offset=4)
        theme_changed.changed.connect(self._on_theme_changed)

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(idle_timeout_ms)
        self._idle_timer.timeout.connect(self.dismiss)
        for widget in (self, *self.findChildren(QWidget)):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        self.hide()

    def _on_theme_changed(self, _mode):
        if not isValid(self):
            return
        apply_card_shadow(self, blur=20, y_offset=4)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 13, 13)
        painter.setClipPath(clip)
        tone_width = min(116.0, self.width() * 0.34)
        painter.setOpacity(0.16)
        draw_tone(painter, QRectF(self.width() - tone_width, 0, tone_width, 54),
                  profile='quiet', direction='right')
        painter.end()

    def show_prompt(self):
        self.reposition()
        self.show()
        fade_in(self, 180)
        self.raise_()
        self._idle_timer.start()

    def reposition(self):
        parent = self.parentWidget()
        margin = 16
        self.setFixedWidth(min(368, max(1, parent.width() - 2 * margin)))
        self.adjustSize()
        self.move(max(margin, parent.width() - self.width() - margin),
                  max(margin, parent.height() - self.height() - margin))

    def dismiss(self):
        self._idle_timer.stop()
        if self.graphicsEffect() is not None:
            self.setGraphicsEffect(None)
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
