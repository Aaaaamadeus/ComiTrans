"""Load the actual inference runtime independently of diagnostic reports."""
from pathlib import Path
from threading import Lock
import os
from .gpu_runtime import GPU_SETUP_URL, runtime_directories

_preload_lock = Lock()
_cuda_preloaded = False
_dll_directory_handles = []


def _preload_cuda(ort):
    global _cuda_preloaded
    with _preload_lock:
        if _cuda_preloaded:
            return
        preload = getattr(ort, 'preload_dlls', None)
        if preload is not None:
            # ORT locates installed CUDA/cuDNN DLLs without importing torch.
            # Available providers alone do not mean their DLLs can be loaded.
            if hasattr(os, 'add_dll_directory'):
                for directory in runtime_directories():
                    # Python 3.8+ does not search PATH for dependent DLLs by
                    # default. Keep handles for cuDNN's late-loaded engines.
                    try:
                        _dll_directory_handles.append(os.add_dll_directory(str(directory)))
                    except OSError as exc:
                        print(f'[WARNING] CUDA 目录不可用: {directory}: {exc}')
            preload()
        _cuda_preloaded = True


def create_onnx_session(model_path, device='cpu', *, sess_options=None):
    import onnxruntime as ort

    requested_cuda = str(device).startswith('cuda')
    providers = ['CPUExecutionProvider']
    if requested_cuda and 'CUDAExecutionProvider' in ort.get_available_providers():
        try:
            _preload_cuda(ort)
        except (OSError, RuntimeError) as exc:
            print(f'[WARNING] CUDA 运行库加载失败: {exc}')
        providers.insert(0, 'CUDAExecutionProvider')
    kwargs = {'providers': providers}
    if sess_options is not None:
        kwargs['sess_options'] = sess_options
    try:
        session = ort.InferenceSession(str(model_path), **kwargs)
    except Exception as exc:
        if len(providers) == 1:
            raise
        print(f'[WARNING] {Path(model_path).name}: GPU 会话创建失败: {exc}')
        kwargs['providers'] = ['CPUExecutionProvider']
        session = ort.InferenceSession(str(model_path), **kwargs)

    actual = session.get_providers()
    gpu_active = 'CUDAExecutionProvider' in actual
    if requested_cuda and not gpu_active:
        print(f'[WARNING] {Path(model_path).name}: GPU 未能启用，实际使用 CPU，处理速度会降低；请打开“设置 → 运行与输出 → GPU 安装说明与下载”。安装指南: {GPU_SETUP_URL}')
    else:
        print(f'[ONNX] {Path(model_path).name}: {"CUDA" if gpu_active else "CPU"}')
    return session
