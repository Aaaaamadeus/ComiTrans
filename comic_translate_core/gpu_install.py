"""Install the pinned NVIDIA Windows runtime next to the portable program."""
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

import requests


def app_directory():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def install(progress=print, *, root=None, canceled=lambda: False):
    assets = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'assets'
    manifest = (assets / 'gpu-runtime-windows.json').read_bytes()
    packages = json.loads(manifest)
    parent = (root or app_directory()) / 'gpu-runtime'
    parent.mkdir(exist_ok=True)
    target = parent / 'nvidia-cu12-v1'
    if target.exists():
        if (target / 'manifest.json').read_bytes() == manifest and all((target / 'bin' / f).is_file() for f in REQUIRED):
            return target
        raise RuntimeError(f'已有运行库不完整，请移走目录后重试：{target}')
    stage = parent / ('.install-' + uuid4().hex)
    stage.mkdir()
    try:
        binaries = stage / 'bin'
        binaries.mkdir()
        for pkg in packages:
            progress(f"{pkg['name']} {pkg['version']} ({pkg['bytes'] / 1e6:.0f} MB)")
            with tempfile.TemporaryFile(dir=stage) as stream, requests.get(pkg['url'], stream=True, timeout=(20, 90)) as response:
                response.raise_for_status()
                checksum = hashlib.sha256()
                for chunk in response.iter_content(1024 * 1024):
                    if canceled():
                        raise InterruptedError('下载已取消')
                    if stream.tell() + len(chunk) > pkg['bytes']:
                        raise ValueError(pkg['name'] + ': unexpected download length')
                    stream.write(chunk)
                    checksum.update(chunk)
                if stream.tell() != pkg['bytes'] or checksum.hexdigest() != pkg['sha256']:
                    raise ValueError(pkg['name'] + ': SHA256 mismatch')
                with zipfile.ZipFile(stream) as wheel:
                    for item in wheel.infolist():
                        name = Path(item.filename).name
                        if name.lower().endswith('.dll'):
                            dst = binaries / name
                        elif not item.is_dir() and ('license' in name.lower() or 'eula' in name.lower()):
                            dst = stage / pkg['name'] / name
                            dst.parent.mkdir(exist_ok=True)
                        else:
                            continue
                        with wheel.open(item) as src, dst.open('xb') as output:
                            shutil.copyfileobj(src, output, 1024 * 1024)
        if not all((binaries / name).is_file() for name in REQUIRED):
            raise RuntimeError('下载包缺少 CUDA/cuDNN DLL')
        (stage / 'manifest.json').write_bytes(manifest)
        stage.rename(target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target


REQUIRED = ('cudart64_12.dll', 'cublas64_12.dll', 'cublasLt64_12.dll', 'cufft64_11.dll',
            'cudnn64_9.dll', 'cudnn_ops64_9.dll', 'cudnn_engines_precompiled64_9.dll')
