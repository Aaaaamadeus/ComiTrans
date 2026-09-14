# ComiTrans 模型来源与可选模型

本文记录 ComiTrans 当前使用的模型来源，以及可替换或未来可评估的 ONNX / 更优模型。

## 当前使用的模型（全 ONNX）

ComiTrans 已全面切换为 ONNX 推理，不再依赖 PyTorch / torchvision / transformers。

| 用途 | 模型 | 来源 |
| --- | --- | --- |
| 漫画气泡与文本检测 | `text_detector/comic-text-detector.onnx` | [mayocream/comic-text-detector-onnx](https://huggingface.co/mayocream/comic-text-detector-onnx)，由 [dmMaze/comic-text-detector](https://github.com/dmMaze/comic-text-detector) 导出 |
| 日文/中英混排 OCR（默认） | `baberu-ocr/`（vision int4 + decoder int8 + vocab） | [genshiai-daichi/baberu-ocr](https://huggingface.co/genshiai-daichi/baberu-ocr)，Apache-2.0，面向漫画气泡、竖排、拟声词与混合字符训练 |
| 日文 OCR（兼容回退） | `manga-ocr-onnx/`（encoder + decoder + tokenizer） | [l0wgear/manga-ocr-2025-onnx](https://huggingface.co/l0wgear/manga-ocr-2025-onnx)，基于 [kha-white/manga-ocr](https://github.com/kha-white/manga-ocr) 与 jzhang533 的 2025 微调权重，使用 Optimum 导出 |
| LaMa 背景修复 | `manga-lama/lama-manga-dynamic.onnx` | manga-lama，本身即为 ONNX |

默认 OCR 推理由 `onnx_baberu_ocr.py` 实现，直接运行作者发布的三段 ONNX 图与 KV cache 解码；`ocr_backend: auto` 在 Baberu 模型缺失或不兼容时回退 `onnx_manga_ocr.py`。两者都不依赖 transformers / torch。

Baberu 官方 Manga109-v2026（n=2000）测试报告的行级 CER 为 0.0345、归一化 CER 为 0.0871；同一报告中 manga-ocr 分别为 0.0422 与 0.0954。当前使用 121 MB 的最小量化组合，官方报告其精度只比 242 MB 组合约低 0.002 nCER。

## 其它可用的 ONNX 版本

- 检测器：
  - [mayocream/comic-text-detector-onnx](https://huggingface.co/mayocream/comic-text-detector-onnx)：当前使用的版本。
  - [ogkalu/comic-text-and-bubble-detector](https://huggingface.co/ogkalu/comic-text-and-bubble-detector)：RT-DETR-v2 训练的漫画文本 + 气泡联合检测，输出格式与当前后处理不同，需要额外适配。
- OCR：
  - [genshiai-daichi/baberu-ocr](https://huggingface.co/genshiai-daichi/baberu-ocr)：当前默认，覆盖日文竖排、多字体、拟声词及日/中/英混排。
  - [mayocream/manga-ocr-onnx](https://huggingface.co/mayocream/manga-ocr-onnx)：另一个 manga-ocr ONNX 导出。
  - [l0wgear/manga-ocr-2025-onnx](https://huggingface.co/l0wgear/manga-ocr-2025-onnx)：当前使用的版本。

## 效果更好的检测模型候选

- [rtr46/meiki.text.detect.v0](https://huggingface.co/rtr46/meiki.text.detect.v0)：低延迟文本检测模型，针对日文游戏和漫画优化，基于 D-FINE + MobileNetV4 small。
- [ragavsachdeva/magiv3](https://huggingface.co/ragavsachdeva/magiv3)：统一视觉语言漫画理解模型，可同时做分镜、角色、文本、气泡尾巴定位和 OCR，效果强但体量大，适合作为未来重型方案评估。
- [dmMaze/BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) 生态：其文本检测模块持续更新，社区也有 [BallonsTranslator-Pro](https://github.com/thomaswantstobeaskeleton/BallonsTranslator-Pro) 等增强分支，可参考其检测模型训练与推理实现。

## 替换模型注意事项

1. 模型文件放在 exe 旁 `comic-translate-ai/models/`（Release 从模型包解压到该目录），在“API 配置”或 `config.yaml` 中指定路径即可。
2. 检测模型必须是输出 `blk / seg / det` 三路的 ONNX（与当前 `comic-text-detector.onnx` 一致）；其它结构需要适配 `onnx_text_detector.py`。
3. Baberu 包需要包含 `onnx/vision_int4.onnx`（或 fp16）、两个 decoder ONNX 与 `tokenizer/vocab.json`；manga-ocr 包需要 encoder、decoder 和 tokenizer。可在“API 配置 → 日文 OCR”切换后端。
