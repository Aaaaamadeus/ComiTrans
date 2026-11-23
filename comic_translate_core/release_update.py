"""Discover stable GitHub releases and prepare verified Windows installers."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

import requests


REPOSITORY_URL = 'https://github.com/Aaaaamadeus/ComiTrans'
RELEASE_API = 'https://api.github.com/repos/Aaaaamadeus/ComiTrans/releases/latest'
SIGNPATH_ASSET_LABEL = 'SignPath Foundation signed'
RESPONSE_LIMIT = 512 * 1024
DELTA_LIMIT = 768 * 1024 * 1024
DELTA_BLOCK_SIZE = 256 * 1024
SETUP_DELTA_BLOCK_SIZE = 8 * 1024
DELTA_OVERLAP = 1024 * 1024
DELTA_FRAME = struct.Struct('<I')
DELTA_COPY = 1 << 31
VERSION = re.compile(r'v?(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})')


def installer_name(version, *, setup=False):
    suffix = '-Setup.exe' if setup else '.msi'
    return f'ComiTrans-v{version}-x64{suffix}'


def delta_name(source, target, *, setup=False):
    return installer_name(f'{source}-to-v{target}', setup=setup) + '.delta'


@dataclass(frozen=True)
class Asset:
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    installer: Asset | None
    delta: Asset | None
    setup: bool = False


def latest_stable(data, current, *, setup=False):
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name')
    remote = VERSION.fullmatch(tag) if isinstance(tag, str) else None
    local = VERSION.fullmatch(current)
    if not remote or not local or tuple(map(int, remote.groups())) <= tuple(map(int, local.groups())):
        return None
    version = '.'.join(remote.groups())
    url = f'{REPOSITORY_URL}/releases/tag/{tag}'
    entries = data.get('assets')
    assets = {}
    if isinstance(entries, list):
        assets = {item['name']: item for item in entries
                  if isinstance(item, dict) and isinstance(item.get('name'), str)}

    def asset(name, *, required_label=None):
        item = assets.get(name, {})
        if required_label is not None and item.get('label') != required_label:
            return None
        download = f'{REPOSITORY_URL}/releases/download/{tag}/{name}'
        size, digest = item.get('size'), item.get('digest')
        if (item.get('browser_download_url') == download and type(size) is int and 0 < size < 2**31
                and isinstance(digest, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', digest)):
            return Asset(download, size, digest[7:])
        return None

    # A digest establishes integrity, so require the publisher's signing label
    # before offering a download. Windows still verifies the actual signature.
    return Release(version, url, asset(installer_name(version, setup=setup), required_label=SIGNPATH_ASSET_LABEL),
                   asset(delta_name(current, version, setup=setup)), setup)


def _check_asset(path, asset):
    if path.stat().st_size != asset.size:
        raise ValueError('Unexpected update size')
    with path.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != asset.sha256:
            raise ValueError('Update SHA-256 mismatch')


def _download(asset, target, canceled):
    with requests.get(asset.url, stream=True, timeout=(8, 15)) as response, target.open('wb') as handle:
        response.raise_for_status()
        for chunk in response.iter_content(1024 * 1024):
            if canceled():
                raise InterruptedError('Update canceled')
            if handle.tell() + len(chunk) > asset.size:
                raise ValueError('Unexpected update size')
            handle.write(chunk)
    _check_asset(target, asset)


def _expand_delta(delta, base, target, size, canceled, *, setup=False):
    import zstandard as zstd

    decoder = zstd.ZstdDecompressor()
    block_size = SETUP_DELTA_BLOCK_SIZE if setup else DELTA_BLOCK_SIZE
    with delta.open('rb') as source, base.open('rb') as previous, target.open('wb') as handle:
        for offset in range(0, size, block_size):
            if canceled():
                raise InterruptedError('Update canceled')
            header = source.read(DELTA_FRAME.size)
            if len(header) != DELTA_FRAME.size:
                raise ValueError('Incomplete update frame header')
            frame_info, = DELTA_FRAME.unpack(header)
            expected = min(block_size, size - offset)
            if frame_info & DELTA_COPY:
                previous.seek(frame_info ^ DELTA_COPY)
                block = previous.read(expected)
            else:
                if not 0 < frame_info <= block_size + 65536:
                    raise ValueError('Unexpected update frame size')
                frame = source.read(frame_info)
                if len(frame) != frame_info or zstd.frame_content_size(frame) != expected:
                    raise ValueError('Unexpected expanded update size')
                block = decoder.decompress(frame, allow_extra_data=False)
            if len(block) != expected:
                raise ValueError('Unexpected expanded update size')
            handle.write(block)
        if source.read(1):
            raise ValueError('Unexpected data at the end of the update')


SIGNATURE_CHECK = r"""
$signature = Get-AuthenticodeSignature -LiteralPath $env:COMITRANS_INSTALL_PACKAGE
if ($signature.Status -ne 'Valid' -or
    $signature.SignerCertificate.GetNameInfo('SimpleName', $false) -ne 'SignPath Foundation') { exit 1 }
