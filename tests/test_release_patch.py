from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from comic_translate_core.release_patch import (
    MANIFEST_NAME, create_patch, file_record, json_bytes, make_manifest,
    managed_path, read_release, validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


class ReleasePatchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.tools = {
            'Apply-Update.ps1': (ROOT / 'scripts/apply_patch.ps1').read_bytes(),
            'Update-ComiTrans.bat': (ROOT / 'scripts/apply_patch.bat').read_bytes(),
        }
        self.old_files = dict(self.tools, **{'ComiTrans.exe': b'old executable',
                             '_internal/value.dat': b'old value', '_internal/delete.dll': b'remove'})
        self.new_files = dict(self.tools, **{'ComiTrans.exe': b'new executable',
                             '_internal/value.dat': b'new value', '_internal/new.dat': b'added'})
        self.base = self.archive('base.zip', self.old_files, '2.4.0')
        self.target = self.archive('target.zip', self.new_files, '2.4.1')
        self.patch = self.root / 'patch.zip'

    def archive(self, name, files, version, baseline=True):
        manifest = make_manifest(version, {name: file_record(io.BytesIO(data)) for name, data in files.items()})
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as archive:
            for entry, data in files.items(): archive.writestr('ComiTrans/' + entry, data)
            if baseline: archive.writestr('ComiTrans/' + MANIFEST_NAME, json_bytes(manifest))
        return path

    def patch_data(self, transform):
        replacement = self.root / 'modified.zip'
        with zipfile.ZipFile(self.patch) as source, zipfile.ZipFile(replacement, 'w') as destination:
            for entry in source.infolist():
                data = source.read(entry)
                if entry.filename == 'patch.json':
                    metadata = json.loads(data)
                    transform(metadata)
                    data = json_bytes(metadata)
                destination.writestr(entry.filename, data)
        return replacement

    def test_build_fingerprint_is_deterministic_and_validated(self):
        manifest, _ = read_release(self.base)
        reverse = dict(reversed(list(manifest['files'].items())))
        self.assertEqual(make_manifest('2.4.0', reverse)['build_id'], manifest['build_id'])
        manifest['version'] = '2.4.9'
        with self.assertRaises(ValueError): validate_manifest(manifest)

    def test_user_data_and_unsafe_windows_paths_are_rejected(self):
        for name in ['../ComiTrans.exe', '_internal/../config.yaml', '_internal/C:evil',
                     '_internal/NUL.txt', '_internal/cache.', '_internal/a\\b',
                     '_internal/models/a.onnx', '_internal/USER_FONTS/a.ttf',
                     'config.yaml', 'page/a.png', '_internal/.env.key', '_internal/a?.dll']:
            with self.subTest(name=name), self.assertRaises(ValueError): managed_path(name)

    def test_archive_content_is_checked_against_sha256(self):
        bad = self.root / 'bad.zip'
        with zipfile.ZipFile(self.base) as source, zipfile.ZipFile(bad, 'w') as destination:
            for entry in source.infolist():
                destination.writestr(entry.filename, b'modified' if entry.filename.endswith('value.dat') else source.read(entry))
        with self.assertRaisesRegex(ValueError, 'does not match'): read_release(bad)

    def test_patch_contains_only_changed_payload_and_deletion_plan(self):
        plan = create_patch(self.base, self.target, self.patch)
        self.assertEqual(plan['deleted'], ['_internal/delete.dll'])
        with zipfile.ZipFile(self.patch) as archive:
            self.assertEqual({name[6:] for name in archive.namelist() if name.startswith('files/')}, set(plan['changed']))
            self.assertNotIn('files/Apply-Update.ps1', archive.namelist())

    def test_standalone_baseline_generates_same_patch_plan(self):
        baseline, _ = read_release(self.base)
        path = self.root / 'baseline.json'
        path.write_bytes(json_bytes(baseline))
        from_zip = create_patch(self.base, self.target, self.patch)
        from_json = create_patch(path, self.target, self.root / 'other.zip')
        self.assertEqual(from_zip, from_json)

    def test_legacy_archive_requires_explicit_version(self):
        legacy = self.archive('legacy.zip', self.old_files, '2.4.0', baseline=False)
        with self.assertRaisesRegex(ValueError, 'base-version'): create_patch(legacy, self.target, self.patch)
        plan = create_patch(legacy, self.target, self.patch, base_version='2.4.0')
        self.assertFalse(plan['requires_manifest'])

    def test_same_build_and_case_only_renames_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            create_patch(self.base, self.target, self.base)
        with self.assertRaisesRegex(ValueError, 'same build'): create_patch(self.base, self.base, self.patch)
        renamed = dict(self.new_files)
        renamed['_internal/VALUE.dat'] = renamed.pop('_internal/value.dat')
        archive = self.archive('case.zip', renamed, '2.4.1')
        with self.assertRaisesRegex(ValueError, 'Case-only'): create_patch(self.base, archive, self.patch)

    def install(self, archive=None):
        folder = self.root / 'installed'
        with zipfile.ZipFile(archive or self.base) as source: source.extractall(folder)
        installed = folder / 'ComiTrans'
        for name, data in [('config.yaml', b'private-key'), ('user_fonts/my.ttf', b'personal font'),
                           ('comic-translate-ai/models/model.onnx', b'model'), ('page/output.png', b'manga')]:
            path = installed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return installed

    def run_updater(self, installed, patch=None, prefix=''):
        engine = shutil.which('powershell.exe')
        if not engine: self.skipTest('Windows PowerShell is needed for updater integration')
        def quote(path): return "'" + str(path).replace("'", "''") + "'"
        script = (f". {quote(ROOT / 'scripts/apply_patch.ps1')}\n" + prefix +
                  f"try {{ Invoke-ComiTransPatch {quote(patch or self.patch)} {quote(installed)} }} "
                  "catch { Write-Host $_.Exception.Message; exit 1 }")
        encoded = base64.b64encode(script.encode('utf-16le')).decode()
        return subprocess.run([engine, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                               '-EncodedCommand', encoded], capture_output=True, timeout=60)

    def assert_preserved(self, installed):
        for name, data in [('config.yaml', b'private-key'), ('user_fonts/my.ttf', b'personal font'),
                           ('comic-translate-ai/models/model.onnx', b'model'), ('page/output.png', b'manga')]:
            self.assertEqual((installed / name).read_bytes(), data)

    def test_windows_update_applies_add_modify_delete_and_preserves_user_data(self):
        create_patch(self.base, self.target, self.patch)
        installed = self.install()
        result = self.run_updater(installed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, data in self.new_files.items(): self.assertEqual((installed / name).read_bytes(), data)
        self.assertFalse((installed / '_internal/delete.dll').exists())
        self.assertEqual(json.loads((installed / MANIFEST_NAME).read_text(encoding='utf-8-sig')), read_release(self.target)[0])
        self.assert_preserved(installed)

    def test_legacy_same_version_migration_and_extracted_patch_work(self):
        old_files = {'ComiTrans.exe': b'old executable', '_internal/value.dat': b'old value'}
        legacy = self.archive('legacy.zip', old_files, '2.4.0', baseline=False)
        target = self.archive('baseline.zip', self.new_files, '2.4.0')
        create_patch(legacy, target, self.patch, base_version='2.4.0')
        unpacked = self.root / 'unpacked'
        with zipfile.ZipFile(self.patch) as source: source.extractall(unpacked)
        installed = self.install(legacy)
        result = self.run_updater(installed, unpacked)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((installed / MANIFEST_NAME).read_text(encoding='utf-8-sig'))['version'], '2.4.0')
        self.assert_preserved(installed)

    def test_wrong_build_or_modified_file_refuses_before_updating(self):
        create_patch(self.base, self.target, self.patch)
        installed = self.install()
        (installed / '_internal/value.dat').write_bytes(b'user modified this file')
        result = self.run_updater(installed)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'File does not match', result.stdout)
        self.assertEqual((installed / 'ComiTrans.exe').read_bytes(), b'old executable')
        self.assert_preserved(installed)

    def test_payload_hash_failure_does_not_modify_the_program(self):
        create_patch(self.base, self.target, self.patch)
        unpacked = self.root / 'unpacked'
        with zipfile.ZipFile(self.patch) as source: source.extractall(unpacked)
        (unpacked / 'files/_internal/value.dat').write_bytes(b'wrong size and bytes')
        installed = self.install()
        result = self.run_updater(installed, unpacked)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((installed / 'ComiTrans.exe').read_bytes(), b'old executable')

    def test_unlisted_or_protected_operations_are_rejected(self):
        create_patch(self.base, self.target, self.patch)
        patch = self.patch_data(lambda data: data['deleted'].append('config.yaml'))
        installed = self.install()
        result = self.run_updater(installed, patch)
        self.assertNotEqual(result.returncode, 0)
        self.assert_preserved(installed)

    def test_failed_write_rolls_back_completed_changes_and_manifest(self):
        create_patch(self.base, self.target, self.patch)
        installed = self.install()
        manifest = (installed / MANIFEST_NAME).read_bytes()
        prefix = """
function Move-Item {
    param($LiteralPath, $Destination, [switch]$Force)
    if ($Destination.EndsWith('value.dat')) { throw 'simulated disk failure' }
    Microsoft.PowerShell.Management\\Move-Item -LiteralPath $LiteralPath -Destination $Destination -Force
}
"""
        result = self.run_updater(installed, prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        for name, data in self.old_files.items(): self.assertEqual((installed / name).read_bytes(), data)
        self.assertEqual((installed / MANIFEST_NAME).read_bytes(), manifest)
        self.assertFalse((installed / '_internal/new.dat').exists())
        journals = list((installed / '.comitrans-update').glob('*/journal.json'))
        self.assertEqual(len(journals), 1)
        self.assertEqual(json.loads(journals[0].read_text(encoding='utf-8-sig'))['status'], 'rolled-back')
        self.assert_preserved(installed)


if __name__ == '__main__': unittest.main()
