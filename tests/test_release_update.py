from contextlib import nullcontext
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from comic_translate_core.release_update import (
    Asset, Release, REPOSITORY_URL, SIGNPATH_ASSET_LABEL, delta_name, installer_name, latest_stable, prepare_update,
)
from comic_translate_desktop.pdf_project import project_link_path
from comic_translate_core.windows_install import InstalledProduct, installed_product, original_package
from installer.build import build_delta


class ReleaseUpdateTests(unittest.TestCase):
    def test_only_newer_stable_versions_are_offered(self):
        for release in (None, {}, {'tag_name': 'v2.5.1'}, {'tag_name': 'v2.5.2'},
                        {'tag_name': 'v2.6.0-rc.1'}, {'tag_name': 'v2.6.0', 'prerelease': True},
                        {'tag_name': 'v2.6.0', 'draft': True}):
            with self.subTest(release=release):
                self.assertIsNone(latest_stable(release, '2.5.2'))
        self.assertEqual(latest_stable({'tag_name': 'v2.10.0'}, '2.9.0').version, '2.10.0')

    def test_only_exact_signed_release_assets_with_digest_can_be_downloaded(self):
        name = installer_name('2.6.0')
        item = {'name': name, 'size': 1024, 'digest': 'sha256:' + 'a' * 64,
                'browser_download_url': f'{REPOSITORY_URL}/releases/download/v2.6.0/{name}'}
        data = {'tag_name': 'v2.6.0', 'html_url': 'https://example.com/fake', 'assets': [item]}
        release = latest_stable(data, '2.5.2')
        self.assertEqual(release.url, f'{REPOSITORY_URL}/releases/tag/v2.6.0')
        self.assertIsNone(release.installer)
        item['label'] = SIGNPATH_ASSET_LABEL
        release = latest_stable(data, '2.5.2')
        self.assertEqual(release.installer.sha256, 'a' * 64)
        item['browser_download_url'] = 'https://example.com/' + name
        self.assertIsNone(latest_stable(data, '2.5.2').installer)

    def test_release_selects_the_installed_format_and_its_delta(self):
        names = [installer_name('2.6.0'), installer_name('2.6.0', setup=True),
                 delta_name('2.5.2', '2.6.0'), delta_name('2.5.2', '2.6.0', setup=True)]
        url = f'{REPOSITORY_URL}/releases/download/v2.6.0/'
        assets = [{'name': name, 'label': SIGNPATH_ASSET_LABEL, 'size': 1024, 'digest': 'sha256:' + 'a' * 64,
                   'browser_download_url': url + name} for name in names]
        published = {'tag_name': 'v2.6.0', 'assets': assets}
        for setup in (False, True):
            with self.subTest(setup=setup):
                release = latest_stable(published, '2.5.2', setup=setup)
                self.assertEqual(release.installer.url, url + names[setup])
                self.assertEqual(release.delta.url, url + names[2 + setup])
        self.assertIsNone(latest_stable({**published, 'assets': assets[:1]}, '2.5.2', setup=True).installer)

    def test_registry_preserves_msi_and_setup_installations(self):
        root = Path.cwd()
        source = root / installer_name('2.5.2', setup=True)
        values = {'InstallDir': str(root), 'ProductCode': 'product'}
        registry = Mock(HKEY_LOCAL_MACHINE=1, KEY_READ=2, KEY_WOW64_64KEY=4)

        def read(_key, name):
            if name not in values:
                raise FileNotFoundError(name)
            return values[name], 1

        registry.OpenKey.return_value = nullcontext(object())
        registry.QueryValueEx.side_effect = read
        with patch.dict('sys.modules', winreg=registry), patch('sys.platform', 'win32'), \
             patch('sys.frozen', True, create=True):
            self.assertEqual(installed_product(root), InstalledProduct('product'))
            values['SetupManaged'] = '1'
            self.assertEqual(installed_product(root), InstalledProduct('product', setup=True))
            values['SetupSource'] = str(source)
            product = installed_product(root)
            self.assertTrue(product.setup)
            self.assertEqual(original_package(product), source)
            self.assertIsNone(installed_product(root / 'other'))

    def test_delta_restore_and_fallback_verify_the_full_signed_package(self):
        for setup in (False, True):
            with self.subTest(setup=setup):
                self._check_delta_and_signature(setup)

    def _check_delta_and_signature(self, setup):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / installer_name('2.5.2', setup=setup)
            target = root / installer_name('2.6.0', setup=setup)
            payload = hashlib.shake_256(b'WiX cabinet data').digest(950_000)
            base.write_bytes(payload)
            target.write_bytes(b'new header' + payload)
            build_delta(base, target)
            delta = root / delta_name('2.5.2', '2.6.0', setup=setup)

            def metadata(path):
                return Asset(str(path), path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())

            release = Release('2.6.0', '', metadata(target), metadata(delta), setup)
            downloaded = []

            def download(asset, output, canceled):
                downloaded.append(asset)
                output.write_bytes(Path(asset.url).read_bytes())

            with patch('comic_translate_core.release_update._download', side_effect=download), \
                 patch('comic_translate_core.release_update._powershell', return_value=Mock(**{'wait.return_value': 0})):
                cache = root / 'cache'
                prepared = prepare_update(release, '2.5.2', cache, base, lambda: False)
                self.assertEqual(prepared.read_bytes(), target.read_bytes())
                self.assertEqual(downloaded, [release.delta])
                downloaded.clear()
                base.write_bytes(b'wrong base file')
                prepared = prepare_update(release, '2.5.2', cache, base, lambda: False)
                self.assertEqual(prepared.read_bytes(), target.read_bytes())
                self.assertEqual(downloaded, [release.delta, release.installer])

            with patch('comic_translate_core.release_update._download', side_effect=download), \
                 patch('comic_translate_core.release_update._powershell', return_value=Mock(**{'wait.return_value': 1})):
                blocked = root / 'blocked'
                with self.assertRaisesRegex(ValueError, 'signature'):
                    prepare_update(release, '2.5.2', blocked, None, lambda: False)
                self.assertFalse((blocked / target.name).exists())

    def test_pdf_links_use_the_association_or_find_the_existing_index(self):
        with TemporaryDirectory() as directory:
            pdf = Path(directory) / '漫画.sample.pdf'
            new = pdf.with_suffix('.comitrans')
            old = pdf.with_suffix('.comitrans.json')
            self.assertEqual(project_link_path(pdf), new)
            old.touch()
            self.assertEqual(project_link_path(pdf), old)
            new.touch()
            self.assertEqual(project_link_path(pdf), new)

    def test_update_offer_dialog_dispatches_actions_and_respects_installer_capability(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from shiboken6 import isValid
        from comic_translate_desktop.ui.update_notice import UpdateOfferDialog
        from tests.qt_utils import destroy_widget

        app = QApplication.instance() or QApplication([])
        release = Release('2.6.0', 'https://github.com/Aaaaamadeus/ComiTrans/releases/tag/v2.6.0',
                          Asset('https://example.com/setup.exe', 100, 'a' * 64), None, True)
        events = []
        installed = UpdateOfferDialog('2.5.2', release, can_install=True,
                                      on_release=lambda: events.append('release'),
                                      on_install=lambda: events.append('install'))
        self.addCleanup(lambda: isValid(installed) and destroy_widget(installed))
        self.assertEqual(installed.windowModality(), Qt.WindowModality.NonModal)
        self.assertIsNotNone(installed.install_button)
        self.assertEqual(installed.install_button.property('role'), 'primary')
        self.assertEqual(installed.release_button.property('role'), 'utility')
        installed.install_button.click()
        self.assertEqual(events, ['install'])

        portable = UpdateOfferDialog('2.5.2', release, can_install=False,
                                     on_release=lambda: events.append('release'),
                                     on_install=lambda: events.append('install'))
        self.addCleanup(lambda: isValid(portable) and destroy_widget(portable))
        self.assertIsNone(portable.install_button)
        self.assertEqual(portable.release_button.property('role'), 'primary')
        portable.release_button.click()
        self.assertEqual(events, ['install', 'release'])

    def test_update_progress_dialog_emits_cancel_without_hardcoded_hex_colors(self):
        import ast
        import inspect
        import os
        import re
        import textwrap

        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication, QAbstractButton, QWidget

        from comic_translate_desktop.ui.motion import MonochromeShimmerBar
        from comic_translate_desktop.ui.update_notice import UpdateProgressDialog

        hex_color = re.compile(
            r'(?<![\w#])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})(?![\w-])',
            re.IGNORECASE,
        )
        dialog_source = ast.parse(textwrap.dedent(inspect.getsource(UpdateProgressDialog)))
        for node in ast.walk(dialog_source):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertNotRegex(node.value, hex_color)

        app = QApplication.instance() or QApplication([])
        dialog = UpdateProgressDialog()
        canceled = []
        destroyed = []
        dialog.canceled.connect(lambda: canceled.append(True))
        dialog.destroyed.connect(lambda *_: destroyed.append(True))

        def flush_deferred_deletes():
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()

        try:
            dialog.show()
            app.processEvents()
            self.assertTrue(dialog.isVisible())
            self.assertIsNotNone(dialog.findChild(MonochromeShimmerBar))

            for widget in (dialog, *dialog.findChildren(QWidget)):
                self.assertNotRegex(widget.styleSheet(), hex_color)

            buttons = [
                button for button in dialog.findChildren(QAbstractButton)
                if button.isVisible() and button.isEnabled()
            ]
            cancel_buttons = [
                button for button in buttons
                if 'cancel' in button.objectName().casefold()
                or button.text().replace('&', '').strip(' \u2026.').casefold()
                in {'cancel', '取消', 'キャンセル'}
            ]
            if not cancel_buttons and len(buttons) == 1:
                cancel_buttons = buttons
            self.assertEqual(len(cancel_buttons), 1)

            cancel_buttons[0].click()
            app.processEvents()
            self.assertEqual(canceled, [True])
            if not destroyed:
                self.assertFalse(dialog.isVisible())
                dialog.deleteLater()

            flush_deferred_deletes()
            self.assertEqual(destroyed, [True])
            self.assertEqual(canceled, [True])
        finally:
            if not destroyed:
                dialog.deleteLater()
                flush_deferred_deletes()
