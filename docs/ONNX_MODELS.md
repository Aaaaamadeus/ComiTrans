# ComiTrans 模型来源与可选模型

本文记录 ComiTrans 当前使用的模型来源，以及可直接替换或未来可评估的 ONNX / 更优模型。

## 当前使用的模型

| 用途 | 模型 | 来源 |
| --- | --- | --- |
| 漫画气泡与文本检测 | `comictextdetector.pt`（PyTorch） | [dmMaze/comic-text-detector](https://github.com/dmMaze/comic-text-detector) |
| 日文 OCR | `manga-ocr-base`（PyTorch） | [kha-white/manga-ocr](https://github.com/kha-white/manga-ocr) |
| LaMa 背景修复 | `lama-manga-dynamic.onnx` | manga-lama（已为 ONNX，无需转换） |

## comictextdetector 的 ONNX 版本

- [mayocream/comic-text-detector-onnx](https://huggingface.co/mayocream/comic-text-detector-onnx)：dmMaze comic-text-detector 的 ONNX 导出，文件 `comic-text-detector.onnx`。
- [ogkalu/comic-text-and-bubble-detector](https://huggingface.co/ogkalu/comic-text-and-bubble-detector)：RT-DETR-v2 训练的漫画文本 + 气泡联合检测模型，文件 `detector.onnx`，同时输出文本块与气泡区域。

当前检测代码（`comic_text_detector/inference.py`）已支持 `.onnx` 后缀，通过 OpenCV DNN 加载，因此上述 ONNX 可直接放到 `models/text_detector/` 并在配置里指定路径试用。

## manga-ocr 的 ONNX 版本

- [l0wgear/manga-ocr-2025-onnx](https://huggingface.co/l0wgear/manga-ocr-2025-onnx)：由 kha-white/manga-ocr 使用 Hugging Face Optimum 导出的 ONNX 版。
- [mayocream/manga-ocr-onnx](https://huggingface.co/mayocream/manga-ocr-onnx)：另一个 manga-ocr ONNX 导出。

注意：当前 OCR 推理走 `manga_ocr` Python 库（PyTorch）。要切换到 ONNX OCR，需要把 `MangaOcr` 推理替换为 onnxruntime 实现，本文档先记录来源，不保证开箱即用。

## 效果更好的检测模型候选

- [rtr46/meiki.text.detect.v0](https://huggingface.co/rtr46/meiki.text.detect.v0)：低延迟文本检测模型，针对日文游戏和漫画优化，基于 D-FINE + MobileNetV4 small，对日文排版效果较好。
- [ragavsachdeva/magiv3](https://huggingface.co/ragavsachdeva/magiv3)：统一视觉语言漫画理解模型，可同时做分镜、角色、文本、气泡尾巴定位和 OCR，效果强但体量大，适合作为未来重型方案评估。
- [dmMaze/BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) 生态：其文本检测模块持续更新，社区也有 [BallonsTranslator-Pro](https://github.com/thomaswantstobeaskeleton/BallonsTranslator-Pro) 等增强分支，可参考其检测模型训练与推理实现。

## 替换模型注意事项

1. 模型文件放在 exe 旁 `comic-translate-ai/models/`（源码运行时为 `comic-translate-ai/models/`），在“API 配置”或 `config.yaml` 中指定路径即可。
2. 检测模型切换为 ONNX 后，`TextDetector` 会走 OpenCV DNN 后端，不再加载 PyTorch 检测权重，可进一步减少打包体积。
3. 切换到重型模型前建议先评估单页耗时、显存占用和气泡区域输出格式是否与现有管线兼容。