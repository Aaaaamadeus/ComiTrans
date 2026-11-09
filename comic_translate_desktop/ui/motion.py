"""Small UI motion helpers that honour the reduced-motion preference."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect

_reduced = False
_pulses = {}


def set_reduced_motion(value):
    global _reduced
    _reduced = bool(value)


def reduced_motion():
    return _reduced


def fade_in(widget, duration=180):
    if widget is None or _reduced:
        return
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(1.0)
    animation = QPropertyAnimation(effect, b'opacity', widget)
    animation.setDuration(duration)
    animation.setStartValue(0.2)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    widget._fade_animation = animation
    animation.start()


def set_pulse(widget, active, duration=1200):
    if widget is None:
        return
    existing = _pulses.pop(widget, None)
    if existing is not None:
        existing.stop()
        widget.setGraphicsEffect(None)
    if not active or _reduced:
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b'opacity', widget)
    animation.setDuration(duration)
    animation.setStartValue(1.0)
    animation.setKeyValueAt(0.5, 0.35)
    animation.setEndValue(1.0)
    animation.setLoopCount(-1)
    animation.setEasingCurve(QEasingCurve.InOutSine)
    _pulses[widget] = animation
    animation.start()
