"""60fps monochrome motion primitives inspired by Google AI Studio & Gemini.

Strictly preserves ComiTrans's Paper White / Night Ink manga palette while
adding responsive Material-style tactile ripples, center-out focus underlines,
gliding navigation/tab indicators, list selection rails, non-blocking overlay
transitions, and monochrome shimmer bars.
"""

from __future__ import annotations

import math

from PySide6.QtCore import (
    QAbstractAnimation,
    QBasicTimer,
    QElapsedTimer,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    QTimer,
    QVariantAnimation,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsOpacityEffect,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QWidget,
)
from shiboken6 import isValid

DURATION_FAST = 140
DURATION_MEDIUM = 210
DURATION_SLOW = 280


EMPHASIZED_DECELERATE = QEasingCurve(QEasingCurve.OutCubic)
STANDARD = QEasingCurve(QEasingCurve.InOutCubic)

_REDUCED_MOTION = False
_MOTION_CONTROLLER = None


def set_reduced_motion(enabled: bool) -> None:
    global _REDUCED_MOTION
    _REDUCED_MOTION = bool(enabled)


def reduced_motion() -> bool:
    return _REDUCED_MOTION


def _theme_color(name: str) -> QColor:
    from .theme import color

    return QColor(color(name))


def _with_alpha(c: QColor, alpha: int) -> QColor:
    out = QColor(c)
    out.setAlpha(max(0, min(255, int(alpha))))
    return out


def _button_is_dark_filled(btn: QAbstractButton) -> bool:
    role = str(btn.property('role') or '')
    if role == 'primary':
        return True
    if btn.isCheckable() and btn.isChecked() and role in ('toggle', 'pill', 'mode', 'segment'):
        return True
    pal_l = btn.palette().color(QPalette.Button).lightness()
    ink_l = _theme_color('ink').lightness()
    paper_l = _theme_color('paper').lightness()
    # Dark button in light mode or bright button in dark mode
    return abs(pal_l - ink_l) < abs(pal_l - paper_l) and abs(ink_l - paper_l) > 60


def _stop_existing_fade(widget: QWidget) -> None:
    anim = getattr(widget, '_motion_fade_anim', None)
    if anim is not None and isValid(anim):
        anim.stop()
    widget._motion_fade_anim = None


def fade_in(widget: QWidget | None, duration: int = 180) -> QPropertyAnimation | None:
    """Fade widget cleanly to full opacity and strip the temporary effect afterward."""
    if widget is None or not isValid(widget):
        return None
    gen = getattr(widget, '_motion_fade_gen', 0) + 1
    widget._motion_fade_gen = gen
    _stop_existing_fade(widget)

    if _REDUCED_MOTION or duration <= 0:
        if widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)
        return None

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b'opacity', widget)
    anim.setDuration(max(50, int(duration)))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(EMPHASIZED_DECELERATE)

    def _finish() -> None:
        if not isValid(widget):
            return
        if getattr(widget, '_motion_fade_gen', 0) != gen:
            return
        if isValid(effect) and widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
        widget._motion_fade_anim = None

    anim.finished.connect(_finish)
    widget._motion_fade_anim = anim
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    return anim


def fade_out(
    widget: QWidget | None,
    duration: int = 130,
    *,
    hide_on_finish: bool = True,
    on_finished=None,
) -> QPropertyAnimation | None:
    """Fade a widget out smoothly without blocking subsequent immediate shows."""
    if widget is None or not isValid(widget):
        return None
    gen = getattr(widget, '_motion_fade_gen', 0) + 1
    widget._motion_fade_gen = gen
    _stop_existing_fade(widget)

    if _REDUCED_MOTION or duration <= 0 or not widget.isVisible():
        if widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)
        if hide_on_finish:
            widget.hide()
        if callable(on_finished):
            on_finished()
        return None

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b'opacity', widget)
    anim.setDuration(max(50, int(duration)))
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(STANDARD)

    def _finish() -> None:
        if not isValid(widget):
            return
        if getattr(widget, '_motion_fade_gen', 0) != gen:
            return
        if isValid(effect) and widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
        if hide_on_finish:
            widget.hide()
        widget._motion_fade_anim = None
        if callable(on_finished):
            on_finished()

    anim.finished.connect(_finish)
    widget._motion_fade_anim = anim
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    return anim


def set_pulse(widget: QWidget | None, active: bool, duration: int = 1200) -> None:
    """Gentle monochrome breathing pulse on a small indicator widget."""
    if widget is None or not isValid(widget):
        return
    existing = getattr(widget, '_motion_pulse_anim', None)
    if existing is not None and isValid(existing):
        existing.stop()
    widget._motion_pulse_anim = None

    if not active or _REDUCED_MOTION:
        if widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)
        return

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)

    anim = QPropertyAnimation(effect, b'opacity', widget)
    anim.setDuration(max(400, int(duration)))
    anim.setStartValue(1.0)
    anim.setKeyValueAt(0.5, 0.42)
    anim.setEndValue(1.0)
    anim.setEasingCurve(STANDARD)
    anim.setLoopCount(-1)
    widget._motion_pulse_anim = anim
    anim.start(QAbstractAnimation.DeleteWhenStopped)


# ---------------------------------------------------------------------------
# 1. Button Hover State Layer + Ink-Wash Radial Ripple
# ---------------------------------------------------------------------------

