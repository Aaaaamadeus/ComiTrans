# ComiTrans v2.6.0

## Windows 安装与升级

下载本页的 `ComiTrans-v2.6.0-x64-Setup.exe` 和 `SHA256SUMS.txt`。安装包为 Windows x64，包含程序、字体和默认 OCR、检测、修补模型。关闭 ComiTrans，核对安装包的 SHA-256 后运行 Setup。安装后在设置中填写翻译 API 密钥与模型。

```powershell
Get-FileHash -Algorithm SHA256 .\ComiTrans-v2.6.0-x64-Setup.exe
Get-Content .\SHA256SUMS.txt
```

两处的十六进制哈希应一致。这个版本的安装包未签名，Windows 可能显示「未知发布者」。请从项目的 GitHub 发布页手动下载和安装。[v2.6.0 发布页](https://github.com/Aaaaamadeus/ComiTrans/releases/tag/v2.6.0)

- **从预发布 NSIS 版升级**：关闭应用后直接运行新版 Setup，沿用原安装目录和用户配置。
- **从旧 MSI / WiX 版迁移**：先在 Windows「已安装的应用」中卸载旧版，再运行 Setup。保留用户数据目录。
- **从 ZIP 版迁移**：原有配置和字体可从旧目录的 `config.yaml`、`user_fonts` 迁入 `%LOCALAPPDATA%\ComiTrans`。保留漫画、项目索引和配套精修目录之间的相对位置。

## 使用变化

- 打开应用后，检测和修补模型在独立进程中预热。加载期间可继续操作界面，顶栏会显示模型状态。
- 在「作品术语库」里记录角色、地点和统一译名。整批翻译前可以先试译少量页面，查看用量和按已配置单价估算的费用。
- 精修支持「全书译稿」跨页查找、替换，以及单气泡重译。CBZ 可以按页翻译，已保存的页面可以重新导出为 CBZ。
- 启动时在后台比较客户端版本与 GitHub 最新正式版。只有发现更高版本时，「模型已就绪」左侧才会出现「有更新」。点击可查看两个版本号及下载入口。

## English

Download `ComiTrans-v2.6.0-x64-Setup.exe` and `SHA256SUMS.txt` from this release. Compare the SHA-256 values using the PowerShell commands above. This Windows x64 installer is **unsigned** and requires a manual download. Windows may display “Unknown publisher.” Setup includes the app, fonts and default models. Enter your translation API key and model in Settings after installation.

Close the app before upgrading an NSIS installation. Uninstall an older MSI or WiX installation through Windows Settings first. ZIP users can migrate `config.yaml` and `user_fonts` into `%LOCALAPPDATA%\ComiTrans`. Keep project indexes and their editing folders together.

Model warm-up runs in a separate process. Project glossaries, trial translations and usage estimates help prepare a batch. The editor supports cross-page transcript search and replacement, single-bubble retranslation and CBZ export. A small **Update** button beside the model status appears when GitHub lists a newer stable version.
