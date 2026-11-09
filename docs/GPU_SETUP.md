# Windows GPU 安装与排查

在「设置 → 运行与输出 → GPU 安装说明与下载」点击「下载安装便携 GPU 运行库」，完成后重启。首次下载约 1.53 GB，需要兼容的 NVIDIA 驱动。DLL 保存在程序旁的 gpu-runtime 目录，无需另外安装 Python 或配置 PATH。

ComiTrans v2.5.0 的程序包和模型包均不附带 CUDA/cuDNN，也不发布额外运行库附件。软件内入口是 **设置 → 运行与输出 → GPU 安装说明与下载**。下载与安装由用户在官方页面完成，程序不会自动下载或启动安装器。

新安装默认优先使用 GPU；旧配置中明确关闭 GPU 的选择保持不变。只有 CPU 或不使用 GPU 时，可以关闭“使用 GPU”，无需安装下面的 NVIDIA 库。

## 首次安装

1. 确认电脑有支持 CUDA 的 NVIDIA 显卡，并安装兼容驱动。
2. 打开 [CUDA 12.8 Update 1 官方下载](https://developer.nvidia.com/cuda-12-8-1-download-archive)，选择 Windows、x86_64 和对应系统版本，按官方安装器完成安装。
3. 打开 [cuDNN 9.10.2 官方下载](https://developer.nvidia.com/cudnn-9-10-2-download-archive)，选择 **CUDA 12** 的 Windows x86_64 版本。CUDA Toolkit 不包含 cuDNN，两者均需安装。已有兼容 CUDA 12 / cuDNN 9 环境可以直接复用。兼容性以 [ONNX Runtime CUDA 说明](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)为准。
4. 确认 CUDA 和 cuDNN 实际存放 DLL 的 `bin` 目录在系统 `PATH` 中。cuDNN 如果使用 ZIP 安装，按 [NVIDIA Windows 安装说明](https://docs.nvidia.com/deeplearning/cudnn/installation/latest/windows.html)解压并设置路径。目录内应能找到 `cudart64_12.dll`、`cublas64_12.dll` 或 `cudnn64_9.dll` 等对应文件；不要只添加压缩包所在目录。
5. 完全退出并重新启动 ComiTrans，在设置里启用 GPU 并保存。模型初始化日志显示 `[ONNX] ...: CUDA` 才表示模型会话实际启用了 GPU。部分 ONNX 运算仍可由 CPU 执行。

若系统提示缺少 `MSVCP140.dll` / `VCRUNTIME140.dll`，安装 [Microsoft VC++ x64 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)。不需要为了运行发布版另外安装 Python、PyTorch 或 pip。

当前随模型包提供的 Baberu int4/int8 OCR 按设计使用 CPU，以保持量化模型兼容性；GPU 加速主要用于检测和 LaMa 修补。日志中这些 Baberu 模型显示 CPU 是正常的，应分别查看检测模型和修补模型的设备。

## 安装位置如何识别

Windows 上，程序在初始化 GPU 模型前注册以下已存在的 DLL 目录，并保留目录句柄供 cuDNN 后续加载引擎：

- `CUDA_PATH_V12_8`、`CUDA_PATH`、`CUDNN_PATH` 指定的目录及其 `bin` 子目录。
- 系统 `PATH` 中实际含有 CUDA 12/cuDNN 9 DLL 的绝对路径，忽略空项和相对路径。
- v2.5.0 修补版及 v2.5.1 会检查已安装的 CUDA 12.x 和 cuDNN 9.x 的版本子目录，也会检查当前 Windows 用户的 `%LOCALAPPDATA%\ComiTrans\gpu-runtime\bin`。便携版在这些目录中分别定位 CUDA 和 cuDNN，可从两个不同目录加载。该用户目录可放入已有的兼容 NVIDIA DLL，多份 ComiTrans 安装共用。
- 默认 `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin` 和 `C:\Program Files\NVIDIA\CUDNN\v9.10\bin`，包括后者的 `12.8` / `12.9` 子目录。

自定义安装位置可以直接把实际 DLL 目录加入 `PATH`，或设置 `CUDA_PATH` / `CUDNN_PATH`。修改环境变量后应重启 ComiTrans；从终端启动时也应重新打开终端。程序只读取这些路径，不修改系统环境变量。

源码运行还可使用 ONNX Runtime 自身支持的 Python 环境依赖发现方式；无需为了检测环境导入 PyTorch。CPU 模式不预加载 CUDA。

## 已勾选 GPU 但速度仍慢

- 看模型初始化日志。出现“GPU 未能启用，实际使用 CPU”时，根据此前的 DLL 或驱动错误检查安装；勾选框只表示请求 GPU。
- 确认安装的是 CUDA **12** 和适用于 CUDA 12 的 cuDNN **9**。不同主版本的 DLL 文件不能只通过改名替代。
- 确认软件位数、安装包位数均为 Windows x86_64，且路径指向解压或安装后的 DLL 目录。
- 运行库齐全仍可能遇到显存不足。原分辨率分块修补会减小处理块重试，不能保证任意显存大小都能完成任意页面，也不会偷偷缩小原图。

## English

CUDA/cuDNN are not bundled. Open **Settings → Runtime & Output → GPU setup and downloads** for official NVIDIA installers. Install CUDA 12.8 Update 1 and cuDNN 9.10.2 for CUDA 12, Windows x86_64, with a compatible NVIDIA driver. Reuse an existing compatible installation if available.

Add their actual DLL directories to `PATH`, or use `CUDA_PATH` / `CUDNN_PATH`. Standard installation locations are detected automatically. Restart ComiTrans and enable GPU. Model logs must report `CUDA`; a CPU fallback warning means acceleration was not activated. CPU users need none of these GPU libraries. No Python or PyTorch installation is required for the released EXE.