"""


def _powershell(command, package, **variables):
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    env = dict(os.environ, COMITRANS_INSTALL_PACKAGE=str(package), **variables)
    return subprocess.Popen([str(executable), '-NoProfile', '-NonInteractive', '-Command', command],
                            env=env, creationflags=subprocess.CREATE_NO_WINDOW)


def prepare_update(release, current, cache, base, canceled):
    installer = release.installer
    if installer is None:
        raise ValueError('Missing verified installer asset')
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / installer_name(release.version, setup=release.setup)
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        stage = Path(directory) / target.name
        delta = release.delta
        if delta and delta.size < installer.size <= DELTA_LIMIT and base:
            import zstandard as zstd

            try:
                if base.stat().st_size > DELTA_LIMIT:
                    raise ValueError('Base installer exceeds delta size limit')
                patch = Path(directory) / delta_name(current, release.version, setup=release.setup)
                _download(delta, patch, canceled)
                _expand_delta(patch, base, stage, installer.size, canceled, setup=release.setup)
                _check_asset(stage, installer)
            except InterruptedError:
                raise
            except (requests.RequestException, OSError, ValueError, zstd.ZstdError):
                stage.unlink(missing_ok=True)
        if not stage.is_file():
            _download(installer, stage, canceled)
        process = _powershell(SIGNATURE_CHECK, stage)
        try:
            if process.wait(timeout=30) != 0:
                raise ValueError('Windows did not verify the SignPath Foundation signature')
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise ValueError('Windows signature verification timed out') from None
        if canceled():
            raise InterruptedError('Update canceled')
        stage.replace(target)
    return target


def launch_update(package):
    _powershell(r"""
try {
    Wait-Process -Id ([int]$env:COMITRANS_EXITING_PID) -Timeout 30 -ErrorAction Stop
} catch {
    if (Get-Process -Id ([int]$env:COMITRANS_EXITING_PID) -ErrorAction SilentlyContinue) { exit 1 }
}
try {
    $stream = [IO.File]::Open($env:COMITRANS_INSTALL_PACKAGE, 'Open', 'Read', 'Read')
""" + SIGNATURE_CHECK + r"""
    $log = Join-Path (Split-Path -Parent $env:COMITRANS_INSTALL_PACKAGE) 'install.log'
    $quotedLog = '"' + $log + '"'
    if ([IO.Path]::GetExtension($env:COMITRANS_INSTALL_PACKAGE) -eq '.exe') {
        $result = Start-Process -FilePath $env:COMITRANS_INSTALL_PACKAGE `
            -ArgumentList '/quiet', '/norestart', '/log', $quotedLog -PassThru -Wait -ErrorAction Stop
    } else {
        $msi = '"' + $env:COMITRANS_INSTALL_PACKAGE + '"'
        $result = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\msiexec.exe') -Verb RunAs `
            -ArgumentList '/i', $msi, '/quiet', '/norestart', '/L*v', $quotedLog -PassThru -Wait -ErrorAction Stop
    }
    exit $result.ExitCode
} finally {
    if ($stream) { $stream.Dispose() }
}
""", package, COMITRANS_EXITING_PID=str(os.getpid()))
