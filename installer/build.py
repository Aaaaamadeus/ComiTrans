"""Stage ComiTrans and build the Windows x64 MSI with WiX 5."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comic_translate_core.release_update import (
    DELTA_BLOCK_SIZE, DELTA_COPY, DELTA_FRAME, DELTA_LIMIT, DELTA_OVERLAP, VERSION, delta_name, installer_name,
)
from comic_translate_desktop import __version__
from package_release import collect_app


def stage_app(dist, stage):
    files = collect_app(dist, portable_tools=False)
    stage.mkdir(parents=True)
    for source, archive_path in files:
        target = stage / archive_path.removeprefix('ComiTrans/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    version_file = stage.parent / f'{stage.name}-version.cs'
    version_file.write_text(f'[assembly: System.Reflection.AssemblyVersion("{__version__}.0")]\n', encoding='ascii')
    try:
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                        '/reference:System.ServiceProcess.dll', f'/out:{stage / "ComiTransReleaseService.exe"}',
                        str(ROOT / 'installer/ReleaseService.cs'), str(version_file)], check=True)
    finally:
        version_file.unlink()


def build_msi(wix, stage, output):
    parts = [int(part) for part in __version__.split('.')]
    if len(parts) != 3 or max(parts[:2]) > 255 or not 0 <= parts[2] <= 65535:
        raise ValueError('An MSI release version needs three numbers within MSI ProductVersion limits')
    output.mkdir(parents=True, exist_ok=True)
    target = output / installer_name(__version__)
    code = uuid5(NAMESPACE_URL, f'https://github.com/Aaaaamadeus/ComiTrans/msi/x64/{__version__}')
    subprocess.run([wix, 'build', '-arch', 'x64', '-d', f'Version={__version__}', '-d', f'ProductCode={code}',
                    '-d', f'Payload={stage}', '-d', f'Icon={ROOT / "assets/ComiTrans.ico"}',
                    '-pdbtype', 'none', '-out', str(target), str(ROOT / 'installer/ComiTrans.wxs')], check=True)
    print(target, flush=True)


def build_delta(base, target):
    """Build a delta using the exact signed MSI binaries distributed to users."""
    import zstandard as zstd

    def version(path):
        name = path.name.removeprefix('ComiTrans-v').removesuffix('-x64.msi')
        if not VERSION.fullmatch(name) or path.name != installer_name(name):
            raise ValueError(f'Unexpected MSI filename: {path.name}')
        return name

    source, destination = map(version, (base, target))
    if tuple(map(int, source.split('.'))) >= tuple(map(int, destination.split('.'))):
        raise ValueError('Delta target must be newer than its base')
    if max(base.stat().st_size, target.stat().st_size) > DELTA_LIMIT:
        print('MSI exceeds delta size limit. Distribute the full installer.', flush=True)
        return
    delta = target.parent / delta_name(source, destination)
    temporary = delta.with_suffix('.partial')
    encoder = zstd.ZstdCompressor(level=5)
    try:
        with base.open('rb') as previous, target.open('rb') as source_file, temporary.open('wb') as output:
            for offset in range(0, target.stat().st_size, DELTA_BLOCK_SIZE):
                block = source_file.read(DELTA_BLOCK_SIZE)
                # Embedded cabinet blocks can shift when the MSI tables grow.
                start = max(0, offset - DELTA_OVERLAP)
                previous.seek(start)
                nearby = previous.read(offset + len(block) + DELTA_OVERLAP - start)
                position = nearby.find(block)
                if position >= 0:
                    output.write(DELTA_FRAME.pack(DELTA_COPY | (start + position)))
                    continue
                frame = encoder.compress(block)
                output.write(DELTA_FRAME.pack(len(frame)))
                output.write(frame)
        if temporary.stat().st_size * 10 >= target.stat().st_size * 9:
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
    parser.add_argument('--wix', default='wix')
    parser.add_argument('--delta', nargs=2, type=Path, metavar=('PREVIOUS_SIGNED_MSI', 'NEW_SIGNED_MSI'))
    args = parser.parse_args()
    if args.delta:
        build_delta(*args.delta)
    else:
        work = ROOT / 'build'
        work.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix='msi-', dir=work) as directory:
            stage = Path(directory) / 'payload'
            stage_app(args.dist.resolve(), stage)
            build_msi(args.wix, stage, args.output.resolve())


if __name__ == '__main__':
    main()
