"""First-launch language choice, before loading models or constructing the main UI."""
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..i18n import UI_LANGUAGES, normalize_ui_language, tr


class InterfaceLanguageDialog(QDialog):
    def __init__(self, language='zh-CN', parent=None):
        super().__init__(parent)
        self.setWindowTitle('ComiTrans · Language / 言語 / 语言')
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        title = QLabel('选择界面语言\nChoose your language\n表示言語を選択')
        title.setWordWrap(True)
        layout.addWidget(title)
        self.language_combo = QComboBox()
        self.language_combo.setAccessibleName('界面语言 / Interface language / 表示言語')
        for code, name in UI_LANGUAGES:
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(normalize_ui_language(language)))
        layout.addWidget(self.language_combo)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.continue_button = QPushButton()
        self.continue_button.setProperty('role', 'primary')
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self.accept)
        actions.addWidget(self.continue_button)
        layout.addLayout(actions)
        self.language_combo.currentIndexChanged.connect(self._preview_language)
        self._preview_language()

    def _preview_language(self):
        code = self.language_combo.currentData()
        self.note.setText(tr('以后可在设置中更改。界面语言不影响漫画译文语言。', language=code))
        self.continue_button.setText(tr('继续', language=code))

    @property
    def selected_language(self):
        return self.language_combo.currentData()


def choose_interface_language(language='zh-CN'):
    dialog = InterfaceLanguageDialog(language)
    result = dialog.exec()
    # Closing the chooser uses the requested Chinese default and records it once.
    selected = dialog.selected_language if result == QDialog.Accepted else 'zh-CN'
    dialog.deleteLater()
    return selected
