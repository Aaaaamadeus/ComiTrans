from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QRectF, QSize, Signal, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QImageReader
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QStackedLayout, QPushButton, QSizePolicy
from ..pdf_utils import render_pdf_preview
from .halftone import COMPACT_BREAKPOINT, draw_tone


class MangaIllustration(QWidget):
    """Small, resolution-independent page panels; never covers the artwork."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(180, 104)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#111111'), 2))
        p.setBrush(QColor('#111111'))
        p.drawRect(54, 11, 82, 86)
        p.setBrush(QColor('#FFFFFF'))
        p.drawRect(49, 6, 82, 86)
        p.drawRect(57, 14, 28, 29)
        p.drawRect(91, 14, 32, 29)
        p.drawRect(57, 49, 66, 35)
        p.drawEllipse(65, 55, 26, 17)
        p.drawLine(78, 72, 75, 78)
        p.drawLine(98, 59, 114, 59)
        p.drawLine(98, 66, 111, 66)
        p.drawLine(98, 73, 116, 73)
        p.drawLine(21, 38, 36, 38)
        p.drawLine(28, 31, 28, 45)
        draw_tone(p, QRectF(144, 65, 28, 27), compact=self.window().width() < COMPACT_BREAKPOINT, profile='quiet')
        p.end()


class ImagePreview(QWidget):
    import_requested = Signal()

    def __init__(self, parent=None, *, import_action=False):
        super().__init__(parent)
        self._original = QPixmap()
        self._zoom = None
        self.setMinimumSize(120, 100)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._empty = QWidget()
        self._empty.setObjectName('emptyPreview')
        layout = QVBoxLayout(self._empty)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)
        layout.addStretch()
        content = QHBoxLayout()
        content.addStretch()
        self._art = MangaIllustration()
        content.addWidget(self._art, 0, Qt.AlignVCenter)
        message_layout = QVBoxLayout()
        message_layout.setSpacing(8)
        self._empty_title = QLabel('从一页漫画开始' if import_action else '等待预览')
        self._empty_title.setObjectName('sectionTitle')
        self._empty_title.setWordWrap(True)
        self._empty_title.setAlignment(Qt.AlignCenter)
        message_layout.addWidget(self._empty_title)
        self._hint = QLabel('导入 → 自动处理 → 检查 → 精修 → 导出' if import_action else '选择页面后在这里检查图像')
        self._hint.setProperty('muted', True)
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        message_layout.addWidget(self._hint)
        self.import_button = QPushButton('添加漫画')
        self.import_button.setProperty('role', 'primary')
        self.import_button.setVisible(import_action)
        self.import_button.clicked.connect(self.import_requested)
        message_layout.addWidget(self.import_button, 0, Qt.AlignHCenter)
        content.addLayout(message_layout)
        content.addStretch()
        layout.addLayout(content)
        layout.addStretch()
        self._stack.addWidget(self._empty)
        self._label = QLabel()
        self._label.setObjectName('previewLabel')
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._scroll = QScrollArea()
        self._scroll.setObjectName('previewCanvas')
        self._scroll.setWidget(self._label)
        self._scroll.setWidgetResizable(True)
        self._scroll.setAlignment(Qt.AlignCenter)
        self._scroll.viewport().installEventFilter(self)
        self._stack.addWidget(self._scroll)

    def eventFilter(self, watched, event):
        if watched is self._scroll.viewport() and event.type() == QEvent.Resize:
            self._update_scaled()
        return super().eventFilter(watched, event)

    def set_image(self, path):
        try:
            if Path(path).suffix.lower() == '.pdf':
                self.set_pixmap(QPixmap.fromImage(render_pdf_preview(path, QSize(1600, 1600))))
            else:
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                self.set_pixmap(QPixmap.fromImage(reader.read()))
        except Exception as exc:
            self.clear(f'无法预览：{exc}')

    def set_pixmap(self, pixmap):
        self._original = pixmap
        if pixmap.isNull():
            self.clear('无法读取图片')
            return
        self._stack.setCurrentWidget(self._scroll)
        self._update_scaled()

    def clear(self, text='等待预览'):
        self._original = QPixmap()
        self._label.clear()
        self._empty_title.setText(text)
        self._stack.setCurrentWidget(self._empty)

    def set_zoom(self, factor=None):
        self._zoom = factor
        self._update_scaled()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._art.setVisible(self.height() >= 150 and self.width() >= 450)
        self._hint.setVisible(self.height() >= 170)
        self._update_scaled()

    def _update_scaled(self):
        if self._original.isNull():
            return
        if self._zoom is None:
            size = self._scroll.viewport().size() - QSize(24, 24)
            self._label.setMinimumSize(0, 0)
        else:
            size = self._original.size() * self._zoom
            self._label.setMinimumSize(size)
        if size.width() > 0 and size.height() > 0:
            self._label.setPixmap(self._original.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
