"""Virtual long-strip view: page metadata is cheap; canvases follow the viewport."""
from bisect import bisect_right
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QEvent, QTimer, Signal
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea

from .preview import ImagePreview, PageCanvas
from .thumbnail_loader import ThumbnailLoader


class _StripScroll(QAbstractScrollArea):
    def __init__(self, preview):
        super().__init__()
        self.preview = preview

    def scrollContentsBy(self, dx, dy):
        # Move only mounted canvases; no document-sized widget or layout.
        self.preview._load_visible()

    def ensureWidgetVisible(self, widget, *_args):
        key = self.preview._canvas_keys.get(widget)
        if key:
            self.preview.reveal_page(key)


class StripPreview(ImagePreview):
    page_requested = Signal(str)

    def __init__(self, *args, **kwargs):
        self._continuous = False
        self._regions = ([], True)
        super().__init__(*args, **kwargs)
        self._single_label = self._label
        self._active_path = None
        self._pages = {}
        self._keys, self._indices = [], {}
        self._offsets, self._dimensions = [], []
        self._layout_signature = None
        self._canvas_keys, self._spares = {}, []
        self._thumbnail_loader = ThumbnailLoader(self)
        self._thumbnail_loader.ready.connect(self._accept_thumbnail)
        self._strip_scroll = _StripScroll(self)
        self._stack.addWidget(self._strip_scroll)
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.timeout.connect(self._load_visible)
        self._strip_scroll.viewport().installEventFilter(self)

    def add_page(self, path, size=None):
        key = str(Path(path).resolve())
        if key in self._pages:
            return
        if size is None:
            reader = QImageReader(key)
            size = reader.size()
            if reader.transformation().value & 4:
                size.transpose()
        if not size.isValid():
            size = QSize(600, 800)
        self._indices[key] = len(self._keys)
        self._keys.append(key)
        self._pages[key] = [None, QSize(size)]
        self._layout_signature = None
        if self._continuous:
            self._visible_timer.start(0)

    def _mount(self, key):
        existing = self._pages[key][0]
        if existing is not None:
            return existing
        if self._spares:
            label = self._spares.pop()
        else:
            label = PageCanvas(self._strip_scroll.viewport())
            label.setAlignment(Qt.AlignCenter)
            label.stretch_pixmap = True
            label.installEventFilter(self)
            label.region_edited.connect(self.region_edited)
            label.region_edit_finished.connect(self.region_edit_finished)
            label.region_clicked.connect(self.region_clicked)
        label.setToolTip(Path(key).name)
        self._pages[key][0] = label
        self._canvas_keys[label] = key
        return label

    def _unmount(self, label):
        key = self._canvas_keys.pop(label)
        self._pages[key][0] = None
        label.cancel_region_drag()
        label.region = None
        label.region_editable = label.region_creation = False
        label.clear()
        label.hide()
        self._spares.append(label)

    def replace_page_path(self, old_path, new_path):
        old, new = str(Path(old_path).resolve()), str(Path(new_path).resolve())
        if old not in self._pages:
            return
        row = self._indices.pop(old)
        self._indices[new] = row
        self._keys[row] = new
        self._pages[new] = self._pages.pop(old)
        label = self._pages[new][0]
        if label is not None:
            self._canvas_keys[label] = new
            label.setToolTip(Path(new).name)
        if self._active_path == old:
            self._active_path = new
        self._thumbnail_loader.request([])
        self._visible_timer.start(0)

    def set_continuous(self, enabled):
        self.cancel_region_drag()
        previous = self._label
        region, editable, creation = previous.region, previous.region_editable, previous.region_creation
        previous.region = None
        previous.region_editable = previous.region_creation = False
        previous.update()
        self._continuous = enabled
        self._label = self._mount(self._active_path) if enabled and self._active_path else self._single_label
        self._label.image_size = self._original.size()
        self._label.region_creation = creation
        self.set_region(region, editable=editable)
        self._apply_regions()
        if not self._original.isNull():
            self.set_pixmap(self._original)
        if enabled:
            self.reveal_active()
        else:
            self._thumbnail_loader.request([])
            for label in list(self._canvas_keys):
                self._unmount(label)
            self._trim_spares()

    def activate_page(self, path):
        key = str(Path(path).resolve())
        self.add_page(key)
        if self._active_path != key:
            self.cancel_region_drag()
            self._label.region = None
            self._label.region_editable = self._label.region_creation = False
            self._label.clear()
        self._active_path = key
        self._label = self._mount(key) if self._continuous else self._single_label
        self._apply_regions()

    def set_regions(self, regions, visible=True):
        self._regions = (list(regions or ()), bool(visible))
        super().set_regions(regions, visible)

    def _apply_regions(self):
        regions, visible = getattr(self, '_regions', ([], True))
        if self._label is not None:
            self._label.set_regions(regions, visible)

    def set_image(self, path):
        self.activate_page(path)
        super().set_image(path)
        if self._continuous:
            self.reveal_active()

    def set_page_pixmap(self, path, pixmap):
        self.add_page(path, pixmap.size())
        self.activate_page(path)
        self.set_pixmap(pixmap)
        if self._continuous:
            self.reveal_active()

    def set_pixmap(self, pixmap):
        if self._continuous and not pixmap.isNull():
            self._original = pixmap
            self._label.image_size = pixmap.size()
            self._stack.setCurrentWidget(self._strip_scroll)
            self._update_scaled()
        else:
            super().set_pixmap(pixmap)

    def reveal_active(self):
        if self._active_path:
            self.reveal_page(self._active_path)

    def reveal_page(self, key):
        if not self._continuous or key not in self._indices:
            return
        self._layout_strip()
        index = self._indices[key]
        top, height = self._offsets[index], self._dimensions[index].height()
        bar = self._strip_scroll.verticalScrollBar()
        if top + height <= bar.value() or top >= bar.value() + self._strip_scroll.viewport().height():
            bar.setValue(top)
        self._load_visible()

    def _layout_strip(self):
        viewport = self._strip_scroll.viewport()
        signature = (viewport.width(), viewport.height(), self._zoom, len(self._keys))
        if signature == self._layout_signature:
            return
        bar = self._strip_scroll.verticalScrollBar()
        anchor = max(0, bisect_right(self._offsets, bar.value()) - 1)
        fraction = ((bar.value() - self._offsets[anchor]) / max(1, self._dimensions[anchor].height())
                    if self._offsets else 0)
        self._layout_signature = signature
        available = max(100, viewport.width() - 26)
        self._offsets, self._dimensions = [], []
        top, widest = 12, available
        for key in self._keys:
            original = self._pages[key][1]
            factor = self._zoom if self._zoom is not None else available / max(1, original.width())
            size = QSize(max(1, round(original.width() * factor)), max(1, round(original.height() * factor)))
            self._offsets.append(top)
            self._dimensions.append(size)
            top += size.height() + 16
            widest = max(widest, size.width())
        self._content_width = widest + 24
        # Scrollbar coordinates have no QWidget maximum-height constraint.
        bar.blockSignals(True)
        self._strip_scroll.horizontalScrollBar().blockSignals(True)
        bar.setPageStep(viewport.height())
        bar.setRange(0, max(0, top - viewport.height()))
        if self._offsets:
            bar.setValue(round(self._offsets[anchor] + fraction * self._dimensions[anchor].height()))
        horizontal = self._strip_scroll.horizontalScrollBar()
        horizontal.setPageStep(viewport.width())
        horizontal.setRange(0, max(0, self._content_width - viewport.width()))
        bar.blockSignals(False)
        horizontal.blockSignals(False)

    def _update_scaled(self):
        if not self._continuous:
            return super()._update_scaled()
        if not hasattr(self, '_strip_scroll'):
            return
        if self._zoom is not None:
            self._scale = self._zoom
        self._layout_strip()
        self._load_visible(refresh_active=True)

    def _trim_spares(self):
        while len(self._spares) > 2:
            self._spares.pop().deleteLater()

    def _load_visible(self, refresh_active=False):
        if not self._continuous:
            return
        self._layout_strip()
        if not self._keys:
            return
        viewport = self._strip_scroll.viewport()
        scroll = self._strip_scroll.verticalScrollBar().value()
        first = max(0, bisect_right(self._offsets, scroll - 100) - 1)
        last = min(len(self._keys), bisect_right(self._offsets, scroll + viewport.height() + 100) + 1)
        wanted = set(self._keys[first:last])
        if self._active_path:
            wanted.add(self._active_path)
        for label, key in list(self._canvas_keys.items()):
            if key not in wanted:
                self._unmount(label)
        requests = []
        for key in wanted:
            label = self._mount(key)
            index = self._indices[key]
            size = self._dimensions[index]
            x = (self._content_width - size.width()) // 2 - self._strip_scroll.horizontalScrollBar().value()
            label.setGeometry(x, self._offsets[index] - scroll, size.width(), size.height())
            in_view = first <= index < last
            label.setVisible(in_view)
            if key == self._active_path:
                if not self._original.isNull() and (refresh_active or label.pixmap().cacheKey() != self._original.cacheKey()):
                    label.setPixmap(self._original)
                continue
            target = self._pages[key][1].scaled(size * self.devicePixelRatioF(), Qt.KeepAspectRatio)
            if max(target.width(), target.height()) > 2048:
                target.scale(QSize(2048, 2048), Qt.KeepAspectRatio)
            cached = label.pixmap()
            if cached is None or cached.isNull() or cached.size() != target:
                requests.append((key, target))
        self._trim_spares()
        self._thumbnail_loader.request(requests)

    def _accept_thumbnail(self, key, image):
        entry = self._pages.get(key)
        if self._continuous and key != self._active_path and entry and entry[0] is not None:
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(self.devicePixelRatioF())
            entry[0].setPixmap(pixmap)

    def eventFilter(self, watched, event):
        if hasattr(self, '_strip_scroll') and watched is self._strip_scroll.viewport():
            if event.type() == QEvent.Resize and self._continuous:
                self.cancel_region_drag()
                self._visible_timer.start(0)
        elif self._continuous and watched in self._canvas_keys:
            key = self._canvas_keys.get(watched)
            if event.type() == QEvent.Wheel:
                if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                    self._zoom_strip(1.12 if event.angleDelta().y() > 0 else 1 / 1.12, key)
                else:
                    bar = self._strip_scroll.verticalScrollBar()
                    bar.setValue(bar.value() - (event.angleDelta().y() // 120) * 80)
                return True
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                if key and key != self._active_path:
                    self.page_requested.emit(key)
                    return True
        return super().eventFilter(watched, event)

    def _zoom_strip(self, step, key):
        """Zoom the whole strip around the page under the cursor."""
        if key not in self._indices:
            return
        available = max(100, self._strip_scroll.viewport().width() - 26)
        current = self._zoom if self._zoom is not None else available / max(1, self._pages[key][1].width())
        self.set_zoom(current * step)
        self.reveal_page(key)
