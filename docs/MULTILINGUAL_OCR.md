# 多语言 OCR 与源语言翻译

支持选择**被翻译的源语言**：日语、韩语、英语和“自定义 OCR”。目标语言为简体中文，继续使用现有中文字体与排版。一次任务使用一种源语言；自动混合语言路由尚未启用。

## 使用

1. 在工作台的“原文语言”选择原文语言，或在“设置”里同时选择源语言和 OCR 引擎。设置自动保存，下一次任务加载对应模型；运行和预热期间锁定切换。
2. 日语自动模式仍优先 Baberu，不可用时回退 manga-ocr。明确指定 Baberu 时，模型错误会直接报告。
3. 韩语、英语使用 PP-OCRv5 ONNX，支持 CPU 和可用 CUDA，不需要安装日语 OCR 模型。
4. 其它语言选择“自定义 OCR”，填写语言代码（例如 `fr`、`de`、`th`）、可选语言名称和独立 OCR 接口。也可为日语、韩语或英语选择“自定义 OCR”引擎，覆盖内置识别方式。
5. 翻译与 OCR 的地址、密钥、模型独立配置。自定义 OCR 接收当前文本区域的 PNG；勾选多模态翻译时，翻译服务还会接收整页图片。

旧配置默认日语。英语、韩语不会因检测器的 `eng` 标签或拉丁字母比例而被跳过。日语本地 OCR 保留原有英文跳过策略；这不是自动混合识别。

## 韩语和英语模型

从项目根目录运行：

```powershell
.\.venv\Scripts\python scripts/download_ocr_models.py
# 只下载英语：
.\.venv\Scripts\python scripts/download_ocr_models.py --languages en
```

保存在 `comic-translate-ai/models/ppocr/`，配置页可选择其它路径。程序不会在启动时自动下载。Release 模型包包含两个文件；二进制依照现有规则不提交到 Git。

| 语言 | 文件 | SHA256 |
| --- | --- | --- |
| 韩语 | `korean_PP-OCRv5_rec_mobile.onnx` | `cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b` |
| 英语 | `en_PP-OCRv5_rec_mobile.onnx` | `c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8` |

