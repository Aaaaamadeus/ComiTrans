"""Build the ComiTrans Windows installer with NSIS Modern UI 2."""

import argparse
import json
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comic_translate_core.release_update import (
    DELTA_BLOCK_SIZE, DELTA_COPY, DELTA_FRAME, DELTA_LIMIT, DELTA_OVERLAP, SETUP_DELTA_BLOCK_SIZE,
    VERSION, delta_name, installer_name,
)
from comic_translate_desktop import __version__
from package_release import MODEL_ARCHIVE_PREFIX, MODEL_FILES, collect_app, collect_models, legacy_detector_entry

ICON = ROOT / 'assets/ComiTrans.ico'


def nsis_literal(value):
    return str(value).replace('$', '$$').replace('"', '$\\"').replace('\n', '$\\r$\\n')


def find_makensis(command):
    candidates = [command, shutil.which('makensis')]
    for folder in ('ProgramFiles(x86)', 'ProgramFiles'):
        if folder in os.environ:
            candidates.append(Path(os.environ[folder]) / 'NSIS/makensis.exe')
    candidates.extend(sorted((ROOT / 'build/installer-native-tools').glob('nsis-*/makensis.exe'), reverse=True))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FileNotFoundError('Install NSIS 3 or pass --makensis PATH')


def nsis_inputs(payload, work):
    """Embed an explicit uninstall list; never recursively delete an installation directory."""
    files = sorted(path.relative_to(payload) for path in payload.rglob('*') if path.is_file()
                   and path.name not in {'ComiTransReleaseService.exe', 'Uninstall.exe'})
    directories = {parent for path in files for parent in path.parents if parent != Path('.')}
    manifest = work / 'uninstall-files.nsh'
    manifest.write_text('\n'.join(
        [f'Delete "$INSTDIR\\{nsis_literal(path)}"' for path in files] +
        [f'RMDir "$INSTDIR\\{nsis_literal(path)}"' for path in
         sorted(directories, key=lambda path: (len(path.parts), str(path)), reverse=True)]
    ) + '\n', encoding='utf-8-sig')
    languages = {'en': 'ENGLISH', 'zh-CN': 'SIMPCHINESE', 'zh-TW': 'TRADCHINESE', 'ja': 'JAPANESE'}
    strings = json.loads((ROOT / 'installer/nsis_strings.json').read_text('utf-8'))
    if set(strings) != set(languages) or any(set(texts) != set(strings['en']) for texts in strings.values()):
        raise ValueError('Installer languages must contain the same strings')
    localization = work / 'languages.nsh'
    localization.write_text('\n'.join(
        f'LangString {key} ${{LANG_{languages[locale]}}} "{nsis_literal(value)}"'
        for locale, texts in strings.items() for key, value in texts.items()
    ) + '\n', encoding='utf-8-sig')
    return manifest, localization


def stage_app(dist, stage, *, include_models=True):
    files = collect_app(dist, portable_tools=False)
    if include_models:
        files.extend((source, f'ComiTrans/_internal/comic-translate-ai/models/{name.removeprefix(MODEL_ARCHIVE_PREFIX)}')
                     for source, name in collect_models())
    stage.mkdir(parents=True)
    for source, archive_path in files:
        target = stage / archive_path.removeprefix('ComiTrans/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    license_file = ROOT / 'LICENSE'
    if license_file.is_file():
        shutil.copyfile(license_file, stage / 'LICENSE')
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    version_file = stage.parent / f'{stage.name}-version.cs'
    version_file.write_text(
        f'[assembly: System.Reflection.AssemblyVersion("{__version__}.0")]\n'
        '[assembly: System.Reflection.AssemblyProduct("ComiTrans")]\n'
        f'[assembly: System.Reflection.AssemblyInformationalVersion("{__version__}")]\n',
        encoding='ascii',
    )
    try:
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                        '/reference:System.ServiceProcess.dll', f'/out:{stage / "ComiTransReleaseService.exe"}',
                        str(ROOT / 'installer/ReleaseService.cs'), str(version_file)], check=True)
    finally:
        version_file.unlink()


def compile_nsis(makensis, payload, work, output, **extra):
    manifest, localization = nsis_inputs(payload, work)
    defines = {'VERSION': __version__, 'PAYLOAD': payload, 'ICON': ICON, 'OUTPUT': output,
               'UNINSTALL_FILES': manifest, 'LOCALIZATION': localization, **extra}
    command = [makensis, '/V2', '/WX', '/INPUTCHARSET', 'UTF8']
    command.extend(f'/D{key}={nsis_literal(value)}' for key, value in defines.items())
    command.append(str(ROOT / 'installer/ComiTrans.nsi'))
    subprocess.run(command, check=True)


def build_uninstaller(makensis, payload, work):
    generator = work / 'write-uninstaller.exe'
    target = payload / 'Uninstall.exe'
    compile_nsis(makensis, payload, work, generator, GENERATE_UNINSTALLER='1', UNINSTALLER_OUT=target)
    if not target.is_file():
        raise FileNotFoundError('NSIS did not generate the uninstaller')


