# ComiTrans 模型来源与可选模型

本文记录 ComiTrans 当前使用的模型来源，以及可替换或未来可评估的 ONNX / 更优模型。

v2.5.1 预览模型包中，日语识别采用 CharSpot Small。旧模型包的引擎和来源列于下表。[新包清单和许可](MODEL_UPGRADE-v2.5.1.md) · [安装与回退](RELEASE-v2.5.1.md)

## v2.5.1 预览程序的模型分工

| 模型 | 什么时候运行 | 给下一步的结果 | 设备 |
| --- | --- | --- | --- |
| ogkalu Small INT8 ＋ PP-OCRv6 manga | 处理原始漫画页时 | Small 提供文字框，PP 提供文字行，按两者中点修边，利用行内对比度提取擦字种子 | CPU 或 CUDA |
| CharSpot Small | 新模型包选择日语自动 OCR 时 | 按阅读顺序解码每个文字块的原文 | CPU |
| 韩语 PP-OCRv5 mobile | 源语言选韩语时 | 识别裁出的韩文文字行，组合成块文本 | CPU 或 CUDA |
| 英语 PP-OCRv5 mobile | 源语言选英语时 | 识别裁出的英文文字行，组合成块文本 | CPU 或 CUDA |
| manga LaMa | 有待擦除像素且平涂、局部背景重建不能完成修补时 | 补出掩膜位置的背景，供排版与回退使用 | CPU 或 CUDA |
| Baberu、manga-ocr | 旧安装显式选择，或日语自动模式按可用性回退时 | 和 CharSpot 一样提供块原文。一次选用一个引擎，新模型包只携带 CharSpot | Baberu 用 CPU，manga-ocr 支持 CPU 或 CUDA |

文字翻译和译文排版是后续步骤。新程序自动选择完整模型包。旧检测器可用绝对路径显式选择。[拆分对照](DETECTOR_SPLIT.md)

## 已发布的 v2.5.0 模型

ComiTrans 已全面切换为 ONNX 推理，不再依赖 PyTorch / torchvision / transformers。

| 用途 | 模型 | 来源 |
| --- | --- | --- |
| 漫画文字块、文字行和像素掩膜 | `text_detector/comic-text-detector.onnx` | [mayocream/comic-text-detector-onnx](https://huggingface.co/mayocream/comic-text-detector-onnx)，由 [dmMaze/comic-text-detector](https://github.com/dmMaze/comic-text-detector) 导出 |
| 日文/中英混排 OCR（默认） | `baberu-ocr/`（vision int4 + decoder int8 + vocab） | [genshiai-daichi/baberu-ocr](https://huggingface.co/genshiai-daichi/baberu-ocr)，Apache-2.0，面向漫画气泡、竖排、拟声词与混合字符训练 |
| 日文 OCR（兼容回退） | `manga-ocr-onnx/`（encoder + decoder + tokenizer） | [l0wgear/manga-ocr-2025-onnx](https://huggingface.co/l0wgear/manga-ocr-2025-onnx)，基于 [kha-white/manga-ocr](https://github.com/kha-white/manga-ocr) 与 jzhang533 的 2025 微调权重，使用 Optimum 导出 |
| LaMa 背景修复 | `manga-lama/lama-manga-dynamic.onnx` | [ogkalu/lama-manga-onnx-dynamic](https://huggingface.co/ogkalu/lama-manga-onnx-dynamic)，本地 SHA256 与固定导出一致，详见升级审计 |

默认 OCR 推理由 `onnx_baberu_ocr.py` 实现，直接运行作者发布的三段 ONNX 图与 KV cache 解码；`ocr_backend: auto` 在 Baberu 模型缺失或不兼容时回退 `onnx_manga_ocr.py`。两者都不依赖 transformers / torch。

Baberu 旧模型卡的 Manga109-v2026（n=2000）成绩不适合直接衡量 v1.2：新版训练使用了部分 Manga109-s 标注。v2.5.0 默认是约 121 MB 的 v1.0 量化组合；独立测试的 v1.2 约 122 MB，只有有限本地样本证据，不能宣称全面提升。

## 其它可用的 ONNX 版本

- 检测器：
  - [mayocream/comic-text-detector-onnx](https://huggingface.co/mayocream/comic-text-detector-onnx)：当前使用的版本。
  - [ogkalu/comic-text-and-bubble-detector](https://huggingface.co/ogkalu/comic-text-and-bubble-detector)：RT-DETR-v2 训练的漫画文本 + 气泡联合检测，输出格式与当前后处理不同，需要额外适配。
- OCR：
  - [genshiai-daichi/baberu-ocr](https://huggingface.co/genshiai-daichi/baberu-ocr)：v2.5.0 默认日语引擎。
  - [mayocream/manga-ocr-onnx](https://huggingface.co/mayocream/manga-ocr-onnx)：另一个 manga-ocr ONNX 导出。
  - [l0wgear/manga-ocr-2025-onnx](https://huggingface.co/l0wgear/manga-ocr-2025-onnx)：旧包的兼容回退版本。

## 效果更好的检测模型候选

- [rtr46/meiki.text.detect.v0](https://huggingface.co/rtr46/meiki.text.detect.v0)：低延迟文本检测模型，针对日文游戏和漫画优化，基于 D-FINE + MobileNetV4 small。
- [ragavsachdeva/magiv3](https://huggingface.co/ragavsachdeva/magiv3)：统一视觉语言漫画理解模型，可同时做分镜、角色、文本、气泡尾巴定位和 OCR，效果强但体量大，适合作为未来重型方案评估。
- [dmMaze/BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) 生态：其文本检测模块持续更新，社区也有 [BallonsTranslator-Pro](https://github.com/thomaswantstobeaskeleton/BallonsTranslator-Pro) 等增强分支，可参考其检测模型训练与推理实现。

## 替换模型注意事项

1. 模型文件放在 exe 旁 `comic-translate-ai/models/`（Release 从模型包解压到该目录），在“API 配置”或 `config.yaml` 中指定路径即可。
2. 自定义旧格式检测模型须输出 `blk / seg / det` 三路的 ONNX（与当前 `comic-text-detector.onnx` 一致）；其它结构需要适配 `onnx_text_detector.py`。
3. Baberu 包需要包含 `onnx/vision_int4.onnx`（或 fp16）、两个 decoder ONNX 与 `tokenizer/vocab.json`；manga-ocr 包需要 encoder、decoder 和 tokenizer。可在“API 配置 → 日文 OCR”切换后端。
