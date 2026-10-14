# 补丁基线与小版本更新

2026-10-14 重新封包的 v2.4.0 是后续小版本补丁的基线。主程序 ZIP 包含 `release-manifest.json`、`Apply-Update.ps1` 和 `Update-ComiTrans.bat`，无需额外安装 Python。

## 使用补丁

1. 关闭 ComiTrans，下载适用于当前构建的补丁 ZIP。
2. 在程序目录双击 `Update-ComiTrans.bat`，选择下载的 ZIP。
3. 更新器校验原程序、备份修改文件、应用补丁并校验结果，完成后重新启动 ComiTrans。

也可以解压补丁，双击其中的 `Update-ComiTrans.bat`，选择 `ComiTrans.exe` 所在目录。命令行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Apply-Update.ps1 -Patch D:\Downloads\ComiTrans-patch.zip -InstallDir D:\ComiTrans
```

更新器只修改程序管理的文件。配置、字体、模型、日志和漫画文件不纳入补丁。原程序文件与要求的基线不符时会停止；写入失败时自动恢复。备份和状态记录保存在安装目录 `.comitrans-update`，确认新程序正常后可以清理。

## 已下载早期 2.4.0 的用户

早期 v2.4.0 没有基线清单。下载 `ComiTrans-v2.4.0-baseline-patch.zip`，解压后运行其中的 `Update-ComiTrans.bat`，选择原安装目录。补丁验证原发行包的每个程序文件，再补入基线和更新入口。

也可以下载重新封包的完整程序包，解压合并到原目录。保留配置、整个 `user_fonts`、模型和漫画。根目录出现 `release-manifest.json` 表示基线已建立。

同一版本号的不同构建以 `build_id` 区分。该指纹根据版本、平台和逐文件大小及 SHA256 生成，补丁不会把早期 2.4.0 与重新封包的 2.4.0 混用。

## 维护者生成补丁

`package_release.py` 为完整程序包加入基线，同时输出 `ComiTrans-v<版本>-baseline.json`。基线不包含自身哈希，避免循环依赖。

```powershell
# 构建并打包后续版本，先更新应用版本号和对应发布说明。
.\build_app.ps1
.\.venv\Scripts\python.exe package_release.py

# 以下以未来的 2.4.1 为例。
.\.venv\Scripts\python.exe scripts/create_patch.py --base release/v2.4.0/ComiTrans-v2.4.0-baseline.json --target release/ComiTrans-v2.4.1-app.zip --output release/ComiTrans-v2.4.0-to-v2.4.1-patch.zip
```

`--base` 也可使用上一版完整程序 ZIP。旧 ZIP 没有清单时需显式指定 `--base-version 2.4.0`，目标 ZIP 必须包含基线。补丁按 SHA256 比较，只携带新增或修改文件及删除清单；生成前校验目标包与其清单一致。

固定 Python、Qt、ONNX 和构建工具版本有助于控制体积。实际升级的依赖会进入补丁。完整包保留用于新安装和无法匹配补丁的安装，模型继续独立发布。

## 验证

13 项新增补丁回归与完整 176 项回归通过，覆盖错版本、修改过的原文件、损坏补丁、用户数据保留和写入失败回滚。实际旧 2.4.0 迁移后，894 个程序文件与新完整包一致，程序启动和真实模型预热通过。[验证记录](ui-review/patch-baseline-review.json)。

## English

The refreshed v2.4.0 establishes a file-level baseline. Close the app, run `Update-ComiTrans.bat` in its folder, and select a patch ZIP; Python is not required.

Original v2.4.0 users can extract `ComiTrans-v2.4.0-baseline-patch.zip`, run its launcher, and select their existing installation. The updater verifies the original files, payload and final result, backs up changed files, and restores them on a failed write. Configuration, fonts, models and manga are preserved. Backups live in `.comitrans-update`.

Build fingerprints distinguish packages sharing a version. Maintainers can use `scripts/create_patch.py` with a prior baseline JSON or app ZIP and a new app ZIP. Full packages remain available for fresh installs.