def build_setup(makensis, payload, output, work):
    for name in ('ComiTrans.exe', 'ComiTransReleaseService.exe', 'Uninstall.exe'):
        if not (payload / name).is_file():
            raise FileNotFoundError(f'Missing installer payload: {payload / name}')
    validate_installer_models(payload)
    output.mkdir(parents=True, exist_ok=True)
    target = output / installer_name(__version__, setup=True)
    compile_nsis(makensis, payload, work, target)
    print(target, flush=True)
    return target


def validate_installer_models(payload):
    """A direct installer must contain every model needed by its default pipeline."""
    from scripts.model_package import verify

    models = payload / '_internal/comic-translate-ai/models'
    for relative in (*MODEL_FILES, legacy_detector_entry()['path']):
        path = models / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f'Full installer is missing a required model: {path}')
    for name in ('charspot-small', 'split-detector'):
        manifest = ROOT / f'docs/models/{name}.json'
        verify(models / name, json.loads(manifest.read_text('utf-8')))
        if (models / name / 'model-manifest.json').read_bytes() != manifest.read_bytes():
            raise ValueError(f'Full installer has an inconsistent {name} manifest')


def build_delta(base, target):
    """Build a delta using the exact signed installers distributed to users."""
    import zstandard as zstd

    setup = target.suffix == '.exe'
    block_size = SETUP_DELTA_BLOCK_SIZE if setup else DELTA_BLOCK_SIZE
    suffix = installer_name('', setup=setup).removeprefix('ComiTrans-v')

    def version(path):
        name = path.name.removeprefix('ComiTrans-v').removesuffix(suffix)
        if not VERSION.fullmatch(name) or path.name != installer_name(name, setup=setup):
            raise ValueError(f'Unexpected installer filename: {path.name}')
        return name

    source, destination = map(version, (base, target))
    if tuple(map(int, source.split('.'))) >= tuple(map(int, destination.split('.'))):
        raise ValueError('Delta target must be newer than its base')
    base_size, target_size = base.stat().st_size, target.stat().st_size
    if not base_size or not target_size:
        raise ValueError('Delta installers must be non-empty')
    if max(base_size, target_size) > DELTA_LIMIT:
        print('Installer exceeds delta size limit. Distribute the full installer.', flush=True)
        return
    delta = target.parent / delta_name(source, destination, setup=setup)
    temporary = delta.with_suffix('.partial')
    encoder = zstd.ZstdCompressor(level=5)
    try:
        with (base.open('rb') as previous, target.open('rb') as source_file, temporary.open('wb') as output,
              mmap.mmap(previous.fileno(), 0, access=mmap.ACCESS_READ) as base_bytes):
            for offset in range(0, target_size, block_size):
                block = source_file.read(block_size)
                # Compressed installer data can shift. Search nearby blocks for reusable bytes.
                start = max(0, offset - DELTA_OVERLAP)
                position = base_bytes.find(block, start, offset + len(block) + DELTA_OVERLAP)
                if position >= 0:
                    output.write(DELTA_FRAME.pack(DELTA_COPY | position))
                    continue
                frame = encoder.compress(block)
                output.write(DELTA_FRAME.pack(len(frame)))
                output.write(frame)
        if temporary.stat().st_size * 10 > target_size * 9:
            print('Delta saves less than 10% of the full installer download.', flush=True)
        else:
            temporary.replace(delta)
            print(delta, flush=True)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist/ComiTrans')
    parser.add_argument('--output', type=Path, default=ROOT / 'release' / f'v{__version__}')
    parser.add_argument('--makensis', help='Path to the NSIS 3 makensis.exe compiler')
    parser.add_argument('--include-models', action='store_true', default=True,
                        help='Embed release models in Setup (always enabled for a direct installer)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--stage-only', action='store_true', help='Stage payload and uninstaller for signing')
    mode.add_argument('--payload', type=Path, help='Build Setup from an already staged/signed payload')
    mode.add_argument('--delta', nargs=2, type=Path, metavar=('PREVIOUS_INSTALLER', 'NEW_INSTALLER'))
    args = parser.parse_args()
    if args.delta:
        build_delta(*args.delta)
        return
    makensis = find_makensis(args.makensis)
    parts = __version__.split('.')
    if len(parts) != 3 or any(not part.isdigit() or int(part) > 65535 for part in parts):
        raise ValueError('NSIS requires a three-part numeric release version')
    work_root = ROOT / 'build'
    work_root.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='nsis-', dir=work_root) as directory:
        work = Path(directory)
        output = args.output.resolve()
        if args.payload:
            payload = args.payload.resolve()
        else:
            payload = output / 'payload' if args.stage_only else work / 'payload'
            stage_app(args.dist.resolve(), payload, include_models=args.include_models)
            build_uninstaller(makensis, payload, work)
        if args.stage_only:
            print(payload, flush=True)
        else:
            build_setup(makensis, payload, output, work)


if __name__ == '__main__':
    main()
