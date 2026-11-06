"""Discover user-installed NVIDIA runtimes without importing or probing Torch."""
import os
import sys
from pathlib import Path

CUDA_DOWNLOAD_URL = 'https://developer.nvidia.com/cuda-12-8-1-download-archive'
CUDNN_DOWNLOAD_URL = 'https://developer.nvidia.com/cudnn-9-10-2-download-archive'
MSVC_DOWNLOAD_URL = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
GPU_SETUP_URL = 'https://github.com/Aaaaamadeus/ComiTrans/blob/main/docs/GPU_SETUP.md'


def runtime_directories(environ=None):
    """Return installed CUDA 12/cuDNN 9 bin directories, ignoring empty PATH entries."""
    env = os.environ if environ is None else environ
    candidates = []
    if getattr(sys, 'frozen', False):
        portable = Path(sys.executable).resolve().parent / 'gpu-runtime'
        candidates.extend([portable / 'nvidia-cu12-v1/bin', portable / 'bin'])
    for name in ('CUDA_PATH', 'CUDNN_PATH', *sorted(k for k in env if k.startswith('CUDA_PATH_V12_'))):
        value = env.get(name, '').strip().strip('"')
        if value:
            root = Path(value)
            if root.is_absolute():
                candidates.extend((root / 'bin', *sorted((root / 'bin').glob('12.*'), reverse=True), root))
    candidates.extend(Path(value.strip().strip('"')) for value in env.get('PATH', '').split(os.pathsep)
                      if value.strip().strip('"') and Path(value.strip().strip('"')).is_absolute())
    program_files = Path(env.get('ProgramFiles', r'C:\Program Files'))
    if program_files.is_absolute():
        cuda = program_files / 'NVIDIA GPU Computing Toolkit/CUDA'
        cudnn = program_files / 'NVIDIA/CUDNN'
        candidates.extend(sorted(cuda.glob('v12.*/bin'), reverse=True))
        for folder in sorted(cudnn.glob('v9*/bin'), reverse=True):
            candidates.extend(sorted(folder.glob('12.*'), reverse=True))
            candidates.append(folder)
    local = Path(env.get('LOCALAPPDATA', ''))
    if local.is_absolute():
        candidates.append(local / 'ComiTrans/gpu-runtime/bin')
    result, seen = [], set()
    for path in candidates:
        if not path.is_absolute() or not path.is_dir():
            continue
        key = os.path.normcase(str(path.resolve()))
        if key not in seen and any((path / name).is_file() for name in ('cudart64_12.dll', 'cudnn64_9.dll')):
            seen.add(key)
            result.append(path.resolve())
    return result
