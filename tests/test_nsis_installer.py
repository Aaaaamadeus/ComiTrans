import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from installer.build import (build_setup, build_uninstaller, find_makensis, nsis_inputs,
                             nsis_literal, validate_installer_models)


ROOT = Path(__file__).resolve().parents[1]


class NsisInstallerTests(unittest.TestCase):
    def test_full_installer_rejects_missing_models(self):
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, 'missing a required model'):
                validate_installer_models(Path(directory))

    @unittest.skipUnless(os.name == 'nt', 'NSIS integration requires Windows')
    def test_folder_creation_reinstall_and_uninstall_with_native_service_arguments(self):
        """Run real NSIS programs, isolating registry/shortcuts and substituting only SCM."""
        try:
            compiler = find_makensis(None)
        except FileNotFoundError as error:
            self.skipTest(str(error))
        zig = next((ROOT / 'build/installer-native-tools').glob('zig-*/zig.exe'), None)
        if not zig:
            self.skipTest('Native SCM argument fixture requires portable Zig')
        import pefile
        import winreg

        with TemporaryDirectory() as directory:
            work = Path(directory)
            fixture = work / 'service-api.dll'
            subprocess.run([str(zig), 'cc', '-target', 'x86-windows-gnu', '-shared', '-O2',
                            '-Wno-dll-attribute-on-redeclaration',
                            str(ROOT / 'tests/installer_fixtures/service_api.c'),
                            '-o', str(fixture)], check=True,
                           env={**os.environ, 'ZIG_GLOBAL_CACHE_DIR': str(ROOT / 'build/zig-cache')})
            key = 'Software\\ComiTransInstallerTest_' + uuid4().hex
            service_dir = work / '服务 with spaces'
            menu, desktop = work / 'menu', work / 'desktop'
            menu.mkdir()
            desktop.mkdir()
            source = (ROOT / 'installer/ComiTrans.nsi').read_text('utf-8')
            source = source.replace('RequestExecutionLevel admin', 'RequestExecutionLevel user')
            source = source.replace('HKLM', 'HKCU').replace('Software\\ComiTrans', key)
            source = source.replace('Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\ComiTrans', key + '\\Uninstall')
            source = source.replace('Software\\Classes', key + '\\Classes')
            source = source.replace('$PROGRAMFILES64\\ComiTrans Release Service', nsis_literal(service_dir))
            source = source.replace('$SMPROGRAMS', nsis_literal(menu)).replace('$DESKTOP', nsis_literal(desktop))
            source = source.replace('Global\\ComiTransSetup', 'Local\\' + key.rsplit('\\', 1)[-1])
            with pefile.PE(str(fixture)) as pe:
                exports = [entry.name.decode('ascii') for entry in pe.DIRECTORY_ENTRY_EXPORT.symbols]
            for name in ('OpenSCManagerW', 'OpenServiceW', 'CreateServiceW', 'ChangeServiceConfigW',
                         'StartServiceW', 'QueryServiceStatus', 'ControlService', 'DeleteService', 'CloseServiceHandle'):
                exported = next(entry for entry in exports if entry == name or entry.startswith(name + '@'))
                source = source.replace('advapi32::' + name + '(', str(fixture) + '::' + exported + '(')
            script = work / 'installer.nsi'
            script.write_text(source, encoding='utf-8')
            payload = work / 'payload'
            payload.mkdir()
            (payload / 'ComiTrans.exe').write_bytes(b'fixture application')
            (payload / 'ComiTransReleaseService.exe').write_bytes(b'fixture service')
            nested = payload / '_internal' / '中文'
            nested.mkdir(parents=True)
            (nested / 'runtime.txt').write_text('runtime', encoding='utf-8')
            manifest, languages = nsis_inputs(payload, work)

            def compile_fixture(output, **extra):
                defines = {'VERSION': '2.6.0', 'OUTPUT': output, 'PAYLOAD': payload,
                           'ICON': ROOT / 'assets/ComiTrans.ico', 'UNINSTALL_FILES': manifest,
                           'LOCALIZATION': languages, **extra}
                command = [compiler, '/V2', '/WX', '/INPUTCHARSET', 'UTF8']
                command.extend(f'/D{name}={nsis_literal(value)}' for name, value in defines.items())
                subprocess.run([*command, str(script)], check=True)

            compile_fixture(work / 'generator.exe', GENERATE_UNINSTALLER='1',
                            UNINSTALLER_OUT=payload / 'Uninstall.exe')
            setup = work / 'ComiTrans-Fixture.exe'
            compile_fixture(setup)
            api_log = work / 'service-api.log'
            state_file = work / 'service-state'
            environment = {**os.environ, 'COMITRANS_FIXTURE_LOG': str(api_log),
                           'COMITRANS_FIXTURE_STATE': str(state_file),
                           'COMITRANS_FIXTURE_BINARY': f'"{service_dir / "ComiTransReleaseService.exe"}"'}

            def run(executable, *arguments):
                # NSIS requires /D= to be the final, unquoted command-line tail.
                command = subprocess.list2cmdline([str(executable)]) + ' /S /LOG="' + str(work / 'install.log') + '"'
                command += ''.join(' ' + argument for argument in arguments)
                result = subprocess.run(command, env=environment, timeout=30)
                log = work / 'install.log'
                self.assertEqual(result.returncode, 0, log.read_text('utf-16-le') if log.exists() else command)

            def read_registration():
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key + '\\Installer', 0,
                                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as installed:
                    return winreg.QueryValueEx(installed, 'InstallDir')[0]

            for name, full_path in (('new nested 中文', False), ('existing parent', False), ('explicit', True)):
                with self.subTest(directory=name):
                    parent = work / name
                    if name == 'existing parent':
                        parent.mkdir()
                        (parent / 'parent-data.txt').write_text('keep', encoding='utf-8')
                    destination = parent / 'ComiTrans'
                    run(setup, '/D=' + str(destination if full_path else parent))
                    self.assertEqual(Path(read_registration()), destination)
                    self.assertTrue((destination / '_internal/中文/runtime.txt').is_file())
                    self.assertFalse((destination / 'ComiTrans').exists())
                    # A reinstall must stop/configure/start the same service and preserve the path.
                    run(setup)
                    self.assertEqual(Path(read_registration()), destination)
                    sentinel = destination / 'keep-user-file.txt'
                    sentinel.write_text('keep', encoding='utf-8')
                    run(destination / 'Uninstall.exe')
                    for _ in range(50):
                        if not (destination / 'Uninstall.exe').exists():
                            break
                        time.sleep(0.1)
                    self.assertEqual(list(destination.iterdir()), [sentinel])
                    self.assertFalse(state_file.exists())
                    self.assertFalse(service_dir.exists())
                    with self.assertRaises(FileNotFoundError):
                        read_registration()
                    if name == 'existing parent':
                        self.assertTrue((parent / 'parent-data.txt').exists())
            calls = api_log.read_text('utf-16-le').splitlines()
            self.assertNotIn('INVALID CONFIGURATION', calls)
            self.assertEqual(calls.count('create'), 3)
            self.assertEqual(calls.count('configure'), 3)
            self.assertEqual(calls.count('start'), 6)
            self.assertEqual(calls.count('delete'), 3)
            # Only empty keys under this test's unique namespace can remain.
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key + '\\Classes')
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)

    def test_uninstall_manifest_only_removes_packaged_files(self):
        with TemporaryDirectory() as directory:
            work = Path(directory)
            payload = work / 'payload'
            nested = payload / '_internal' / '中文 $asset'
            nested.mkdir(parents=True)
            (nested / 'runtime.dll').write_bytes(b'runtime')
            (payload / 'ComiTrans.exe').write_bytes(b'app')
            (payload / 'ComiTransReleaseService.exe').write_bytes(b'service')
            (payload / 'Uninstall.exe').write_bytes(b'uninstall')
            manifest, _ = nsis_inputs(payload, work)
            text = manifest.read_text('utf-8-sig')
            self.assertIn('Delete "$INSTDIR\\_internal\\中文 $$asset\\runtime.dll"', text)
            self.assertIn('Delete "$INSTDIR\\ComiTrans.exe"', text)
            self.assertNotIn('ReleaseService', text)
            self.assertNotIn('Uninstall.exe', text)
            self.assertNotIn('/r', text)
            self.assertNotIn('*', text)
            self.assertNotIn('$LOCALAPPDATA', text)
            self.assertLess(text.index('runtime.dll'), text.index('RMDir'))
            self.assertLess(text.index('RMDir "$INSTDIR\\_internal\\中文'),
                            text.index('RMDir "$INSTDIR\\_internal"'))

    def test_installer_translations_match_application_catalogs(self):
        strings = json.loads((ROOT / 'installer/nsis_strings.json').read_text('utf-8'))
        self.assertEqual(set(strings), {'en', 'ja', 'zh-CN', 'zh-TW'})
        for locale, texts in strings.items():
            self.assertEqual(set(texts), set(strings['en']))
            if locale in {'en', 'ja'}:
                catalog = json.loads((ROOT / f'assets/i18n/{locale}.json').read_text('utf-8'))
                for key, value in texts.items():
                    self.assertEqual(catalog[f'installer.{key}'], value)

    @unittest.skipUnless(os.name == 'nt', 'NSIS PE compilation requires Windows')
    def test_setup_and_exported_uninstaller_compile_with_admin_manifests(self):
        try:
            compiler = find_makensis(None)
        except FileNotFoundError as error:
            self.skipTest(str(error))
        import pefile

        with TemporaryDirectory() as directory:
            work = Path(directory)
            payload = work / 'payload'
            payload.mkdir()
            (payload / 'ComiTrans.exe').write_bytes(b'fixture app')
            (payload / 'ComiTransReleaseService.exe').write_bytes(b'fixture service')
            (payload / '中文 $file.txt').write_text('fixture', encoding='utf-8')
            build_uninstaller(compiler, payload, work)
            with patch('installer.build.validate_installer_models'):
                setup = build_setup(compiler, payload, work, work)
            for executable in (setup, payload / 'Uninstall.exe'):
                with self.subTest(executable=executable.name), pefile.PE(str(executable)) as pe:
                    manifests = [entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries if entry.id == 24]
                    self.assertEqual(len(manifests), 1)
                    entry = manifests[0].directory.entries[0].directory.entries[0].data.struct
                    manifest = pe.get_data(entry.OffsetToData, entry.Size).decode('utf-8')
                    self.assertIn('level="requireAdministrator"', manifest)
                    strings = pe.FileInfo[0][0].StringTable[0].entries
                    self.assertEqual(strings[b'ProductName'], b'ComiTrans')
