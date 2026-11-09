# 漫画检测器本地对照

2026-11-03。仅比较当前 `comic-text-detector.onnx` 和 ogkalu 官方仓库的 FP32 `detector.onnx`。结论是有检测加速和气泡结构信息的价值，目前证据不足以将它直接替换进 ComiTrans 的完整擦字流程。此处记录 FP32 单图实验。随后 v2.5.1 预览采用了 Small INT8 和独立文字行模型。

后续已测试两个 INT8 导出、FP32 搭配轻量文字行模型，以及裁剪旧图保留行和掩膜的路径。真实页修补结果及总耗时见[检测职责拆分实验](DETECTOR_SPLIT.md)。

## 固定来源与接口

候选来自 [官方仓库](https://huggingface.co/ogkalu/comic-text-and-bubble-detector/tree/16e8a622f91fabc6b5b65c96d32d1183f8843546)，提交 `16e8a622f91fabc6b5b65c96d32d1183f8843546`，模型卡声明 Apache-2.0。FP32 文件 168,481,531 字节，SHA256 `065744e91c0594ad8663aa8b870ce3fb27222942eded5a3cc388ce23421bd195`。现有文件 94,669,756 字节，SHA256 `1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f`。均无外部 ONNX 权重。完整图接口和实测数值见 [机器记录](models/detector-comparison.json)。

候选输入为 RGB、Pillow bilinear 640×640、float32 除以 255，按官方 `preprocessor_config.json` 不做 mean/std 标准化、不 letterbox。另一路 `orig_target_sizes` 在本导出图中直接 Tile 为框的乘数，必须提供 `[width,height]`，已检查计算图及输出覆盖图。输出为 `labels/boxes/scores`，类别 0 气泡、1 框内文字、2 框外文字。用于文字统计时排除气泡类别，主阈值预先选 0.5，另记录 0.3/0.7 敏感性结果。

现有模型使用主程序的 `OnnxTextDetector`，1024 letterbox、原有 0.4 置信阈值及分组/掩膜细化。两者接收同一批原尺寸页，没有给任一方案额外降低页面分辨率以换速度。两者本身的标准网络输入大小不同。

## 样本与准确性范围

用户许可本地评测的三张日语漫画页，尺寸 1220×1762、1220×1756、800×1138。候选推理前看图补标了页边文案、黑底招牌、拟声词，共 32 个文字组（6、10、16）。排除水印和单独爱心符号。沿用之前 22 个 OCR 文字框，并补上此前未选作 OCR 评测的小字/拟声词。标注由助手完成，框比较粗，也没有独立人工复核。

| 目检项目 | 当前模型 | 候选 |
|---|---:|---:|
| 三页输出文字框数，阈值 0.5 | 5 / 9 / 10 | 5 / 9 / 11 |
| 可定位的标注文字组 | 6 / 9 / 10 | 6 / 9 / 11 |
| 明显落在无文字图案上的误框 | 0 | 0 |

同一个输出框可能覆盖两个标注组，定位计数仅表示找到区域，不表示文字全部识别正确。两者都把第一页底部两行文案合为一个框。候选补到了第三页黑底招牌，部分小字/宣传文案框也更完整。候选对话框留白更大，可能影响排版范围。两者都漏掉第二页大幅描边拟声词和第三页五处蝉鸣拟声词。这些样本没有显示候选在复杂背景拟声词上的优势。

也保存了 IoU≥0.5 的一对一最大匹配统计。当前匹配 24/32，候选 21/32。候选 4 个未匹配输出框经目检仍位于真实文字，其中包括留白较大和合并行导致的匹配失败，不能将其全部称为误检。该粗标注集不适合据此给出通用 mAP，也不能用上面的目检计数宣称全面召回提升。阈值扫描只作诊断，未挑选最有利的阈值作为主成绩。

## CPU 和 CUDA 性能

Windows、RTX 4060 Laptop 8GB、AMD64 Family 25 Model 117、ORT 1.23.2。各方案启动独立进程，最终四组串行运行。首次推理单独计时，随后每页三轮，取每页中位数。图像提前加载，预处理及后处理计入总耗时。新进程会话加载不清理 Windows 磁盘缓存。

| 指标 | 当前 CPU | 候选 CPU | 当前 CUDA | 候选 CUDA |
|---|---:|---:|---:|---:|
| 会话加载，秒 | 0.349 | 1.376 | 1.572 | 2.512 |
| 首次完整调用，秒 | 1.077 | 0.421 | 0.503 | 0.444 |
| 三页平均热调用，ms/页 | 948.0 | 405.0 | 133.0 | 55.7 |
| 仅 ORT session.run，ms/页 | 854.3 | 390.9 | 49.3 | 41.5 |
| 进程峰值工作集，MB | 1104.0 | 419.6 | 1138.0 | 1025.3 |

完整调用耗时在本样本下降约 57.3% / 58.1%，但输出任务不同。当前模型还生成文字行和擦字掩膜并执行细化，候选只生成框。CUDA 纯网络部分下降约 15.9%，不能将 58.1% 全部当成网络加速，也不能据此预测完整翻译耗时。显存独占峰值本轮没有测量。CUDA 使用已有 NVIDIA DLL，通过进程环境指定，程序无 PyTorch 导入。CPU 和 CUDA 都确实启用了对应 EP。

## 升级决策与接入成本

候选具有升级价值，适合继续验证气泡范围、检测加速、招牌召回。直接更换 ONNX 文件不可行。现有后处理读取 `blk/seg/det`，生成 `TextBlock` 的行多边形、字号、语言/方向和像素级掩膜，pipeline 的行裁剪、擦字和布局依赖这些数据。候选需建立气泡与文字关联、文字方向/行信息、框合并及重叠处理，并验证独立掩膜生成方法。尤其是韩英行识别与描边复杂背景擦字，当前三个日语页面没有提供替换所需证据。

如果保留现有分割图来提供掩膜，仍需跑旧模型，当前测得的检测加速不能直接兑现。如果只依据候选矩形擦字，框内背景和线稿可能受到影响，本轮没有采用这一处理。

候选比现有模型增加 73,811,775 字节。基于当前 CharSpot 单日语模型包的 366,431,736 字节，单换权重后约为 440,243,511 字节，另加候选来源/预处理配置和许可文件。约为 v2.5.0 基线的 75.3%，有充足预算。体积不是本次主要限制。

本轮只新增独立评测脚本和报告，候选权重留在忽略的本地实验目录。图片、标注坐标、逐框输出及覆盖图均留在 `tmp/detector-comparison/`，不可公开分发。CPU 覆盖图已逐页检查，CPU/CUDA 输出文字框数与类别一致。按用户缩小后的范围，最终主对照仅使用 FP32 候选和现有检测器，未运行其它精度候选，也未更换默认或重打预览包。

## 本地复现

下载并校验上述固定提交的 FP32 ONNX、预处理配置。私有标注文件需有 `rights`、`pages`，每页含来源路径、SHA256 及 `regions` 中的 `box`。

```powershell
.\.venv\Scripts\python scripts/benchmark_detectors.py --model legacy --device cpu --annotations tmp/detector-comparison/annotations.json --output tmp/detector-comparison/legacy-cpu.json
.\.venv\Scripts\python scripts/benchmark_detectors.py --model tmp/detector-comparison/detector.onnx --device cpu --annotations tmp/detector-comparison/annotations.json --output tmp/detector-comparison/candidate-cpu.json --overlays tmp/detector-comparison/candidate-cpu
```

GPU 运行在已配置 CUDA/cuDNN 的环境中将 `--device` 设为 `cuda`。输出中的 `providers` 可确认是否实际启用 CUDA，不能只看请求参数。