class _RippleOverlay(QWidget):
    """Translucent 60fps monochrome hover veil & cursor-centered ink ripple."""

    _MAX_RIPPLES = 4
    _EXPAND_MS = 280.0
    _FADE_MS = 240.0

    def __init__(self, target: QAbstractButton) -> None:
        # Qt may dispatch paint while the native widget is being constructed.
        # Establish the idle paint state before any QWidget calls can re-enter us.
        self._target = target
        self._hover_alpha = 0.0
        self._hover_target = 0.0
        self._last_ms = 0.0
        self._ripples: list[dict] = []

        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(target.rect())

        self._clock = QElapsedTimer()
        self._clock.start()

        # Deliver frames to the widget itself, including inside modal dialogs.
        self._timer = QBasicTimer()
        self.show()

    def set_hovered(self, hovered: bool) -> None:
        if _REDUCED_MOTION:
            self._hover_target = 1.0 if hovered else 0.0
            self._hover_alpha = self._hover_target
            self.update()
            return
        self._hover_target = 1.0 if hovered else 0.0
        self._ensure_running()

    def trigger_ripple(self, pos: QPointF) -> None:
        if _REDUCED_MOTION or not isValid(self._target):
            return
        w = max(1, self._target.width())
        h = max(1, self._target.height())
        max_r = max(
            math.hypot(pos.x(), pos.y()),
            math.hypot(w - pos.x(), pos.y()),
            math.hypot(pos.x(), h - pos.y()),
            math.hypot(w - pos.x(), h - pos.y()),
        )
        now = float(self._clock.elapsed())
        self._ripples.append(
            {
                'pos': QPointF(pos),
                'max_r': max_r * 1.08,
                'start_ms': now,
                'release_ms': None,
            }
        )
        if len(self._ripples) > self._MAX_RIPPLES:
            self._ripples = self._ripples[-self._MAX_RIPPLES :]
        self._ensure_running()

    def release_ripples(self) -> None:
        if not self._ripples:
            return
        now = float(self._clock.elapsed())
        for rp in self._ripples:
            if rp['release_ms'] is None:
                rp['release_ms'] = now
        self._ensure_running()

    def _ensure_running(self) -> None:
        self._last_ms = float(self._clock.elapsed())
        if not self._timer.isActive():
            self._timer.start(16, self)

    def hideEvent(self, event) -> None:
        timer = getattr(self, '_timer', None)
        if timer is not None:
            timer.stop()
            self._ripples.clear()
            self._hover_alpha = self._hover_target = 0.0
        super().hideEvent(event)

    def timerEvent(self, event) -> None:
        timer = getattr(self, '_timer', None)
        if timer is None or event.timerId() != timer.timerId():
            super().timerEvent(event)
            return
        if not isValid(self._target):
            self._timer.stop()
            return
        now = float(self._clock.elapsed())
        dt = max(1.0, min(48.0, now - self._last_ms))
        self._last_ms = now

        # Hover spring settle (~110ms)
        if abs(self._hover_alpha - self._hover_target) > 0.005:
            rate = 1.0 - math.exp(-dt / 42.0)
            self._hover_alpha += (self._hover_target - self._hover_alpha) * rate
        else:
            self._hover_alpha = self._hover_target

        alive: list[dict] = []
        for rp in self._ripples:
            age = now - rp['start_ms']
            rel = rp['release_ms']
            if rel is not None and (now - rel) >= self._FADE_MS and age >= self._EXPAND_MS * 0.65:
                continue
            if age > 2400.0:
                continue
            alive.append(rp)
        self._ripples = alive

        if not self._ripples and abs(self._hover_alpha - self._hover_target) <= 0.005:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        # Qt can request paint before the Python animation state is available.
        if getattr(self, '_timer', None) is None:
            return
        if not isValid(self._target) or (self._hover_alpha <= 0.004 and not self._ripples):
            return
        r = QRectF(self.rect())
        if r.width() <= 2 or r.height() <= 2:
            return

        dark_fill = _button_is_dark_filled(self._target)
        base = _theme_color('paper' if dark_fill else 'ink')
        role = str(self._target.property('role') or '')

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        radius = 8.0
        if role in ('pill', 'toggle'):
            radius = min(r.height() / 2.0, 14.0)
        elif role == 'nav':
            radius = 4.0

        clip = QPainterPath()
        clip.addRoundedRect(r, radius, radius)
        p.setClipPath(clip)

        # Hover state veil (Material 3 surface tint, strictly monochrome)
        if self._hover_alpha > 0.004:
            max_veil = 24 if dark_fill else (10 if role == 'nav' else 14)
            p.fillRect(r, _with_alpha(base, int(round(max_veil * self._hover_alpha))))

        # Ink-wash ripples
        now = float(self._clock.elapsed())
        for rp in self._ripples:
            age = max(0.0, now - rp['start_ms'])
            t = min(1.0, age / self._EXPAND_MS)
            eased_r = 1.0 - (1.0 - t) ** 3
            rad = max(2.0, rp['max_r'] * eased_r)

            fade = 1.0
            if rp['release_ms'] is not None:
                fade_t = min(1.0, max(0.0, (now - rp['release_ms']) / self._FADE_MS))
                fade = 1.0 - fade_t * fade_t
            peak_alpha = 46 if dark_fill else 28
            alpha = int(round(peak_alpha * fade * (0.65 + 0.35 * (1.0 - t))))
            if alpha <= 0:
                continue

            pt = rp['pos']
            grad = QRadialGradient(pt, rad)
            grad.setColorAt(0.0, _with_alpha(base, alpha))
            grad.setColorAt(0.72, _with_alpha(base, int(alpha * 0.55)))
            grad.setColorAt(1.0, _with_alpha(base, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawEllipse(pt, rad, rad)
        p.end()


# ---------------------------------------------------------------------------
# 2. Text / Combo / Spin Center-Out Focus Underline
# ---------------------------------------------------------------------------

class _FocusLineOverlay(QWidget):
    """Draws Google AI Studio center-out expanding monochrome focus underline."""

    def __init__(self, target: QWidget) -> None:
        # Keep early native paint callbacks safe, as with the ripple overlay.
        self._target = target
        self._progress = 0.0
        self._target_progress = 0.0
        self._last_ms = 0.0

        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(target.rect())

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)
        self.show()

    def set_focused(self, focused: bool) -> None:
        self._target_progress = 1.0 if focused else 0.0
        if _REDUCED_MOTION:
            self._progress = self._target_progress
            self._timer.stop()
            self.update()
            return
        self._last_ms = float(self._clock.elapsed())
        if not self._timer.isActive():
            self._timer.start()

    def _step(self) -> None:
        if not isValid(self) or not isValid(self._target):
            self._timer.stop()
            return
        now = float(self._clock.elapsed())
        dt = max(1.0, min(48.0, now - self._last_ms))
        self._last_ms = now

        duration = 175.0 if self._target_progress > self._progress else 130.0
        step = dt / duration
        if self._target_progress > self._progress:
            self._progress = min(1.0, self._progress + step)
        else:
            self._progress = max(0.0, self._progress - step)

        if abs(self._progress - self._target_progress) <= 0.004:
            self._progress = self._target_progress
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        if getattr(self, '_timer', None) is None:
            return
        if self._progress <= 0.004 or not isValid(self._target):
            return
        r = QRectF(self.rect())
        if r.width() <= 6 or r.height() <= 6:
            return
        # OutCubic curve for snappy AI Studio expand
        t = self._progress
        eased = 1.0 - (1.0 - t) ** 3

        usable_w = max(0.0, r.width() - 6.0)
        span = usable_w * eased
        if span <= 1.0:
            return
        cx = r.center().x()
        x0 = cx - span * 0.5
        y = r.bottom() - 2.0

        ink = _theme_color('ink')
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(_with_alpha(ink, int(round(235 * min(1.0, eased * 1.15)))))
        p.drawRoundedRect(QRectF(x0, y, span, 2.0), 1.0, 1.0)
        p.end()


# ---------------------------------------------------------------------------
# 3. Application-Wide Material Motion Event Filter
# ---------------------------------------------------------------------------

class _MangaComboItemDelegate(QStyledItemDelegate):
    """Monochrome Paper White / Night Ink pill item renderer for combo popups."""

    def sizeHint(self, option, index) -> QSize:
        base = super().sizeHint(option, index)
        return QSize(max(base.width() + 24, 72), max(30, base.height() + 10))

    def paint(self, painter: QPainter, option, index) -> None:
        rect = QRectF(option.rect)
        if rect.width() <= 4 or rect.height() <= 4:
            return
        pill = rect.adjusted(2.0, 1.0, -2.0, -1.0)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        enabled = bool(option.state & QStyle.State_Enabled)

        ink = _theme_color('ink')
        paper = _theme_color('paper')
        muted = _theme_color('muted')
        disabled = _theme_color('disabled')

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(ink)
            painter.drawRoundedRect(pill, 6.0, 6.0)
            bar_h = min(12.0, max(6.0, pill.height() * 0.44))
            painter.setBrush(paper)
            painter.drawRoundedRect(
                QRectF(pill.left() + 5.0, pill.center().y() - bar_h * 0.5, 2.5, bar_h),
                1.25,
                1.25,
            )
            fg = paper
        elif hovered and enabled:
            painter.setPen(Qt.NoPen)
            painter.setBrush(muted)
            painter.drawRoundedRect(pill, 6.0, 6.0)
            fg = ink
        else:
            fg = ink if enabled else disabled

        text = str(index.data(Qt.DisplayRole) or '')
        font = QFont(option.font)
        if selected:
            font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(fg)
        text_rect = pill.adjusted(12.0, 0.0, -10.0, 0.0)
        view = getattr(option, 'widget', None)
        wrap = bool(hasattr(view, 'wordWrap') and view.wordWrap())
        if wrap:
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, text)
        else:
            elided = QFontMetrics(font).elidedText(text, Qt.ElideRight, int(max(12.0, text_rect.width())))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft | Qt.TextSingleLine, elided)
        painter.restore()