来源为 [RapidOCR 模型清单](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml)中固定的 ModelScope `v3.9.2` 资源。上游项目及许可证：[RapidOCR](https://github.com/RapidAI/RapidOCR)、[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)。

适配器遵循[识别输入格式](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/ch_ppocr_rec/main.py)和[CTC 格式](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/ch_ppocr_rec/utils.py)：BGR、NCHW、48 像素高、归一化与补零、内置 `character` 字典、CTC 去重与 blank 过滤，保留词间空格。

管线按检测器的文本行多边形做透视校正，从上到下识别后以换行合并为一个气泡结果。无有效行时回退到整个文本框。装饰字、竖排韩语/英语、严重倾斜或漏检文本仍需真实漫画评估。

## 自定义 OCR：标准 HTTP

选择“标准 HTTP OCR”，填写完整 POST 地址，如 `http://127.0.0.1:9000/ocr`。服务可以在本机或远程运行，内部 OCR 实现不限。请求：

```http
POST /ocr
Content-Type: application/json
Authorization: Bearer <独立 OCR 密钥，可留空>
```

```json
{
  "image_base64": "<PNG 的纯 Base64，不含 data: 前缀>",
  "mime_type": "image/png",
  "language": "fr",
  "model": "<选填，未填写时不发送该字段>"
}
```

成功响应：

```json
{"text": "Bonjour le monde !\nDeuxième ligne.", "confidence": 0.96}
```

`text` 必须是原文字符串，保留空格、标点和换行；无文字返回 `{"text": ""}`。`confidence` 可省略或为 `null`，否则须为 `[0, 1]` 的数值。语言使用用户配置，不依赖响应。

服务端适配逻辑示例：

```python
import base64
import io
from PIL import Image

def recognize_request(body, my_ocr):
    image = Image.open(io.BytesIO(base64.b64decode(body["image_base64"]))).convert("RGB")
    # 替换为自己的第三方/本地 OCR 调用。
    text = my_ocr(image, language=body["language"])
    return {"text": text}
```

默认超时 60 秒，可设为 1–300 秒。HTTP 错误、超时和响应结构错误使当前页面失败，不继续擦字。不自动重试或跟随重定向。错误日志不包含 OCR 密钥、图片 Base64 或响应正文。停止任务在当前请求结束或超时后生效，不继续下一个区域。

## 自定义 OCR：兼容视觉模型接口

选择“兼容 OpenAI 的视觉模型”，填写 Base URL（例如服务提供的 `/v1` 地址）、独立 API Key 和支持图片输入的模型名。发送 `chat.completions` 并要求直接返回原文，不要求 JSON，无需额外包装 HTTP 服务。纯文本模型不能用于 OCR，本地免鉴权服务可以不填 Key。

## Python 接口

共享模块 `comic_translate_core/ocr.py` 不依赖 Qt。`OcrEngine` 协议要求 `name`、`uses_lines` 属性及 `recognize(image: PIL.Image.Image, language: str) -> OcrResult` 方法。结果包含 `text`、`language`、`backend`、可选 `confidence`。

内置引擎由 `create_ocr(config, device)` 创建。新增进程内后端时实现该协议并扩展工厂及配置校验；独立服务通过上述 HTTP 接口接入，无需修改主程序。

`ComicTranslatorPipeline` 原构造参数保持兼容，新增 `ocr_config` 字典，例如：

```python
ocr_config = {
    "source_language": "ko",
    "ocr_backend": "auto",
    "korean_ocr_model": "/absolute/path/korean_PP-OCRv5_rec_mobile.onnx",
}
# 在原有构造参数之外传入 ocr_config=ocr_config。
```

每个气泡的 OCR 原文、源语言、后端及置信度保存到布局 JSON。翻译请求和续译使用选定源语言；源文或译文为空时保留原图文字。

## 混合语言识别与翻译：下一阶段讨论

建议采用“用户指定候选语言 + 文本块路由 + 不确定时复核”：

1. **检测与身份。** 给气泡、文本行稳定 ID，保留阅读顺序和坐标。现有检测器的 `ja/eng` 标签不能判断韩语，不能作为最终分类。
2. **快速初识别。** 优先用户选定主语言，结合假名、韩文字母、拉丁字母等脚本证据判断。纯汉字短句、拟声词、品牌名不能单凭字符集判断。
3. **按需复核。** 低置信度、空结果、脚本不符或疑似混语时，只对该行调用第二候选 OCR 或多语言视觉模型。不同引擎的置信度不能直接比较，应在标注集上校准，并综合字符覆盖、脚本一致性及乱码比例选结果。
4. **气泡内混语。** 不同行分别识别并按顺序合并；同一行混合脚本优先交给支持该组合的多语言识别器。冲突保留给用户复核，避免拼接候选导致重复对白。
5. **统一翻译。** 全页发送 `{id, source_language, source_text}` 和共享人名、背景；按 ID 校验译文完整性。每个区域只擦除、排版一次。
6. **性能与验证。** 按需加载并缓存模型，限制复核预算。在单语、多气泡混语、同气泡混语三组样本测字符错误率、遗漏率、译文一致性和耗时，再决定默认策略。

本次提供统一结果和元数据，以上自动混合策略尚未实现。建议先验证“日语/韩语主语言 + 英语辅语言”，再扩展任意组合。

## 验证

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

覆盖旧配置兼容、路由、HTTP/视觉接口与错误、源语言提示词和续译、缓存失效、空译文保护、UI 同步及 CTC。安装模型和 Windows 韩文字体后执行真实识别测试，否则跳过。接口测试使用模拟服务，不消耗翻译 API 额度。
