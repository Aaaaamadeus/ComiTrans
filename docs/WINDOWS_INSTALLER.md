# Windows 安装与更新

提供 MSI 的版本可在 GitHub Releases 下载 `ComiTrans-v<版本>-x64.msi`。双击安装需要管理员授权。开始菜单和桌面会创建 ComiTrans 快捷方式，Windows 设置的「已安装的应用」提供卸载入口。双击 `.comitrans` 项目索引可以直接进入 PDF 精修。

安装版把程序写入 `%ProgramFiles%\ComiTrans`。每个 Windows 用户的配置、模型、导入字体、日志、默认输出及下载的更新保存在 `%LOCALAPPDATA%\ComiTrans`。模型独立分发，首次安装将模型包解压到 `%LOCALAPPDATA%`，保留包内的 `ComiTrans\comic-translate-ai\models` 目录结构。

从历史 ZIP 版迁移时，关闭旧版，并将 `config.yaml`、`user_fonts` 和 `comic-translate-ai\models` 复制到 `%LOCALAPPDATA%\ComiTrans` 对应位置。可同时复制 `gpu-runtime` 和默认输出目录 `page`。如果曾将设置写成指向旧目录的绝对路径，在新版设置中更新路径。把 PDF、索引和精修资料目录一起保留，旧 `.comitrans.json` 索引仍可通过导入对应 PDF 读取。

每次启动在后台查询 GitHub 的最新正式 Release。安装版经由以 Windows `LocalService` 账户运行的 `ComiTransReleaseCheck` 服务查询，服务不可用时应用直接查询。网络失败时应用照常打开。发现较新版本后可以查看 GitHub 发布、稍后提醒，或在安装版中下载并更新。更新下载完成后沿用正常退出流程，确认退出后由 Windows 安装程序静默升级。Windows 仍会按系统策略要求管理员授权。

有匹配差分且上一版 MSI 仍在下载位置或更新缓存时，应用优先下载差分。它将差分还原为新版本的完整 MSI，然后校验 GitHub SHA-256 和 Windows Authenticode 签名。差分不可用或校验失败时下载完整 MSI。安装失败由 Windows Installer 回滚本次升级；安装及卸载事务只管理程序目录、服务、快捷方式和安装注册表项。安装日志保存在 `%LOCALAPPDATA%\ComiTrans\updates\install.log`。

管理员可在管理工具或已提升权限的终端运行同一安装包进行静默安装或升级。

```powershell
msiexec.exe /i "ComiTrans-v<版本>-x64.msi" /quiet /norestart /L*v "ComiTrans-install.log"
```

## 构建与签名

安装 .NET 8 SDK 和 WiX 5.0.2，按 README 构建主程序后运行以下命令。本地生成的 MSI 用于测试。

```powershell
dotnet tool install --tool-path build/wix wix --version 5.0.2
$env:DOTNET_ROLL_FORWARD = 'Major'
.\.venv\Scripts\python.exe installer/build.py --wix build/wix/wix.exe
.\.venv\Scripts\python.exe package_release.py --models-only --output release
```

应用、EXE 文件属性、服务和 MSI 均使用 `comic_translate_desktop/__init__.py` 中的 `__version__`。维护者准备同版本的发布说明，创建对应的 `v<版本>` tag，然后从该 tag 手动运行 `Build and sign Windows installer`。工作流检查 tag 与版本一致，验证安装与卸载，取得签名、检查 Windows 信任链和时间戳，并生成下载校验文件。填入已有签名安装包的版本可以生成 `.msi.delta` 差分，至少节省 10% 下载量时才输出。上传工作流产出的已签名 MSI、差分（如有）、`SHA256SUMS.txt` 和独立模型包到对应 GitHub Release。

免费签名由 SignPath.io 提供，证书由 SignPath Foundation 提供，需项目所有者申请并获批。该计划要求项目及拟签名组件符合开源许可条件。申请前需明确仓库根目录的开源许可证，并核对程序包内的各组件授权。当前 CharSpot Small 权重独立分发，适用模型自己的许可。获批后，将 [签名规则](../installer/signpath.xml) 导入 SignPath 的 `windows-msi` 制品配置，为 `windows-release-signing` 环境配置 `SIGNPATH_API_TOKEN`，并配置 `SIGNPATH_ORGANIZATION_ID`、`SIGNPATH_PROJECT_SLUG` 和 `SIGNPATH_SIGNING_POLICY_SLUG`。发布者签名通过系统证书链验证，SmartScreen 下载信誉由 Windows 独立评估。 [SignPath 申请条件](https://signpath.org/terms) · [Microsoft SmartScreen 说明](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