class _MaterialMotionController(QObject):
    """Hooks buttons, inputs & combo popups lazily with zero form boilerplate."""

    _INPUT_TYPES = (QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit)

    def _polish_combo(self, combo: QComboBox) -> None:
        if not isValid(combo) or getattr(combo, '_motion_combo_polished', False):
            return
        combo._motion_combo_polished = True
        views: list[QAbstractItemView] = []
        view = combo.view()
        if view is not None and isValid(view):
            views.append(view)
        if combo.isEditable() and combo.completer() is not None:
            comp_popup = combo.completer().popup()
            if isinstance(comp_popup, QAbstractItemView) and isValid(comp_popup) and comp_popup not in views:
                views.append(comp_popup)

        for v in views:
            if not isinstance(v.itemDelegate(), _MangaComboItemDelegate):
                v.setItemDelegate(_MangaComboItemDelegate(v))
            v.setMouseTracking(True)
            popup = v.window()
            if popup is not None and isValid(popup) and popup is not combo.window():
                if not popup.isVisible():
                    popup.setWindowFlags(popup.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
                    popup.setAttribute(Qt.WA_TranslucentBackground, True)
                    if isinstance(popup, QFrame):
                        popup.setFrameShape(QFrame.NoFrame)
                    popup.setStyleSheet('QComboBoxPrivateContainer { background: transparent; border: none; }')
                popup._motion_combo_popup = True
                popup._motion_combo_owner = combo

    def _stop_popup_anims(self, popup: QWidget) -> None:
        for attr in ('_motion_popup_op_anim', '_motion_popup_pos_anim'):
            anim = getattr(popup, attr, None)
            if anim is not None and isValid(anim):
                anim.stop()
            setattr(popup, attr, None)

    def _animate_combo_popup(self, popup: QWidget) -> None:
        if not isValid(popup):
            return
        self._stop_popup_anims(popup)
        target_pos = popup.pos()
        owner = getattr(popup, '_motion_combo_owner', None)
        opening_above = bool(
            owner is not None and isValid(owner) and target_pos.y() < owner.mapToGlobal(QPoint(0, 0)).y()
        )
        gap = -4 if opening_above else 4
        final_pos = QPoint(target_pos.x(), max(0, target_pos.y() + gap))
        if _REDUCED_MOTION:
            popup.move(final_pos)
            popup.setWindowOpacity(1.0)
            return
        dy = 6 if opening_above else -6
        start_pos = QPoint(final_pos.x(), max(0, final_pos.y() + dy))
        popup.move(start_pos)
        popup.setWindowOpacity(0.0)

        op_anim = QPropertyAnimation(popup, b'windowOpacity', popup)
        op_anim.setDuration(130)
        op_anim.setStartValue(0.0)
        op_anim.setEndValue(1.0)
        op_anim.setEasingCurve(QEasingCurve.OutCubic)

        pos_anim = QPropertyAnimation(popup, b'pos', popup)
        pos_anim.setDuration(145)
        pos_anim.setStartValue(start_pos)
        pos_anim.setEndValue(final_pos)
        pos_anim.setEasingCurve(EMPHASIZED_DECELERATE)

        popup._motion_popup_op_anim = op_anim
        popup._motion_popup_pos_anim = pos_anim
        op_anim.start(QAbstractAnimation.DeleteWhenStopped)
        pos_anim.start(QAbstractAnimation.DeleteWhenStopped)

    def _overlay_for_button(self, btn: QAbstractButton, create: bool = True) -> _RippleOverlay | None:
        if not isValid(btn) or btn.property('noRipple') is True:
            return None
        # Skip internal QScrollBar/QTabBar tiny sub-buttons
        if btn.objectName().startswith('qt_') or btn.width() < 12 or btn.height() < 12:
            return None
        ov = getattr(btn, '_motion_ripple_overlay', None)
        if ov is not None and isValid(ov):
            if ov.geometry() != btn.rect():
                ov.setGeometry(btn.rect())
            return ov
        if not create:
            return None
        ov = _RippleOverlay(btn)
        btn._motion_ripple_overlay = ov
        return ov

    def _overlay_for_input(self, inp: QWidget, create: bool = True) -> _FocusLineOverlay | None:
        if not isValid(inp) or inp.property('noFocusLine') is True:
            return None
        if isinstance(inp, (QPlainTextEdit, QTextEdit)) and inp.isReadOnly():
            return None
        # Avoid duplicate underline on embedded QComboBox/SpinBox inner QLineEdit
        if isinstance(inp, QLineEdit) and isinstance(inp.parentWidget(), (QComboBox, QSpinBox, QDoubleSpinBox)):
            return None
        ov = getattr(inp, '_motion_focus_overlay', None)
        if ov is not None and isValid(ov):
            if ov.geometry() != inp.rect():
                ov.setGeometry(inp.rect())
            return ov
        if not create:
            return None
        ov = _FocusLineOverlay(inp)
        inp._motion_focus_overlay = ov
        return ov

    def eventFilter(self, watched: QObject | None, event: QEvent) -> bool:
        if watched is None or not isValid(watched):
            return False
        etype = event.type()

        if isinstance(watched, QComboBox):
            if not getattr(watched, '_motion_combo_polished', False) and etype in (
                QEvent.Show,
                QEvent.Enter,
                QEvent.MouseButtonPress,
                QEvent.FocusIn,
                QEvent.Paint,
            ):
                self._polish_combo(watched)
        elif isinstance(watched, QWidget) and (
            getattr(watched, '_motion_combo_popup', False)
            or watched.metaObject().className() == 'QComboBoxPrivateContainer'
        ):
            if etype == QEvent.Show:
                self._animate_combo_popup(watched)
            elif etype == QEvent.Hide:
                self._stop_popup_anims(watched)
                watched.setWindowOpacity(1.0)
        elif isinstance(watched, QAbstractButton):
            if etype == QEvent.Enter:
                if watched.isEnabled():
                    ov = self._overlay_for_button(watched, create=True)
                    if ov is not None:
                        ov.set_hovered(True)
            elif etype == QEvent.Leave:
                ov = self._overlay_for_button(watched, create=False)
                if ov is not None:
                    ov.set_hovered(False)
                    ov.release_ripples()
            elif etype == QEvent.MouseButtonPress:
                if watched.isEnabled():
                    ov = self._overlay_for_button(watched, create=True)
                    if ov is not None:
                        ov.trigger_ripple(QPointF(event.position()))
            elif etype == QEvent.MouseButtonRelease:
                ov = self._overlay_for_button(watched, create=False)
                if ov is not None:
                    ov.release_ripples()
            elif etype == QEvent.Resize:
                ov = self._overlay_for_button(watched, create=False)
                if ov is not None:
                    ov.setGeometry(watched.rect())

        elif isinstance(watched, self._INPUT_TYPES):
            if etype == QEvent.FocusIn:
                if watched.isEnabled():
                    ov = self._overlay_for_input(watched, create=True)
                    if ov is not None:
                        ov.set_focused(True)
            elif etype == QEvent.FocusOut:
                ov = self._overlay_for_input(watched, create=False)
                if ov is not None:
                    ov.set_focused(False)
            elif etype == QEvent.Resize:
                ov = self._overlay_for_input(watched, create=False)
                if ov is not None:
                    ov.setGeometry(watched.rect())

        return False


def install_material_motion(app: QApplication | None) -> _MaterialMotionController | None:
    """Install application-wide monochrome ripple & focus-line controller once."""
    global _MOTION_CONTROLLER
    if app is None or not isValid(app):
        return None
    if _MOTION_CONTROLLER is not None and isValid(_MOTION_CONTROLLER) and _MOTION_CONTROLLER.parent() is app:
        return _MOTION_CONTROLLER
    _MOTION_CONTROLLER = _MaterialMotionController(app)
    app.installEventFilter(_MOTION_CONTROLLER)
    return _MOTION_CONTROLLER


# ---------------------------------------------------------------------------
# 4. Gliding Ink Underlines for Top Nav & Tab Bars
# ---------------------------------------------------------------------------

class SlidingNavUnderline(QWidget):
    """Gliding 2px monochrome ink underline beneath checkable navigation buttons."""

    def __init__(self, parent: QWidget, buttons: list[QAbstractButton]) -> None:
        super().__init__(parent)
        self._buttons = [b for b in buttons if b is not None]
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(parent.rect())

        self._cur_x = 0.0
        self._cur_w = 0.0
        self._start_x = 0.0
        self._start_w = 0.0
        self._target_x = 0.0
        self._target_w = 0.0
        self._t = 1.0
        self._initialized = False
        self._active_btn: QAbstractButton | None = next((b for b in self._buttons if b.isChecked()), None)

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)

        parent.installEventFilter(self)
        for btn in self._buttons:
            btn.setProperty('animatedIndicator', 'true')
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.toggled.connect(lambda checked, b=btn: self._on_button_toggled(b, checked))
            btn.installEventFilter(self)

        self.show()
        self.raise_()
        self.sync_immediately()

    def _active_rect(self) -> QRect | None:
        parent = self.parentWidget()
        if parent is None or not isValid(parent):
            return None
        btn = self._active_btn
        if btn is not None and isValid(btn) and btn.isChecked():
            tl = btn.mapTo(parent, btn.rect().topLeft())
            return QRect(tl, btn.size())
        for b in self._buttons:
            if isValid(b) and b.isChecked():
                self._active_btn = b
                tl = b.mapTo(parent, b.rect().topLeft())
                return QRect(tl, b.size())
        self._active_btn = None
        return None

    def sync_immediately(self) -> None:
        parent = self.parentWidget()
        if parent is not None and isValid(parent):
            self.setGeometry(parent.rect())
        r = self._active_rect()
        if r is None or r.width() <= 0:
            self.update()
            return
        self._cur_x = float(r.x())
        self._cur_w = float(r.width())
        self._start_x = self._cur_x
        self._start_w = self._cur_w
        self._target_x = self._cur_x
        self._target_w = self._cur_w
        self._t = 1.0
        self._initialized = True
        self._timer.stop()
        self.update()

    def _on_button_toggled(self, btn: QAbstractButton, checked: bool) -> None:
        if checked:
            self._active_btn = btn
            self._animate_to_active()
            return
        if self._active_btn is btn:
            self._active_btn = next((b for b in self._buttons if isValid(b) and b.isChecked()), None)
            if self._active_btn is None:
                self._timer.stop()
                self.update()
            else:
                self._animate_to_active()

    def _animate_to_active(self) -> None:
        r = self._active_rect()
        if r is None or r.width() <= 0:
            return
        if _REDUCED_MOTION or not self._initialized or not self.isVisible():
            self.sync_immediately()
            return
        self._start_x = self._cur_x
        self._start_w = self._cur_w
        self._target_x = float(r.x())
        self._target_w = float(r.width())
        if abs(self._target_x - self._cur_x) < 0.5 and abs(self._target_w - self._cur_w) < 0.5:
            return
        self._t = 0.0
        self._clock.restart()
        if not self._timer.isActive():
            self._timer.start()

    def eventFilter(self, watched: QObject | None, event: QEvent) -> bool:
        if watched is None or not isValid(watched):
            return False
        etype = event.type()
        if etype in (QEvent.Resize, QEvent.Move, QEvent.LayoutRequest):
            parent = self.parentWidget()
            if parent is not None and isValid(parent) and self.geometry() != parent.rect():
                self.setGeometry(parent.rect())
            if not self._timer.isActive():
                self.sync_immediately()
        elif etype == QEvent.Show and watched is self.parentWidget():
            self.sync_immediately()
        return False

    def _step(self) -> None:
        if not isValid(self):
            self._timer.stop()
            return
        elapsed = float(self._clock.elapsed())
        raw = min(1.0, elapsed / 165.0)
        # Smooth cubic decelerate
        eased = 1.0 - (1.0 - raw) ** 3
        self._t = raw
        self._cur_x = self._start_x + (self._target_x - self._start_x) * eased
        self._cur_w = self._start_w + (self._target_w - self._start_w) * eased
        if raw >= 1.0:
            self._cur_x = self._target_x
            self._cur_w = self._target_w
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        r = self._active_rect()
        if r is None or self._cur_w <= 1.0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(_theme_color('ink'))
        y = float(r.bottom()) - 1.5
        p.drawRoundedRect(QRectF(self._cur_x + 2.0, y, max(4.0, self._cur_w - 4.0), 2.0), 1.0, 1.0)
        p.end()


