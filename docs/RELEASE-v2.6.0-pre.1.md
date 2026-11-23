# ComiTrans v2.6.0-pre.1

这是安装方式变更和 UI 优化的测试包。漫画翻译、OCR、擦字和嵌字功能沿用 v2.5.2。

## 安装与更新

- **一次安装程序和模型。** 下载 `ComiTrans-v2.6.0-pre.1-x64-Setup.exe` 并双击安装。Setup 内置程序、7 个 ONNX 模型和现有字体，CPU 模式安装后可直接加载模型。翻译仍需配置 API。GPU 加速沿用设置中的运行库安装指引。
- **启动时检查正式版。** 应用在后台查询 GitHub Releases，发现新版后提醒。无签名新版通过「前往发布页下载安装」手动更新。正式版用户不会收到本预发布的更新提醒。
- **Windows 安装方式。** 安装器创建开始菜单和桌面快捷方式、注册更新查询服务及 `.comitrans` 项目文件关联，并提供系统卸载入口。此 Setup 未签名，Windows 可能提示未知发布者。
- **迁移旧版。** 已通过 v2.5.2 Setup 安装的用户可关闭程序后运行新版 Setup。使用旧 ZIP 版的用户若要保留设置，可迁移 `config.yaml` 和 `user_fonts/` 到 `%LOCALAPPDATA%\ComiTrans`。本测试包内部安装版本为 `2.5.999`，以便后续升级至正式 `2.6.0`。若已安装此前的本地 `2.6.0` 测试包，先在 Windows 中卸载它，再安装本预发布包。

## 界面优化

- 统一纸白和夜墨主题下的按钮、下拉框、对话框、卡片和选中态，完善控件反馈与过渡动画。
- 优化自动处理工作流、精修画布和工具栏的交互反馈，同步调整设置、字体库、语言选择和日志窗口。

## English

This pre-release tests the new installer and UI refinements. Manga translation, OCR, inpainting, and lettering features remain the same as in v2.5.2.

- **Install with a single Setup.** Run `ComiTrans-v2.6.0-pre.1-x64-Setup.exe` to install the app, seven ONNX models, and bundled fonts. CPU inference is ready after installation. Translation still requires an API configuration. For GPU acceleration, follow the runtime instructions in Settings.
- **Check for updates at startup.** ComiTrans checks GitHub for newer stable releases. For unsigned updates, choose **Download from releases** and run the newer Setup yourself. Stable users will not receive an alert for this pre-release.
- **Windows integration.** Setup adds shortcuts, an update-check service, a `.comitrans` file association, and an uninstall entry. Windows may show an unknown publisher prompt for this unsigned package.
- **Upgrade or migrate.** Close v2.5.2 before running Setup. From the old ZIP edition, copy `config.yaml` and `user_fonts/` to `%LOCALAPPDATA%\ComiTrans` to migrate settings. This preview uses Windows installer version `2.5.999`, leaving an upgrade path to `2.6.0`. Remove the earlier local `2.6.0` test installer before installing this preview.
- **UI refinements.** Improved light and dark themes, control feedback, transitions, and consistency across the translation workspace, lettering editor, settings, font library, language chooser, and logs.
