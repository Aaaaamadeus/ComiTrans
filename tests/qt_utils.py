"""Destroy test-owned windows while the Qt application is still alive."""
from PySide6.QtCore import QCoreApplication, QEvent


def destroy_widget(widget):
    # Only delete the explicitly owned fixture, never Qt's internal popups.
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