class _SlidingTabIndicator(QWidget):
    """Gliding 2px monochrome ink underline inside a QTabBar."""

    def __init__(self, tab_bar: QTabBar) -> None:
        super().__init__(tab_bar)
        self._bar = tab_bar
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(tab_bar.rect())

        self._cur_x = 0.0
        self._cur_w = 0.0
        self._start_x = 0.0
        self._start_w = 0.0
        self._target_x = 0.0
        self._target_w = 0.0
        self._initialized = False

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)

        tab_bar.setProperty('animatedIndicator', 'true')
        tab_bar.style().unpolish(tab_bar)
        tab_bar.style().polish(tab_bar)
        tab_bar.currentChanged.connect(self._on_current_changed)
        tab_bar.tabMoved.connect(lambda *_: self.sync_immediately())
        tab_bar.installEventFilter(self)

        self.show()
        self.raise_()
        self.sync_immediately()

    def sync_immediately(self) -> None:
        if not isValid(self._bar):
            return
        self.setGeometry(self._bar.rect())
        idx = self._bar.currentIndex()
        if idx < 0:
            return
        rect = self._bar.tabRect(idx)
        if rect.width() <= 0:
            return
        self._cur_x = float(rect.x())
        self._cur_w = float(rect.width())
        self._start_x = self._cur_x
        self._start_w = self._cur_w
        self._target_x = self._cur_x
        self._target_w = self._cur_w
        self._initialized = True
        self._timer.stop()
        self.update()

    def _on_current_changed(self, idx: int) -> None:
        if not isValid(self._bar) or idx < 0:
            return
        rect = self._bar.tabRect(idx)
        if rect.width() <= 0:
            return
        if _REDUCED_MOTION or not self._initialized or not self._bar.isVisible():
            self.sync_immediately()
            return
        self._start_x = self._cur_x
        self._start_w = self._cur_w
        self._target_x = float(rect.x())
        self._target_w = float(rect.width())
        if abs(self._target_x - self._cur_x) < 0.5 and abs(self._target_w - self._cur_w) < 0.5:
            return
        self._clock.restart()
        if not self._timer.isActive():
            self._timer.start()

    def eventFilter(self, watched: QObject | None, event: QEvent) -> bool:
        if watched is None or not isValid(watched) or not isValid(self._bar):
            return False
        etype = event.type()
        if etype in (QEvent.Resize, QEvent.LayoutRequest, QEvent.Show):
            self.setGeometry(self._bar.rect())
            if not self._timer.isActive():
                self.sync_immediately()
        return False

    def _step(self) -> None:
        if not isValid(self) or not isValid(self._bar):
            self._timer.stop()
            return
        raw = min(1.0, float(self._clock.elapsed()) / 165.0)
        eased = 1.0 - (1.0 - raw) ** 3
        self._cur_x = self._start_x + (self._target_x - self._start_x) * eased
        self._cur_w = self._start_w + (self._target_w - self._start_w) * eased
        if raw >= 1.0:
            self._cur_x = self._target_x
            self._cur_w = self._target_w
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        if not isValid(self._bar) or self._bar.currentIndex() < 0 or self._cur_w <= 1.0:
            return
        rect = self._bar.tabRect(self._bar.currentIndex())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(_theme_color('ink'))
        y = float(rect.bottom()) - 1.5
        p.drawRoundedRect(QRectF(self._cur_x + 2.0, y, max(4.0, self._cur_w - 4.0), 2.0), 1.0, 1.0)
        p.end()


