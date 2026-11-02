"""Discover user-installed NVIDIA runtimes without importing or probing Torch."""
import os
from pathlib import Path

CUDA_DOWNLOAD_URL = 'https://developer.nvidia.com/cuda-12-8-1-download-archive'
CUDNN_DOWNLOAD_URL = 'https://developer.nvidia.com/cudnn-9-10-2-download-archive'
MSVC_DOWNLOAD_URL = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
GPU_SETUP_URL = 'https://github.com/Aaaaamadeus/ComiTrans/blob/main/docs/GPU_SETUP.md'


def runtime_directories(environ=None):
    """Return installed CUDA 12/cuDNN 9 bin directories, ignoring empty PATH entries."""
    env = os.environ if environ is None else environ
    candidates = []
    for name in ('CUDA_PATH_V12_8', 'CUDA_PATH', 'CUDNN_PATH'):
        value = env.get(name, '').strip().strip('"')
        if value:
            root = Path(value)
            candidates.extend((root / 'bin', root / 'bin/12.8', root / 'bin/12.9', root))
    candidates.extend(Path(value.strip().strip('"')) for value in env.get('PATH', '').split(os.pathsep)
                      if value.strip().strip('"') and Path(value.strip().strip('"')).is_absolute())
    program_files = Path(env.get('ProgramFiles', r'C:\Program Files'))
    candidates.extend((program_files / 'NVIDIA GPU Computing Toolkit/CUDA/v12.8/bin',
                       program_files / 'NVIDIA/CUDNN/v9.10/bin/12.8',
                       program_files / 'NVIDIA/CUDNN/v9.10/bin/12.9',
                       program_files / 'NVIDIA/CUDNN/v9.10/bin'))
    result, seen = [], set()
    for path in candidates:
        if not path.is_absolute() or not path.is_dir():
            continue
        key = os.path.normcase(str(path.resolve()))
        if key not in seen and any((path / name).is_file() for name in ('cudart64_12.dll', 'cudnn64_9.dll')):
            seen.add(key)
            result.append(path.resolve())
    return result
