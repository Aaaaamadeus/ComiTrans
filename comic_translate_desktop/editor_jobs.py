"""Bounded background I/O for editing. Workers never access live widgets."""
import json
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, QSize, Qt, Slot
from PySide6.QtGui import QImageReader

from .pdf_project import load_pdf_project, read_project


class _Result(QObject):
    done = Signal(int, object, str)


class _Job(QRunnable):
    def __init__(self, generation, function, cancellable=False):
        super().__init__()
        self.generation, self.function = generation, function
        self.signals = _Result()
        self.cancelled = threading.Event()
        self.cancellable = cancellable

    def run(self):
        value, error = None, ''
        try:
            value = self.function(self.cancelled.is_set) if self.cancellable else self.function()
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        try:
            self.signals.done.emit(self.generation, value, error)
        except RuntimeError:
            pass  # The owning window was destroyed while native decoding finished.


class LatestJobQueue(QObject):
    """One running job and one replaceable pending job, never an unbounded backlog."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.generation = 0
        self._active = self._pending = None
        self._closed = False

    @property
    def busy(self):
        return self._active is not None or self._pending is not None

    def submit(self, function, success, failure, *, cancellable=False):
        self.generation += 1
        if self._active is not None:
            self._active[0].cancelled.set()
        self._pending = (self.generation, function, success, failure, cancellable)
        self._start()

    def _start(self):
        if self._active is not None or self._pending is None or self._closed:
            return
        generation, function, success, failure, cancellable = self._pending
        self._pending = None
        job = _Job(generation, function, cancellable)
        self._active = (job, success, failure)
        job.signals.done.connect(self._accept, Qt.QueuedConnection)
        QThreadPool.globalInstance().start(job)

    @Slot(int, object, str)
    def _accept(self, generation, value, error):
        _job, success, failure = self._active
        self._active = None
        if not self._closed and generation == self.generation:
            if error:
                failure(error)
            else:
                success(value)
        self._start()

    def invalidate(self):
        if self._active is not None:
            self._active[0].cancelled.set()
        self.generation += 1
        self._pending = None

    def close(self):
        self.invalidate()
        self._closed = True


@dataclass
class PageData:
    preview: object
    cleaned: object
    items: list
    error: str = ''


def read_page(path, settings=None, cancelled=lambda: False):
    if cancelled():
        raise RuntimeError('页面加载已取消')
    path = Path(path)
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    preview = reader.read()
    if preview.isNull():
        raise ValueError(f'无法读取图片：{path.name}')
    if cancelled():
        raise RuntimeError('页面加载已取消')
    cleaned_path = path.parent.parent / f'{path.parent.name}_cleaned' / f'{path.stem}_cleaned.png'
    layout_path = path.parent.parent / f'{path.parent.name}_layout' / f'{path.stem}_layout.json'
    try:
        items = json.loads(layout_path.read_text(encoding='utf-8'))
        if not isinstance(items, list) or any(not isinstance(item, dict) or len(item.get('box', [])) < 4 for item in items):
            raise ValueError('布局数据格式不正确')
        with Image.open(cleaned_path) as image:
            cleaned = image.convert('RGB')
        data = PageData(preview, cleaned, items)
        if settings is not None:
            prepare_legacy_regions(data, settings)
        return data
    except (OSError, ValueError, TypeError) as exc:
        return PageData(preview, None, [], f'缺少或无法读取配套清理底图、布局：{exc}')


def prepare_legacy_regions(data, settings):
    legacy = [item for item in data.items if len(item.get('mask_box', [])) < 4]
    if not legacy:
        return
    from vertical_typesetter import VerticalTypesetter
    from .font_library import inspect_font, resolve_font_reference
    default = VerticalTypesetter(settings['font_map'], 16, fallback_fonts=settings.get('font_fallbacks'))
    for item in legacy:
        typesetter = default
        if item.get('font_reference'):
            try:
                path = str(inspect_font(resolve_font_reference(item['font_reference'])).path)
                typesetter = VerticalTypesetter({style: path for style in settings['font_map']}, 16,
                                               fallback_fonts=settings.get('font_fallbacks'))
            except (OSError, ValueError):
                pass
        typesetter.draw_text(data.cleaned, item['box'], item.get('text', ''), item.get('style', 'dialogue'),
            direction=int(item.get('direction', 1)), target_font_size=item.get('font_size'),
            non_bubble=bool(item.get('non_bubble', False)), composite=False)
        item['mask_box'] = list(typesetter.last_layout_box or item['box'][:4])
        if not item.get('rendered_font_size'):
            item['rendered_font_size'] = typesetter.last_font_size


def read_project_pages(path, cancelled=lambda: False):
    path = Path(path).resolve()
    project = read_project(path.parent) if path.name == 'project.json' else load_pdf_project(path)
    sizes = {}
    for image in project.images:
        if cancelled():
            raise RuntimeError('页面索引已取消')
        # PIL reads PNG headers without Qt scanning the full compressed image for metadata.
        with Image.open(image) as source:
            sizes[str(image)] = QSize(*source.size)
    return project, sizes


@dataclass(frozen=True)
class SaveRequest:
    rendered: object
    output: Path
    items: list
    layout: Path
    cleaned: object
    cleaned_path: Path
    original: object = None
    original_path: object = None

    def write(self, writer):
        writer(self.rendered, self.output, self.items, self.layout, self.cleaned, self.cleaned_path,
               self.original, self.original_path)
        return self