def install_tab_motion(
    tab_target: QTabWidget | QTabBar | None,
    *,
    animate_pages: bool = True,
) -> _SlidingTabIndicator | None:
    """Attach a smooth 60fps gliding ink indicator to a QTabWidget or QTabBar."""
    if tab_target is None or not isValid(tab_target):
        return None
    if animate_pages and isinstance(tab_target, QTabWidget):
        stack = tab_target.findChild(QStackedWidget)
        if stack is not None:
            install_stack_motion(stack)
    bar = tab_target.tabBar() if isinstance(tab_target, QTabWidget) else tab_target
    if bar is None or not isValid(bar):
        return None
    existing = getattr(bar, '_motion_tab_indicator', None)
    if existing is not None and isValid(existing):
        return existing
    indicator = _SlidingTabIndicator(bar)
    bar._motion_tab_indicator = indicator
    return indicator


# ---------------------------------------------------------------------------
# 5. Non-Blocking Drawer & Page Transition Overlays
# ---------------------------------------------------------------------------

def _cancel_widget_transition_overlay(widget: QWidget) -> None:
    ov = getattr(widget, '_motion_transition_overlay', None)
    if ov is not None and isValid(ov):
        timer = getattr(ov, '_timer', None)
        if timer is not None and isValid(timer):
            timer.stop()
        ov.hide()
        ov.deleteLater()
    widget._motion_transition_overlay = None


def _overlay_host(widget: QWidget) -> QWidget | None:
    """Return nearest ancestor that is safe to parent overlays onto (never QSplitter)."""
    host = widget.parentWidget()
    while host is not None and isValid(host) and isinstance(host, (QSplitter, QStackedWidget)):
        host = host.parentWidget()
    if host is None or not isValid(host):
        return None
    return host


def _sync_splitter_layout(widget: QWidget) -> None:
    """Force QSplitter/layout settlement so a newly-shown drawer has final size immediately."""
    parent = widget.parentWidget()
    if parent is not None and isValid(parent):
        QApplication.sendPostedEvents(parent, QEvent.LayoutRequest)
        if parent.layout() is not None:
            parent.layout().activate()
    if widget.layout() is not None:
        widget.layout().activate()


def _infer_edge(edge: str | None, dx: float, dy: float) -> str:
    if edge in ('left', 'right', 'top', 'bottom'):
        return edge
    if abs(dx) >= abs(dy):
        return 'right' if dx > 0 else 'left'
    return 'bottom' if dy > 0 else 'top'


