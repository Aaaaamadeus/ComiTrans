# 漫画字体判断策略设计（非多模态 / 多模态）

> 状态：设计稿（第 4 节"多模态字体选择"已细化为可实现规格；代码仍未改动）
> 适用范围：`text_style.choose_font_style()`（非多模态启发式）、`ComicTranslatorPipeline.configure_fonts()`（多模态 AI）、`VerticalTypesetter`（渲染兜底）
> 关联改动：第 7 节为已完成的可选字体新增；第 4 节为本次细化的多模态字体选择逻辑，其中**多模态字号匹配已按设计移除**（见 4.7）。

## 1. 检索结论：公开方案现状

需求是"非多模态下的字体判断策略"。检索了主流开源漫画翻译项目与视觉字体识别（VFR）文献，结论是**没有可直接复用的漫画嵌字字体判断策略**，现有方案分两类，都不落在"非多模态、按文本块判断字体族"这个点上：

| 来源 | 是否判断字体族 | 实际做法 |
| --- | --- | --- |
| [BallonTranslator 自动翻译文档](https://mintlify.wiki/dmMaze/BallonsTranslator/features/automated-translation) | 否 | 只自动推断**颜色 / 旋转角 / 对齐 / 横竖方向 / 字号**；字体是全局设置，支持"全局字体格式"覆盖 |
| [manga-image-translator](https://github.com/zyddnys/manga-image-translator) | 否 | 全局字体族配置 + 逐块字号/方向/排版，不做字体族判断 |
| [DeepFont: Identify Your Font from An Image](https://ar5iv.labs.arxiv.org/html/1507.03196)（ACM MM'15） | 是（视觉分类） | 视觉字体识别 VFR：CNN 在 AdobeVFR（2383 类、238 万合成图）上 top-5 >80%；只覆盖**西文字体**，且需要专有数据集与训练 |
| [Enhancing Chinese Font Recognition with CNN](https://ieeexplore.ieee.org/document/10529661) | 是（视觉分类） | 中文字体识别 CNN，属文档图像分析范畴，同样需要训练专用分类器 |
| [Extraction of Semantic Content and Styles in Comic Books](https://journal.icter.org/index.php/ICTer/article/view/299)（ICTer 2020） | 否 | 研究漫画语义内容、气泡关联与阅读顺序（0.89 准确率），不含字体族判断 |
| 本项目的多模态路径 | 是（视觉 + 语言） | `configure_fonts()` 把整页图 + 原文/译文交给视觉大模型，直接返回 `font_style`；依赖多模态模型与按页 API 调用 |

因此：**非多模态侧没有公开可直接搬运的策略**，只有两类可选技术路线——（A）纯文本/几何/笔画特征的确定性规则，（B）本地视觉字体分类器（DeepFont 式，需要自建数据集与训练）。按确认的范围，本文档只输出设计，不落地逻辑代码。

## 2. 现状基线

当前项目已经有"三层"字体决策，设计要嵌进这三层而不是另起一套：

1. **非多模态启发式**（`comic-translate-ai/main/text_style.py::choose_font_style`）
   输入：OCR 文本、`direction`、`width`/`height`、`non_bubble`、`emphasis`
   输出：12 → 15 个风格之一；`emphasis` 由 `estimate_text_emphasis()` 用 Otsu 二值化 + 距离变换估计笔画强度。
   现状：正则关键词 + 长宽比 + 强调度的优先级瀑布，任何一条命中即返回。
2. **多模态 AI**（`comic_translator_pipeline.py::configure_fonts`）
   现状：system prompt 要求返回 `{"items":[{"index","font_style","font_size","direction"}]}`，`font_style` 必须在 `FONT_STYLES` 白名单内（越界即降级 `dialogue`）；失败整体回退启发式结果。
   本次设计改为**两段式字体族选择**并**移除字号**（见 §4）。
3. **渲染兜底**（`vertical_typesetter.py::_style_for_text`）
   现状：目标字体缺字时，按风格映射到回退风格（如 `handwriting → narration → dialogue`），逐块整段判定，避免出现豆腐块。

## 3. 设计 A：非多模态（文本 + 几何 + 笔画）字体判断

### A.1 特征集

| 组 | 特征 | 现状 | 计划 |
| --- | --- | --- | --- |
| 文本 | 关键词/拟声词/下回预告/标题正则、标点强度（`！？`、`〜〜`、`♥♪`）、长度、是否含 CJK | 已有 | 复用 |
| 几何 | 框长宽比、是否非气泡、掩膜有效面积、质心 | 已有 | 复用 |
| 笔画 | Otsu 墨量比、距离变换 80 分位笔画半径 → `emphasis` | 已有 | 复用 |
| 手写特征 | 笔画端点/分叉数、骨架抖动方差、笔画宽度方差、行内基线倾斜 | **缺失** | 新增（区分三款手写字体所必需） |

关键判断：**只靠 `emphasis` 无法稳定区分濑户字体 / 851手写杂书体 / 手写注记**——三者都是手写族，`emphasis` 只反映笔画粗细与墨量。要落到具体字体，必须先有"手写证据"特征（端点密度、抖动方差），否则新增手写字体在非多模态下应当**只作为可选值暴露，不参与自动判定**（即当前已交付的状态）。

### A.2 决策表（拟扩展，保持确定性优先级）

```
标题/下回预告   → title / next_preview          （已有）
心形・波浪・音符  → cute                          （已有）
非气泡 + 短/重笔 → sfx                           （已有）
横向长条        → narration                      （已有）
连续 !?         → radiating                      （已有）
emphasis ≥ .43  → bold_dialogue                  （已有）
括号包裹        → thought                        （已有）
省略号/小声     → whisper                        （已有）
手写关键词      → handwriting                    （已有）
新增：手写族细分（仅在手写证据充分时）
  ├─ 抖动方差高 + 端点密度高 + 笔画细 → tegaki_851（851 手写杂书，随性潦草）
  ├─ 抖动低 + 圆润闭合 + 笔画均匀   → seto        （濑户字体，圆体手写）
  └─ 证据不足                        → handwriting （保持现状，不冒险）
新增：漫黑（display）细分
  └─ 非气泡 + emphasis ≥ .50 且不是拟声短词 → lxgw_marker（霞鹜漫黑，标题/强调用粗圆显示体）
```

规则写成"命中即返回"的瀑布，新增分支放在原有分支**之后**，这样默认行为（现有 12 风格）在任何情况下都不回归。

### A.3 置信度与冲突处理

- 每条新增规则返回 `(style, confidence)`；`confidence < 0.6` 时退回上一条既有规则的结果。
- 新增规则之间互斥（手写族细分与漫黑细分输入条件不重叠），避免多规则竞争。
- 失败/异常时保持现有的 `dialogue`，不做猜测——嵌字错字体的观感损失大于"没换字体"。

### A.4 评测方式（不依赖人工标注也可启动）

1. 用 `font_file/` 内各字体渲染已知风格样本，构造"合成评测集"（文本 + 字体标签）。
2. 指标：新风格 top-1 准确率、对既有 12 风格的**回归率**（目标 0 变化）。
3. 合成集上的手写特征可分性用散点图/混淆矩阵检查后再决定阈值，避免拍脑袋定常数。

## 4. 设计 B：多模态字体选择逻辑（两段式）

多模态路径的价值是"看得见原字形"。设计原则：**模型只在"字面"这一个维度做判断；角色（拟声/标题/情绪）与字号都由本地决定**，避免模型越权。

### 4.1 职责边界

| 维度 | 决定方 | 理由 |
| --- | --- | --- |
| 字体族（字面） | **多模态模型**（第一段） | 只有它能看见原字形 |
| 具体风格（style） | **本地映射表**（第二段） | 模型不知道本地有哪些字体文件，让它点名必然幻觉 |
| 角色（拟声 / 标题 / 旁白 / 情绪） | **本地启发式** `choose_font_style()` | 角色由文本语义 + 文本块几何决定，与原字形无关 |
| 字号 | **本地排版器** `draw_text()`（掩膜面积 + 二分搜索） | 多模态不再参与字号，见 4.7 |
| 排版方向 | 模型建议 + 本地校验 | 保持现状（本次不改） |

### 4.2 模型契约（无字号）

```json
{"items": [
  {"index": 0,
   "family": "handwriting",
   "weight": "regular",
   "slanted": false,
   "direction": "vertical",
   "confidence": 0.82,
   "reason": "笔画断裂、基线抖动"}
]}
```

- `family`：闭合枚举，必填。`gothic`(黑体/ゴシック)、`mincho`(宋体/明朝)、`handwriting`(手写)、`rounded`(圆体)、`marker`(漫黑/马克笔)、`brush`(毛笔/提按)、`display`(装饰)、`unknown`(无法判断)。
- `weight`：`light` | `regular` | `heavy`。
- `slanted`：布尔，字形是否倾斜。
- `direction`：`vertical` | `horizontal`。
- `confidence`：`0..1`，低于阈值不覆盖（见 4.6）。
- `reason`：一句依据，**只用于日志与人工复核**，不参与逻辑。
- **契约中没有 `font_size`**：模型不得输出字号，本地也不读取。原实现读取模型字号并覆盖检测器字号，本次设计将其移除（见 4.7）。

### 4.3 字体族判定依据（写进提示词）

| family | 可判别的视觉依据 |
| --- | --- |
| `gothic` | 笔画等宽、无衬线、端点平直或微圆，字形方正 |
| `mincho` | 横细竖粗、有字脚/三角衬线，笔画末端有装饰 |
| `handwriting` | 笔画抖动、基线不稳、连笔或断笔、字面大小不均 |
| `rounded` | 笔画端点圆钝、转角全为圆弧、字面饱满 |
| `marker` | 笔画粗且等宽、端点圆钝如马克笔、字形紧凑方正 |
| `brush` | 提按变化明显、有飞白/枯笔、起收笔有锋芒 |
| `display` | 明显装饰化：描边、变形、镂空、字面极度夸张 |
| `unknown` | 字太小、模糊、被遮挡，无法判断 |

#### 4.3.1 提示词草案（可直接落地）

```
你是漫画嵌字字体识别助手。你会看到一整页漫画原图与若干文本块（含原文和译文）。
你只做一件事：判断每个文本块里【原文字形属于哪个字体族】。
不要输出字号，不要输出字体文件名，不要输出风格名。

family 只能取以下之一：
gothic      = 黑体（笔画等宽、无衬线、端点平直或微圆，字形方正）
mincho      = 宋体/明朝体（横细竖粗、有字脚，笔画末端有装饰）
handwriting = 手写体（笔画抖动、基线不稳、连笔断笔、字面大小不均）
rounded     = 圆体（端点圆钝、转角全为圆弧、字面饱满）
marker      = 漫黑/马克笔（笔画粗且等宽、端点圆钝、字形紧凑方正）
brush       = 毛笔（提按明显、飞白枯笔、起收笔有锋芒）
display     = 装饰体（描边、变形、镂空、字面极度夸张）
unknown     = 无法判断（字太小、模糊或被遮挡）

每块另外给出：
weight     : light | regular | heavy   笔画粗细
slanted    : true | false              字形是否倾斜
direction  : vertical | horizontal     原文排版方向
confidence : 0~1                       你对 family 判断的置信度，不确定就写低分
reason     : 一句中文依据               仅用于日志复核

只输出 JSON，不要解释：
{"items":[{"index":0,"family":"handwriting","weight":"regular","slanted":false,
           "direction":"vertical","confidence":0.82,"reason":"笔画断裂、基线抖动"}]}
items 必须覆盖输入中的每一个 index，index 只能取自输入。
```

要点：

- 每个 family 都给一句**可判别的视觉依据**，比只列枚举名准确得多；
- 明确禁止输出字号与字体文件名（对应 4.2 契约与 4.7 移除项）；
- few-shot 用本项目自带字体渲染的对照图（同文不同族）比文字描述更稳；
- 中文提示词 + `response_format={"type":"json_object"}` 组合，与现有调用方式一致。

### 4.4 第二段：本地映射表（确定性，纯函数）

| family | weight | slanted | → style | 默认字体 |
| --- | --- | --- | --- | --- |
| `gothic` | `heavy` | — | `bold_dialogue` | 思源黑体 Heavy |
| `gothic` | `regular` / `light` | — | `lxgw_marker` | 霞鹜漫黑 |
| `mincho` | 任意 | — | `serious` | 思源宋体 |
| `handwriting` | `light` / `regular` | `false` | `handwriting` | setofont |
| `handwriting` | `heavy`，或 `slanted=true` | — | `tegaki_851` | 851手写杂书体 |
| `rounded` | 任意 | — | `cute` | Klee One |
| `marker` | 任意 | — | `lxgw_marker` | 霞鹜漫黑 |
| `brush` | 任意 | — | `radiating` | 得意黑斜体（近似） |
| `display` | 任意 | — | `sfx` | 得意黑斜体 |
| `unknown` | — | — | **不覆盖** | 沿用启发式结果 |

映射表说明：

- 表是**确定性纯函数**，同输入永远同输出，可逐行单测，不需要模型。
- 默认配置下 `seto` 与 `handwriting` 指向同一个 `setofont.ttf`，所以表里**不区分**这两者（区分没有意义）；`seto` 保留为纯手动/显式选择。若日后把两者改成不同字体，再加一条 `handwriting + 圆润` 分支即可。
- 本地没有毛笔字体，`brush` 用得意黑斜体近似；实现时可在结果里带 `approximated=true` 供日志提示。
- 表中 style 的实际字体来自 `config.yaml` 的 `font_*` 项，映射只保证"风格"。若用户把 `serious` 改成黑体，"宋体 → serious"的意图就会落空。可选第三阶段改进：在配置里声明每个 style 的字体族（`FONT_FAMILIES`），映射时校验并跳过族不匹配的候选。

### 4.5 角色门控（防止模型抢角色）

模型只看得到字形，看不到"这是拟声词还是下回预告"。因此按角色分三类处理：

| 类别 | 角色（`choose_font_style()` 的结果） | 规则 |
| --- | --- | --- |
| A 正文类 | `dialogue` `narration` `bold_dialogue` `serious` | **直接采用 4.4 映射结果**（模型价值最大的地方） |
| B 手写类 | `handwriting` | 模型也判 `handwriting` → 按 weight/slanted 细分到 `tegaki_851`；模型判非手写族 → 说明关键词误判，退回 A 类映射 |
| C 装饰/情绪类 | `title` `next_preview` `sfx` `radiating` `cute` `whisper` `thought` | **保留本地角色，模型不覆盖**；仅当 role ∈ {`sfx`, `radiating`} 且 family ∈ {`marker`, `display`, `brush`} 时接受同族细化（→ `lxgw_marker` / `sfx`） |

效果：正文块的字面跟着原图走（视觉价值），拟声/标题/情绪的外观不被模型破坏（稳定价值）。

### 4.6 校验与降级（必须实现）

| 环节 | 处理 |
| --- | --- |
| JSON 解析失败 | 整体不覆盖，全部沿用启发式（现有行为） |
| `family` 缺失 / 越界 | 记为 `unknown` → 不覆盖 |
| `weight` 越界 | 归为 `regular` |
| `slanted` 非布尔 | 归为 `false` |
| `confidence` < 0.5 | 不覆盖，沿用启发式 |
| `direction` 非 vertical/horizontal | 回退检测器结果 |
| 命中 C 类角色 | 按 4.5 门控，默认不覆盖 |
| 目标风格缺字 | 交给 `_style_for_text()` 回退链（新风格已登记） |
| 任何异常 | 记日志并保持现有渲染，**绝不因 AI 失败阻断整页排版** |

### 4.7 去掉多模态字号匹配（本次设计明确移除）

原实现让模型返回 `font_size` 并覆盖检测器字号。问题有两个：一是模型看不到排版器的掩膜有效面积、框内留白与二分搜索上下界，它给出的像素值（例如 18px）与本地实际可用空间无关，容易出现字太大溢出或太小留白；二是"字体选择"与"字号适配"本是两件事，混在同一契约里会稀释模型注意力，也让字号这种纯几何问题被语义模型猜。

移除清单（实现阶段执行）：

| 位置 | 改动 |
| --- | --- |
| system prompt | 删除 `font_size` 字段与"font_size 为整数像素"的说明，明确"不要输出字号" |
| `configure_fonts()` 解析 | 删除 `size = int(item.get("font_size") or 0)` 以及结果字典中的 `font_size` 键 |
| `finish_comic_page()` | `target_font_size` 不再取 `font_cfg.get("font_size")`，恒为 `item['target_font_size']`（检测器建议值） |
| layout JSON | `font_size` 语义固定为"检测器建议字号"；`rendered_font_size` 仍由排版器回写实际值 |
| 编辑器 | 不改动：`_size_spin`（自动/手动字号）仍可人工覆盖 |

影响与收益：字号完全由 `draw_text()` 的掩膜有效面积 + 二分搜索决定，与非多模态路径行为一致；多模态的契约更小、出错面更窄；`target_font_size` 仍作为 `preferred_size` 参与上限约束，字号不会失控。

### 4.8 成本、并发与缓存

- 现状每页 1 次额外调用（`configure_fonts`）。建议与翻译请求合并为一次 `chat.completions`（同一响应里返回译文 + family/weight/slanted/direction），可省一半往返与一次图片 token。
- 若暂不合并：复用同一个 `httpx.Client`，并发度与翻译页数一致；失败只记日志、不重试。
- 结果按"页面图片 + OCR 文本"哈希缓存，重跑同页不重复计费。

### 4.9 评测与验收标准

1. **合成对照集**：用 `font_file/` 内各字体渲染同文样本，得到已知 `family` 标签，测 family top-1/top-3。
2. **映射表单测**：4.4 是纯函数，逐行断言，无需模型。
3. **角色保持率**：构造 C 类角色样本，断言无论模型返回什么 family，输出风格都不变（目标 100%）。
4. **非多模态回归**：既有路径输出必须逐块不变（已有断言 `test_new_optional_styles_are_not_auto_selected_yet`）。
5. **人工 A/B**：真实页对比"模型选字面 vs 启发式默认"，按块记录更贴近原图的比例。
6. **字号回归**：移除多模态字号后抽页对比溢字率与留白观感，确认不劣化。

### 4.10 输入形态与分辨率门槛（实测）

用本机 `page/output_page_output_layout/` 里 13 页真实布局、142 个文本块统计"模型到底能看到多大的字"（单字像素 = `sqrt(框面积 / 字数)`）：

| 送图形态 | 单字像素（中位） | 判字形族是否够用 |
| --- | --- | --- |
| 原图 1:1（页面 1220×1735） | **41.6 px**（p25 36，min 21） | 充足 |
| 整页缩到长边 1024（视觉编码器常见） | **24.5 px**，仅 3% 的块 < 16 px | 基本够用：笔画端点、等宽性、字脚仍可见 |
| 整页缩到长边 1568 | **37 px** | 充足 |
| 逐块裁剪放大到长边 224 | **57 px**（p25 45） | 宽裕 |
| 逐块裁剪放大到长边 320 | **81 px** | 过剩 |

结论与建议：

- **瓶颈不是"能不能看见"，而是"把注意力放在字形上"**。整页 1024 下 24.5 px/字，字体族之间的差异（等宽、字脚、圆角、抖动）对人眼仍然清晰可辨，对视觉模型同理。
- 需要留意模型训练目标带来的偏差：视觉语言模型被训练为对**字体不变**（内容不变性），"能读出是什么字"不等于"会注意字形风格"。提示词必须显式给出每族可判别特征（4.3），最好再配 few-shot 对照图。
- 真正困难的是**同一族内的细分**：`marker` vs `gothic+heavy`、`brush` vs `handwriting`。这两对只影响 4.4 的映射结果，且有 `unknown` 与置信度阈值兜底，判错代价可控。
- **推荐送图形态**：把每个文本块的裁剪图放大后拼成一张 contact sheet（每块标注 `index`），而不是只送整页图。一次调用即可覆盖全页，每字 200 px 以上，同时省掉"整页大图 + 逐块小图"的往返；裁剪坐标本来就有（检测框），实现成本低。
- 与模型能力无关但同样会毁掉观感的因素：本地字体自身的字形缺口。例如 24 px 下 Klee One 缺「识别测试」、濑户字体缺「识别」（见 7.1），必须靠 `_style_for_text()` 回退链兜住，否则画出来是豆腐块——这属于字体覆盖问题，不是模型水平问题。

### 4.11 实测：模型能力下限（`deepseek-flash` / “4.1 flash”）

在 `api.deepseek.com` 上用本项目配置的模型做了三组实测（合成分块是**最好情况**，真实页有网点、描边、遮挡，只会更差）：

| 实验 | 结果 |
| --- | --- |
| 单块 8 分类（7 个已知字体，每次只发 1 块） | **4/7 = 57%**：黑体✓ 宋体✓ 手写✓×2；圆体→`handwriting`、漫黑→`gothic`、得意黑→`gothic` |
| 整页拼图 8 分类（20 块一次发） | **7/18 = 39%**：同一字体两次给出不同答案（黑体 Heavy 一次 `gothic` 一次 `marker`） |
| 单块 3 分类（`gothic`/`mincho`/`handwriting`，9 个字体） | **7/9 = 78%**，但边界不稳定：思源宋 Regular→`handwriting` 而 Heavy→`mincho`；濑户→`gothic` 而 851/Klee→`handwriting` |
| `confidence` 是否可用于门控 | **不可用**：单块模式逢答必 0.9~0.95（答错也一样）；批量模式 0.45~0.9 且与正误无关 |
| `unknown` 弃权率 | 0%（flash 从不弃权） |
| 成本与延迟 | 单页拼图：prompt 1,352 tokens + completion 10,168（其中 reasoning 9,685）、51 s；单块：约 250 prompt + 140~700 reasoning、1~3 s |

同一批测试暴露的两个环境事实：

- `deepseek-v4.1-flash` 作为 API id 会被拒绝（`The supported API model names are deepseek-flash, deepseek-v4-pro`）；配置里的 `deepseek-v4-flash` 可用，返回体 `"model":"deepseek-flash"` —— “4.1 flash”是它的版本号。
- `deepseek-v4-pro` 接受 `image_url` 字段但**实际读不到图**：纯 OCR 提问回答「图片无法显示，请重新上传」。因此“换更强的模型”在当前 API 下不是选项，**只有 `deepseek-flash` 具备视觉**。

结论：**§4.2 的 8 类契约在 ds-4.1-flash 下无法落地**（39%~57%，且置信度失效、从不弃权——错答也不拒答，是最危险的组合）。据实测给出三条路线：

| 路线 | 做法 | 预期效果 | 代价 |
| --- | --- | --- | --- |
| **A 移除多模态字体配置**（推荐） | 多模态只做翻译；字体全部交本地启发式（字号已按 4.7 移除） | 无幻觉风险，输出不劣化，还省掉 1 万 reasoning tokens/页 | 放弃“跟着原图字形选字体” |
| B 降级为 3 分类 | 枚举缩到 `gothic`/`mincho`/`handwriting`，仅对 A 类角色生效；同块多次采样一致才采纳 | 单块 78%，但字重翻类风险仍在 | 需 3× 采样投票，成本上升，收益有限 |
| C 本地小模型 | 用 `font_file/` 合成渲染数据训练 8 类小 CNN，导出 ONNX 复用现有 onnxruntime | 合成数据无限、任务窄，可达 90%+，且无 API 成本 | 需要训练与评测工程，新增约 1–5 MB 模型 |

### 4.12 降低模型决策占比的策略（全部有实测支撑）

补充实测（同一模型、同一批合成块，只改提问方式）：

| 实验 | 结果 | 说明 |
| --- | --- | --- |
| 同一提示词重复 3 次问同一块 | 自一致率 **100%**（三分类与二分类都是） | 误差是**系统性**的，不是随机噪声 |
| 开放式 3 分类提问 | 80%（4/5，濑户手写被判成 gothic） | 与 4.11 的 78% 一致 |
| 同批块改为**三候选比对**（原块 vs 黑体/宋体/手写 三张渲染图） | **100%（5/5）** | 连开放式提问判错的濑户也选对了 |
| 同批块改为**八候选比对**（A~H） | **40%（2/5）** | 一次调用 8,000 token 全被 reasoning 吃光、没产出结果 |

两点测量上的诚实说明：

- 八候选那次实验的候选标签里**带着字体族名称**（"A 思源黑 Heavy"），等于泄题；即便如此仍只有 40%，所以"候选一多就崩"的结论成立，但这个 40% 不能当作无泄题条件下的准确率上限。
- 三候选实验的候选标签只有字母（**无泄题**），这是 A′ 采用三候选的直接依据；生产代码 `probe_prompt()` 与 `build_probe_sheet()` 也只写字母，并有单测锁死"提示词不出现任何字体族名称"。

**模型能力对"选项数量"极度敏感：3 个选项 100%，8 个选项 40%。** 所以降占比的正确方向不是"少问"，而是"把问题收窄成低选项数的判别题"。

**落地时又发现一个关键细节**：候选必须与原图**同字形尺寸**渲染。第一版实现把候选渲染成 ~80 px、原图块才 44 px，生产路径实测只有 80%（思源黑 Medium 被选成手写）；改成用检测器给出的 `target_font_size` 对齐两边尺寸后，同一批样本升到 **100%（5/5）**。这属于"比较题也要公平"的基本要求，已由 `font_probe.estimate_glyph_px()` + `glyph_px` 参数保证，并有单测覆盖。

| 策略 | 模型决策占比 | 实测支撑 | 状态 |
| --- | --- | --- | --- |
| **1. 选项收窄到 ~3 个** | 1-of-3 | 3 选项 100% vs 8 选项 40%；reasoning 从数百涨到数千 | ✅ 已实现（`font_probe.CANDIDATES`） |
| **2. 比对代替分类** | 判别而非生成 | 同批块：开放式 80% → 三候选比对 100% | ✅ 已实现（`build_probe_sheet` + `probe_prompt`） |
| **3. 本地持有候选集** | 模型只在本地许可范围内选 | 杜绝"点名不存在的字体" | ✅ 已实现（`candidate_specs` / `resolve_style`） |
| **4. 不确定性路由** | 只处理正文/手写类角色 | 真实布局实测：145/454 = **32%** 的块外发，其余（radiating/title/next_preview 等）全留本地；reasoning token 占旧单页成本 95%（9,685/10,168） | ✅ 已实现（`should_probe`） |
| **5. 精确率门控的选择性采纳** | 只采纳历史高精确的族对 | 需小规模校准集（合成集即可） | ✅ 机制已实现（`PRECISION_GATE` + `accept_family`），阈值待更大样本更新 |
| **6. 全书/整章一次定风格先验** | O(1)/章，而非每块 | —— | ⏳ 未实现 |
| **7. 蒸馏到本地小模型** | 运行时 **0** | 合成标签由本地字体渲染免费获得 | ⏳ 未实现 |

已实测**否定**的做法（不要再投入）：

- **多次采样投票**：自一致率 100%，投票毫无收益；
- **用模型自己的 `confidence` 门控**：错答也给 0.8~0.95；
- **期待模型弃权**：`unknown` 弃权率 0%，拒答能力不存在；
- **开放式 8 类分类**：39%~57%，且批量越大越差。

**推荐架构（模型占比最小化）**：

```text
本地启发式定角色与默认风格          ← 多数文本块到此结束，模型不参与
        │
        ├─ 仅当本地方案落在阈值带内（不确定）
        ▼
本地生成 3 个候选（黑体 / 宋体 / 手写 各一张代表渲染，同尺寸同内容）
        │
        ▼
模型只回答「原块更像哪个候选」→ A / B / C / none
        │
        ▼
精确率门控 + 本地许可 → 通过才替换，否则保留本地结果
```

预期：模型只覆盖约三分之一的文本块（真实布局实测 32%）、每次只有 3 个选项、随时可被本地否决；不再有"整页一次调用、单页一万 reasoning token"的开销，最坏情况退化为"和纯本地一样"。

实现落地：`comic-translate-ai/main/font_probe.py`（纯函数层）+ `comic_translator_pipeline.configure_fonts()`（每块一张对比图，串行/小并发调用，共享一个客户端）；生产路径实测 5/5。后续可把"角色路由"进一步收窄成"角色 + 本地证据落在阈值带"以继续降成本。

### 4.13 句内字体/字号变化：现状能力与分层方案

**结论：当前架构表达不了"一句里字体变化"，而且这不是模型能力问题，是数据模型与渲染器的问题。**

- layout JSON 每个文本块只有**一个** `style`；
- `draw_text()` 对整块算**一个**字号、**一个**风格；
- A′ 也只输出**一个**字体族（1-of-3）。
  即使模型看出"这行是手写、那行是黑体"，也没有地方存放。
- **手动修字同样做不到**：嵌字精修页的粒度就是块级——选中一个文本块后，「字体风格」下拉与「字号」输入框都作用于整块（`editor_page._store_properties()` 把 `style` / `font_size` 写回 `items[row]`）；译文是一个 `QPlainTextEdit`，没有字符级格式（`QTextCharFormat` 全项目只出现在日志面板 `log_panel.py`），界面也没有"拆块/加块"入口。所以手动路径与自动路径的粒度一致，都无法表达句内混排。

但**信息并没有丢**：检测器本来就给逐行数据——`TextBlock.lines` 是逐行多边形，块级有 `font_size`，类里还留着 `bold / italic / font_family` 字段；而 `VerticalTypesetter._get_font_for_char()` **本来就是逐字解析字体**（目前只用于缺字回退）。所以逐行/逐段换字体在工程上是通的，缺的是表达层与产品决策。

**实测（2 张真实源页、14 个检出块、10 个多行块）**：

| 指标 | 结果 |
| --- | --- |
| 行间字形尺寸比 ≥ 1.25 的块 | **4/10 = 40%**（最大 1.54×） |
| 行间笔画强调度差 ≥ 0.15 的块 | 0/10 = 0% |
| 至少一项有变化的块 | 4/10 = 40% |

也就是说：**句内变化真实存在，但在这批样本里主要表现是"字号/强调"变化，而不是字体族切换。** 字重/族层面的混杂在这两页里没有量到。

为什么没被切开：`group_output()` 里由 YOLO 框分配进来的行只做**距离切分**（`split_textblk`，`distance_tol = font_size * 2`），那个 1.3× 的**字号容差只作用于 scattered lines**（`try_merge_textline`，label=2）。所以"一个气泡里字号差 1.5 倍"会作为同一个块活下来。

分层方案（模型决策占比从低到高）：

| 层级 | 表达粒度 | 模型参与 | 代价 | 说明 |
| --- | --- | --- | --- | --- |
| L0 | 整块一个风格（现状） | 1-of-3 | 无 | 句内变化直接丢失 |
| **L1 逐行** | 每个检测行一个风格/字号 | 仍只做 1-of-3，且只对行级证据不足的行发问 | 中：layout JSON 加行级字段，编辑器要能显示行级选择 | 能表达"一行强调、一行正文" |
| **L2 逐段/逐字** | 按脚本或角色切 run（数字、拉丁、拟声、关键词各一个风格） | 同样只做 1-of-3 | 高：schema、编辑器、字号分配都要改 | 能表达句内混排；`_horizontal_runs` 已有 run 机制可扩展 |
| **L3 同族内的字重/字号变化** | 逐行字号 + 描边宽度 | **不需要模型** | 低：纯本地，`estimate_text_emphasis()` 已是现成信号 | 实测中最主要的变化形态，性价比最高 |
| L4 | 像素级复刻原字体 | 风格迁移模型 | 极高 | 超出当前范围 |

**推荐顺序：L3 → L1 →（需要时）L2。** 并且确立一条原则：**模型永远不增加表达维度**——维度由本地先建好（行、run、字号），模型只在本地已有的候选里做选择。否则又会掉回"让模型承担它做不到的细粒度判断"。

**今天就能用的绕道（不改代码）**：直接编辑 `<输出目录>_layout/<页>_layout.json`，把一句话对应的块拆成多个块（各带自己的 `box` 与 `style`），再在精修页分别微调。注意：`box` 要与原图文字位置对齐；重跑自动流程会覆盖该文件。

**要进界面的话，两条路线的选择**：

| 路线 | 做法 | 优点 | 代价 |
| --- | --- | --- | --- |
| **A. 块内片段列表** | layout 增加 `segments: [{text, style, size?}]`（缺席即现状，向后兼容）；编辑器用「可增删的片段列表」而非富文本；渲染逐段排版 | 文本切分明确、可单测、兼容旧布局 | 要动 `draw_text()` 的**字号二分搜索**（现有排版测试最敏感的地方） |
| **B. 富文本选区** | 译文框换成可"选中一段 → 应用风格"的富文本控件，保存时导出 runs | 体验最自然 | 编辑器与 schema 复杂度最高；竖排下逐段字号分配最难 |

技术现状值得强调：`_horizontal_runs()` 与 `_draw_vertical_cell()` **本来就是逐字解析字体**，所以"同一块里混用多种字体"的底层机制已经存在，缺的是①数据字段②跨段字号分配策略③编辑 UI。

## 5. 落地顺序（建议）

1. ~~新增三款字体并注册为可选风格~~（已完成）
2. ~~移除多模态字号匹配（4.7）~~（已完成）
3. ~~多模态字体选择：路线 A′「本地三候选 + 模型 1-of-3 判别」~~（已完成：`comic-translate-ai/main/font_probe.py` + `configure_fonts()` 重写；生产路径实测 5/5）
4. 非多模态：实现手写特征（端点/抖动）+ A.2 新增分支 + 回归测试
5. 扩大校准集更新 `PRECISION_GATE`；再决定是否需要路线 6/7
6. 按 4.9 做合成集与 A/B 评测，再决定新风格是否进入**自动**判定（当前只作为可选值）
7. 句内变化：先做 **L3**（逐行字号/强调，纯本地），再按需要做 **L1**（行级风格，模型仍只做 1-of-3），见 4.13

## 6. 风险

- **AI 幻觉字体**：靠 4.4 确定性映射表 + 4.6 白名单兜住，模型永不直接指定字体文件。
- **模型越权改角色**：靠 4.5 角色门控限制，装饰/情绪类角色本地保留。
- **误判成本不对称**：换错字体比不换更糟，因此新规则一律"证据不足即回退"。
- **字体许可**：濑户字体（免费商用）、851手写杂书体（[作者授权页](https://pm85122.onamae.jp/851fontTerm.html)，免费商用）、霞鹜漫黑（SIL OFL 1.1）均可分发，README 已记录来源。
- **体积**：851 手写杂书体约 28.6 MB、霞鹜漫黑约 3.2 MB，打包体积增加约 31.8 MB（`ComiTrans.spec` 整个 `font_file` 目录入包，无需改 spec）。

## 7. 本次已交付的改动（不涉及判断逻辑）

| 位置 | 改动 |
| --- | --- |
| `comic_translate_desktop/config.py` | `FONT_KEYS` / `FONT_DEFAULTS` 新增 `seto`、`tegaki_851`、`lxgw_marker` |
| `comic-translate-ai/main/text_style.py` | `FONT_STYLES` 新增同名三个风格（进入多模态 AI 白名单） |
| `comic_translate_desktop/ui/editor_page.py` | `STYLE_LABELS` 新增「濑户字体」「851手写杂书体」「霞鹜漫黑」，精修页可直接选 |
| `comic-translate-ai/main/vertical_typesetter.py` | 新风格登记进**既有**字号档位与缺字回退链（`seto`/`tegaki_851` 跟 `handwriting`，`lxgw_marker` 跟 `sfx` 档），未新增任何判断规则 |
| `config.yaml` / `config.example.yaml` | 新增 `font_seto` / `font_tegaki_851` / `font_lxgw_marker` 三项 |
| `font_file/CN/special/` | 新增 `851tegaki_zatsu_normal_0883.ttf`、`LXGWMarkerGothic-Regular.ttf`（濑户字体复用已有 `CN/setofont.ttf`） |
| `comic-translate-ai/main/font_probe.py` | **新增**：A′ 的纯函数层——角色路由、候选装配、原图字形尺寸估算、对比图拼装、许可表、精确率门控、A/B/C 解析、中性提示词 |
| `comic-translate-ai/main/comic_translator_pipeline.py` | `configure_fonts()` 重写为「本地三候选 + 模型 1-of-3」，不再下发整页配置任务；字号与方向全部归本地 |
| `tests/test_multimodal_font_config.py` | 覆盖上述纯函数与 `configure_fonts()` 端到端行为（含装饰类不外发、候选缺失即跳过、模型失败/`none` 保留本地、契约无字号无风格名） |
| `tests/` | 新增字体注册与渲染回归测试（三款字体可加载、可绘制、缺字回退正常） |

**未改动**：`choose_font_style()` 的规则、`configure_fonts()` 的提示词与解析、任何自动判定行为。三款新字体当前只能通过"精修页手动选择"或"多模态 AI 主动指定"使用，符合"暂不改判断逻辑"的约定。

### 7.1 实测字形覆盖率与缺字行为

对三款新字体做了 cmap 与实测渲染（同一脚本可复现）：

| 字体 | 总码位 | CJK 基本区 4E00–9FA5 | 真实中文样本（795 字）cmap 缺失 | 样本中"有映射但画不出"的空字形 |
| --- | --- | --- | --- | --- |
| SetoFont 濑户字体 | 57,020 | 20,902 / 20,902（100%） | 0 | **100（12.6%）** |
| 851tegakizatsu 851手写杂书体 | 60,275 | 20,902 / 20,902（100%） | 0 | 0 |
| LXGW Marker Gothic 霞鹜漫黑 | 15,288 | 12,764 / 20,902（61.1%） | 0 | 0 |

结论与注意事项：

- **濑户字体的 cmap 不可信**：它声明覆盖全部 CJK 基本区，但样本里 100 个字（含 `计 认 讨 让 训 补 见 观 规 视 览 觉` 这类极常用简体字）映射到字形后渲染为空白。这正好验证了 `VerticalTypesetter._font_supports()` 里"cmap + `getmask().getbbox()`"双重校验的必要性——**该探针不能删**，只查 cmap 会画出空白。
- **851手写杂书体与霞鹜漫黑在样本中零空字形**，是更可靠的简体中文选择；濑户字体更适合日文原文场景。
- 霞鹜漫黑是"常用字够用、生僻字不足"的显示体（源自 Tanugo，由 lxgw 扩充简体），生僻字/异体字会触发回退，且缺 `♥`。
- 现有回退粒度是**整块**：`_style_for_text()` 要求该块所有可见字符都能画出来，否则整块改用回退家族（`seto/tegaki_851 → handwriting → narration → dialogue`；`lxgw_marker → bold_dialogue → dialogue`）。因此含 `计`、`见` 这类字的译文即使选了濑户字体，整块仍会变成霞鹜文楷——观感上"像是没生效"。
- 两种可选修法（属判断/渲染逻辑，留待 Phase 2 决定）：① 保持整块回退，在编辑器对触发回退的块给出提示；② 改为逐字回退（`_font_path_for_char()` 已具备逐字能力，只需绕开 `_style_for_text()` 的整块判定），代价是同一块内混排两种字体。

## 8. 来源

- [BallonTranslator — Automated Translation](https://mintlify.wiki/dmMaze/BallonsTranslator/features/automated-translation)
- [DeepFont: Identify Your Font from An Image (arXiv:1507.03196)](https://ar5iv.labs.arxiv.org/html/1507.03196)
- [Enhancing Chinese Font Recognition with Convolutional Neural Networks (IEEE)](https://ieeexplore.ieee.org/document/10529661)
- [Extraction of Semantic Content and Styles in Comic Books (ICTer 2020)](https://journal.icter.org/index.php/ICTer/article/view/299)
- [LXGW Marker Gothic（霞鹜漫黑，OFL-1.1）](https://github.com/lxgw/LxgwMarkerGothic)
- [851 手書き雑フォント 官方发布页](https://pm85122.onamae.jp/851fontpage.html) ・ [使用条款](https://pm85122.onamae.jp/851fontTerm.html)
