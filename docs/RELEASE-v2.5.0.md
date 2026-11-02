# ComiTrans v2.5.0

发布日期：2026-11-02。此版本集中改进长篇漫画与高分辨率 PDF 的翻译、精修、恢复和导出流程，保留现有模型与完整页图像素。

## 重要更新

- **PDF 精修以图片为工作单位**：后台打开项目、按需加载页图，保存和切页不再合成整本 PDF；完成后显式导出。
- **连续翻译流水线**：当前页修补时，后续页继续读图、检测、OCR 和请求翻译；按并发设置限制在途页数。
- **原分辨率修补**：高分辨率页面使用带上下文的重叠分块，内存不足时缩小处理块重试，不缩小整张图片。
- **更精细的擦字与描边**：改进黑底白字、局部白描边、网点、渐变和彩色背景的文字掩膜；文字掩膜可独立测试和替换。
- **按气泡还原原图**：同时撤销所选块的修补和嵌字，恢复处理前像素，也可切回处理结果。
- **按页断点续传**：保留已完成页与合法译文，失败、停止或重启后继续；重试排版可复用已保存译文。
- **大项目精修与偏好交互**：连续长条复用可见画布，后台保存保留新编辑，侧栏和折叠栏记住手动选择。
- **翻译 JSON 约束**：优先严格结构化输出，兼容降级也执行本地类型、字段与条数校验，避免错位嵌字。

## 下载、安装与升级

### 新安装

1. 下载 `ComiTrans-v2.5.0-app.zip` 和 `ComiTrans-v2.5.0-models.zip`。
2. 所需压缩包解压到同一个父目录，合并顶层 `ComiTrans` 文件夹，保持子目录结构。
3. 双击 `ComiTrans/ComiTrans.exe`，在“设置”中填写翻译服务，并选择原文语言与 OCR。
4. 根据需要选择简体/繁体译文、译文字体、颜色与对齐方式，再导入图片或 PDF。

```text
ComiTrans/
├── ComiTrans.exe
├── _internal/                 # 程序、字体与运行库
├── comic-translate-ai/
│   └── models/                # 解压模型包得到
├── README-release.md
├── CHANGELOG.md
└── release-manifest.json
```

发布包无需安装 Python 或 PyTorch。新安装默认优先使用 GPU，保留旧配置中明确选择的 CPU 模式；GPU 无法启用时回退 CPU 并提示。GPU 加速需要兼容的 NVIDIA 驱动、CUDA 12 和 cuDNN 9；模型加载日志显示实际使用 CUDA 还是 CPU。不要仅以勾选“使用 GPU”判断加速已经生效。

本版不打包上传 CUDA/cuDNN。软件“设置 → 运行与输出 → GPU 安装说明与下载”提供 CUDA 12.8 Update 1、cuDNN 9.10.2 和 Microsoft VC++ 的官方链接。程序识别默认安装位置及 CUDA_PATH、CUDNN_PATH、PATH 中的运行库目录；已有兼容环境可以复用，CPU 用户无需安装 GPU 库。旧包未附带完整运行库，仅有驱动不能保证 GPU 生效。[安装与排查指南](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/GPU_SETUP.md)。

当前随模型包提供的 Baberu int4/int8 OCR 按设计使用 CPU，以保持量化模型兼容性；GPU 加速主要用于检测和 LaMa 修补。日志中这些 Baberu 模型显示 CPU 是正常的，应分别查看检测模型和修补模型的设备。

### 从旧版升级

- v2.3.0 / v2.4.x 的现有模型可以继续复用，只需新的程序包；GPU 用户另外检查本机 CUDA/cuDNN 环境。本版没有替换模型权重或要求重新下载模型。
- 关闭旧程序，将新程序解压到新目录，再复制原有 `config.yaml`、整个 `user_fonts/` 和 `comic-translate-ai/models/`。源码运行的配置位于 `comic-translate-ai/main/config.yaml`，迁移到 EXE 时放在 EXE 同目录。
- 保留漫画输出以及相邻的 `_cleaned`、`_layout`、`_original` 资料目录。PDF 还应保留 `.comitrans.json`、项目目录和其中的 `project.json`。
- 继续未完成任务时，保留原输入文件路径、输出目录及 `.comitrans-resume`。更换原文、输出目录或影响输出的设置，可能建立新进度。
- 本次提供完整程序包，不提供针对所有旧版本的通用增量补丁。确认新程序和原有项目可正常使用后，再自行整理旧目录。

