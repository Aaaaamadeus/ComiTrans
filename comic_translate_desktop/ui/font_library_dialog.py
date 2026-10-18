"""Search the complete offline catalog and download a chosen font face."""
from __future__ import annotations
from ..i18n import tr

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                              QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout)

from ..font_catalog import CATEGORY_LABELS, LANGUAGE_LABELS, download_face, installed_faces, load_catalog, search_text
from ..font_library import font_alias, resolve_font_reference


class FontDownloadThread(QThread):
    completed = Signal(str)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, family, face, parent):
        super().__init__(parent)
        self.family, self.face = family, face

    def run(self):
        try:
            reference = download_face(self.family, self.face, cancelled=self.isInterruptionRequested,
                                      progress=self.progress.emit)
            self.completed.emit(reference)
        except Exception as exc:
            self.failed.emit(str(exc))


class FontLibraryDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('开源字体库'))
        self.resize(820, 660)
        self.setMinimumSize(560, 480)
        self.reference = None
        self._settings = settings
        self._worker = None
        self._closing = False
        self._downloaded = None
        self._installed = installed_faces()
        catalog = load_catalog()
        self._families = [(family, search_text(family)) for family in catalog['families']]
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        intro = QLabel(tr('Google Fonts · {_0:,} 款字体族\n完整目录离线检索，按需下载；下载后离线使用。', _0=len(self._families)))
        intro.setWordWrap(True)
        root.addWidget(intro)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('搜索名称、中文别名、语言或风格，例如：霞鹜、中文、手写…'))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(tr('检索开源字体库'))
        root.addWidget(self.search)
        filters = QHBoxLayout()
        self.language = QComboBox()
        self.language.addItem(tr('全部语言'), '')
        for subset, label in LANGUAGE_LABELS.items():
            self.language.addItem(tr(label), subset)
        self.category = QComboBox()
        self.category.addItem(tr('全部风格'), '')
        for category, label in CATEGORY_LABELS.items():
            self.category.addItem(tr(label), category)
        self.availability = QComboBox()
        self.availability.addItem(tr('全部字体'), False)
        self.availability.addItem(tr('已下载'), True)
        for widget in (self.language, self.category, self.availability):
            filters.addWidget(widget)
        root.addLayout(filters)
        self.count = QLabel()
        self.count.setProperty('muted', True)
        root.addWidget(self.count)
        self.font_list = QListWidget()
        self.font_list.setAccessibleName(tr('开源字体检索结果'))
        root.addWidget(self.font_list, 1)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setProperty('muted', True)
        root.addWidget(self.details)
        self.face = QComboBox()
        self.face.setMinimumContentsLength(20)
        self.face.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.face.setAccessibleName(tr('字体款式与字重'))
        root.addWidget(self.face)
        self.preview = QLabel(tr('下载后显示实际字体预览'))
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(52)
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self.progress = QProgressBar()
        self.progress.hide()
        root.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = QPushButton(tr('关闭'))
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.cancel_button)
        self.use_button = QPushButton(tr('下载并使用'))
        self.use_button.setProperty('role', 'primary')
        self.use_button.clicked.connect(self._use_font)
        actions.addWidget(self.use_button)
        root.addLayout(actions)
        self.search.textChanged.connect(self._filter)
        for widget in (self.language, self.category, self.availability):
            widget.currentIndexChanged.connect(self._filter)
        self.font_list.currentItemChanged.connect(self._family_changed)
        self.face.currentIndexChanged.connect(self._face_changed)
        self._filter()

    def _filter(self):
        tokens = self.search.text().casefold().split()
        language, category = self.language.currentData(), self.category.currentData()
        downloaded = self.availability.currentData()
        self.font_list.blockSignals(True)
        self.font_list.clear()
        for family, searchable in self._families:
            if (any(token not in searchable for token in tokens)
                    or language and language not in family['subsets']
                    or category and category != family['category']
                    or downloaded and not any(face['sha1'] in self._installed for face in family['faces'])):
                continue
            badge = tr(' · 已下载') if any(face['sha1'] in self._installed for face in family['faces']) else ''
            alias = font_alias(family['name'])
            name = f'{alias} · {family["name"]}' if alias else family['name']
            item = QListWidgetItem(f"{name}  ·  {tr(CATEGORY_LABELS.get(family['category'], '其它'))}{badge}")
            item.setData(Qt.UserRole, family)
            self.font_list.addItem(item)
        self.font_list.blockSignals(False)
        self.count.setText(tr('{_0:,} / {_1:,} 款字体族', _0=self.font_list.count(), _1=len(self._families)))
        self.font_list.setCurrentRow(0)
        if not self.font_list.count():
            self._family_changed(None)

    def _family_changed(self, item, previous=None):
        self.face.blockSignals(True)
        self.face.clear()
        if item:
            family = item.data(Qt.UserRole)
            languages = ', '.join(tr(LANGUAGE_LABELS.get(subset, subset)) for subset in family['subsets']) or tr('语言信息未收录')
            self.details.setText(f"{family['name']} · {family['license']} · {languages}")
            for face in family['faces']:
                label = face['name'] + (tr(' · 已下载') if face['sha1'] in self._installed else '')
                self.face.addItem(tr(label), face)
        else:
            self.details.setText(tr('没有匹配的字体，请更换关键词或筛选条件。'))
        self.face.blockSignals(False)
        self._face_changed()

    def _face_changed(self):
        self.preview.clear()
        face = self.face.currentData()
        family = self.font_list.currentItem().data(Qt.UserRole) if self.font_list.currentItem() else None
        reference = self._installed.get(face['sha1']) if face else None
        self.use_button.setText(tr('使用此字体') if reference else tr('下载并使用'))
        self.use_button.setEnabled(bool(face and (reference or family['licenses'])))
        if family and not family['licenses']:
            self.status.setText(tr('上游目录缺少独立许可证附件，该条目暂不提供下载。'))
        else:
            self.status.clear()
        if reference:
            self._show_preview(reference)
        else:
            self.preview.setText(tr('下载后显示实际字形；未覆盖的字符会使用内置字体。'))

    def _show_preview(self, reference):
        from vertical_typesetter import VerticalTypesetter
        path = str(resolve_font_reference(reference))
        typesetter = VerticalTypesetter({style: path for style in self._settings['font_map']}, 24,
                                       fallback_fonts=self._settings.get('font_fallbacks'))
        dpr = self.devicePixelRatioF()
        image = Image.new('RGB', (round(500 * dpr), round(52 * dpr)), 'white')
        typesetter.draw_text(image, [0, 0, image.width, image.height], '故事，从这里开始。Aa 0123',
                             'dialogue', direction=0, target_font_size=round(24 * dpr), manual_layout=True)
        pixmap = QPixmap.fromImage(ImageQt(image))
        pixmap.setDevicePixelRatio(dpr)
        self.preview.setPixmap(pixmap)

    def _use_font(self):
        face = self.face.currentData()
        if not face or self._worker:
            return
        reference = self._installed.get(face['sha1'])
        if reference:
            self.reference = reference
            self.accept()
            return
        family = self.font_list.currentItem().data(Qt.UserRole)
        self._downloaded = None
        self._worker = FontDownloadThread(family, face, self)
        self._worker.progress.connect(self._download_progress)
        self._worker.completed.connect(self._download_complete)
        self._worker.failed.connect(self._download_failed)
        self._worker.finished.connect(self._download_finished)
        for widget in (self.search, self.language, self.category, self.availability, self.font_list, self.face, self.use_button):
            widget.setEnabled(False)
        self.cancel_button.setText(tr('取消下载'))
        self.status.setText(tr('正在下载字体与许可证…'))
        self.progress.setRange(0, 0)
        self.progress.show()
        self._worker.start()

    def _download_progress(self, received, total):
        if total:
            self.progress.setRange(0, 100)
            self.progress.setValue(round(received * 100 / total))
        self.status.setText(tr(tr('已下载 {_0:.1f} MB', _0=received / 1048576) + (f' / {total / 1048576:.1f} MB' if total else '')))

    def _download_complete(self, reference):
        self._downloaded = reference

    def _download_failed(self, message):
        self.status.setText(tr('下载失败：{_0}。可以稍后重试；已有字体仍可使用。', _0=message))

    def _download_finished(self):
        worker, self._worker = self._worker, None
        worker.deleteLater()
        if self._closing:
            super().reject()
        elif self._downloaded:
            self.reference = self._downloaded
            self.accept()
        else:
            for widget in (self.search, self.language, self.category, self.availability, self.font_list, self.face, self.use_button):
                widget.setEnabled(True)
            self.progress.hide()
            self.cancel_button.setText(tr('关闭'))

    def reject(self):
        if self._worker:
            self._closing = True
            self._worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.status.setText(tr('正在取消下载…'))
        else:
            super().reject()

    def closeEvent(self, event):
        if self._worker:
            event.ignore()
            self.reject()
        else:
            super().closeEvent(event)
