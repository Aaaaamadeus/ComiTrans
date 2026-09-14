# ComiTrans

<div align="center">

**[简体中文](README.md)** ｜ **[English](README_en.md)**

<br>

<img src="https://img.shields.io/github/v/release/Aaaaamadeus/ComiTrans?color=76bad9" alt="release">
<img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="python">
<img src="https://img.shields.io/badge/UI-PySide6-green.svg" alt="PySide6">
<img src="https://img.shields.io/badge/Inference-ONNX%20Runtime-orange.svg" alt="ONNX Runtime">
<img src="https://img.shields.io/github/stars/Aaaaamadeus/ComiTrans?color=76bad9" alt="stars">

</div>

ComiTrans 是一款纯本地运行的漫画自动汉化桌面客户端。它把文本检测、日文 OCR、大模型翻译、背景修复和中文排版全部放在本地桌面端完成，不依赖浏览器、服务器或 Web 后端。

从 v2.2.1 开始，检测、OCR、修复全部切换为 **ONNX Runtime 推理**，彻底移除 PyTorch / torchvision / transformers 依赖；主程序和模型拆分发布，程序压缩包约 0.4GB，更新程序时不再需要重新下载模型。

## 翻译前后对比

> [!NOTE]
> 目前仅进行中文翻译效果展示，需要其他语言功能可提出issue。

| 翻译前 | 翻译后 |
| --- | --- |
| ![翻译前](docs/images/before1.jpg) | ![翻译后](docs/images/after1.jpg) |
| ![翻译前](docs/images/before2.jpg) | ![翻译后](docs/images/after2.jpg) |
## 目录

