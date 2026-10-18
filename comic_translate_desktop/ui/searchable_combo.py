"""Search an existing font choice without creating arbitrary new values."""
from ..i18n import tr
from PySide6.QtCore import QIdentityProxyModel, Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QSizePolicy

SEARCH_ROLE = Qt.UserRole + 1


class _FontSearchModel(QIdentityProxyModel):
    def data(self, index, role=Qt.DisplayRole):
        if role == SEARCH_ROLE:
            label = super().data(index, Qt.DisplayRole) or ''
            details = super().data(index, Qt.ToolTipRole) or ''
            return f'{label} {details}'
        return super().data(index, role)


class _FontCompleter(QCompleter):
    def pathFromIndex(self, index):
        return index.data(Qt.DisplayRole) or ''


class SearchableFontCombo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMinimumContentsLength(8)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lineEdit().setPlaceholderText(tr('输入字体名称检索…'))
        self.lineEdit().setObjectName('fontSearchEditor')
        self.lineEdit().setClearButtonEnabled(True)
        self._search_model = _FontSearchModel(self)
        self._search_model.setSourceModel(self.model())
        self.setCompleter(_FontCompleter(self._search_model, self))
        self.completer().setCompletionRole(SEARCH_ROLE)
        self.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.completer().setFilterMode(Qt.MatchContains)
        self.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.currentIndexChanged.connect(self._show_name_start)
        self.lineEdit().textEdited.connect(lambda: self._fit_popup(self.completer().popup()))
        self.setMaxVisibleItems(14)

    def _show_name_start(self):
        self.lineEdit().setCursorPosition(0)

    def _fit_popup(self, view):
        view.setFont(self.font())
        screen_width = self.screen().availableGeometry().width() - 24
        text_width = max((view.fontMetrics().horizontalAdvance(self.itemText(row))
                          for row in range(self.count())), default=0)
        width = min(screen_width, max(self.width(), text_width + 64))
        view.setMaximumWidth(screen_width)
        view.setMinimumWidth(width)
        view.setTextElideMode(Qt.ElideNone)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        if hasattr(view, 'setWordWrap'):
            view.setWordWrap(True)

    def showPopup(self):
        self._fit_popup(self.view())
        super().showPopup()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Searching alone must not replace the last real selection.
        self.setEditText(self.itemText(self.currentIndex()))
        self._show_name_start()