class _DrawerSlideOverlay(QWidget):
    """Clipped physical edge-slide transition rendered safely above QSplitter/layouts."""

    def __init__(
        self,
        host: QWidget,
        rect: QRect,
        pixmap: QPixmap,
        *,
        edge: str,
        reveal: bool,
        duration: int,
        target_widget: QWidget | None = None,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._widget = target_widget
        self._pixmap = pixmap
        self._edge = edge
        self._reveal = reveal
        self._duration = float(max(60, duration))
        self._progress = 0.0

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(rect)

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)

        host.installEventFilter(self)
        if target_widget is not None and isValid(target_widget):
            target_widget.installEventFilter(self)

        self.show()
        self.raise_()
        self._timer.start()

    def _finish(self) -> None:
        self._timer.stop()
        if self._widget is not None and isValid(self._widget):
            if getattr(self._widget, '_motion_transition_overlay', None) is self:
                self._widget._motion_transition_overlay = None
        if isValid(self):
            self.hide()
            self.deleteLater()

    def eventFilter(self, watched: QObject | None, event: QEvent) -> bool:
        if watched is None or not isValid(watched) or not isValid(self):
            return False
        etype = event.type()
        if watched is self._host and etype in (QEvent.Resize, QEvent.Hide):
            self._finish()
        elif self._widget is not None and watched is self._widget:
            if etype in (QEvent.Hide, QEvent.Destroy):
                self._finish()
            elif etype in (QEvent.Resize, QEvent.Move) and isValid(self._host):
                self.setGeometry(QRect(self._widget.mapTo(self._host, QPoint(0, 0)), self._widget.size()))
        return False

    def _step(self) -> None:
        if not isValid(self) or not isValid(self._host) or not self._host.isVisible():
            self._finish()
            return
        if self._reveal and (self._widget is None or not isValid(self._widget) or not self._widget.isVisible()):
            self._finish()
            return
        raw = min(1.0, float(self._clock.elapsed()) / self._duration)
        self._progress = raw
        if raw >= 1.0:
            self._finish()
            return
        self.update()

    def paintEvent(self, event) -> None:
        if self._pixmap.isNull():
            return
        eased = 1.0 - (1.0 - self._progress) ** 3
        factor = (1.0 - eased) if self._reveal else eased
        w = float(self.width())
        h = float(self.height())
        if self._edge == 'left':
            ox, oy = -w * factor, 0.0
        elif self._edge == 'right':
            ox, oy = w * factor, 0.0
        elif self._edge == 'top':
            ox, oy = 0.0, -h * factor
        else:
            ox, oy = 0.0, h * factor

        p = QPainter(self)
        p.setClipRect(self.rect())
        if self._reveal:
            # Cover static widget beneath cleanly while sliding new panel into its clipped slot
            p.fillRect(self.rect(), _theme_color('paper'))
            p.setOpacity(1.0)
        else:
            alpha = 1.0 if eased <= 0.65 else max(0.0, (1.0 - eased) / 0.35)
            p.setOpacity(alpha)
        p.drawPixmap(QPointF(ox, oy), self._pixmap)
        p.end()


def play_slide_overlay(
    widget: QWidget | None,
    dx: float = 0.0,
    dy: float = 0.0,
    duration: int = 165,
    *,
    edge: str | None = None,
) -> None:
    """Capture widget BEFORE synchronously hiding it, then slide cleanly into its bezel."""
    if widget is None or not isValid(widget):
        return
    _cancel_widget_transition_overlay(widget)
    if _REDUCED_MOTION:
        return
    host = _overlay_host(widget)
    if host is None or not isValid(host) or not widget.isVisible():
        return
    if widget.width() <= 2 or widget.height() <= 2:
        return
    rect = QRect(widget.mapTo(host, QPoint(0, 0)), widget.size())
    pix = widget.grab()
    if pix.isNull():
        return
    ov = _DrawerSlideOverlay(
        host,
        rect,
        pix,
        edge=_infer_edge(edge, dx, dy),
        reveal=False,
        duration=duration,
        target_widget=None,
    )
    widget._motion_transition_overlay = ov


def play_reveal_overlay(
    widget: QWidget | None,
    dx: float = 0.0,
    dy: float = 0.0,
    duration: int = 190,
    *,
    edge: str | None = None,
) -> None:
    """Slide a newly-shown widget cleanly out from its clipped edge without delaying visibility."""
    if widget is None or not isValid(widget):
        return
    _cancel_widget_transition_overlay(widget)
    if _REDUCED_MOTION:
        return
    host = _overlay_host(widget)
    if host is None or not isValid(host) or not widget.isVisible():
        return
    _sync_splitter_layout(widget)
    if widget.width() <= 2 or widget.height() <= 2:
        return
    rect = QRect(widget.mapTo(host, QPoint(0, 0)), widget.size())
    pix = widget.grab()
    if pix.isNull():
        return
    ov = _DrawerSlideOverlay(
        host,
        rect,
        pix,
        edge=_infer_edge(edge, dx, dy),
        reveal=True,
        duration=duration,
        target_widget=widget,
    )
    widget._motion_transition_overlay = ov


class _StackSlideOverlay(QWidget):
    """Cross-slide transition overlay for QStackedWidget with opaque paper backing."""

    def __init__(self, stack: QStackedWidget) -> None:
        super().__init__(stack)
        self._stack = stack
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(stack.rect())
        self._progress = 1.0
        self._direction = 1
        self._pixmap = QPixmap()

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)
        stack.installEventFilter(self)
        self.hide()

    def trigger(self, direction: int, idx: int) -> None:
        if _REDUCED_MOTION or not isValid(self._stack) or not self._stack.isVisible():
            return
        if self._stack.width() <= 20 or self._stack.height() <= 20:
            return
        self._timer.stop()
        self.hide()
        new_widget = self._stack.widget(idx)
        if new_widget is None or not isValid(new_widget):
            return
        if new_widget.size() != self._stack.size():
            new_widget.resize(self._stack.size())
        if new_widget.layout() is not None:
            new_widget.layout().activate()
        self._pixmap = new_widget.grab()
        if self._pixmap.isNull():
            return
        self._direction = 1 if direction >= 0 else -1
        self._progress = 0.0
        self.setGeometry(self._stack.rect())
        self.show()
        self.raise_()
        self._clock.restart()
        self._timer.start()
        self.update()

    def eventFilter(self, watched: QObject | None, event: QEvent) -> bool:
        if watched is self._stack and isValid(self) and event.type() in (QEvent.Resize, QEvent.Hide):
            self._timer.stop()
            self._progress = 1.0
            self.hide()
        return False

    def _step(self) -> None:
        if not isValid(self) or not isValid(self._stack):
            self._timer.stop()
            return
        raw = min(1.0, float(self._clock.elapsed()) / 150.0)
        self._progress = raw
        if raw >= 1.0:
            self._timer.stop()
            self._pixmap = QPixmap()
            self.hide()
            return
        self.update()

    def paintEvent(self, event) -> None:
        if self._progress >= 1.0 or self._pixmap.isNull():
            return
        eased = 1.0 - (1.0 - self._progress) ** 3
        inv = 1.0 - eased
        p = QPainter(self)
        p.fillRect(self.rect(), _theme_color('paper'))
        p.setOpacity(0.35 + 0.65 * eased)
        p.drawPixmap(QPointF(float(self._direction) * 14.0 * inv, 0.0), self._pixmap)
        p.end()


