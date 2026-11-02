"""Decode display-only thumbnails off the UI thread, one bounded job at a time."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, QSize, Qt, Slot
from PySide6.QtGui import QImageReader


class _Signals(QObject):
    ready = Signal(str, object, object)


class _ReadImage(QRunnable):
    def __init__(self, path, size):
        super().__init__()
        self.path, self.size = path, size
        self.signals = _Signals()

    def run(self):
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        target = self.size.transposed() if reader.transformation().value & 4 else self.size
        original = reader.size()
        reader.setScaledSize(original.scaled(target, Qt.KeepAspectRatio))
        image = reader.read()
        try:
            self.signals.ready.emit(self.path, self.size, image)
        except RuntimeError:
            # The preview/application may have closed while decoding. There is
            # no UI recipient left, so discard this display-only result.
            pass


class ThumbnailLoader(QObject):
    ready = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wanted = {}
        self._pending = {}
        self._active = None

    def request(self, requests):
        self._wanted = {path: QSize(size) for path, size in requests}
        self._pending = dict(self._wanted)
        if self._active is not None:
            self._pending.pop(self._active.path, None)
        self._start_next()

    def _start_next(self):
        if self._active is not None or not self._pending:
            return
        path = next(iter(self._pending))
        job = _ReadImage(path, self._pending.pop(path))
        self._active = job
        job.signals.ready.connect(self._accept, Qt.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    @Slot(str, object, object)
    def _accept(self, path, size, image):
        self._active = None
        if self._wanted.get(path) == size:
            self._wanted.pop(path, None)
            self._pending.pop(path, None)
            self.ready.emit(path, image)
        elif path in self._wanted:
            self._pending[path] = self._wanted[path]
        self._start_next()
