"""Explicit, cancellable image-to-PDF export; never runs on the UI thread."""
from PySide6.QtCore import QThread, Signal
from .pdf_utils import build_pdf_from_images


class PdfExportCancelled(Exception):
    pass


class PdfExportWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, int)

    def __init__(self, images, sizes, output, parent=None):
        super().__init__(parent)
        self.images, self.sizes = tuple(images), tuple(sizes)
        self.output = output

    def _check_cancel(self):
        if self.isInterruptionRequested():
            raise PdfExportCancelled()

    def run(self):
        try:
            result = build_pdf_from_images(self.images, self.sizes, self.output,
                progress_callback=self.progress.emit, cancel_callback=self._check_cancel)
            self.succeeded.emit(str(result))
        except PdfExportCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
