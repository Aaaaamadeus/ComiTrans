# ComiTrans v2.5.2

发布日期：2026-11-17

## 下载与升级

### 无模型包变更（可复用 v2.5.1 模型包）

- **已是 v2.5.1 用户：** 模型包与检测器权重未发生变更，只需下载 `ComiTrans-v2.5.2-app.zip`，关闭旧程序后解压到新目录，并把旧目录中的 `config.yaml`、`user_fonts/` 和 `comic-translate-ai/models/` 复制到新目录对应位置（与 `ComiTrans.exe` 及已有相对目录结构保持一致）。
- **全新安装或从 v2.5.0 及更早版本升级：** 请同时下载 `ComiTrans-v2.5.2-app.zip` 和 `ComiTrans-v2.5.2-models.zip`，解压到同一个空目录并合并其中的 `ComiTrans` 文件夹，再启动 `ComiTrans.exe`。
- 如果旧版 `config.yaml` 中手动填写过绝对模型路径，升级后请确认路径有效；如需随 CUDA 状态自动切换快/轻检测器，请将检测器设置为 `auto`。

## 更新内容

### 上下文翻译与并行流水线

- **滚动上下文与缓存保留：** 自动批处理在单批内按阅读顺序保留跨页翻译语境（最多最近 12 页、序列化上限 24,000 字符、单条不超过 2,000 字符），并以原子写入保存在输出目录的 `.cache/translation-context.json`。翻译偏好新增「保留上下文缓存」，开启时同步锁定「断点续传」，便于中断恢复后延续上文语境与译名表。
- **OCR 后分叉并行（Fork-Join）执行：** 在完成当前页气泡检测与 OCR 之后，流程即刻分叉为两条并行路径：一条按阅读顺序携带上下文向翻译 API 请求译文，另一条在独立后台线程执行整页擦字与背景修补（`repair_comic_page`）；汇合阶段再对最终非空译文做掩码对账，空译文气泡自动跳过涂抹并还原对应区域。
- **启动首帧优化：** 模型预热延后至主窗口完成首次绘制之后触发，缩短桌面端冷启动到可交互界面的等待时间。

### 翻译页工作流可视化

- **Fork-Join 有向流水线画布：** 重新设计自动处理页的工作流面板（`StepPanel`），取消传统单一路径进度条，改用与真实后台并发引擎一一对应的实时拓扑图：`开始 → 识别气泡 → 提取文字 → 分叉并行（按序上下文翻译 ∥ 后台线程擦字修补）→ 汇合排版 → 保存成品 / PDF 汇编`。
- **实时在途态与每页矩阵：** 节点与连线按阶段活跃状态、并发在途页角标（如 `P2`、`P3`）、后台修补就绪标记、累计上下文页数和续传跳过页数实时跳动；底部附带紧凑逐页状态矩阵与悬停提示，并在「纸白」浅色与「夜墨」深色主题以及 `66px` 紧凑模式下保持清晰可读。

### 嵌字精修与导出修复

- **手动画框与页面列表清理：** 支持在精修画布手工框选新增译文气泡并写入排版数据；页面列表补充移除当前页与清空列表操作，气泡切换显示 `1 / N` 计数，工具栏在窄窗口下自动折行。
- **取色与任意 RGB 框选填色：** 新增画布取色工具（自动避开辅助线，兼容连续长条模式）及自定义 RGB/Hex 调色板框选填充，填充结果纳入「撤回修补」与原位保存历史。
- **9 槽收藏字体快捷栏：** 翻译偏好默认字体与精修页字体选择支持置顶最多 9 个常用字体（含本地导入字体），在精修编辑区按数字键 `1–9` 即可快速套用；气泡文字颜色变更完整持久化。
- **文字拉伸、旋转、描边与竖排预设：** 右侧编辑栏新增字体拉伸（`10%–400%`）、角度旋转（`±180°`）、描边宽度（`0–30 px`）及「白字黑边竖排」一键预设；样式调整仅作用于精修手工图层，不影响自动批处理默认排版参数。
- **单页滚动隔离与 PDF 边缘修复：** 关闭「连续长条」时隔离上下滚轮切页干扰；PDF 导出修复小数尺寸页面铺底覆盖不完整导致的边缘露白问题。

## 验证

- 完整单元测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests` 全部 481 项通过。
- UI 截图检查：`scripts/review_ui.py` 浅色与深色（夜墨）双主题 × 多分辨率（1440 / 1024 / 960 / 820）均返回 `success: true`，UI 字体解析为 `Microsoft YaHei UI`。
- Windows 打包解压冒烟验证：合并解压 `ComiTrans-v2.5.2-app.zip` 与 `ComiTrans-v2.5.2-models.zip` 后运行 `ComiTrans.exe --smoke-test` 通过（`version: "2.5.2"`、`frozen: true`、`no_torch_import: true`、`ocr_backend: "charspot"`、CPU ONNX 实际检测 / OCR / LaMa 修复 `success: true`）。

## English

### Download and Upgrade

- **Model reuse for v2.5.1 users:** Model weights are unchanged since v2.5.1. Existing v2.5.1 users only need `ComiTrans-v2.5.2-app.zip`: extract it into a fresh folder, close the old app, and copy `config.yaml`, `user_fonts/`, and `comic-translate-ai/models/` over alongside `ComiTrans.exe`.
- **Fresh install or upgrading from v2.5.0 and earlier:** Download both `ComiTrans-v2.5.2-app.zip` and `ComiTrans-v2.5.2-models.zip`, extract both into the same empty directory merging the `ComiTrans` folder, then launch `ComiTrans.exe`.

### Highlights

- **Contextual translation & Fork-Join pipeline:** Rolling cross-page translation context (up to 12 pages / 24,000 serialized chars, atomically saved in `.cache/translation-context.json`) with a new "Keep context cache" preference that keeps page resume enabled. Immediately after OCR, sequential API translation and isolated-thread page inpainting run in parallel, reconciling masks at join when empty translations occur. Startup model warmup is deferred until after first paint.
- **Redesigned Fork-Join workflow visualizer:** Replaces the linear progress track on the translation page with a live directed graph reflecting the parallel pipeline, showing in-flight page badges, repair-ready join state, context count, resumed pages, hover tooltips, a compact per-page matrix strip, and Paper / Night Ink theme support.
- **Editor enhancements & PDF fix:** Manual bubble frame creation, eyedropper color picking on canvas/strip, custom RGB/Hex selection fills (undoable), 9 pinned favorite fonts (`1–9` shortcuts), persisted text colors, horizontal/vertical stretch (`10–400%`), rotation (`±180°`), manual outline stroke (`0–30 px`) with a vertical white-text black-outline preset, page-list removal/clear controls, `1 / N` block counter, single-page wheel isolation, wrapping toolbars, and fractional-edge coverage during PDF export.
