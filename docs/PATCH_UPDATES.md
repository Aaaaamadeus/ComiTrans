# 补丁基线与小版本更新

v2.4.0 是后续小版本补丁的基线。主程序 ZIP 包含 `release-manifest.json`、`Apply-Update.ps1` 和 `Update-ComiTrans.bat`，无需额外安装 Python。

## 使用补丁

1. 关闭 ComiTrans，下载适用于当前构建的补丁 ZIP。
2. 在程序目录双击 `Update-ComiTrans.bat`，选择下载的 ZIP。
3. 更新器校验原程序、备份修改文件、应用补丁并校验结果，完成后重新启动 ComiTrans。

也可以解压补丁，双击其中的 `Update-ComiTrans.bat`，选择 `ComiTrans.exe` 所在目录。命令行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Apply-Update.ps1 -Patch D:\Downloads\ComiTrans-patch.zip -InstallDir D:\ComiTrans
```

更新器只修改程序管理的文件。配置、用户导入/下载的 `user_fonts`、模型、日志和漫画文件不纳入补丁。内置字体属于程序资源，会随补丁新增或更新。原程序文件与要求的基线不符时会停止；写入失败时自动恢复。备份和状态记录保存在安装目录 `.comitrans-update`，确认新程序正常后可以清理。

v2.4.1 使用完整程序包发布，模型继续复用，见[版本说明](RELEASE-v2.4.1.md)。本页的补丁流程仅适用于另行提供补丁的版本。

`build_id` 根据版本、平台和逐文件大小及 SHA256 生成，标识补丁适用的确切程序构建。

## 维护者生成补丁

`package_release.py` 为完整程序包加入基线，同时将 `baseline.json` 和 `SHA256SUMS.txt` 写入源码目录 `docs/releases/v<版本>/`，随发布源码提交。Release 只提供程序包和模型包。基线不包含自身哈希，校验文件也不进入程序包，避免循环依赖。

```powershell
# 构建并打包后续版本，先更新应用版本号和对应发布说明。
.\build_app.ps1
.\.venv\Scripts\python.exe package_release.py

# 示例：为将来版本生成补丁，替换 vNext 为实际目标版本。
.\.venv\Scripts\python.exe scripts/create_patch.py --base docs/releases/v2.4.0/baseline.json --target release/ComiTrans-vNext-app.zip --output release/ComiTrans-v2.4.0-to-vNext-patch.zip
```

`--base` 也可使用包含基线的上一版完整程序 ZIP。目标 ZIP 必须包含基线。补丁按 SHA256 比较，只携带新增或修改文件及删除清单；生成前校验目标包与其清单一致。

固定 Python、Qt、ONNX 和构建工具版本有助于控制体积。实际升级的依赖会进入补丁。完整包保留用于新安装和无法匹配补丁的安装，模型继续独立发布。

## 验证

13 项补丁回归与完整 176 项回归通过，覆盖错版本、修改过的原文件、损坏补丁、用户数据保留和写入失败回滚。894 个程序文件通过基线校验，程序启动和真实模型预热通过。[验证记录](ui-review/patch-baseline-review.json)。

## English

v2.4.0 includes a file-level baseline. Close the app, run `Update-ComiTrans.bat` in its folder, and select a patch ZIP for a future version; Python is not required.

The updater verifies the installed files, payload and final result, backs up changed files, and restores them on a failed write. Configuration, fonts, models and manga are preserved. Backups live in `.comitrans-update`.

Build fingerprints identify the source and target of each patch. Maintainers can use `scripts/create_patch.py` with a prior baseline JSON or app ZIP and a new app ZIP. Full packages remain available for fresh installs.

Baseline JSON and SHA256 checksums are committed under `docs/releases/v<version>/` in the source repository. Releases provide the app and model archives; the app includes its own baseline.
