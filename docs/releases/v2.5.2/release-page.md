## 下载与升级

### 无模型包变更（可复用 v2.5.1 模型包）

**已经是 v2.5.1 的用户，只需下载本页的 `ComiTrans-v2.5.2-app.zip`。** 模型权重与检测器自 v2.5.1 起未发生变更；全新安装或从 v2.5.0 及更早版本升级时，请同时下载本页的程序包（`ComiTrans-v2.5.2-app.zip`）和模型包（`ComiTrans-v2.5.2-models.zip`），将两个 ZIP 解压到同一个空目录并合并其中的 `ComiTrans` 文件夹，再启动 `ComiTrans.exe`。

**可以保留原来的 `config.yaml`、`user_fonts/` 与 `comic-translate-ai/models/`。** 退出程序后，把旧安装目录里的上述内容复制到新安装目录对应位置，并与输出目录及其伴随的 `_cleaned`、`_layout` 目录保持原有相对位置。如果旧配置手动指定了模型路径，请检查路径是否仍然有效；要按 CUDA 状态自动选择检测器，请将检测器设为 `auto`。

## 更新内容

### 上下文翻译与并行流水线

- **跨页滚动上下文与缓存保留：** 批处理按阅读顺序自动携带最近 12 页上下文语境（序列化上限 24,000 字符、单条不超过 2,000 字符），并以原子方式缓存在 `.cache/translation-context.json`。翻译偏好新增「保留上下文缓存」选项，开启后联动锁定「断点续传」，便于多次续译沿用前文术语与人名对照。
- **OCR 后 Fork-Join 并行执行：** 单页完成气泡检测与 OCR 后立即分叉并发执行：一条路径按阅读顺序携上下文请求翻译 API，另一条路径在独立后台线程执行整页擦字修补（`repair_comic_page`）；汇合时按最终译文动态对账，空译文气泡自动跳过涂抹并还原对应掩码。
- **冷启动首帧优化：** 模型预热延后至主窗口首次绘制完成后进行，减少冷启动卡顿。

### 翻译页工作流可视化

- **工作流拓扑替代线性进度条：** 自动处理页底部重绘为真实反映后台并发流水线的有向工作流图：`01 读取图片 → 02 气泡检测 → 03 OCR 识别 → 分叉并行（04 AI 翻译 ∥ 05 背景修复）→ 06 中文排版 → 07 保存输出 / PDF 汇编`。
- **并发在途与逐页矩阵：** 节点徽章实时显示各在途页（如 `P2`、`P3`）、后台修补「待汇合」、上下文累计页数与续传跳过数，底部提供逐页状态矩阵及悬停详情，适配「纸白」与「夜墨」双主题及 `66px` 紧凑显示模式。

[自动处理并行工作流](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.2/docs/ui-review/automatic-workflow-v252.png) · [夜墨工作流](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.2/docs/ui-review/dark-workflow-v252.png)

### 嵌字精修与导出修复

- **手动画框与列表清理：** 支持在精修画布手工框选新增气泡文本块并融入既有排版、擦字保存流程；页面列表新增移除选中与清空操作，气泡切换显示 `1 / N` 计数，窄窗下工具栏自动折行。
- **图片取色与自定义 RGB 框选填色：** 新增画布与长条兼容的取色工具（自动避开辅助线），并支持十六进制 / RGB 任意颜色框选填充，纳入「撤回修补」与保存链路。
- **9 槽收藏字体快捷栏：** 支持置顶最多 9 个常用字体（含本地导入字体），编辑区可直接按数字键 `1–9` 套用至当前文本块，文字颜色变更完整持久化。
- **文字拉伸、旋转、描边与预设：** 右侧编辑栏支持字体拉伸（`10%–400%`）、旋转（`±180°`）、描边（`0–30 px`）及「白字黑边竖排」一键预设（只作用于手工精修图层，不改变自动批量默认排版）。
- **单页滚动隔离与 PDF 边缘修复：** 关闭「连续长条」后单页视图不会因滚轮误翻页；PDF 导出修复小数尺寸页面背景铺底覆盖不完整的问题。

[取色与填色界面](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.2/docs/ui-review/editor-color-pick-1440-style-review.png) · [常用字体快捷栏](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.2/docs/ui-review/editor-fill-fonts-1440-style-review.png) · [夜墨精修界面](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.5.2/docs/ui-review/dark-editor.png)

两个 ZIP 与 `baseline.json` 可用同页的 `SHA256SUMS.txt` 校验。Windows 解压版已验证 `ComiTrans.exe --smoke-test`（`frozen: true`、ONNX CPU 实际检测/OCR/LaMa 推理与多语言界面检查均通过），完整单元测试 481 项及纸白/夜墨双主题 UI 截图检查全部通过。

## English

Model weights are unchanged since v2.5.1. If you are already on v2.5.1, download only **`ComiTrans-v2.5.2-app.zip`** and copy your existing `config.yaml`, `user_fonts/`, and `comic-translate-ai/models/` folder next to `ComiTrans.exe`. For fresh installs or upgrades from v2.5.0 and earlier, download both **`ComiTrans-v2.5.2-app.zip`** and **`ComiTrans-v2.5.2-models.zip`** and extract them into a fresh directory merging `ComiTrans`.

This release adds rolling cross-page translation context (up to 12 pages / 24,000 serialized chars in `.cache/translation-context.json`) with a "Keep context cache" toggle, an OCR-forked sequential-translation ∥ background-repair Fork-Join pipeline, and a redesigned live Fork-Join workflow graph with a per-page status matrix on the translation page. In the editor, it introduces manual bubble frames, eyedropper color picking, custom RGB/Hex selection fills, 9 pinned favorite fonts (`1–9` shortcuts), persisted text colors, stretch (`10–400%`), rotation (`±180°`), manual outline stroke (`0–30 px`) with a vertical white-text black-outline preset, page cleanup controls, single-page wheel isolation, deferred post-first-paint model warmup, and fractional-edge coverage during PDF export.
