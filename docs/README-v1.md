# ComiTrans 本地漫画翻译客户端

ComiTrans 是一个纯本地运行的漫画自动汉化客户端。AI 识别、翻译、背景修复和排版全部在当前机器上直接执行，不再依赖浏览器页面、Spring Boot、FastAPI、PostgreSQL、Redis 或 Nginx。

## 架构

```text
ComiTrans
├── run.py                         # 本地客户端启动入口
├── comic-translate-ai/            # AI 核心：检测 / OCR / 翻译 / 修复 / 排版
│   ├── main/
│   │   ├── comic_translator_pipeline.py
│   │   ├── manga_lama.py
│   │   └── vertical_typesetter.py
│   ├── models/                    # 模型权重（.pt 不入库）
│   └── font_file/                 # 中文字体
├── comic_translate_desktop/       # PySide6 桌面客户端
│   ├── main.py                    # 应用入口
│   ├── config.py                  # 本地配置读写
│   ├── worker.py                  # 后台翻译线程
│   └── ui/                        # 主窗口与设置对话框
└── legacy/web/                    # 旧 Web 架构存档，不再参与运行
```

本地客户端直接调用 `ComicTranslatorPipeline`，每一张图片按以下流程处理：

1. YOLOv5 漫画气泡检测
2. Manga-OCR 日文文本识别
3. 大模型整页上下文翻译
4. LaMa 背景修复去字
5. 动态中文排版并导出图片

## 环境准备

推荐 Python 3.10+，并准备支持 CUDA 的 GPU（可选，CPU 也可运行）。

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -r comic-translate-ai/requirements.txt
```

NVIDIA GPU 环境建议额外安装 CUDA 版 PyTorch，检测模型会直接使用 GPU：

```bash
.\.venv\Scripts\python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128
```

安装后可在“API 配置”页打开“使用 GPU”。程序会自动把 PyTorch 自带的 CUDA/cuDNN 运行库加入 PATH，供 ONNX LaMa 使用。

模型权重放在：

- 气泡检测模型：`comic-translate-ai/models/text_detector/comictextdetector.pt`
- Manga-OCR 模型：`comic-translate-ai/models/manga-ocr-base/`
- LaMa 修复模型：`comic-translate-ai/models/manga-lama/lama-manga-dynamic.onnx`

## 启动客户端

```bash
.\.venv\Scripts\python run.py
```

Windows 下也可以直接双击 `start.bat` 启动。

## 打包为桌面应用

项目已提供 PyInstaller 打包配置，可生成 Windows 桌面程序：

```powershell
.\build_app.ps1
```

打包完成后，程序位于 `dist\ComiTrans\ComiTrans.exe`。模型、字体和 OCR 权重会一并打包，首次启动会比源码运行稍慢。

客户端启动后：

1. 点击“添加图片”或“添加文件夹”，也可以直接把多张漫画图片或文件夹拖进窗口。
2. 点击顶部“API 配置”或切换到同名页签，填写翻译 API Key、API Base URL 和翻译模型；输出目录和 GPU 开关也可在这里修改，字号由排版算法根据气泡大小自动计算。
勾选“多模态翻译”后，翻译会发送整页图片，并在翻译后额外让 AI 为每个文本块配置字体、字号和横竖方向；不勾选则只做纯文本翻译，使用默认字体算法。
3. 翻译页顶部的“偏好设置”可折叠展开，可填写自定义背景提示词和中文人名（每行一个，AI 会自动对照日文角色），翻译时会自动注入到提示词中。
4. 点击“开始翻译”，逐张处理并实时显示执行步骤、进度与日志。
5. 处理结果会保存到配置中的输出目录，默认是 `comic-translate-ai/page/test_page_output`。

切换到“嵌字编辑”页，可以选择已翻译图片，微调每个文本块的字体风格、字号、横竖方向和位置，重新渲染并保存覆盖输出。

右上角“Issue”按钮可跳转到 API 配置页里填写的 GitHub Issue 链接；翻译失败时会弹出提示，并支持一键复制诊断提示词或打开 Issue 页面。

执行过程中会以列表方式可视化“读取图片、气泡检测、OCR 识别、AI 翻译、背景修复、中文排版、保存输出”每个步骤的状态。点击“停止”后任务立即进入取消状态，不再处理剩余图片，当前模型步骤结束后中断。

运行日志会写入 `Log/app.log`。顶部“报错日志”页会自动把环境信息、模型路径、最近日志和报错堆栈整理成诊断提示词，支持一键复制提示词或原始日志。

“报错日志”页还提供 AI 诊断对话：每次提问会自动携带当前日志上下文，并保留多轮对话记忆，只有点击“清空上下文”才会手动重置。

翻译设置保存在 `comic-translate-ai/main/config.yaml`，保存后即时生效；修改字体大小、GPU 或模型路径后，会在下一次翻译时重新加载模型。

## 命令行批量处理

如果不启动图形界面，也可以使用原有的目录监听模式批量处理：

```bash
python comic-translate-ai/main/main.py
```

把图片放入 `page/test_page` 后会自动处理，输出到 `page/test_page_output`。

## 旧 Web 架构

旧的前端 Vue、Spring Boot、FastAPI、Nginx、Docker Compose 和数据库初始化文件已归档到 `legacy/web/`，仅供查看历史实现，不再作为运行架构的一部分。