def install_stack_motion(stack: QStackedWidget | None) -> None:
    """Attach a non-blocking fast page cross-slide transition to a QStackedWidget."""
    if stack is None or not isValid(stack):
        return
    if getattr(stack, '_motion_stack_installed', False):
        return
    stack._motion_stack_installed = True
    stack._motion_prev_index = stack.currentIndex()
    overlay = _StackSlideOverlay(stack)
    stack._motion_stack_overlay = overlay

    def _on_changed(idx: int) -> None:
        if not isValid(stack) or not isValid(overlay):
            return
        prev = getattr(stack, '_motion_prev_index', idx)
        stack._motion_prev_index = idx
        if idx != prev:
            overlay.trigger(1 if idx > prev else -1, idx)

    stack.currentChanged.connect(_on_changed)


# ---------------------------------------------------------------------------
# 6. List Gliding Selection Rail & Hover Wash
# ---------------------------------------------------------------------------

class _ListSelectionRail(QWidget):
    """Gliding 3px monochrome ink pill rail + hover wash on QListWidget viewport."""

    def __init__(self, lst: QListWidget) -> None:
        vp = lst.viewport()
        super().__init__(vp)
        self._list = lst
        self._vp = vp
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(vp.rect())

        self._cur_top = 0.0
        self._cur_h = 0.0
        self._start_top = 0.0
        self._start_h = 0.0
        self._target_top = 0.0
        self._target_h = 0.0
        self._has_rail = False

        self._hover_row = -1
        self._hover_alpha = 0.0

        self._clock = QElapsedTimer()
        self._clock.start()
        self._last_ms = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)

        lst.setMouseTracking(True)
        vp.setMouseTracking(True)
        vp.installEventFilter(self)
        lst.currentRowChanged.connect(self._on_row_changed)
        lst.itemSelectionChanged.connect(lambda: self._on_row_changed(lst.currentRow()))
        if lst.verticalScrollBar() is not None:
            lst.verticalScrollBar().valueChanged.connect(lambda *_: self._sync_instant())
        model = lst.model()
        if model is not None:
            model.modelReset.connect(self._sync_instant)
            model.rowsRemoved.connect(lambda *_: self._sync_instant())

        self.show()
        self.raise_()
        self._sync_instant()

    def _selected_rect(self) -> QRect | None:
        if not isValid(self._list):
            return None
        item = self._list.currentItem()
        if item is None:
            return None
        r = self._list.visualItemRect(item)
        if not r.isValid() or r.height() <= 0:
            return None
        return r

    def _sync_instant(self) -> None:
        if not isValid(self._vp):
            return
        self.setGeometry(self._vp.rect())
        r = self._selected_rect()
        if r is None:
            self._has_rail = False
            self.update()
            return
        self._cur_top = float(r.top())
        self._cur_h = float(r.height())
        self._start_top = self._cur_top
        self._start_h = self._cur_h
        self._target_top = self._cur_top
        self._target_h = self._cur_h
        self._has_rail = True
        self.update()

    def _on_row_changed(self, row: int) -> None:
        if not isValid(self._list):
            return
        r = self._selected_rect()
        if r is None:
            self._has_rail = False
            self.update()
            return
        if _REDUCED_MOTION or not self._has_rail or not self._list.isVisible():
            self._sync_instant()
            return
        self._start_top = self._cur_top
        self._start_h = self._cur_h
        self._target_top = float(r.top())
        self._target_h = float(r.height())
        self._has_rail = True
        self._last_ms = float(self._clock.elapsed())
        self._clock.restart()
        self._last_ms = 0.0
        if not self._timer.isActive():
            self._timer.start()

    def eventFilter(self, watched: QObject | None, event: QEvent) -> bool:
        if watched is None or not isValid(watched) or not isValid(self._list) or not isValid(self._vp):
            return False
        etype = event.type()
        if etype == QEvent.Resize:
            self.setGeometry(self._vp.rect())
            self._sync_instant()
        elif etype == QEvent.MouseMove:
            item = self._list.itemAt(event.position().toPoint())
            new_row = self._list.row(item) if item is not None else -1
            if new_row != self._hover_row:
                self._hover_row = new_row
                if _REDUCED_MOTION:
                    self._hover_alpha = 1.0 if new_row >= 0 else 0.0
                    self.update()
                else:
                    self._last_ms = float(self._clock.elapsed())
                    if not self._timer.isActive():
                        self._timer.start()
        elif etype == QEvent.Leave:
            if self._hover_row != -1:
                self._hover_row = -1
                if _REDUCED_MOTION:
                    self._hover_alpha = 0.0
                    self.update()
                elif not self._timer.isActive():
                    self._last_ms = float(self._clock.elapsed())
                    self._timer.start()
        return False

    def _step(self) -> None:
        if not isValid(self) or not isValid(self._list):
            self._timer.stop()
            return
        now = float(self._clock.elapsed())
        dt = max(1.0, min(48.0, now - self._last_ms))
        self._last_ms = now

        rail_done = True
        if self._has_rail:
            raw = min(1.0, now / 170.0)
            eased = 1.0 - (1.0 - raw) ** 3
            self._cur_top = self._start_top + (self._target_top - self._start_top) * eased
            self._cur_h = self._start_h + (self._target_h - self._start_h) * eased
            rail_done = raw >= 1.0

        hover_target = 1.0 if self._hover_row >= 0 else 0.0
        rate = 1.0 - math.exp(-dt / 45.0)
        self._hover_alpha += (hover_target - self._hover_alpha) * rate
        hover_done = abs(self._hover_alpha - hover_target) <= 0.01
        if hover_done:
            self._hover_alpha = hover_target

        if rail_done and hover_done:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        if not isValid(self._list):
            return
        ink = _theme_color('ink')
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)

        # Hover wash
        if self._hover_row >= 0 and self._hover_alpha > 0.01:
            item = self._list.item(self._hover_row)
            if item is not None:
                hr = QRectF(self._list.visualItemRect(item))
                if hr.isValid() and not hr.isEmpty() and self._hover_row != self._list.currentRow():
                    p.setBrush(_with_alpha(ink, int(round(12 * self._hover_alpha))))
                    p.drawRoundedRect(hr.adjusted(2, 1, -2, -1), 6.0, 6.0)

        # Gliding left selection rail
        if self._has_rail and self._cur_h > 6.0:
            inset = min(7.0, self._cur_h * 0.24)
            rail = QRectF(3.0, self._cur_top + inset, 3.0, max(6.0, self._cur_h - 2.0 * inset))
            p.setBrush(ink)
            p.drawRoundedRect(rail, 1.5, 1.5)
        p.end()


def install_list_motion(list_widget: QListWidget | None) -> _ListSelectionRail | None:
    """Attach gliding selection rail and subtle monochrome hover wash to QListWidget."""
    if list_widget is None or not isValid(list_widget):
        return None
    existing = getattr(list_widget, '_motion_list_rail', None)
    if existing is not None and isValid(existing):
        return existing
    rail = _ListSelectionRail(list_widget)
    list_widget._motion_list_rail = rail
    return rail


