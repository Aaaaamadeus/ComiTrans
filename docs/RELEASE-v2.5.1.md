# ComiTrans v2.5.1 本地预览

## 下载与安装

将同目录的程序包和模型包解压到一个空目录，合并 ComiTrans 文件夹，启动 ComiTrans.exe。本次产物在 release/v2.5.1/。日语选择「自动」。需要沿用配置时复制旧 config.yaml，保留原安装目录和项目。源码用户可运行 scripts/download_split_detector.py、scripts/download_charspot_small.py 安装新权重。下载器按固定提交、长度和 SHA256 校验。

## 更新内容

修复白色漫画气泡擦字后出现灰斑的问题：先检查框内纸色和笔画周围的像素，纸面足够均匀时，在已有擦除掩膜内按原纸色填充。

在「设置 → 运行与输出 → GPU 安装说明与下载」点击「下载安装便携 GPU 运行库」，完成后重启。首次下载约 1.53 GB，需要兼容的 NVIDIA 驱动。DLL 保存在程序旁的 gpu-runtime 目录，无需另外安装 Python 或配置 PATH。

修复 Windows 程序包缺少 TLS 证书策略文件导致翻译请求在发送前失败的问题。失败弹窗复制诊断时会重新读取当前配置及日志。

Windows 源码安装的模型现在继承模型库的访问权限。如果某个模型无法读取，工作台仍可打开，并在诊断中显示对应路径。

默认检测器改用 ogkalu Small INT8 提供文字框、PP-OCRv6 manga v0.2 提供文字行，取原框和文字行外接框对应边的中点作为最终边界。孤立行不会自动送去擦字。两张图均支持 ONNX Runtime CPU/CUDA。日语 OCR 使用 CharSpot Small（CPU），韩英继续使用 PP-OCRv5，背景修补使用 LaMa。模型包含所有必要配置、词表、清单及许可证共 **284,712,120 字节**，是 v2.5.0 的 **48.71%**。CharSpot 权重以 CC BY-NC-SA 4.0 供非商业使用，两张新检测图的模型卡标注 Apache-2.0。

仅有完整 v2.5.0 模型包时，新程序仍可使用旧检测器和旧 OCR。要在两套模型共存时指定旧检测器，请将 detector_model 设为现有 comic-text-detector.onnx 的绝对路径。切回新版设为 auto。完整回退可直接启动保留的旧安装。使用新输出目录比较，以免复用已有结果。

## 验证

相同三页日漫的 32 处粗标注中，Small 修框后一对一 IoU≥0.5 命中 23 处，覆盖标注面积至少 80% 的有 25 处，旧检测器分别为 23、20 处。覆盖指标同时限制预测面积不超过标注面积的四倍。该指标衡量文字框，整页修补速度及复杂背景质量需分开评估。独立的 22 个固定日语裁剪中，CharSpot 的字符错误数是 5，v2.5.0 默认 Baberu 为 12。核对同目录 SHA256SUMS.txt 验证两包。详见 [检测实测](DETECTOR_SPLIT.md) 和 [模型升级记录](MODEL_UPGRADE-v2.5.1.md)。

## English

Windows source installs now inherit the model library permissions. The workbench can open and report an inaccessible model path. Extract both ZIPs into a fresh directory and run ComiTrans.exe. The default detector combines ogkalu Small INT8 with PP-OCRv6 manga line detection and midpoint box refinement. Both graphs run in ONNX Runtime on CPU or CUDA. The package includes CharSpot Small for Japanese, PP-OCRv5 for Korean and English, and LaMa for repair. Its uncompressed model inventory is 284,712,120 bytes. On three Japanese pages the new pipeline matched 23 of 32 coarse regions at IoU ≥ 0.5, the same as the legacy detector, and covered at least 80% of 25 regions versus 20. Existing legacy model directories remain usable. Set detector_model to the absolute path of the old ONNX file to select it explicitly. See SHA256SUMS.txt to verify the archives.
