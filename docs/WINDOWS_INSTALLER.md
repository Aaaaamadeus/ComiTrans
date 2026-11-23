# Windows 安装与更新

从 GitHub Releases 下载 `ComiTrans-v<版本>-x64-Setup.exe` 并双击，按 NSIS 标准向导完成「欢迎 → 选择安装目录 → 安装进度 → 完成」。安装需要管理员授权，支持简体中文、繁体中文、英文和日文，语言跟随 Windows。安装器使用系统控件和 ComiTrans 图标。

完整版 Setup 默认包含检测、CharSpot 日语 OCR、韩语 / 英语 OCR 和修补模型，安装后无需另下模型包。程序和模型一起安装，默认目录为 `%ProgramFiles%\ComiTrans`，可在目录页输入或浏览本地安装位置；安装程序自动创建 `ComiTrans` 子文件夹，已选中同名文件夹时直接使用。新建的多级目录和中文路径均受支持。开始菜单和桌面会创建快捷方式，「已安装的应用」提供卸载入口。双击 `.comitrans` 项目索引可进入 PDF 精修。更新检查服务固定安装在 `%ProgramFiles%\ComiTrans Release Service`。

每个 Windows 用户的配置、自定义模型、导入字体、日志、默认输出与下载的更新存放在 `%LOCALAPPDATA%\ComiTrans`，卸载保留这些数据。卸载按安装包的文件清单删除程序，保留安装目录中的其他文件。同一 NSIS 安装可直接覆盖更新或重新安装，沿用原目录；更换目录前请先卸载。内置模型在配置中保存为 `models/...` 相对路径，启动时根据当前安装目录解析；旧版保存的失效安装目录路径自动迁移，用户选择的外部自定义模型路径会保留。旧 MSI / WiX Setup 版须先从 Windows 设置卸载，再安装 NSIS 版，避免两套卸载记录相互覆盖。

从历史 ZIP 版迁移时，关闭旧版，并将 `config.yaml`、`user_fonts` 和 `comic-translate-ai\models` 复制到 `%LOCALAPPDATA%\ComiTrans` 对应位置。可同时复制 `gpu-runtime` 和默认输出目录 `page`。如果曾将设置写成指向旧目录的绝对路径，在新版设置中更新路径。把 PDF、索引和精修资料目录一起保留，旧 `.comitrans.json` 索引仍可通过导入对应 PDF 读取。

每次启动在后台查询 GitHub 的最新正式版。安装版优先通过 `ComiTransReleaseCheck` 服务查询，服务不可用时应用直接查询。无签名新版和预发布版需要从 GitHub 手动下载。签名版发布时，维护者可将已签名的 Setup 在 GitHub 标记为 `SignPath Foundation signed`，启用应用内更新；应用在执行前仍验证 SHA-256 和 Windows Authenticode 签名。符合条件时使用差分包，否则下载完整版。

静默安装使用 NSIS 的 `/S`（区分大小写）；`/D=` 必须放在命令最后，目录不加引号。首次安装时自动补上 `ComiTrans` 子目录，已安装版本沿用原目录。省略 `/D=` 时沿用现有目录或默认目录。`/LOG=` 指定 UTF-16LE 安装摘要日志，默认 `%TEMP%\ComiTrans-install.log`。兼容现有应用内更新使用的 `/quiet /norestart /log "路径"`，安装器不会主动重启系统。NSIS 不提供 MSI 事务回滚；失败后可重新安装或通过 Windows 设置卸载。若遇到旧版 NSIS 安装器的服务配置错误（1639），直接用修复版重新安装到原目录即可，无需删除用户数据。服务的创建、配置、启动和删除直接调用 Windows 服务接口，日志会记录失败操作与错误码。

```powershell
.\ComiTrans-v2.6.0-x64-Setup.exe /S /LOG="D:\install.log" /D=D:\Apps\ComiTrans
& 'D:\Apps\ComiTrans\Uninstall.exe' /S
```

## 构建与签名

安装 [NSIS 3.13](https://nsis.sourceforge.io/Download)，按 README 构建主程序，然后运行：

```powershell
.\.venv\Scripts\python.exe installer/build.py --include-models
# 编译器不在 PATH 时：
.\.venv\Scripts\python.exe installer/build.py --makensis 'C:\Program Files (x86)\NSIS\makensis.exe' --include-models
```

构建只需 NSIS 和 Windows 自带的 .NET Framework C# 编译器，不再依赖 WiX、.NET SDK 或 C++ 编译器。版本取自 `comic_translate_desktop/__init__.py`；需要同版的 `docs/RELEASE-v<版本>.md`。`--stage-only` 先生成 payload 和卸载程序，`--payload <目录>` 使用已暂存或签名的文件构建 Setup。卸载程序通过 NSIS `!uninstfinalize` 在编译时导出，不运行安装器来生成。

维护者创建与版本一致的 tag 后，手动运行 `Build and sign Windows installer`。工作流先签名应用、服务和卸载程序，再嵌入这些文件生成并签名最终 Setup；验证信任链、时间戳，并在干净 Windows runner 上测试自定义中文目录、重复安装、更新检查服务、快捷方式、文件关联、卸载和用户数据保留。填写上一版签名 Setup 的版本时，也检查升级或旧 MSI 迁移路径，并尝试生成节省至少 10% 下载量的差分包。发布完整 Setup、差分（如有）和 `SHA256SUMS.txt`；用户直接运行 Setup 即可，无需额外模型包。构建阶段会校验默认模型是否齐全，缺少模型时停止生成安装器。

免费签名需项目所有者申请并获批。将 [应用与卸载程序签名规则](../installer/signpath.xml) 和 [Setup 签名规则](../installer/signpath-setup.xml) 分别导入 SignPath 的 `windows-payload` 和 `windows-setup` 制品配置；为 `windows-release-signing` 环境配置 `SIGNPATH_API_TOKEN`、`SIGNPATH_ORGANIZATION_ID`、`SIGNPATH_PROJECT_SLUG` 和 `SIGNPATH_SIGNING_POLICY_SLUG`。本地构建没有发布签名。[SignPath 申请条件](https://signpath.org/terms)