# ---------------------------------------------------------------------------
# 7. Gemini Status Pill Shimmer & Monochrome Dual-Segment Progress Bar
# ---------------------------------------------------------------------------

class StatusShimmerOverlay(QWidget):
    """Subtle 60fps monochrome sheen sweeping across statusPill when active."""

    def __init__(self, pill: QWidget) -> None:
        super().__init__(pill)
        self._pill = pill
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(pill.rect())
        self._active = False

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        pill.installEventFilter(self)
        self.hide()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if not self._active or _REDUCED_MOTION:
            self._timer.stop()
            self.hide()
            return
        self.setGeometry(self._pill.rect())
        self.show()
        self.raise_()
        if self._pill.isVisible() and not self._timer.isActive():
            self._clock.restart()
            self._timer.start()

    def eventFilter(self, watched: QObject | None, event: QEvent) -> bool:
        if watched is None or not isValid(watched) or not isValid(self._pill):
            return False
        etype = event.type()
        if etype == QEvent.Resize:
            self.setGeometry(self._pill.rect())
        elif etype == QEvent.Show and self._active and not _REDUCED_MOTION:
            if not self._timer.isActive():
                self._clock.restart()
                self._timer.start()
        elif etype == QEvent.Hide:
            self._timer.stop()
        return False

    def _tick(self) -> None:
        if not isValid(self) or not isValid(self._pill) or not self._active or not self._pill.isVisible():
            self._timer.stop()
            return
        self.update()

    def paintEvent(self, event) -> None:
        if not self._active or _REDUCED_MOTION:
            return
        r = QRectF(self.rect())
        if r.width() <= 8 or r.height() <= 4:
            return
        phase = (self._clock.elapsed() % 1500) / 1500.0
        # Sweep smoothly left -> right during first 72% of cycle, rest slightly between sweeps
        sweep_t = min(1.0, phase / 0.72)
        alpha_fade = 1.0 if phase <= 0.72 else max(0.0, 1.0 - (phase - 0.72) / 0.14)
        band_w = max(24.0, r.width() * 0.42)
        cx = -band_w * 0.6 + (r.width() + band_w * 1.2) * sweep_t

        ink = _theme_color('ink')
        peak = 24 if ink.lightness() < 128 else 32
        peak = int(round(peak * alpha_fade))
        if peak <= 1:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(r, min(r.height() * 0.5, 10.0), min(r.height() * 0.5, 10.0))
        p.setClipPath(clip)

        grad = QLinearGradient(cx - band_w * 0.5, 0.0, cx + band_w * 0.5, r.height())
        grad.setColorAt(0.0, _with_alpha(ink, 0))
        grad.setColorAt(0.5, _with_alpha(ink, peak))
        grad.setColorAt(1.0, _with_alpha(ink, 0))
        p.fillRect(r, grad)
        p.end()


class MonochromeShimmerBar(QProgressBar):
    """Gemini-style dual-segment 60fps monochrome indeterminate progress bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)
        self._display_frac = 0.0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def _is_indeterminate(self) -> bool:
        return self.minimum() == 0 and self.maximum() == 0

    def _sync_timer(self) -> None:
        if _REDUCED_MOTION or not self.isVisible():
            self._timer.stop()
            return
        if self._is_indeterminate():
            if not self._timer.isActive():
                self._clock.restart()
                self._timer.start()
        else:
            span = max(1, self.maximum() - self.minimum())
            target = (self.value() - self.minimum()) / float(span)
            if abs(target - self._display_frac) > 0.005:
                if not self._timer.isActive():
                    self._timer.start()
            else:
                self._display_frac = target
                self._timer.stop()

    def setRange(self, minimum: int, maximum: int) -> None:
        super().setRange(minimum, maximum)
        self._sync_timer()
        self.update()

    def setValue(self, value: int) -> None:
        super().setValue(value)
        if _REDUCED_MOTION:
            span = max(1, self.maximum() - self.minimum())
            self._display_frac = max(0.0, min(1.0, (value - self.minimum()) / float(span)))
        self._sync_timer()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        if not isValid(self) or not self.isVisible():
            self._timer.stop()
            return
        if not self._is_indeterminate():
            span = max(1, self.maximum() - self.minimum())
            target = max(0.0, min(1.0, (self.value() - self.minimum()) / float(span)))
            self._display_frac += (target - self._display_frac) * 0.25
            if abs(target - self._display_frac) <= 0.004:
                self._display_frac = target
                self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        r = QRectF(self.rect())
        if r.width() <= 2 or r.height() <= 1:
            return
        h = min(r.height(), 4.0)
        y = r.center().y() - h * 0.5
        track = QRectF(r.left(), y, r.width(), h)
        rad = h * 0.5

        ink = _theme_color('ink')
        rule = _theme_color('rule')

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(_with_alpha(rule, 160))
        p.drawRoundedRect(track, rad, rad)

        if not self._is_indeterminate():
            fill_w = track.width() * max(0.0, min(1.0, self._display_frac))
            if fill_w > 1.0:
                p.setBrush(ink)
                p.drawRoundedRect(QRectF(track.left(), y, fill_w, h), rad, rad)
            p.end()
            return

        if _REDUCED_MOTION:
            p.setBrush(_with_alpha(ink, 190))
            seg_w = track.width() * 0.35
            p.drawRoundedRect(QRectF(track.left() + (track.width() - seg_w) * 0.5, y, seg_w, h), rad, rad)
            p.end()
            return

        # Dual-segment Material 3 indeterminate wave, strictly monochrome
        cycle = (self._clock.elapsed() % 1400) / 1400.0
        clip = QPainterPath()
        clip.addRoundedRect(track, rad, rad)
        p.setClipPath(clip)

        # Primary bar: sweeps from -0.25 -> 1.15
        p1_head = -0.05 + 1.35 * (cycle ** 0.85)
        p1_tail = -0.35 + 1.45 * (cycle ** 1.35)
        # Secondary bar: delayed chase
        c2 = max(0.0, (cycle - 0.35) / 0.65) if cycle >= 0.35 else 0.0
        p2_head = -0.02 + 1.18 * (c2 ** 0.78) if c2 > 0 else -1.0
        p2_tail = -0.22 + 1.25 * (c2 ** 1.25) if c2 > 0 else -1.0

        for tail, head, alpha in ((p1_tail, p1_head, 235), (p2_tail, p2_head, 165)):
            if head <= tail:
                continue
            x0 = track.left() + tail * track.width()
            x1 = track.left() + head * track.width()
            seg = QRectF(x0, y, max(4.0, x1 - x0), h)
            grad = QLinearGradient(seg.left(), 0.0, seg.right(), 0.0)
            grad.setColorAt(0.0, _with_alpha(ink, int(alpha * 0.35)))
            grad.setColorAt(0.45, _with_alpha(ink, alpha))
            grad.setColorAt(1.0, _with_alpha(ink, alpha))
            p.setBrush(grad)
            p.drawRoundedRect(seg, rad, rad)
        p.end()
