# ComiTrans v2.0.0

ComiTrans v2.0.0 是本地漫画自动汉化桌面客户端，从原来的 Web 架构重构为纯本地 PySide6 应用。AI 检测、OCR、翻译、背景修复和中文排版全部在当前机器上直接执行，不再依赖浏览器、Spring Boot、FastAPI、PostgreSQL、Redis 或 Nginx。

## v2.0.0 重点改动

- **纯本地桌面客户端**：抛弃 Web 页面，改为 PySide6 桌面应用，启动后即可使用。
- **启动即预热**：打开客户端后自动加载 AI 管线，不再等到点击翻译才加载模型。
- **GPU 推理**：支持 NVIDIA CUDA，PyTorch 与 ONNX LaMa 均可使用 GPU。
- **多模态翻译开关**：勾选后发送整页图片给 AI，翻译后额外让 AI 配置字体、字号和横竖方向；不勾选则走纯文本翻译。
- **可折叠偏好设置**：翻译页顶部可展开填写背景提示词和中文人名，AI 会自动对照日文角色。
- **执行步骤可视化**：实时显示读取图片、气泡检测、OCR、翻译、背景修复、排版、保存等步骤状态。
- **即时停止**：点击停止后立即进入取消状态，不再处理剩余图片。
- **报错日志与 AI 诊断**：日志写入 `Log/app.log`，自动生成诊断提示词；报错日志页支持 AI 多轮诊断。
- **嵌字人工编辑**：翻译后可在“嵌字编辑”页微调每个文本块的字体风格、字号、横竖方向和位置，并保存覆盖输出。
- **文件夹批量选择**：支持选择整个文件夹，递归添加图片。
- **Issue 反馈**：右上角可跳转到自填的 GitHub Issue 链接，失败时弹窗提醒提交 Issue。
- **可打包 exe**：提供 PyInstaller 打包配置，可生成 Windows 桌面程序。
- **可调整布局**：左右主区域、预览与日志区域均可拖拽调整大小。

## 核心流程

每一张图片按以下流程处理：

1. YOLOv5 漫画气泡与文本检测
2. Manga-OCR 日文文本识别
3. 大模型翻译（多模态或纯文本）
4. LaMa 背景修复去字
5. 动态中文排版并导出图片
6. 保存清理底图与布局 JSON，供人工编辑

## 环境准备

推荐 Python 3.10+，支持 CUDA 的 NVIDIA GPU 可选。

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -r comic-translate-ai/requirements.txt
```

本地配置从 `comic-translate-ai/main/config.yaml` 读取；仓库只提供安全模板：

```powershell
Copy-Item comic-translate-ai/main/config.example.yaml comic-translate-ai/main/config.yaml
```

NVIDIA GPU 环境建议安装 CUDA 版 PyTorch：

```bash
.\.venv\Scripts\python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128
```

程序会自动把 PyTorch 自带的 CUDA/cuDNN 运行库加入 PATH，供 ONNX LaMa 使用。

模型权重放在：

- 气泡检测模型：`comic-translate-ai/models/text_detector/comictextdetector.pt`
- Manga-OCR 模型：`comic-translate-ai/models/manga-ocr-base/`
- LaMa 修复模型：`comic-translate-ai/models/manga-lama/lama-manga-dynamic.onnx`

## 启动客户端

```bash
.\.venv\Scripts\python run.py
```

Windows 下也可以直接双击 `start.bat`。

客户端启动后会自动预热 AI 管线，完成后即可开始翻译。

## 使用说明

1. 点击“添加图片”或“添加文件夹”，也可以直接拖拽图片或文件夹到窗口。
2. 在“API 配置”页填写 API Key、Base URL、翻译模型、Issue 链接等。
3. 勾选“多模态翻译”后，翻译会发送整页图片，并在翻译后让 AI 配置字体；不勾选则使用纯文本翻译和默认字体算法。
4. 在翻译页顶部展开“偏好设置”，填写背景提示词和中文人名（每行一个，AI 自动对照）。
5. 点击“开始翻译”，实时查看执行步骤、进度和日志。
6. 翻译失败时可在“报错日志”页查看诊断提示词，或点击右上角 Issue 按钮提交反馈。
7. 需要微调时，切换到“嵌字编辑”页，选择已翻译图片，调整字体风格、字号、横竖方向和位置后保存。

## 报错日志与 AI 诊断

- 所有运行日志写入 `Log/app.log`。
- “报错日志”页自动整理环境信息、模型路径、最近日志和报错堆栈。
- 支持复制诊断提示词、复制原始日志、打开日志文件。
- AI 诊断会携带当前日志上下文，并保留多轮对话记忆，只有点击“清空上下文”才会重置。

## 打包为桌面应用

```powershell
.\build_app.ps1
```

打包完成后，程序位于 `dist\ComiTrans\ComiTrans.exe`。模型、字体和 OCR 权重会一并打包。

## 命令行批量处理

不使用图形界面时，可使用目录监听模式：

```bash
python comic-translate-ai/main/main.py
```

将图片放入 `page/test_page` 后自动处理，输出到 `page/test_page_output`。

## 项目结构

```text
ComiTrans
├── run.py                         # 桌面客户端入口
├── comic-translate-ai/            # AI 核心
│   ├── main/
│   │   ├── comic_translator_pipeline.py
│   │   ├── manga_lama.py
│   │   └── vertical_typesetter.py
│   ├── models/                    # 模型权重
│   └── font_file/                 # 字体
├── comic_translate_desktop/       # PySide6 桌面客户端
├── docs/README-v1.md              # v1 历史文档归档
└── legacy/web/                    # 旧 Web 架构存档
```

## 版本历史

- v2.0.0：本地桌面客户端、GPU 推理、多模态翻译、AI 字体配置、嵌字编辑、报错诊断、exe 打包。
- v1.x：基于 Web 的漫画翻译平台，已归档至 `legacy/web/` 与 `docs/README-v1.md`。
