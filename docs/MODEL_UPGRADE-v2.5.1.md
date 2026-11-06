# v2.5.1 本地模型升级审计与验证

审计日期：2026-11-03（Asia/Hong_Kong）。状态：本地预览，未发布。以已发布 v2.5.0 的程序和模型包为基线；开始工作时之后仅有 README 横幅改动，用户未跟踪图片/提示词保留。

## 结论与实际改动

新模型包仅携带 **CharSpot Small** 作为日语 OCR。Baberu、CharSpot 和 manga-ocr 在主程序内都读取相同的日语文字框并返回文字。旧自动模式只初始化 Baberu，成功时从不加载 manga-ocr 权重。manga-ocr 只有在 Baberu 初始化失败时回退或手动选择时启动。识别结果不佳不会触发逐框重试。

新自动模式优先加载已安装的 CharSpot，缺少或加载失败时仍支持已有的 Baberu 和 manga-ocr。显式选择的旧后端保留原语义。Baberu v1.2 适配器与下载清单保留给旧安装使用。三个日语引擎的权重只在开发对照时并存。

## v2.5.0 实际清单与调用链

口径：v2.5.0 标签的 `package_release.collect_models()` 的全部文件；与本机已发布 `release/v2.5.0/ComiTrans-v2.5.0-models.zip` 每个成员的未压缩长度之和一致。包含模型、词表、tokenizer、配置、许可证、README、附带推理脚本；排除未发布的开发权重 `manga-ocr-base/pytorch_model.bin`、重复副本、缓存。这里 MB = 1,000,000 字节，不使用 ZIP 文件长度。

| 模型/文件 | 字节 | 设备 | 调用位置 |
|---|---:|---|---|
| comic-text-detector.onnx | 94,669,756 | CPU / CUDA | `main/onnx_text_detector.py:OnnxTextDetector`，pipeline 检测 |
| lama-manga-dynamic.onnx | 206,291,843 | CPU / CUDA | `main/manga_lama.py:MangaLama`，pipeline/编辑器共享会话 |
| korean_PP-OCRv5_rec_mobile.onnx | 13,488,748 | CPU / CUDA | `comic_translate_core/onnx_ppocr.py:OnnxPPOcr`，`ocr.py:create_ocr` |
| en_PP-OCRv5_rec_mobile.onnx | 7,872,351 | CPU / CUDA | 同上 |
| Baberu v1.0 vision_int4.onnx | 52,293,486 | CPU | `main/onnx_baberu_ocr.py:OnnxBaberuOcr` |
| Baberu v1.0 decoder_prefill_int8.onnx | 35,133,596 | CPU | 同上，首 token 与 KV cache |
| Baberu v1.0 decoder_step_int8.onnx | 33,929,034 | CPU | 同上，逐 token 解码 |
| Baberu 词表/配置/许可证/文档/参考脚本 | 156,248 | — | 包含 vocab.json 130,761 字节 |
| manga-ocr encoder_model.onnx | 22,356,885 | CPU / CUDA | `main/onnx_manga_ocr.py:OnnxMangaOcr` |
| manga-ocr decoder_model.onnx | 118,053,454 | CPU / CUDA | 同上，完整前缀解码，无 KV cache |
| manga-ocr tokenizer/配置/文档等 | 221,784 | — | `tokenizers.Tokenizer`，配置 special token，jaconv 后处理 |
| **合计** | **584,467,185** | | |

逐文件大小、SHA256 见 [基线清单](models/v2.5.0-manifest.json)。全套上限取整为 **876,700,777 字节**。新版采用 Small＋文字行半幅修框方案，新模型包共 **284,712,120 字节**，为基线的 **48.7131%**、上限的 **32.4754%**。旧检测器、Baberu 和 manga-ocr 权重仅供旧安装使用。[检测实测与限制](DETECTOR_SPLIT.md)

