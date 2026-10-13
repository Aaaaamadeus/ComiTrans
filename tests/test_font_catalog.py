from __future__ import annotations

from hashlib import sha1
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from comic_translate_desktop import config
from comic_translate_desktop.font_catalog import download_face, installed_faces, load_catalog, search_text
from comic_translate_desktop.font_library import resolve_font_reference
from comic_translate_desktop.ui.font_library_dialog import FontLibraryDialog
from comic_translate_desktop.ui.searchable_combo import SearchableFontCombo


ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = {'Content-Length': str(len(content))}


class FontCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, path in (('PROJECT_ROOT', self.root), ('CONFIG_PATH', self.root / 'config.yaml')):
            setting = patch.object(config, name, path)
            setting.start()
            self.addCleanup(setting.stop)
        font = (ROOT / 'assets/ui/fonts/Skribble.ttf').read_bytes()
        license_text = b'Copyright Test Authors\nSIL Open Font License, Version 1.1\n'
        self.content = {'font.ttf': font, 'OFL.txt': license_text}
        def asset(name):
            content = self.content[name]
            return dict(path='ofl/test/' + name, size=len(content), name=name,
                        sha1=sha1(f'blob {len(content)}\0'.encode() + content).hexdigest())
        self.family = dict(id='ofl/test', name='Test', category='handwriting', subsets=['latin'],
                           license='OFL-1.1', licenses=[asset('OFL.txt')], faces=[asset('font.ttf')])
        self.catalog = dict(schema=1, repository='google/fonts', revision='a' * 40, families=[self.family])

    def request(self, request, timeout):
        return Response(self.content[Path(request.full_url).name])

    def dialog(self):
        dialog = FontLibraryDialog(config.load_ai_config())
        self.addCleanup(dialog.close)
        return dialog

    def wait_download(self, dialog):
        for _ in range(200):
            if dialog._worker is None:
                return
            QTest.qWait(10)
        self.fail('Font download thread did not finish')

    def test_complete_offline_catalog_contains_faces_languages_licenses_and_alias_search(self):
        catalog = load_catalog()
        self.assertGreaterEqual(len(catalog['families']), 2000)
        self.assertGreaterEqual(sum(len(f['faces']) for f in catalog['families']), 3800)
        self.assertEqual(len({f['id'] for f in catalog['families']}), len(catalog['families']))
        wenkai = next(f for f in catalog['families'] if f['name'] == 'LXGW WenKai TC')
        self.assertIn('霞鹜', search_text(wenkai))
        self.assertIn('繁体中文', search_text(wenkai))
        for family in catalog['families']:
            for asset in (*family['faces'], *family['licenses']):
                self.assertEqual(len(asset['sha1']), 40)
                self.assertTrue(asset['path'].startswith(family['id'] + '/'))

    def test_download_verifies_font_and_license_and_reuses_them_offline(self):
        with patch('comic_translate_desktop.font_catalog.load_catalog', return_value=self.catalog), \
             patch('comic_translate_desktop.font_catalog.urlopen', side_effect=self.request) as network:
            reference = download_face(self.family, self.family['faces'][0])
        self.assertEqual(network.call_count, 2)
        path = resolve_font_reference(reference)
        self.assertEqual(path.read_bytes(), self.content['font.ttf'])
        licenses = path.parent / 'licenses' / path.stem
        self.assertEqual((licenses / 'OFL.txt').read_bytes(), self.content['OFL.txt'])
        self.assertEqual(json.loads((licenses / 'source.json').read_text())['revision'], 'a' * 40)
        self.assertEqual(installed_faces()[self.family['faces'][0]['sha1']], reference)
        with patch('comic_translate_desktop.font_catalog.load_catalog', return_value=self.catalog), \
             patch('comic_translate_desktop.font_catalog.urlopen', side_effect=AssertionError('offline')):
            self.assertEqual(download_face(self.family, self.family['faces'][0]), reference)

    def test_corrupt_download_and_cancellation_leave_no_available_font(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), \
                 patch('comic_translate_desktop.font_catalog.load_catalog', return_value=self.catalog), \
                 patch('comic_translate_desktop.font_catalog.urlopen', return_value=Response(b'incomplete')):
                with self.assertRaises((ValueError, InterruptedError)):
                    download_face(self.family, self.family['faces'][0], cancelled=lambda: cancel)
            self.assertFalse((self.root / 'user_fonts').exists())

    def test_font_library_filters_by_alias_language_style_and_download_status(self):
        dialog = self.dialog()
        dialog.search.setText('霞鹜')
        self.assertGreater(dialog.font_list.count(), 0)
        self.assertTrue(all('LXGW' in dialog.font_list.item(i).data(Qt.UserRole)['name']
                            for i in range(dialog.font_list.count())))
        dialog.search.clear()
        dialog.language.setCurrentIndex(dialog.language.findData('chinese-simplified'))
        dialog.category.setCurrentIndex(dialog.category.findData('handwriting'))
        self.assertGreater(dialog.font_list.count(), 0)
        for i in range(dialog.font_list.count()):
            family = dialog.font_list.item(i).data(Qt.UserRole)
            self.assertIn('chinese-simplified', family['subsets'])
            self.assertEqual(family['category'], 'handwriting')
        dialog.availability.setCurrentIndex(1)
        self.assertEqual(dialog.font_list.count(), 0)
        self.assertFalse(dialog.use_button.isEnabled())

    def test_font_library_background_download_and_failed_retry(self):
        with patch('comic_translate_desktop.ui.font_library_dialog.load_catalog', return_value=self.catalog):
            dialog = self.dialog()
        dialog.show()
        with patch('comic_translate_desktop.ui.font_library_dialog.download_face', side_effect=OSError('offline')):
            dialog._use_font()
            self.wait_download(dialog)
        self.assertIn('下载失败', dialog.status.text())
        self.assertTrue(dialog.use_button.isEnabled())
        with patch('comic_translate_desktop.ui.font_library_dialog.download_face', return_value='user_fonts/test.ttf'):
            dialog._use_font()
            self.wait_download(dialog)
        self.assertEqual(dialog.reference, 'user_fonts/test.ttf')
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_closing_during_download_cancels_before_destroying_worker(self):
        started = threading.Event()
        def download(*_, cancelled, progress):
            started.set()
            while not cancelled():
                threading.Event().wait(.01)
            raise InterruptedError('cancelled')
        with patch('comic_translate_desktop.ui.font_library_dialog.load_catalog', return_value=self.catalog):
            dialog = self.dialog()
        dialog.show()
        with patch('comic_translate_desktop.ui.font_library_dialog.download_face', side_effect=download):
            dialog._use_font()
            self.assertTrue(started.wait(1))
            dialog.close()
            self.wait_download(dialog)
        self.assertIsNone(dialog.reference)
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertFalse(dialog.isVisible())

    def test_local_font_search_is_contains_case_insensitive_and_does_not_add_values(self):
        combo = SearchableFontCombo()
        self.addCleanup(combo.close)
        combo.addItem('普通对话', 'dialogue')
        combo.addItem('霞鹜文楷 · LXGW WenKai', 'wenkai')
        combo.addItem('思源宋体 · Noto Serif SC', 'serif')
        combo.completer().setCompletionPrefix('sErIf')
        self.assertEqual(combo.completer().completionCount(), 1)
        self.assertEqual(combo.completer().currentCompletion(), '思源宋体 · Noto Serif SC')
        combo.show()
        combo.lineEdit().setFocus()
        combo.lineEdit().selectAll()
        QTest.keyClicks(combo.lineEdit(), 'sErIf')
        QTest.qWait(30)
        popup = combo.completer().popup()
        popup.setCurrentIndex(combo.completer().completionModel().index(0, 0))
        QTest.keyClick(popup, Qt.Key_Return)
        self.assertEqual(combo.currentData(), 'serif')
        combo.lineEdit().setText('不存在的字体')
        QTest.keyClick(combo.lineEdit(), Qt.Key_Return)
        self.assertEqual(combo.count(), 3)
        self.assertEqual(combo.currentData(), 'serif')

    def test_catalog_entry_without_license_cannot_start_download(self):
        family = dict(self.family, licenses=[])
        with patch('comic_translate_desktop.ui.font_library_dialog.load_catalog', return_value=dict(self.catalog, families=[family])):
            dialog = self.dialog()
        self.assertFalse(dialog.use_button.isEnabled())
        self.assertIn('许可证', dialog.status.text())
        with self.assertRaisesRegex(ValueError, '许可证'):
            download_face(family, family['faces'][0])


if __name__ == '__main__':
    unittest.main()
