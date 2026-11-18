"""Build the ComiTrans Windows MSI and branded Setup EXE with WiX 5."""

import argparse
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, uuid5

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comic_translate_core.release_update import (
    DELTA_BLOCK_SIZE, DELTA_COPY, DELTA_FRAME, DELTA_LIMIT, DELTA_OVERLAP, SETUP_DELTA_BLOCK_SIZE,
    VERSION, delta_name, installer_name,
)
from comic_translate_desktop import __version__
from package_release import collect_app


ICON = ROOT / 'assets/ComiTrans.ico'
BAL = ROOT / '.wix/extensions/WixToolset.Bal.wixext/5.0.2/wixext5/WixToolset.BootstrapperApplications.wixext.dll'


def stage_app(dist, stage):
    files = collect_app(dist, portable_tools=False)
    stage.mkdir(parents=True)
    for source, archive_path in files:
        target = stage / archive_path.removeprefix('ComiTrans/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
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


def build_msi(wix, stage, output):
    parts = [int(part) for part in __version__.split('.')]
    if len(parts) != 3 or max(parts[:2]) > 255 or not 0 <= parts[2] <= 65535:
        raise ValueError('An MSI release version needs three numbers within MSI ProductVersion limits')
    output.mkdir(parents=True, exist_ok=True)
    target = output / installer_name(__version__)
    code = uuid5(NAMESPACE_URL, f'https://github.com/Aaaaamadeus/ComiTrans/msi/x64/{__version__}')
    subprocess.run([wix, 'build', '-arch', 'x64', '-d', f'Version={__version__}', '-d', f'ProductCode={code}',
                    '-d', f'Payload={stage}', '-d', f'Icon={ICON}',
                    '-pdbtype', 'none', '-out', str(target), str(ROOT / 'installer/ComiTrans.wxs')], check=True)
    print(target, flush=True)
    return target


def build_bundle(wix, msi, output):
    if msi.name != installer_name(__version__) or not msi.is_file():
        raise ValueError(f'Expected an existing {installer_name(__version__)}')
    if not BAL.is_file():
        raise FileNotFoundError('Run wix extension add WixToolset.Bal.wixext/5.0.2 from the repository root')
    output.mkdir(parents=True, exist_ok=True)
    target = output / installer_name(__version__, setup=True)
    with TemporaryDirectory(prefix='burn-', dir=ROOT / 'build') as work:
        logo = Path(work) / 'logo.png'
        with Image.open(ICON) as image:
            image.thumbnail((64, 64), Image.Resampling.LANCZOS)
            image.save(logo)
        # The MSI cabinets are already compressed. Embed the exact bytes so they can be reused in EXE deltas.
        subprocess.run([wix, 'build', '-arch', 'x64', '-ext', str(BAL), '-dcl', 'none',
                        '-d', f'Version={__version__}', '-d', f'Msi={msi}', '-d', f'Icon={ICON}',
                        '-d', f'Logo={logo}', '-pdbtype', 'none', '-out', str(target),
                        str(ROOT / 'installer/ComiTransSetup.wxs')], check=True)
    print(target, flush=True)


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
                # Cabinet data can shift. Setup uses smaller blocks to reuse data between Burn cabinet headers.
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
    parser.add_argument('--wix', default='wix')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--msi-only', action='store_true', help='Build only the MSI, for signing before bundling')
    mode.add_argument('--bundle-from', type=Path, metavar='MSI', help='Build the Setup EXE around an existing MSI')
    mode.add_argument('--delta', nargs=2, type=Path, metavar=('PREVIOUS_INSTALLER', 'NEW_INSTALLER'))
    args = parser.parse_args()
    if args.delta:
        build_delta(*args.delta)
    elif args.bundle_from:
        work = ROOT / 'build'
        work.mkdir(exist_ok=True)
        build_bundle(args.wix, args.bundle_from.resolve(), args.output.resolve())
    else:
        work = ROOT / 'build'
        work.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix='msi-', dir=work) as directory:
            stage = Path(directory) / 'payload'
            stage_app(args.dist.resolve(), stage)
            msi = build_msi(args.wix, stage, args.output.resolve())
        if not args.msi_only:
            build_bundle(args.wix, msi, args.output.resolve())


if __name__ == '__main__':
    main()
