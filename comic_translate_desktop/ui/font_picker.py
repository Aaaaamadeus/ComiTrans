"""Translation font choice on the workbench, using real output-font previews."""
from __future__ import annotations
from ..i18n import tr

import sys
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .. import config
from comic_translate_core.chinese import convert_chinese
from ..font_library import available_fonts, font_description, font_display_name, font_reference, import_font, inspect_font, resolve_font_reference
from .searchable_combo import SearchableFontCombo


class TranslationFontPicker(QWidget):
    selection_changed = Signal(str)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setObjectName('translationFontPicker')
        self.setAccessibleName(tr('译文默认字体与字体导入'))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(QLabel(tr('译文字体')))
        self.combo = SearchableFontCombo()
        self.combo.setMinimumWidth(160)
        self.combo.setMaximumWidth(320)
        self.combo.setMinimumContentsLength(18)
        self.combo.setSizeAdjustPolicy(SearchableFontCombo.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setToolTip(tr('指定字体用于全部译文；自动匹配保留漫画风格。缺字自动回退到内置中文字体。'))
        self.combo.setAccessibleName(tr('翻译默认字体'))
        row.addWidget(self.combo, 1)
        self.import_button = QPushButton(tr('＋ 导入字体'))
        self.import_button.setProperty('role', 'quiet')
        self.import_button.setProperty('compact', True)
        self.import_button.setToolTip(tr('导入 TTF、OTF、TTC 或 OTC；字体集合使用第一个款式'))
        row.addWidget(self.import_button)
        self.library_button = QPushButton(tr('字体库'))
        self.library_button.setProperty('role', 'quiet')
        self.library_button.setProperty('compact', True)
        self.library_button.setToolTip(tr('检索完整开源字体目录，按需下载后离线使用'))
        self.library_button.clicked.connect(self._open_library)
        row.addWidget(self.library_button)
        self.preview = QLabel()
        self.preview.setFixedHeight(34)
        self.preview.setMaximumWidth(300)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.preview.setAccessibleName(tr('实际译文字体预览'))
        row.addWidget(self.preview, 1)
        row.addStretch(1)
        layout.addLayout(row)
        self.name_label = QLabel()
        self.name_label.setObjectName('fontChoiceName')
        self.name_label.setAccessibleName(tr('译文默认字体完整名称'))
        self.name_label.setTextFormat(Qt.PlainText)
        self.name_label.setWordWrap(True)
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.name_label)
        self.status = QLabel()
        self.status.setProperty('muted', True)
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        layout.addWidget(self.status)
        self.combo.currentIndexChanged.connect(self._selection_changed)
        self.import_button.clicked.connect(self._choose_fonts)
        self.load_config(settings)

    def load_config(self, settings: dict):
        self._settings = settings
        reference = font_reference(settings['translation_font']) if settings.get('translation_font') else ''
        self._refresh_options(reference)
        if reference and not settings.get('translation_font_active', True):
            self.show_error(tr('选择的字体已不可用，当前回退到自动匹配；请重新导入或选择其它字体。'))
        else:
            self.status.setVisible(False)

    def _refresh_options(self, reference):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(tr('自动匹配漫画风格'), '')
        for font in available_fonts(self._settings):
            item_reference = font_reference(font.path)
            name = font_display_name(font) + (tr('（本地）') if item_reference.startswith('user_fonts/') else '')
            self.combo.addItem(tr(name), item_reference)
            self.combo.setItemData(self.combo.count() - 1, font_description(font), Qt.ToolTipRole)
        index = self.combo.findData(reference)
        if index < 0 and reference:
            self.combo.addItem(tr('不可用：{_0}', _0=Path(reference).name), reference)
            index = self.combo.count() - 1
            self.combo.model().item(index).setEnabled(False)
        self.combo.setCurrentIndex(max(0, index))
        self.combo.blockSignals(False)
        self.combo.lineEdit().setCursorPosition(0)
        self._update_preview()

    def _update_preview(self):
        self.name_label.setText(tr(tr('当前字体：') + self.combo.itemText(self.combo.currentIndex())))
        self.name_label.setToolTip(tr(self.combo.itemData(self.combo.currentIndex(), Qt.ToolTipRole) or ''))
        self.name_label.setVisible(bool(self.combo.currentData()))
        if str(config.MAIN_DIR) not in sys.path:
            sys.path.insert(0, str(config.MAIN_DIR))
        from vertical_typesetter import VerticalTypesetter
        reference = self.combo.currentData() or ''
        path = resolve_font_reference(reference) if reference else None
        fonts = self._settings.get('style_font_map') or {
            style: str(config.AI_ROOT / value) for style, value in config.FONT_DEFAULTS.items()
        }
        if path is not None:
            try:
                inspect_font(path)
                fonts = {style: str(path) for style in config.FONT_KEYS}
            except Exception:
                pass
        fallbacks = self._settings.get('font_fallbacks') or [str(config.AI_ROOT / value) for value in config.FONT_DEFAULTS.values()]
        typesetter = VerticalTypesetter(fonts, 18, fallback_fonts=fallbacks)
        dpr = self.devicePixelRatioF()
        image = Image.new('RGB', (round(300 * dpr), round(34 * dpr)), 'white')
        sample = convert_chinese('故事，从这里开始。Aa 0123', self._settings.get('target_language'))
        typesetter.draw_text(image, [0, 0, image.width, image.height], sample,
                             'dialogue', direction=0, target_font_size=round(18 * dpr))
        pixmap = QPixmap.fromImage(ImageQt(image))
        pixmap.setDevicePixelRatio(dpr)
        self.preview.setPixmap(pixmap)
        self.preview.setToolTip(tr(tr('与漫画输出使用相同嵌字器：') + sample))

    def _selection_changed(self):
        self.status.setVisible(False)
        self._update_preview()
        self.selection_changed.emit(self.combo.currentData() or '')

    def _choose_fonts(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr('导入漫画译文字体'), '',
                                               tr('字体 (*.ttf *.otf *.ttc *.otc)'))
        if paths:
            self.import_paths(paths)

    def _open_library(self):
        from .font_library_dialog import FontLibraryDialog
        try:
            dialog = FontLibraryDialog(self._settings, self)
            if dialog.exec() and dialog.reference:
                self._refresh_options(dialog.reference)
                self.selection_changed.emit(dialog.reference)
        except Exception as exc:
            self.show_error(tr('字体库未能打开：{_0}', _0=exc))

    def import_paths(self, paths):
        imported, failures = [], []
        for path in paths:
            try:
                imported.append(import_font(path))
            except Exception as exc:
                failures.append(f'{Path(path).name}：{exc}')
        message = tr('已导入或复用 {_0} 款字体，选择会自动保存。', _0=len({font.path for font in imported})) if imported else ''
        if failures:
            message += tr('\n未导入：') + '；'.join(failures)
        self.status.setText(message.strip())
        self.status.setVisible(bool(message))
        if imported:
            reference = font_reference(imported[-1].path)
            self._refresh_options(reference)
            self.selection_changed.emit(reference)
        return imported

    def show_error(self, message):
        self.status.setText(tr(message))
        self.status.setVisible(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.preview.setVisible(self.width() >= 720)
