"""Search an existing font choice without creating arbitrary new values."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QSizePolicy


class SearchableFontCombo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMinimumContentsLength(8)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lineEdit().setPlaceholderText('输入字体名称检索…')
        self.lineEdit().setObjectName('fontSearchEditor')
        self.lineEdit().setClearButtonEnabled(True)
        self.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.completer().setFilterMode(Qt.MatchContains)
        self.completer().setCaseSensitivity(Qt.CaseInsensitive)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Searching alone must not replace the last real selection.
        self.setEditText(self.itemText(self.currentIndex()))
