from contextlib import nullcontext
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from comic_translate_core.release_update import (
    Asset, Release, REPOSITORY_URL, delta_name, installer_name, latest_stable, prepare_update,
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

    def test_only_exact_release_assets_with_digest_can_be_downloaded(self):
        name = installer_name('2.6.0')
        item = {'name': name, 'size': 1024, 'digest': 'sha256:' + 'a' * 64,
                'browser_download_url': f'{REPOSITORY_URL}/releases/download/v2.6.0/{name}'}
        data = {'tag_name': 'v2.6.0', 'html_url': 'https://example.com/fake', 'assets': [item]}
        release = latest_stable(data, '2.5.2')
        self.assertEqual(release.url, f'{REPOSITORY_URL}/releases/tag/v2.6.0')
        self.assertEqual(release.installer.sha256, 'a' * 64)
        item['browser_download_url'] = 'https://example.com/' + name
        self.assertIsNone(latest_stable(data, '2.5.2').installer)

    def test_release_selects_the_installed_format_and_its_delta(self):
        names = [installer_name('2.6.0'), installer_name('2.6.0', setup=True),
                 delta_name('2.5.2', '2.6.0'), delta_name('2.5.2', '2.6.0', setup=True)]
        url = f'{REPOSITORY_URL}/releases/download/v2.6.0/'
        assets = [{'name': name, 'size': 1024, 'digest': 'sha256:' + 'a' * 64,
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
