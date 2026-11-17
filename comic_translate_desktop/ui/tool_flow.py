"""Wrap canvas actions at their natural widths, including translated labels."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class ToolFlowLayout(QLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(4)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), measure=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        left, top, right, bottom = self.getContentsMargins()
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        return QSize(size.width() + left + right, size.height() + top + bottom)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect)

    def _item_size(self, item):
        size = item.sizeHint()
        widget = item.widget()
        if widget is not None and hasattr(widget, 'text') and not widget.property('toolDivider'):
            # Some styles reserve less than the compact button's text padding.
            width = widget.fontMetrics().horizontalAdvance(widget.text()) + 20
            if hasattr(widget, 'icon') and not widget.icon().isNull():
                width += widget.iconSize().width() + 4
            size.setWidth(max(size.width(), width))
        return size

    def _arrange(self, rect, *, measure=False):
        left, top, right, bottom = self.getContentsMargins()
        inner = rect.adjusted(left, top, -right, -bottom)
        spacing = self.spacing()
        rows = []
        current = []
        x = inner.x()
        for item in self._items:
            if item.isEmpty():
                continue
            widget = item.widget()
            is_divider = bool(widget is not None and widget.property('toolDivider'))
            size = self._item_size(item)
            if current and x + size.width() > inner.x() + inner.width():
                rows.append(current)
                current = []
                x = inner.x()
            if is_divider and not current:
                if not measure:
                    item.setGeometry(QRect(0, 0, 0, 0))
                continue
            current.append((item, size, is_divider))
            x += size.width() + spacing
        if current:
            rows.append(current)

        y = inner.y()
        for row_items in rows:
            while row_items and row_items[-1][2]:
                divider_item = row_items.pop()[0]
                if not measure:
                    divider_item.setGeometry(QRect(0, 0, 0, 0))
            if not row_items:
                continue
            row_height = max(size.height() for _, size, _ in row_items)
            x = inner.x()
            for item, size, _ in row_items:
                if not measure:
                    item_y = y + max(0, (row_height - size.height()) // 2)
                    item.setGeometry(QRect(x, item_y, size.width(), size.height()))
                x += size.width() + spacing
            y += row_height + spacing
        used = (y - spacing) if rows else inner.y()
        return max(0, used - rect.y() + bottom)
