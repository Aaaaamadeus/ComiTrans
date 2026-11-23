"""Nine persistent font slots shared by the editor bar and number keys."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ..font_library import available_fonts, font_description, font_display_name, font_reference, inspect_font, resolve_font_reference
from ..i18n import tr
from .manga_components import PanelHeading
from .searchable_combo import SearchableFontCombo
from .theme import set_themed_icon, ui_font


class FavoriteFontBar(QFrame):
    font_selected = Signal(str)
    add_current_requested = Signal()
    hide_requested = Signal()
    slots_changed = Signal(bool)
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
        self.manage_button = QToolButton(self)
        self.manage_button.setText(tr('管理'))
        self.manage_button.setProperty('compact', True)
        self.manage_button.setProperty('role', 'chip')
        self.manage_button.setProperty('menuButton', True)
        self.manage_button.setPopupMode(QToolButton.InstantPopup)
        self.manage_button.setToolTip(tr('管理快捷字体槽位与显示'))
        self.manage_menu = QMenu(self.manage_button)
        self._add_action = self.manage_menu.addAction(tr('加入当前字体'), self.add_current_requested.emit)
        self._settings_action = self.manage_menu.addAction(tr('设置快捷字体…'), self.configure)
        self.manage_menu.addSeparator()
        self._hide_action = self.manage_menu.addAction(tr('隐藏快捷字体栏'), self.hide_requested.emit)
        self.manage_button.setMenu(self.manage_menu)
        heading.addWidget(self.manage_button)
        self.add_button = QPushButton(tr('加入当前字体'), self)
        set_themed_icon(self.add_button, 'plus', size=12)
        self.add_button.clicked.connect(self.add_current_requested)
        self.add_button.hide()
        self.settings_button = QPushButton(tr('设置快捷字体'), self)
        self.settings_button.clicked.connect(self.configure)
        self.settings_button.hide()
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

    def has_active_slots(self):
        return any(bool(slot) for slot in self.slots)

    def set_slots(self, slots):
        self.slots = (list(slots) + [''] * 9)[:9]
        QSettings().setValue(self.SETTINGS_KEY, json.dumps(self.slots, ensure_ascii=False))
        self._refresh()
        self.slots_changed.emit(self.has_active_slots())

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
        self._add_action.setEnabled(self._can_apply)
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
        available = max(0, self.width() - self._heading.sizeHint().width() - 36)
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
        dialog.setMinimumSize(460, 360)
        dialog.resize(560, 560)
        dialog.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName('dialogHeader')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 18, 24, 14)
        header_layout.setSpacing(6)
        header_layout.addWidget(PanelHeading('', '设置快捷字体'))
        hint = QLabel(tr('最多 9 个字体，对应数字键 1–9；留空可清除该快捷键。'))
        hint.setProperty('muted', True)
        hint.setWordWrap(True)
        header_layout.addWidget(hint)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName('dialogScroll')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName('dialogScrollContent')
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(24, 16, 24, 16)
        container_layout.setSpacing(12)

        card = QFrame()
        card.setObjectName('dialogCard')
        form = QFormLayout(card)
        form.setContentsMargins(20, 16, 20, 16)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        fonts = available_fonts(self.config)
        choices = []
        for index, reference in enumerate(self.slots):
            badge = QLabel(f'{index + 1:02d}')
            badge.setObjectName('stepBadge')
            badge.setFont(ui_font(11, QFont.Bold, mono=True))
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(28, 24)

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
            form.addRow(badge, combo)
            choices.append(combo)
        container_layout.addWidget(card)
        container_layout.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        footer = QFrame()
        footer.setObjectName('pageActions')
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 12, 24, 12)
        actions = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = actions.button(QDialogButtonBox.Ok)
        cancel_btn = actions.button(QDialogButtonBox.Cancel)
        if ok_btn is not None:
            ok_btn.setProperty('role', 'primary')
            ok_btn.setDefault(True)
        if cancel_btn is not None:
            cancel_btn.setProperty('role', 'utility')
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        footer_layout.addWidget(actions)
        root.addWidget(footer)

        if dialog.exec() == QDialog.Accepted:
            self.set_slots([combo.currentData() or '' for combo in choices])
