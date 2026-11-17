"""Nine persistent font slots shared by the editor bar and number keys."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout,
)

from ..font_library import available_fonts, font_description, font_display_name, font_reference, inspect_font, resolve_font_reference
from ..i18n import tr
from .searchable_combo import SearchableFontCombo
from .theme import set_themed_icon


class FavoriteFontBar(QFrame):
    font_selected = Signal(str)
    add_current_requested = Signal()
    SETTINGS_KEY = 'ui/editorFavoriteFonts'

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setObjectName('favoriteFontsBar')
        self.config = config
        self._can_apply = False
        self._available = [False] * 9
        try:
            stored = json.loads(QSettings().value(self.SETTINGS_KEY, '[]'))
        except (ValueError, TypeError):
            stored = []
        self.slots = (([value if isinstance(value, str) else '' for value in stored]
                       if isinstance(stored, list) else []) + [''] * 9)[:9]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        self._heading = heading
        heading.setSpacing(6)
        title = QLabel(tr('常用字体'))
        title.setObjectName('barCaption')
        heading.addWidget(title)
        self.add_button = QPushButton(tr('加入当前字体'))
        set_themed_icon(self.add_button, 'plus', size=12)
        self.add_button.clicked.connect(self.add_current_requested)
        heading.addWidget(self.add_button)
        self.settings_button = QPushButton(tr('设置快捷字体'))
        self.settings_button.clicked.connect(self.configure)
        heading.addWidget(self.settings_button)
        for button in (self.add_button, self.settings_button):
            button.setProperty('compact', True)
            button.setProperty('role', 'chip')
        layout.addLayout(heading)
        divider = QFrame()
        divider.setObjectName('toolbarDivider')
        divider.setFrameShape(QFrame.VLine)
        divider.setFixedSize(1, 18)
        layout.addWidget(divider)
        self._empty_hint = QLabel(tr('暂无常用字体 · 支持 1–9 键'))
        self._empty_hint.setProperty('muted', True)
        self._empty_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout.addWidget(self._empty_hint, 1)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(5)
        self._grid.setVerticalSpacing(4)
        layout.addLayout(self._grid, 1)
        self.buttons = []
        self._names = [''] * 9
        for index in range(9):
            button = QPushButton(self)
            button.setProperty('compact', True)
            button.setProperty('role', 'chip')
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.clicked.connect(lambda checked=False, slot=index: self.activate(slot))
            self.buttons.append(button)
        self.setToolTip(tr('数字键 1–9 切换当前文本块字体；输入文字时不触发。'))
        self._refresh()

    def set_slots(self, slots):
        self.slots = (list(slots) + [''] * 9)[:9]
        QSettings().setValue(self.SETTINGS_KEY, json.dumps(self.slots, ensure_ascii=False))
        self._refresh()

    def add_font(self, reference):
        if reference in self.slots:
            return True
        if '' not in self.slots:
            return False
        slots = list(self.slots)
        slots[slots.index('')] = reference
        self.set_slots(slots)
        return True

    def activate(self, index):
        if not 0 <= index < 9 or not self.slots[index] or not self.buttons[index].isEnabled():
            return False
        self.font_selected.emit(self.slots[index])
        return True

    def set_apply_enabled(self, enabled):
        self._can_apply = bool(enabled)
        self.add_button.setEnabled(self._can_apply)
        for index, button in enumerate(self.buttons):
            button.setEnabled(self._can_apply and self._available[index])

    def _refresh(self):
        for index, (reference, button) in enumerate(zip(self.slots, self.buttons)):
            available = False
            name = reference
            if reference:
                try:
                    font = inspect_font(resolve_font_reference(reference))
                    name = font_display_name(font)
                    available = True
                except Exception:
                    name = tr('不可用：{_0}', _0=reference.rsplit('/', 1)[-1])
            self._names[index] = name
            self._available[index] = available
            button.setVisible(bool(reference))
            button.setEnabled(available and self._can_apply)
            button.setAccessibleName(f'{index + 1} · {name}')
            button.setToolTip(f'{index + 1} · {name}\n{reference}')
        self._reflow()

    def _reflow(self):
        active_indices = [index for index, value in enumerate(self.slots) if value]
        has_active = bool(active_indices)
        self._empty_hint.setVisible(not has_active)
        columns = max(1, len(active_indices))
        available = max(0, self.width() - self._heading.sizeHint().width() - 40)
        for button in self.buttons:
            self._grid.removeWidget(button)
        for column in range(9):
            self._grid.setColumnStretch(column, 1 if (has_active and column < columns) else 0)
        if not has_active:
            return
        width = max(0, (available - 5 * (columns - 1)) // columns - 22)
        for occupied, index in enumerate(active_indices):
            button = self.buttons[index]
            self._grid.addWidget(button, 0, occupied)
            label = f'{index + 1} · {self._names[index]}'
            button.setText(button.fontMetrics().elidedText(label, Qt.ElideRight, width)
                           if width >= 54 else str(index + 1))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def configure(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('设置快捷字体'))
        layout = QVBoxLayout(dialog)
        hint = QLabel(tr('最多 9 个字体，对应数字键 1–9；留空可清除该快捷键。'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        fonts = available_fonts(self.config)
        choices = []
        for index, reference in enumerate(self.slots):
            combo = SearchableFontCombo()
            combo.addItem(tr('未设置'), '')
            for font in fonts:
                combo.addItem(font_display_name(font), font_reference(font.path))
                combo.setItemData(combo.count() - 1, font_description(font), Qt.ToolTipRole)
            row = combo.findData(reference)
            if row < 0:
                combo.addItem(tr('不可用：{_0}', _0=reference), reference)
                row = combo.count() - 1
            combo.setCurrentIndex(row)
            form.addRow(str(index + 1), combo)
            choices.append(combo)
        layout.addLayout(form)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        dialog.resize(540, dialog.sizeHint().height())
        if dialog.exec() == QDialog.Accepted:
            self.set_slots([combo.currentData() or '' for combo in choices])
