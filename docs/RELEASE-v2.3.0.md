# ComiTrans v2.3.0

## 新 UI 与日志

- 黑白漫画杂志风界面：大号章节标题、边缘渐疏网点、Skribble 字标，自动处理与嵌字精修统一视觉。
- 七个流程节点沿一条直线排列，按真实页面事件推进；原文语言、输出目录和开始按钮采用紧凑布局。
- 日志正文使用 Aa今日花晴 春懒猫困，约每秒 250 字快速展开，积压时自动加速；保留搜索、级别筛选、选区、回看、复制和完整导出。
- 任务结束与错误立即补齐日志；并行页面、跳过、失败和取消保留独立状态。

## 多语言与 OCR 接口

- 内置日语 Baberu / manga-ocr，新增韩语、英语 PP-OCRv5 ONNX。
- 支持独立标准 HTTP OCR，以及兼容 OpenAI `chat.completions` 的视觉 OCR 接口，地址、密钥和模型与翻译服务分别配置。
- 原文、语言、后端与置信度保存在布局 JSON；空识别、空译文和 OCR 错误保护原文。
- 一次任务选择一种源语言，输出简体中文；自动混合语言路由尚未启用。

## 下载与升级

1. 下载 `ComiTrans-v2.3.0-app.zip` 和 `ComiTrans-v2.3.0-models.zip`。
2. 两个压缩包解压到同一个父目录，合并顶层 `ComiTrans` 文件夹。最终结构应为 `ComiTrans/ComiTrans.exe` 和 `ComiTrans/comic-translate-ai/models/`。
3. 双击 `ComiTrans.exe`，在“设置”中配置翻译服务和 OCR。

从 v2.2.2 升级时可复用日语模型；使用韩语或英语需合并新版模型包。保留原有 `config.yaml` 与输出文件。`ComiTrans-v2.3.0-SHA256SUMS.txt` 提供两个压缩包的校验值。

## 界面与接入文档

[新 UI、逐字日志动画与 A/B 对比图](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.3.0/README.md) · [OCR 接入协议](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.3.0/docs/MULTILINGUAL_OCR.md) · [English](https://github.com/Aaaaamadeus/ComiTrans/blob/v2.3.0/README_en.md)

![v2.3.0 自动处理界面](https://raw.githubusercontent.com/Aaaaamadeus/ComiTrans/v2.3.0/docs/ui-review/automatic-idle.png)

![实际 Qt 逐字日志录屏（界面测试文本）](https://raw.githubusercontent.com/Aaaaamadeus/ComiTrans/v2.3.0/docs/ui-review/log-reveal.gif)

## 验证

- 74 项自动化测试通过，含 OCR 接口、韩英本地识别、流程事件、日志和精修回归。
- 真实本地管线处理 8 张无文字测试页，8 成功、0 失败；本轮未调用外部翻译 API。
- 修复打包依赖受外部 PATH 干扰的问题，构建使用当前 Python、Qt 和 Windows 的 DLL 来源。
- Windows 封包 EXE 启动验证通过：真实检测、Baberu 和 LaMa 模型预热成功，两款 UI 字体与 SVG 加载正常。
