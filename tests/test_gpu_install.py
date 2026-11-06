"""Offline checks of the portable runtime installer and its promotion step."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from comic_translate_core import gpu_install


class PortableRuntimeTests(unittest.TestCase):
    def test_verified_package_is_installed_as_a_unit_and_can_be_reused(self):
        self._run_install(corrupt=False)

    def test_download_hash_failure_leaves_no_runtime(self):
        self._run_install(corrupt=True)

    def _run_install(self, *, corrupt):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / 'assets'
            assets.mkdir()
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                for name in gpu_install.REQUIRED:
                    archive.writestr('nvidia/bin/' + name, b'test')
                archive.writestr('nvidia.dist-info/LICENSE', b'license')
            data = stream.getvalue()
            metadata = [{'name': 'fixture', 'version': '1', 'bytes': len(data),
                         'sha256': '0' * 64 if corrupt else hashlib.sha256(data).hexdigest(),
                         'url': 'https://example.invalid/fixture.whl'}]
            (assets / 'gpu-runtime-windows.json').write_text(json.dumps(metadata))
            response = MagicMock()
            response.__enter__.return_value.iter_content.return_value = [data]
            with patch.object(gpu_install.sys, '_MEIPASS', str(root), create=True), patch.object(gpu_install.requests, 'get', return_value=response) as get:
                if corrupt:
                    with self.assertRaisesRegex(ValueError, 'SHA256'):
                        gpu_install.install(root=root)
                    self.assertEqual(list((root / 'gpu-runtime').iterdir()), [])
                else:
                    target = gpu_install.install(root=root)
                    self.assertEqual((target / 'fixture/LICENSE').read_bytes(), b'license')
                    self.assertEqual(gpu_install.install(root=root), target)
                get.assert_called_once()