发布附件 `SHA256SUMS.txt` 用于核对程序包、模型包及基线清单；[版本元数据](https://github.com/Aaaaamadeus/ComiTrans/tree/v2.5.0/docs/releases/v2.5.0)包含各文件哈希与构建标识。

## PDF：从整本文件改为逐页工作

### 自动翻译

导入 PDF 后先读取页数与物理尺寸。在并发设置允许的页数范围内，按需生成原分辨率 PNG，不必等整本 PDF 渲染结束才翻译第一页。已有有效页图直接复用，缺失、损坏或尺寸不匹配的缓存按页重建。所有页成功后，自动任务仍会生成译文 PDF。

PDF 页图保持设置的渲染 DPI。对于超过渲染安全上限的页面，程序明确报错，不静默降低 DPI 或缩小页面。PDF 内容会被栅格化，不保留可搜索的矢量文字层；加密 PDF 仍不支持直接处理。

### 精修和导出

1. 从翻译结果进入“嵌字精修”，或导入译文 PDF / 项目目录中的 `project.json`。
2. 选择单页，或开启“连续长条”，滚动浏览并切换当前编辑页。
3. 修改译文、字体、颜色、字号、方向、对齐或位置；需要时修补背景、还原气泡。
4. 点击“保存图片”或按 Ctrl+S。保存只写当前页图片及布局，不重建整本 PDF。
5. 全部修改完成后点击“导出 PDF”，选择输出位置。后台按保存后的页图无损合成，保留页序和物理尺寸，显示进度并支持取消。

导出前会处理当前未保存修改；保存失败时保留草稿。移动项目时，保持索引和页图资料之间的相对位置。详见 [PDF 工作流](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/PDF_EDITING.md)。

## 翻译速度、内存和连续调度

旧的分批方式需要等待本批全部 API 返回，再完成本批修补，才准备下一批。新流程中，一页准备完成便提交其翻译；轮到该页且译文就绪时立即修补，其他页继续准备或等待 API。

- 默认最多 4 页在途，包括正在修补的页；并发设置为 1 时按单页顺序处理。完成一页才释放一个名额，避免无限预取整本 PDF。
- CPU 工作与网络等待可重叠。CUDA 检测、OCR 和 LaMa 通过公平队列执行，在 LaMa 的修补块之间交错，减少同时推理的资源争用。
- 准备和修补分别保存页掩膜及 OCR 状态，共用已经加载的模型，避免跨页状态覆盖。
- 每页记录 PDF 页图准备、检测/OCR、API 翻译、修补/嵌字/保存耗时；模型会话报告实际执行设备，GPU 回退到 CPU 会明确提示。
- 自动翻译与手动修补按模型和设备共享 LaMa 会话，限制同时分配推理工作内存。设备或模型配置改变后，后续手动修补使用新的配置。

### 性能数据如何理解

下面是同一 RTX 4060 Laptop GPU（8 GB）环境中的局部测试，**不能当作整本 PDF 的速度保证**。

| 测试 | 之前 | 本次结果 | 范围 |
|---|---:|---:|---|
| 三页原图的背景修补 | 旧日志约 75～106 秒/页 | 约 6～9 秒/页 | 修复实际 CPU 回退和大字背景估计瓶颈；仅统计修补 |
| 同三页的调度对照 | 42.43 秒 | 37.85 秒 | 真实读取/OCR/修补/嵌字/保存；每次 API 等待模拟为 2 秒 |
| 调度对照的首张完成 | 23.12 秒 | 18.69 秒 | 与上一行相同测试 |

调度对照使用 3928×5556 原图，两种调度输出的解码像素完全一致，无远程翻译请求。GPU 本身的计算瓶颈仍然存在，增加并发不会简单倍增速度。[测量方法与原始数据](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/TRANSLATION_PERFORMANCE.md)。

## 擦字、背景修补与清晰度

### 原尺寸分块

复杂背景进入 LaMa 时，以带上下文的重叠块处理并融合，结果只更新掩膜覆盖的像素。内存不足时尝试更小的块，不缩小整页图像；到达最小块仍失败时返回明确错误，不伪造成功或保存半张结果。PNG 和 PDF 页图均使用无损保存策略。

这降低单次模型输入的工作内存，但当前页底图、合成图和保存快照仍占用内存，因此不是任意大页面都能在任意设备上处理。[内存策略](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/INPAINT_MEMORY_STRATEGY.md)。

### 更精细的掩膜与背景判断

- 同时分析深浅文字和颜色差异，改善黑底白字与彩色文字的擦除。
- 对文字与头发、线稿等相连的情况限制掩膜扩张，降低大块吞掉背景的风险。
- 纯色区域使用实际底色，不统一填成纯白；识别局部白描边，减少擦除日文后留下白印。
- 经背景校验的规则网点、平滑渐变优先局部重建；不满足条件的复杂纹理交给分块模型修补。
- 大尺寸背景估计使用等价滤波加速，保留原有系数量化、边界处理和像素输出。

复杂头发、交叠线稿和不规则纹理仍可能需要人工精修，本版不承诺准确复原所有被文字遮住的细节。

`TextMaskGenerator` 已成为独立可替换组件，输出擦除掩膜、排版掩膜、底色信息和可选的描边比例。开发者可独立运行诊断、比较算法，无需启动完整翻译或调用付费 API。[掩膜组件与测试命令](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/TEXT_MASK_COMPONENT.md)。

## 精修：颜色、修补与按气泡还原

### 文字和修补

翻译偏好支持设置默认文字颜色。精修可按文本块选择颜色，保留已有字体、分行、描边与对齐设置；保存重开后保持选择。中文自动换行/换列会尽量保留完整词语，手动换行仍优先。

原稿深色文字带白色描边时，可识别局部描边并按字号比例应用于译文。用户也可手动选择黑字白边、白字黑边等效果。此功能复用文字效果，不表示逐字复制原稿字体或保证所有艺术字都能识别。

使用“修补选区”在画布框选需要清理的背景，后台修补并保留当前会话中的选区撤回记录。成功保存后释放这些临时撤回像素；它与下述长期保存的气泡还原状态不同。

### 还原此气泡

1. 在精修右侧文本块列表选中要还原的气泡。
2. 点击“还原此气泡”：隐藏该块译文，并从处理前原图恢复原框及所属擦字边缘。
3. 点击“保存图片”，将还原状态写入布局。关闭并重新打开仍然有效。
4. 再点击“恢复处理结果”，可切回修补底图与译文；原有文字、字体和位置没有被删除。

新结果自动保留原图信息，PDF 复用项目的源页图。旧结果没有原图时，可以“关联原图”，但必须选择同一页、相同像素尺寸的原图；软件不会缩放或猜测丢失像素。JPEG 等结果使用还原后无损另存为 PNG，保留旧文件。相邻气泡受到保护，但原检测框本身重叠时，还原区域优先。[完整说明](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/BUBBLE_RESTORATION.md)。

## 长篇项目与折叠栏

索引、页图解码和保存移到后台。快速切页只保留一个正在执行的加载和一个最新待加载请求，旧结果不能覆盖新选择或加载期间产生的编辑。保存时使用快照，保存期间继续修改会保留未保存状态。

连续长条只保留视口附近画布，侧栏缩略图缓存上限为 128 张。文字调整优先复合受影响区域，不反复绘制整页；需要完整合成的情况仍保留正确性优先的路径。预览可以缩小显示，实际修补与导出仍使用完整像素。

在 3000×4500 合成页项目中，100/500/1000 页打开约 0.40/0.85/1.40 秒，操作后进程工作集约 400 MB。这不包含 PDF 转页、模型推理、翻译或整本导出，也不是全过程峰值。[大项目测试与限制](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/EDITOR_PERFORMANCE.md)。

翻译偏好和精修侧栏记住手动展开/收起选择，缩小窗口和专注模式不覆盖偏好。提示词、人名等设置防抖自动保存，折叠、切换功能页和退出前刷新；失败时显示状态并允许重试。展开面板时尽量保留画布与输入区域，小窗口选择文本块后滚动到编辑位置。

## 续传与 API 返回格式

### 续传

默认开启“断点续传：跳过已完成页面”。相同任务再次开始时，完整的已完成页跳过检测、OCR 和翻译；只有译文已保存的页重新检测/OCR，原文匹配后复用译文，重试排版无需再次请求翻译。

并发回包和完成记录加锁保存，避免相互覆盖。停止后不继续预取，已发出的请求若返回合法译文仍会缓存；停止不会强行中断正在执行的原生推理或 HTTP 请求。无法恢复服务端已计费但客户端未收到或未能写盘的响应。[续传边界](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/RESUMABLE_TRANSLATION.md)。

### JSON 校验与错误

优先请求严格 JSON Schema；服务明确不支持时才逐级降级。所有路径都进行本地字符串类型、字段、数量等校验，不把错误数量的结果直接错位嵌字，也不把限流、鉴权或网络失败当成“不支持格式”反复尝试。只有明确的 token 截断才允许续译后缀。

合法译文先缓存，再进入修补、嵌字与文件事务。排版或写盘失败会报告页面失败，不能标为成功；鉴权、账户或全局配置错误停止后续调度。诊断报告不再为了生成环境信息导入 PyTorch 或检测 CUDA，实际异常和完整堆栈保留。[协议细节](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/TRANSLATION_JSON_CONTRACT.md)。

## 架构与扩展状态

翻译服务、JSON 校验、运行配置快照、文件事务、推理调度、页面预取和掩膜算法已拆成独立模块，自动翻译与精修复用相同的核心服务。

修图插件协议 v1 已有接口设计，定义工具、选区、笔画、参数、取消和像素补丁。但插件发现、宿主工具注册与编辑器集成仍未完成，**v2.5.0 不宣称已经可以安装独立 PS 风格修图插件**。[架构图](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/ARCHITECTURE.md) · [插件接口](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/RETOUCH_PLUGIN_API.md)。

## 发布验证

发布前执行完整自动化回归，并验证打包后的 Windows EXE、实际推理设备、本地模型推理、字体与语言资源、原尺寸图像保存，以及压缩包内容和文件哈希。测试不读取用户 API 密钥，不向翻译服务发送付费请求。

最终测试数量、打包运行结果、附件大小与哈希记录在 [v2.5.0 发布验收](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/docs/ui-review/release-v2.5.0.json)。性能章节引用各自注明范围的历史测量，不将合成项目或模拟 API 的数据描述成真实整本漫画的端到端结果。

## English

v2.5.0 introduces image-based PDF editing, explicit lossless PDF export, bounded streaming translation, native-resolution tiled inpainting, per-bubble restoration of original pixels, per-page resume, improved text masks/background reconstruction, outline and color handling, responsive large-project editing, and stricter translation JSON validation.

Preparation and translation of later pages overlap the current page's repair. GPU calls are interleaved between repair tiles; the concurrency setting caps all in-flight pages. Page-local state is isolated, checkpoints are synchronized, and valid responses already in flight are cached after cancellation.

Download the **app** and **models** ZIPs and merge their `ComiTrans` folders. Existing v2.3.0/v2.4.x models can be reused. Keep configuration, imported fonts, resume records, original/cleaned images and layout/project files when upgrading. CUDA/cuDNN are not bundled or uploaded. Settings → Runtime & Output → GPU setup and downloads provides official links for CUDA 12.8 Update 1 and cuDNN 9.10.2. A compatible NVIDIA driver is required; existing compatible runtimes can be reused. CPU users need no GPU libraries. New installations prefer GPU and report CPU fallback if CUDA is unavailable; an existing explicit CPU preference is preserved. No Python or PyTorch installation is required.

Editing and Save Image work on page images; use Export PDF after editing. Original page dimensions and lossless output are preserved. Complex textures may still need manual retouching. Plugin API v1 is a design interface; loading independent retouch plugins is not implemented in this release.

The three-page offline scheduling comparison reduced elapsed time from 42.43 to 37.85 seconds with pixel-identical outputs and a simulated two-second API delay. This is not an end-to-end PDF or live API benchmark. See the [English README](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.0/README_en.md) and linked performance records for scope and limitations.
