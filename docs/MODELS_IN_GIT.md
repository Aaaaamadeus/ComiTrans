# 源码仓库中的模型

本次仅同步开发源码与模型，不创建标签或正式 Release。源码版本号保留为 2.5.1 本地预览。

仓库使用 Git LFS 保存六个 ONNX 文件：CharSpot Small、ogkalu Small INT8、PP-OCRv6 manga 文字行检测、韩语与英语 PP-OCRv5、LaMa。词表、配置和许可证作为普通文件保存。旧模型仍可通过兼容路径使用。

```powershell
git lfs install
git clone https://github.com/Aaaaamadeus/ComiTrans.git
cd ComiTrans
# 切换到模型适配更新所在分支后运行：
git lfs pull
```

如果跳过 LFS 下载，`.onnx` 会是文本指针，不能用于推理。先运行 `git lfs pull`。新检测器和日语 OCR 也可通过 `scripts/download_split_detector.py`、`scripts/download_charspot_small.py` 从固定上游提交安装到尚不存在的目录；下载器校验长度与 SHA256，并保留已有目录。

模型清单共 284,712,120 字节（未压缩），包含必要配置、词表、清单和许可证，与 `docs/models/v2.5.1-inventory.json` 一致。开发环境可执行：

```powershell
.\.venv\Scripts\python scripts/audit_local_models.py --output tmp/models-check.json
```

固定版本、许可证和逐文件 SHA256 见 [升级审计](MODEL_UPGRADE-v2.5.1.md)、[CharSpot 清单](models/charspot-small.json)、[检测器清单](models/split-detector.json)。CharSpot 权重适用 **CC BY-NC-SA 4.0**，代码适用 Apache-2.0；权重的非商业限制仍适用于下游。保留包内署名、模型卡与许可文本。

本次提交仅同步模型、适配及对应验证资料。历史本地打包记录不代表此开发快照已完成发行验收。漫画评测页和对照图片仅供本地评测，不随仓库分发。