1. [核心特性](#核心特性)
2. [快速开始](#快速开始)
3. [使用说明](#使用说明)
4. [翻译流程](#翻译流程)
5. [模型说明](#模型说明)
6. [打包与发布](#打包与发布)
7. [项目结构](#项目结构)
8. [更新日志](#更新日志)
9. [常见问题](#常见问题)
10. [反馈与支持](#反馈与支持)
11. [开源协议](#开源协议)

## 核心特性

- **纯本地桌面客户端**：PySide6 桌面应用，抛弃 Web 页面，启动后即可使用。
- **全 ONNX 推理**：漫画文本检测、Baberu/manga-ocr、LaMa 修复全部为 ONNX 模型，不再依赖 PyTorch。
- **模型拆包发布**：主程序约 0.4GB，模型单独一个下载包，更新程序无需重新下载模型。
- **启动即预热**：打开客户端自动加载 AI 管线，不等点击翻译才加载模型。
- **GPU 推理**：支持 NVIDIA CUDA，只需本机已有 NVIDIA 驱动。
- **多模态翻译开关**：勾选后发送整页图片给 AI，翻译后额外让 AI 配置字体、字号和横竖方向；不勾选则走纯文本翻译。
- **PDF 整本翻译**：可与图片混合导入 PDF，逐页翻译后按原页序和原页面尺寸生成一个 `*_translated.pdf`。
- **12 类字体适配**：普通/粗体对话、强调、手写、内心、低语、严肃、旁白、拟声、可爱、预告和标题自动分类，并对缺字逐字回退。
- **掩膜擦除与掩膜嵌字**：擦除只按检测文字掩膜执行；嵌字可用面积与排版中心按掩膜计算。
- **嵌字人工编辑**：翻译后可微调每个文本块的字体风格、字号、横竖方向和位置，并保存覆盖输出。
- **报错日志与 AI 诊断**：日志写入 `Log/app.log`，自动生成诊断提示词，支持 AI 多轮诊断。
- **文件夹批量选择**：支持选择整个文件夹并递归添加图片和 PDF。
- **即时停止**：点击停止后立即进入取消状态，不再处理剩余图片。
- **Issue 反馈**：右上角可跳转到自填的 GitHub Issue 链接。
- **可调整布局**：左右主区域、预览与日志区域均可拖拽调整大小。

## 快速开始

### Release 用户（推荐）

1. 下载 `ComiTrans-v2.2.2-app.zip`（主程序）和 `ComiTrans-v2.2.2-models.zip`（模型包）。
2. 解压主程序包得到 `ComiTrans` 文件夹。
3. 将模型包解压到同一个 `ComiTrans` 文件夹内，模型会合并到 `ComiTrans\comic-translate-ai\models\`。
4. 双击 `ComiTrans.exe`，在“API 配置”页填写翻译 API Key 和模型。

Release 用户不需要安装 Python、PyTorch、pip 或 CUDA Toolkit。GPU 加速只需本机已有 NVIDIA 驱动。

### 源码运行（开发者）

推荐 Python 3.12+，支持 CUDA 的 NVIDIA GPU 可选。

```powershell
cd D:\ComiTrans
python -m venv .venv
.\.venv\Scripts\python -m pip install -r comic-translate-ai/requirements.txt
```

复制示例配置：

```powershell
Copy-Item comic-translate-ai/main/config.example.yaml comic-translate-ai/main/config.yaml
```

启动客户端：

```powershell
.\.venv\Scripts\python run.py
```

也可以直接双击 `start.bat`。客户端启动后会自动预热 AI 管线，完成后即可开始翻译。
## 使用说明

1. 点击“添加文件”或“添加文件夹”，也可以直接拖拽图片、PDF 或文件夹到窗口。
2. 在“API 配置”页填写 API Key、Base URL、翻译模型、Issue 链接等；日文 OCR 默认“自动”，优先使用 Baberu，也可手动切回 manga-ocr。
3. 勾选“多模态翻译”后，翻译会发送整页图片给 AI，并在翻译后让 AI 配置字体；不勾选则使用纯文本翻译和自动排版算法。
4. 在翻译页顶部展开“偏好设置”，填写背景提示词和中文人名（每行一个，AI 自动对照）。
5. 点击“开始翻译”，实时查看执行步骤、进度和日志。
6. 翻译失败时可在“报错日志”页查看诊断提示词，或点击右上角 Issue 按钮提交反馈。
7. 需要微调时，切换到“嵌字编辑”页，选择已翻译图片，调整字体风格、字号、横竖方向和位置后保存。

PDF 会以一个文件任务显示，内部按页分批处理，成功后输出 `<原文件名>_translated.pdf`。输出 PDF 保留页数、顺序和页面尺寸；页面内容会栅格化。加密或需要密码的 PDF 暂不支持，PDF 页面也暂不支持在“嵌字编辑”页逐块调整。

### 字体风格

| 风格 | 用途 | 默认字体 |
| --- | --- | --- |
| `dialogue` / `bold_dialogue` | 普通 / 粗体对话 | 霞鹜文楷 / 思源黑体 Heavy |
| `radiating` / `sfx` | 强调放射 / 拟声词 | 得意黑 Smiley Sans 斜体 |
| `handwriting` | 手写注记 | setofont |
| `thought` / `serious` | 内心 / 严肃正式 | 思源宋体 |
| `whisper` / `cute` | 低语 / 可爱活泼 | Klee One（缺字自动回退思源字体） |
| `narration` | 横向长条旁白 | 霞鹜文楷 LXGW WenKai |
| `next_preview` | 下回预告 | Klee One |
| `title` | 章节标题 | 思源黑体 Heavy |

普通气泡默认 `dialogue`，再根据 OCR 内容、检测类别、原字笔画强度和文本框比例选择其它风格。方向以检测器结果为主，仅在长宽比明显矛盾时纠偏；编辑器提供自动、明确竖排和明确横排三种选择。

嵌字使用局部 3 倍超采样后以 Lanczos 缩回原尺寸，小字号对白不再直接落在低分辨率画布上；普通气泡同时取消强制白描边，使笔画边缘更自然，复杂背景上的非气泡文字仍会保留描边以保证可读性。

### 报错日志与 AI 诊断

- 所有运行日志写入 `Log/app.log`。
- “报错日志”页自动整理环境信息、模型路径、最近日志和报错堆栈。
- 支持复制诊断提示词、复制原始日志、打开日志文件。
- AI 诊断会携带当前日志上下文，并保留多轮对话记忆，只有点击“清空上下文”才会重置。

## 翻译流程

每一张图片或 PDF 页面按以下流程处理：

1. **气泡与文本检测**：ONNX 文本检测器输出气泡、文字掩膜和文本行。
2. **日文 OCR**：默认使用 Baberu ONNX 识别竖排、多字体、拟声词与混排文本，模型缺失时回退 manga-ocr；检测为英文、或 OCR 结果明显是英文乱码的文本块会整块保留。
3. **大模型翻译**：纯文本模式发送 OCR 结果；多模态模式发送整页图片，并让 AI 配置字体、字号和方向。
4. **背景修复**：按检测文字掩膜擦除，简单白气泡直接涂白，复杂背景调用 LaMa ONNX 修复。
5. **中文排版**：按掩膜有效面积估算字号、按掩膜质心定位，横竖方向自适应，长文本自动收紧字号。
6. **保存与编辑**：输出翻译图，清理底图单独保存到 `<输出目录>_cleaned/`，布局 JSON 保存到 `<输出目录>_layout/`，可在嵌字编辑页继续人工微调。
7. **PDF 重组**：PDF 的全部页面成功后，按原页面尺寸重组并重新打开校验；任一页失败时不生成半成品 PDF。

翻译服务返回 401/403（鉴权）、402（余额不足）或 404（接口/模型不存在）时，客户端会显示实际原因并停止请求剩余页面。HTTP 402 需要为对应 API 账户充值，或更换有额度的 API Key，代码本身无法绕过服务商额度限制。

## 模型说明

| 用途 | 模型 | 来源 |
| --- | --- | --- |
| 漫画气泡与文本检测 | `comic-text-detector.onnx` | [mayocream/comic-text-detector-onnx](https://huggingface.co/mayocream/comic-text-detector-onnx)，由 [dmMaze/comic-text-detector](https://github.com/dmMaze/comic-text-detector) 导出 |
| 日文 OCR（默认） | `baberu-ocr/` | [genshiai-daichi/baberu-ocr](https://huggingface.co/genshiai-daichi/baberu-ocr)，Apache-2.0，121 MB 量化 ONNX 组合 |
| 日文 OCR（回退） | `manga-ocr-onnx/` | [l0wgear/manga-ocr-2025-onnx](https://huggingface.co/l0wgear/manga-ocr-2025-onnx)，基于 [kha-white/manga-ocr](https://github.com/kha-white/manga-ocr) |
| LaMa 背景修复 | `lama-manga-dynamic.onnx` | manga-lama |

模型来源、可替换的其它 ONNX 版本以及效果更好的漫画文本检测模型候选见 [docs/ONNX_MODELS.md](docs/ONNX_MODELS.md)。

## 打包与发布

### 打包主程序

```powershell
.\build_app.ps1
```

默认只打包主程序，不复制模型；本地联调模型时使用：

```powershell
.\build_app.ps1 -IncludeModels
```

### 生成发布包

```powershell
python package_release.py
```

会生成两个 release 包：

- `ComiTrans-v2.2.2-app.zip`：主程序，不含模型
- `ComiTrans-v2.2.2-models.zip`：ONNX 模型包

模型包解压到 `ComiTrans\comic-translate-ai\models\`。

## 项目结构

```text
ComiTrans
├── run.py                         # 桌面客户端入口
├── comic-translate-ai/            # AI 核心
│   ├── main/
│   │   ├── comic_translator_pipeline.py
│   │   ├── onnx_text_detector.py  # ONNX 文本检测
│   │   ├── onnx_manga_ocr.py      # ONNX 日文 OCR
│   │   ├── onnx_baberu_ocr.py     # Baberu ONNX OCR（默认）
│   │   ├── manga_lama.py          # ONNX 背景修复
│   │   └── vertical_typesetter.py # 中文排版
│   ├── models/                    # 模型权重（Release 中位于 exe 旁）
│   └── font_file/                 # 中文字体
├── comic_translate_desktop/       # PySide6 桌面客户端
├── docs/ONNX_MODELS.md            # 模型来源与可选模型
├── legacy/web/                    # 旧 Web 架构存档
├── build_app.ps1                  # 打包脚本
└── package_release.py             # Release 拆包脚本
```
## 更新日志

### v2.2.2（2026-09-14）

**新增与优化**

- 全面美化桌面端 UI 与操作反馈，加入克制的过渡动画、递归目录导入和拖放操作。
- 支持整本 PDF 漫画导入、逐页翻译与重新导出。
- 默认使用 Baberu ONNX OCR，并保留 manga-ocr-onnx 回退路径。
- 优化漫画嵌字：采用更圆润的字体风格与 3 倍超采样渲染，降低文字像素感。
- 竖排文本中的双破折号 `——` 改为连续长竖线，并扩展字体样式与标点布局规则。

**修复**

- 修复 Issue #19：翻译 API 请求日志引用未定义变量 `zhengzai`，导致请求发出前直接报错。
- 改进 API 错误分类与提示，遇到鉴权、余额、模型、限流和服务端错误时给出明确原因；致命错误会停止剩余任务。

### v2.2.1（2026-08-07）

**新功能**

- 翻译工作台新增“输出目录”设置，默认输出路径不变，与 API 配置页双向同步。
- 主窗口与按钮补齐应用图标，统一 UI 样式与交互观感。
- 多图翻译优化：检测/OCR 与修复/嵌字串行，各页翻译 API 请求并行发起（默认 4 并发），整体处理时间显著压缩。
- 翻译 API 请求日志：记录请求模型、文本条数、返回条数、耗时、数量不匹配与失败原因；未嵌字时输出明确警告。
- 翻译系统提示词严谨化：统一 JSON 对象输出格式，严格约束数量一致，拟声词强制翻译，减少空译文导致的漏嵌字。
- 下回预告与画外音字号分档：章节预告识别扩展（第 N 话、后篇、预告、最终话等），两档字号独立调优。

**调整**

- 输出目录系列改为 `output_page_*`；测试素材统一放在 `page/test`，测试输出写入 `page/test_output`。
- 测试与输出目录不再上传、不再打包。

### v2.1.0（2026-08-06）

**架构重构**

- 抛弃 Web 架构（Spring Boot / FastAPI / PostgreSQL / Redis / Nginx），重构为纯本地 PySide6 桌面客户端。
- 检测、OCR、修复全部切换为 ONNX Runtime 推理，彻底移除 PyTorch / torchvision / transformers 依赖。
- 主程序与模型拆分发布：主程序压缩包约 0.4GB，模型单独一个下载包，更新程序无需重新下载模型。

**新增功能**

- 启动即预热：打开客户端自动加载 AI 管线。
- 多模态翻译开关：勾选后发送整页图片，翻译后让 AI 配置字体、字号和横竖方向。
- 嵌字人工编辑：调整字体风格、字号、横竖方向和位置，保存覆盖输出。
- 报错日志与 AI 诊断：自动生成诊断提示词，支持多轮对话上下文。
- 文件夹批量选择、即时停止任务、Issue 反馈、可拖拽调整布局。
- 特殊字体分类：画外音、拟声词、下回预告、大标题使用不同开源字体。

**优化与修复**

- 修复打包版 exe 预热停滞问题（unittest 误排除、检测器动态导入、pyclipper / unidic / manga_ocr assets 缺失）。
- 横竖方向判断与嵌字方向阈值调整，减少横排误判竖排。
- 字号算法平衡：竖排放大、横排收紧，长文本自动收紧，按掩膜面积估算字号、按掩膜质心排版。
- 擦除只按检测文字掩膜执行，不再擦除整个气泡。
- 英文文本块完整跳过：不 OCR、不擦除、不嵌字；OCR 结果中拉丁/全角拉丁占比高时自动判定为英文并保留原文。
- 清理底图移入独立的 `<输出目录>_cleaned/` 目录。
- 移除训练/可视化依赖（matplotlib、wandb、pandas、torchsummary）。

### v1.x（已归档）

- 基于 Web 的漫画翻译平台：Spring Boot 后端、Vue 前端、PostgreSQL / Redis / Nginx，图像处理由 Python worker 完成。
- 支持批量图片翻译、文字擦除、字体分类、横向排版、模型托管。
- 旧代码归档在 `legacy/web/`，旧文档见 `docs/README-v1.md`。

## 常见问题

**Release 需要安装 Python 或 CUDA Toolkit 吗？**

不需要。主程序和模型包解压后即可运行，GPU 加速只需本机已有 NVIDIA 驱动。

**模型放哪里？**

模型位于 exe 旁的 `comic-translate-ai/models/`。Release 用户需要把 `ComiTrans-v2.2.2-models.zip` 解压到同一个 `ComiTrans` 文件夹内。

**为什么英文文本没有被翻译？**

Baberu 模型本身覆盖日/中/英字符，但当前翻译流程仍会保留检测器直接标出的英文块；OCR 结果中拉丁/全角拉丁占比 ≥ 40% 的块也会保留原图，避免误擦网站标识和英文拟声词。如需强制翻译英文，可开启多模态翻译。

**为什么主程序包这么小？**

v2.2.1 已全面 ONNX 化并移除 PyTorch。检测、OCR、修复均为 ONNX 模型，运行库只需 onnxruntime。

## 反馈与支持

使用中遇到问题，可以在 [GitHub Issues](https://github.com/Aaaaamadeus/ComiTrans/issues) 提交，或使用客户端右上角的 Issue 按钮。建议附上“报错日志”页生成的诊断提示词，方便快速定位。

## 开源协议

- 项目代码遵循相应开源协议发布（详见仓库 LICENSE 文件）。
- 字体：得意黑 Smiley Sans、霞鹜文楷 LXGW WenKai、Klee One、思源黑体/宋体、setofont 均为开源字体，各自的授权见字体项目说明。
- 模型：comic-text-detector、Baberu OCR、manga-ocr、manga-lama 均为开源模型，来源见 [docs/ONNX_MODELS.md](docs/ONNX_MODELS.md)。
