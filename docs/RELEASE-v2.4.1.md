# ComiTrans v2.4.1

## 下载与安装

本版提供完整程序包 **`ComiTrans-v2.4.1-app.zip`**，不提供本版增量补丁。无需安装 Python 或 CUDA Toolkit。

- 首次安装：解压程序包，再将 [v2.4.0 模型包](https://github.com/Aaaaamadeus/ComiTrans/releases/download/v2.4.0/ComiTrans-v2.4.0-models.zip) 合并到 `ComiTrans/comic-translate-ai/models/`，运行 `ComiTrans.exe`。
- 已有安装：关闭程序，将完整程序包解压到新目录。从旧目录复制 `config.yaml`、`user_fonts/` 和整个 `comic-translate-ai/models/` 到新目录的对应位置，再启动新程序。已有模型无需重复下载。
- 漫画、输出图片、布局和日志继续保留在原位置；需要迁移时一并复制，保持输出图片与对应 `_cleaned`、`_layout` 目录的相对位置。确认新程序正常后再整理旧目录。

基线 JSON 和 SHA256 校验信息保存在 [源码 docs/releases/v2.4.1/](https://github.com/Aaaaamadeus/ComiTrans/tree/v2.4.1/docs/releases/v2.4.1)，不作为额外下载附件。

## 更新内容

- 新增中文、English、日本語界面，默认中文；首次启动选择，之后在设置第一页修改并保存，下次启动生效。界面语言独立于漫画原文、简繁译文及字体设置。[界面语言说明](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.4.1/docs/UI_LANGUAGES.md)。
- 修复竖排省略号、破折号断列和连接间距，兼容常见变体；连续标点整体排版，保留手动换列，预览、保存和恢复一致。
- 翻译批次全部成功后，以 15% 概率在右下角显示求 Star 提示；8 秒无操作自动收起，支持 X 关闭，点击按钮打开仓库。每批只抽取一次概率，浮层不抢输入焦点。
- 翻译页“译文”可选择简体中文或繁體中文，自动保存。翻译请求、续传和本地 OpenCC 字形统一使用所选简繁模式。
- 译文字体和默认竖排列对齐收进可折叠的“翻译偏好”。支持上对齐、居中对齐、下对齐，以最长列为基准，整组文字保持居中；用于后续图片、PDF 翻译和精修布局，切换复用已加载的模型。
- 精修支持 Enter 和“插入换行”手动分行，竖排向左换列，连续回车保留空行/空列。文字效果新增黑字白边及白字黑边（空心），每个块可单独选择竖排列对齐，实时预览并随图片和布局保存恢复。
- 内置 10 个繁体漫画字体系列、12 个字重，另配狮尾 B2 黑体与狮尾牙膏圆体的独立 SC/TC 特黑版本。16 个字体文件合计约 242 MiB，原始字体、授权和来源记录一并保留，可离线使用。
- 字体选择框显示中文名称与字重，支持原名检索和完整名称显示。
- 默认添加半透明 `@ComiTrans` 水印，开关在设置第一页“翻译服务”；保留用户已保存的关闭选择。

## 验证

- 246 项自动化回归通过，覆盖界面语言、首次选择与设置保存、简繁输出、字体、精修分行/对齐、竖排标点、Star 提示和更新器校验。
- 1440×900 和 820×480 窗口、100% 与 200% 缩放下检查三种界面的翻译、精修、设置和提示；共 66 张 Qt 截图。
- 完整包解压后核对全部程序文件哈希；Windows EXE 验证真实本地模型预热、离线字体、简繁转换、偏好持久化、英日界面资源和 Star 提示。

## English

v2.4.1 adds English and Japanese interfaces (Chinese remains the default), a first-launch language chooser and a language setting. It also includes Simplified/Traditional Chinese output, bundled manga fonts, manual line breaks, outline lettering, vertical column alignment and continuous vertical punctuation. Font and alignment choices are grouped inside Translation Preferences. Successful batches have a 15% chance to show a dismissible Star prompt that closes after eight idle seconds.

Download the full **`ComiTrans-v2.4.1-app.zip`**. This release does not provide an incremental patch. Close the old app, extract the full archive into a new folder, and copy `config.yaml`, `user_fonts/` and `comic-translate-ai/models/` from the old installation to the same relative locations. Keep your output images and their companion cleaned/layout folders together. Existing models remain reusable; fresh installs use the [v2.4.0 model archive](https://github.com/Aaaaamadeus/ComiTrans/releases/download/v2.4.0/ComiTrans-v2.4.0-models.zip).
