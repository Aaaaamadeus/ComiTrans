# ComiTrans v2.4.0

漫画工作台、可检索的开源字体库与蒙版热预览。程序和模型继续拆包发布，v2.3.0 用户可复用原有模型。

## 更新内容

- 提供逐文件 SHA256 补丁基线、构建指纹和 Windows 更新入口，支持后续小版本的增量补丁。更新器校验原程序和补丁内容，备份修改文件并在失败时恢复。[补丁说明](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.4.0/docs/PATCH_UPDATES.md)。
- 沿用黑白漫画风，移除冗余章节横幅，柔化按钮和边框；加入局部网点和空状态漫画插画。
- 翻译页直接导入字体与选择默认译文字体；翻译和精修选择框均支持名称检索。
- Google Fonts 完整仓库目录快照包含 2,056 个字体族，索引约 1 MB。支持语言与风格筛选、按需下载、取消和重试；下载后可离线使用，保留许可证与来源记录。10 个缺少许可证附件的条目暂仅展示。
- 精修支持八个蒙版拖拽点、自由调整宽高、拖动位置与 Esc 取消当前拖动。字号、X/Y、译文、方向和字体实时预览；保存图片或 Ctrl+S 直接输出当前结果。
- 修复精修字体切换：手动选择只作用于当前块，优先于翻译默认字体，缺字逐字回退，保存后重新打开保留选择。
- 删除已确认的 82 个旧 Web、失效 CLI 和未使用训练文件，简化 ONNX 包导入、模型预热及构建依赖，修复诊断客户端释放。
- 多模态翻译与实验性字体比对采用独立开关，字体比对默认关闭；本地字体、字号和方向为默认行为。

## 下载与升级

1. 下载 `ComiTrans-v2.4.0-app.zip` 和 `ComiTrans-v2.4.0-models.zip`。
2. 两个压缩包解压到同一个父目录，合并顶层 `ComiTrans` 文件夹。最终结构应为 `ComiTrans/ComiTrans.exe` 和 `ComiTrans/comic-translate-ai/models/`。
3. 双击 `ComiTrans.exe`，在“设置”中配置翻译服务和 OCR，在翻译页选择译文字体。

从 v2.3.0 升级时可直接复用已有模型，只更新主程序。从 v2.2.2 升级可复用日语模型，韩语/英语识别需要新版模型包。保留 `config.yaml`、整个 `user_fonts` 文件夹和漫画输出及布局；不要覆盖旧的用户配置。

基线清单和 SHA256 校验信息保存在[源码的版本元数据目录](https://github.com/Aaaaamadeus/ComiTrans/tree/v2.4.0/docs/releases/v2.4.0)，发布页下载程序包、模型包即可。无需安装 Python、PyTorch 或 CUDA Toolkit；GPU 加速只需要已有 NVIDIA 驱动。

## 验证

- 176 项自动化测试通过，覆盖精修热预览、保存恢复、字体优先级、检索、下载校验、取消、离线使用及补丁失败回滚。
- 正常与 200% 缩放各 33 张真实 Qt 窗口截图检查通过，包含小窗口入口、蒙版拖拽和字体库。
- 实际字体下载、许可证保留和断网选用通过；本轮未调用翻译 API。
- 新版 Windows EXE 实际启动与本地模型预热通过；字体导入、默认字体持久化、模型复用、2,056 字体族目录加载与检索通过。

## 文档与界面

[中文 README](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.4.0/README.md) · [English](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.4.0/README_en.md) · [完整更新日志](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.4.0/CHANGELOG.md) · [字体库](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.4.0/docs/FONT_LIBRARY.md) · [精修热预览](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.4.0/docs/EDITOR_LIVE_PREVIEW.md)

![字体检索与按需下载](https://raw.githubusercontent.com/Aaaaamadeus/ComiTrans/v2.4.0/docs/ui-review/font-library-search-style-review.png)

![蒙版拖拽与热预览](https://raw.githubusercontent.com/Aaaaamadeus/ComiTrans/v2.4.0/docs/ui-review/editor-mask-drag-style-review.png)

## English

v2.4.0 refreshes the manga workbench, adds a searchable Google Fonts catalog with on-demand downloads and offline reuse, and introduces free mask resizing with live typesetting previews. Manual editor fonts override the translation default only for the selected block and persist after saving.

It also includes a file-level patch baseline and Windows update launcher for future minor releases, with build checks, backups and restoration on failed writes.

Baseline JSON and SHA256 checksums are stored in the [source repository](https://github.com/Aaaaamadeus/ComiTrans/tree/v2.4.0/docs/releases/v2.4.0). The Release provides the app and model archives.

Download the app and model ZIPs and merge their top-level `ComiTrans` folders. Existing v2.3.0 models can be reused. Preserve your configuration, the entire `user_fonts` folder, and manga outputs/layouts when upgrading. The SHA256 file verifies both archives. See the English README for setup and usage.