所有实际选中的 ONNX 已检查外部权重引用，本次均内嵌权重，没有漏计 `.data` 文件。未来外部权重必须纳入文件清单，否则审计失败。[完整新清单与 I/O](models/v2.5.1-inventory.json)。

## 官方来源、许可证与候选决策

| 对象 | 核验来源/版本 | 收益与兼容成本 | 本轮决定 |
|---|---|---|---|
| Baberu | [官方模型库](https://huggingface.co/genshiai-daichi/baberu-ocr)，v1.2 固定 `b9868433dbda3ed9ba1357d008599ff4ada873d5`；本地旧三图 SHA256 与官方 v1.0 全部一致 | Apache-2.0 权重及代码；v1.1 修复长文本训练截断，v1.2 也重训视觉编码器；三个图须整套更新。224×224 RGB、ImageNet 归一化、字符词表、6 层 K/V 顺序仍兼容；v1.2 step 图增大 786,432 字节。增加版本配置、256 token 与符号 cap，改动小 | 兼容已有 Baberu 路径。v1.2 参与对照，新包不携带 Baberu 权重 |
| CharSpot Small | [官方模型卡](https://huggingface.co/muscgab/manga-ocr-charspot-small)，`72ca29202673880ca9c67b1c02c107535be4472b`；[代码](https://github.com/muscgab/manga-ocr-charspot) | ONNX 43,992,111 字节，vocab 62,244 字节，另需配置/许可。官方 ONNX 已含字符框解码、NMS 和阅读顺序；仍需适配保长宽比的预处理及 ids/order 到词表的输出处理，不能替换 Baberu 文件直接使用。代码 Apache-2.0，权重 **CC BY-NC-SA 4.0** | 按官方 CPU 实现独立评测，再经主程序验证，选为唯一随包日语 OCR |
| manga-ocr 2025 | [ONNX 导出](https://huggingface.co/l0wgear/manga-ocr-2025-onnx)，`e8b27bbd3f424fe3877e0bda704d6a920e4f0a33`；[原始微调](https://huggingface.co/jzhang533/manga-ocr-base-2025) | 导出页没有独立 license 字段，微调与原始 manga-ocr 标明 Apache-2.0。现有编码器/decoder 哈希固定；实测更快但该组误字更多 | 保留原回退；发布应保留上游授权、归属和导出来源，不能仅据文件名推断许可 |
| 韩/英 PP-OCRv5 | [RapidOCR 当前官方清单](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml)，v3.10.0 URL 中韩英文件 SHA256 仍与项目固定 v3.9.2 完全相同 | RapidOCR/PaddleOCR Apache-2.0；当前 v5 输入 BGR、48 高、动态宽、零补齐、内置字典、NTC CTC 去重。更新下载版本号并不会更换权重 | 保留；没有韩英真实页与独立人工标注来证明其他模型收益 |
| PP-OCRv6_manga | [官方模型库](https://huggingface.co/Kellenok/PP-OCRv6_manga)，`02af751fcea728fba69ee421a95838f3e549daa2` | Apache-2.0，v0.2 det FP32 1,816,954 字节、rec 21,167,540 字节；需外置 18,708 字词表与行检测/方向/分组，针对日/中，不是韩英 v5 的直接替换 | 已采用 v0.2 det 作文字行定位。rec 未采用，日语识别由 CharSpot 完成 |
| comic-text-detector | [当前导出](https://huggingface.co/mayocream/comic-text-detector-onnx)，`a5d67ec772adef819ef5b0e7aa701fcf4c8bf74a`；[上游代码](https://github.com/dmMaze/comic-text-detector) | 导出页 Apache 标签不能覆盖上游 GPL-3.0。现有后处理依赖 block/seg/line 三路输出及像素掩膜；仓库已带 GPL 文本 | 仅保留旧包加载路径；正式公开分发仍须满足 GPL 对应源码/许可义务，不重新宣称为纯 Apache |
| RT-DETR-v2 detector | [ogkalu 官方模型库](https://huggingface.co/ogkalu/comic-text-and-bubble-detector)，`16e8a622f91fabc6b5b65c96d32d1183f8843546` | Apache-2.0；FP32 168,481,531 字节 / int8 43,838,857 字节。输出气泡及文本框，没有现有擦字像素掩膜；重做后处理和掩膜较多，OCR框召回不等于修补收益 | FP32 对照已完成，框检测更快并补到一处招牌；缺少行/掩膜，已补测三种导出、轻量文字行与裁剪旧图的实际擦字结果，已采用 Small INT8＋PP 文字行半幅修框。[拆分实验](DETECTOR_SPLIT.md)。[对照报告](DETECTOR_COMPARISON.md) |
| meiki | [官方模型卡](https://huggingface.co/rtr46/meiki.text.detect.v0)，`a9cffa4f60cbf72ddb87edf19c6f98a01cd042e6` | LGPL-3.0；小模型约 10.6–41.6 MB，v0.1 偏游戏文本且最多 64 框，上游明确较不适合直接用于漫画；也缺现有像素掩膜 | 不凭延迟宣传替换漫画检测 |
| LaMa | [精确 ONNX 来源](https://huggingface.co/ogkalu/lama-manga-onnx-dynamic/tree/ee4ed4a8447b6730fc41d34f90876b6c48af925a)，SHA256 `de31ffa5ba26916b8ea35319f6c12151ff9654d4261bccf0583a69bb095315f9` 与本地一致 | 导出页 Apache-2.0；[原微调](https://huggingface.co/dreMaz/AnimeMangaInpainting) 标明 MIT。[Sanster 发布页](https://github.com/Sanster/models/releases/tag/AnimeMangaInpainting) 指向该微调；[mayocream 新格式](https://huggingface.co/mayocream/lama-manga)说明只是保留 FP32 张量的 SafeTensors 转换，不能据格式或日期视作更优模型 | 保留现有动态 ONNX 与原尺寸分块。未做新的修补权重 A/B，也不宣称擦字改善；正式分发需保留各层声明，导出源码/训练可复现信息仍有限 |

许可判断更正（2026-11-03）：此前把“公开分发”额外解释为“必须允许商业使用”，这不是用户要求。根据 [官方 NOTICE](https://huggingface.co/muscgab/manga-ocr-charspot-small/blob/main/NOTICE.md) 和 [CC BY-NC-SA 4.0 正文](https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en)，非商业使用和再分发获许可；分发时须保留署名、来源、许可及有关声明，标明修改，若发布改编权重则遵守相同方式共享条件。应分别标明代码和权重许可，不能将权重标为 Apache-2.0，也不据此给全部独立程序代码增加 NC 条款。非商业项目不会自动授权下游商业使用该权重。本次包内保留 `LICENSE`、`LICENSE_MODEL`、`NOTICE.md`、模型卡和来源清单，使用上游原始 ONNX 与词表。程序端按 Apache-2.0 适配预处理与文本解码，随程序附上对应许可与声明。[下载清单与 SHA256](models/charspot-small.json)

## 独立对照方法与结果

真实样本：用户授权本地评测、禁止公开的仓库 3 页日语漫画，共 22 个裁剪（276→278 字的修订来自补入标题装饰线），覆盖竖排、横排、小字、描边、黑底白字和复杂背景。先看图转录，再跑模型；首次检查后发现两处裁剪截断，统一修正并给全部真实裁剪加 4px 边距，重跑全部模型。保留首轮及修订记录于 `tmp/model-upgrade/`。不是随机抽样，也不是独立人工金标准；不能视作 22 个独立漫画作品。

另外用本机字体生成每种语言 6 张控制图，涵盖上述六种形态。韩英无真实漫画，只能检验可运行性与暴露失败。测试原尺寸裁剪，不缩小整页；各自采用本模型的标准预处理，CharSpot 以 16 像素网格和 256 格面积预算对文字框等比缩放并补边。未调用翻译服务。

CER = NFKC + 去空白后的 Levenshtein 编辑距离 / 参考字符总数；不丢弃标点，不截断长输出，不把上游分数混入本地结果。正确率为整个区域字符串完全一致率。模型各自启动独立进程，记录会话加载和首次推理（不清空 Windows 磁盘缓存，故不是断电冷启动）；图像预加载，3 次完整热运行，按每个裁剪取中位数再求和，含模型预处理与解码。硬件为 RTX 4060 Laptop 8GB、AMD64 Family 25 Model 117，Python 3.12.14 / ORT 1.23.2。

| 本轮同批日语真实数据（22 框，278 字，CPU） | Baberu v1.0 | Baberu v1.2 | manga-ocr 2025 | CharSpot 官方 | CharSpot 主程序 |
|---|---:|---:|---:|---:|---:|
| 字符错误数 | 12 | 10 | 16 | 5 | 5 |
| CER | 4.32% | 3.60% | 5.76% | 1.80% | 1.80% |
| 整框正确数 | 14 | 15 | 13 | 18 | 18 |
| 热运行总计（秒） | 4.112 | 5.279 | 3.615 | 0.620 | 0.505 |
| 每框中位数（毫秒） | 189.81 | 245.01 | 170.28 | 27.79 | 22.93 |
| 新进程加载（秒，含后端导入） | 0.624 | 0.579 | 0.695 | 0.401 | 0.594 |
| 首框推理（毫秒） | 195 | 190 | 248 | 39 | 26 |
| 进程峰值工作集（MB） | 312.78 | 313.43 | 234.61 | 166.54 | 176.86 |

主程序所用 CharSpot 对比 v2.5.0 默认，22 框热运行总耗时缩短约 87.7%，逐框错误数有 8 框更少、1 框更多、13 框持平。相对 v1.2 有 6 框更好、1 框更差。一次对照中 ORT 线程调度和本机负载影响绝对耗时，旧 Baberu 在上一轮同图测得 3.576 秒，不能据此推断整页翻译或 GPU 加速倍数。CharSpot OCR 只使用 CPU EP，显存推理分配为零。不同连载、手写、长文仍需更大规模验证。

随后在同一进程预热两个 OCR，交替跑三轮完整的 CPU 检测与识别。输入为 3 张原尺寸页面（1220×1762、1220×1756、800×1138），两条路径均检测到 5、9、10 个区域。三页总耗时的中位数由旧 Baberu 的 10.439 秒降至 CharSpot 的 4.179 秒，缩短约 60.0%。计时含标准检测预处理、气泡分组、实际加边裁剪和 OCR，不含磁盘读取、翻译、修补和排版。

模型输入为 RGB 原始像素而非 ImageNet 标准化。按官方 bicubic 缩放，以边缘中位颜色补边。单张 ONNX 图执行 NMS、振假名过滤和阅读顺序计算。主程序取 `ids[order]` 查字符词表并拼接，保留组合标点。空框输出空串。引擎复用一个 ORT 会话，无自回归 KV 缓存。28 个日语框（含 6 张合成图）与固定提交官方参考实现逐字一致，三轮热运行稳定。CharSpot 合成 6/6 完全正确。Baberu v1.2 与其官方实现在此前三轮也逐框一致。

Baberu v1.0 与 v1.2 的合成日语 CER 分别为 7.41%、1.85%；不能将这 6 张同一句话的控制图当成额外独立漫画证据。韩语合成 6 张 CER 16.67%、整段正确 5/6；英语合成 CER 75.93%、正确 1/6，宽边距/低字高及竖排存在明显失败。测试直接把控制图喂给行识别器，没有冒充完整检测+行裁剪流程；没有据此臆造新的韩英模型优势。韩英真实漫画、长气泡、手写/更多拟声词、不同题材仍待有权样本与人工金标准验证。

## 检测、修补与打包验证

初次隔离 OCR 对照时固定了旧检测器和 LaMa：真实日语整页在 CPU/CUDA 均检测到 9 个区域，检测热运行约 0.757/0.119 s；512×512 合成背景的小区域原尺寸修补热运行约 0.349/0.060 s，蒙版外像素完全相同。这里是保留路径的可运行性验证，不是新旧修补质量比较。

同进程 CPU 后 GPU 验证的进程峰值 working set 1.441 GB（包含先前 CPU 运行峰值）；整卡显存运行后快照 CPU 阶段 1543 MiB、CUDA 阶段 3186 MiB，含其它应用，不是本程序独占峰值。CUDA LaMa 图仍存在 CPU/GPU 拷贝节点，未假称所有算子都在 GPU。

2.5.1 启动修复后通过 404 项回归。已用不同的 Windows 安装账户和桌面账户验证模型读取，原有 start.bat 能打开主界面并完成模型预热。两个发布 ZIP 在空目录解压，CPU 和 CUDA 均通过实际检测、识别及修补；两张检测图分别核对了执行设备。体积、哈希见[打包记录](models/v2.5.1-packaging.json)，三页检测与修补对照见[最终实测](models/v2.5.1-detector-integration.json)。

早期 OCR 方案 79 项针对性测试通过：单日语模型路由、打包时拒绝夹带旧权重、新包/旧包解码、重复符号终止、失败安装不覆盖、体积超限、韩英路由、GPU 回退、LaMa 分块、擦字与补丁。另有 16 项界面语言测试通过。将两个 ZIP 解压到空目录，CPU 和 CUDA 的预览程序均实际选中 CharSpot；CUDA 条件下检测与 LaMa 使用 CUDA，OCR 使用 CPU。旧模型目录内 22 个文件的哈希与 v2.5.0 一致。完整数值和打包验收见 [评测记录](models/v2.5.1-evaluation.json) 和 [打包记录](models/v2.5.1-packaging.json)。

## 复现、升级与回退

在仓库根目录运行。参考评测的 `tmp/model-upgrade/charspot-small` 是已经审阅且校验过的官方固定版本源码与 ONNX 文件。私有图像和逐框原文仅在本机使用。

```powershell
.\.venv\Scripts\python scripts/download_split_detector.py
.\.venv\Scripts\python scripts/download_charspot_small.py
.\.venv\Scripts\python scripts/benchmark_local_ocr.py --manifest tmp/model-upgrade/samples/manifest.json --backend charspot-reference --model tmp/model-upgrade/charspot-small --output tmp/model-upgrade/reference-check.json
.\.venv\Scripts\python scripts/benchmark_local_ocr.py --manifest tmp/model-upgrade/samples/manifest.json --backend charspot --model comic-translate-ai/models/charspot-small --output tmp/model-upgrade/integration-check.json
.\.venv\Scripts\python package_release.py --dist dist/v2.5.1-nativegpu/ComiTrans --output release/v2.5.1 --metadata-dir tmp/model-upgrade/package-split
.\.venv\Scripts\python scripts/audit_local_models.py --archive release/v2.5.1/ComiTrans-v2.5.1-models.zip --output tmp/model-upgrade/current-inventory.json
```

新包解压至空目录，日语选择「自动」。沿用 v2.5.0 模型包时原有自动回退仍可使用。新旧模型同时在场时，显式选择 Baberu 或 manga-ocr 即可复用原模型。Baberu v1.2 如需单独使用，运行 `scripts/download_baberu_v12.py` 并在 `config.yaml` 设置 `ocr_backend: baberu`、`baberu_ocr_model: models/baberu-ocr-v1.2`。续传仍复用已完成的页，比较模型时请指定新输出目录。[升级说明](RELEASE-v2.5.1.md)
