# 擦字链路审计 — Agent 交接报告

> 生成时间：2026-11-04（含第二轮「干净度归因」） · 仓库 `D:\ComiTrans` · 分支 `codex/local-model-v2.6.0`（工作区有未提交改动）
> **重要约束：本篇是审计结论，用户明确要求「只评估算法，不要修改源码/不出补丁」。接手时若未被另行授权，不要改 `comic_translate_core/` 或 `comic-translate-ai/main/` 下的任何文件。**

---

## 0. 一句话结论

新擦字链路（`AdaptiveTextMask` + `reconstruct_background` + LaMa 分块）的**掩膜能力不差于旧版**（覆盖持平、误擦少 20%、掩膜面积少 25%），但**平涂分支在真实漫画页上 0% 命中**（`collar_ptp<=1` 这道闸门 106 个框全部拦截），100% 的框落入 LaMa 重绘：白气泡从「纯白（std 0.92）」退化为「灰斑（std 5.09）」，干净框 88% → 3.8%。

第二轮归因进一步把「不干净」拆成三个独立成分，并实测了修复上限：**① 残留（34% 的白气泡仍有残字）② 纸面花（50% 的字擦掉了但白底发灰）③ 框内固有内容（不该消除）**。修路由 + 补掩膜可以做到「残留≈0、std≈1.8」，但**永远达不到旧版 0.92**——旧版那个数字是把框内画面一起涂白的代价。

---

## 1. 环境与复现

```powershell
# 解释器（必须用仓库 venv，系统 Python 缺 cv2/onnxruntime）
D:\ComiTrans\.venv\Scripts\python.exe   # Python 3.12.14 / cv2 4.11.0 / numpy 1.26.4

# 模型（均已本地存在，CPU 即可跑；16 逻辑核，无需 GPU）
comic-translate-ai/models/text_detector/comic-text-detector.onnx      # 旧检测器（v2.4.1 基线）
comic-translate-ai/models/split-detector/detector-v4-s_int8.onnx      # 新检测器（当前默认）
comic-translate-ai/models/split-detector/manga_det_v0.2.onnx          # PP 文字行
comic-translate-ai/models/manga-lama/lama-manga-dynamic.onnx          # 修补模型
```

**复跑序列（全量约 9 分钟）**

```powershell
cd D:\ComiTrans
# ① 掩膜层 + 端到端层（8 分钟）：L1 同框同种子 A/B，L2b 各自框集端到端
& .venv\Scripts\python.exe tmp\ch_all.py
& .venv\Scripts\python.exe tmp\l2b_stats.py          # 端到端分布（std / 残留 / 干净率）
& .venv\Scripts\python.exe tmp\plot_l2b.py           # 分布图 l2b-distribution.png

# ② 门控中间量（~40s）：哪道闸门在拦
$env:PAGES_DIR='C:\Users\OS\Desktop\pa\生\chapter-2.1'; $env:OUT_JSON='l3_ch_rows.json'
& .venv\Scripts\python.exe tmp\eval_l3.py
& .venv\Scripts\python.exe tmp\l3ch_stats.py

# ③ 干净度归因与路由重放（~7 分钟，含一次 LaMa 全页跑）
& .venv\Scripts\python.exe tmp\eval_l4.py
& .venv\Scripts\python.exe tmp\l4_stats.py
```

**测试样本**
- 主样本：`C:\Users\OS\Desktop\pa\生\chapter-2.1`（12 页 JPG，1200×836，106 框）
- 扩展样本（10 页 204 框，已归档）：`tmp/erase-eval/l1_rows_10pages.json`
  - `app/page/test_page/test10.jpg`（彩色字页）、`comic-translate-ai/page/test/test1.jpg`（网点/深色页，双版均翻车）、`test2.jpg`、`page/temp_api/*_input.jpg` ×3、`docs/images/before*.png` ×4

---

## 2. 已确认结论（每条都可复算）

### 2.1 掩膜与路由

| # | 结论 | 证据 |
|---|---|---|
| C1 | **平涂分支 0% 命中**：章样本 `fill_color` = 0/106；扩展样本 0/103；`test1` 上 3 个 ring=1.000、inner≥0.985 的框也返回 `None` | `l3_ch_rows.json` 字段 `fill` |
| C2 | **`collar_ptp<=1` 是唯一致命闸门**：章样本 P5=18.0、中位 171.5；≤8 通过 0 个，≤16 通过 1 个；`ring>=0.97` 通过 19/106，`inner>=0.98` 通过 47/106 | `l3ch_stats.py` |
| C3 | **58% 的框本该平涂**：独立判据「框内非墨迹像素与模态色 p99 偏差 ≤10」成立 61/106；扩展样本 63/103 | `l3_ch_rows.json` 字段 `paper_p99_dev` |
| C4 | **干净度塌陷**：`paper std` 中位 0.92 → 5.09，P90 1.84 → 13.01；干净(≤1.5) 92/105 → 4/106；脏(>3) 10 → 84 | `l2b_rows.json`、`l2b-distribution.png` |
| C5 | **掩膜层不差**：同框同种子 recall 0.976/0.966（平坦 0.992/0.984、纹理 0.964/0.953）；spill 0.656→0.527；掩膜面积 0.520→0.387 | `l1_rows.json`、`eval_l1_stats.py` |
| C6 | **小字是唯一系统性退化**：size<20px（31 框）recall 0.9793→0.9646（−1.46pp）；size≥30px +0.30pp | `l1_rows.json` 按 size 分组 |
| C7 | **LaMa 分块是次要因素**：同掩膜整页单次 vs 768 分块，mean\|diff\|=3.19/255、max 109、>8 仅 8.9% | `tmp/lama_page_ab.py` |
| C8 | **历史坐标**：v2.5.0（`c0a45ea`，2026-11-02）一次性重写 268 行，此后**无任何调参提交**；旧逻辑最后两轮针对真实样本的兜底补丁在 `64b9225`(v2.0) 与 `0b784cb`(v2.2.2) | `git log -- comic_translate_core/text_mask.py` |

### 2.2 干净度归因（第二轮，`eval_l4.py` 路由重放）

把 104 个有效框按「框内纸面是否均匀」分成两类：**A 类 50 框**（p99 偏差 ≤10 且结构化像素 ≤1%）＝标准白气泡；**B 类 54 框**＝框内有画/网点。

| # | 结论 | 实测 |
|---|---|---|
| C9 | **「不干净」是三个独立成分**，必须分开度量 | A 类：① 残留 17/50 框（P90=14px，最差 1101px）② 字擦掉但 std>2 有 25/50 ③ 固有内容导致平涂后仍有 38/50 的 std>1.5 |
| C10 | **改路由到平涂的真实收益（同一掩膜，只换填充）** | A 类：残留框 17/50 → **4/50**；std 中位 3.55 → **1.85**；std≤2 8/50 → **30/50**；std≤3 22/50 → **47/50（94%）** |
| C11 | **干净度的物理天花板 ≈ std 1.8**，不是 0.92 | A 类平涂后 46/50 残留清零，std 仍 1.85；这 1.85 全部来自框内气泡轮廓/网点/JPEG 纹理——旧版 0.92 是把这些一并涂掉换来的 |
| C12 | **残留的主战场在 B 类** | B 类 30/54 框擦后仍有残留；平涂对 B 类几乎无改善（std 5.94 → 4.38），只能靠掩膜完整性 |
| C13 | **总闸门收益有限**：若只调阈值，需要放到 `ptp<=32` 才救回 29/106 | `l3ch_stats.py` 网格 |

---

## 3. 代码坐标

| 位置 | 作用 | 备注 |
|---|---|---|
| `comic_translate_core/text_mask.py:105` | `version = 'adaptive-v3'` | 全仓库仅此一个版本，从未迭代 |
| `:120` | `domain = dilate(inside, ≤8px)` | 框外 8px 以上永远擦不到 |
| `:125` | `seeds = detector_mask & domain` | 种子裁剪边界 |
| `:130` | `ring = dilate(inside, min(12, size//2)) & ~inside` | 环带必然包住气泡外框/邻列文字 → C2 |
| `:148` | `flat_hint = consensus >= .97` | 实测中位 0.91，通过 19/106 |
| `:208-222` | 有种子时只接受种子邻域连通块 | 漏检标点/注音永久残留（C6、C12 的根因） |
| `:226` | `radius = max(1, min(3, round(size*.075)))` | 旧版 `max(3,min(5,.15*size))` + 3×3 close |
| `:233` | 平涂四门：`flat_hint & (local_reference or inner>=.98) & small_components<8` | |
| `:238` | `np.max(np.ptp(local, axis=0)) <= 1` | **唯一的 0 通过闸门**（C2） |
| `:249-260` | 白描边扩张 `_white_outline` | 可扩大掩膜，也可能把外框带进 erase |
| `comic-translate-ai/main/comic_translator_pipeline.py:286-345` | 擦字调度：掩膜 → `reconstruct_background` → `fill_color` 平涂 → LaMa | `:327-336` 是 LaMa 分支 |
| `comic_translate_core/background_reconstruction.py:30-38` | 颜色平面拟合，要求全部已知像素残差 ≤3 | 真实页几乎不命中（章样本 0/106） |
| `comic-translate-ai/main/manga_lama.py` `_repair_tiles` | 768 分块 + 上下文 96 + 重叠加权 | 见 C7 |
| `comic-translate-ai/main/onnx_split_detector.py:88-94` | `midpoint_box`（区域框与 PP 行外接框取中点） | v2.5.1 未提交改动 |
| `:105-114` | `seed_strokes`：PP 行多边形内 `|gray-paper|>36` | 种子比旧 `refine_mask` 稀疏 |

**旧版基线（对比用）**：`git show c0a45ea^:comic-translate-ai/main/comic_translator_pipeline.py`
- `_is_simple_bubble_v2`（L311）：`mean>232 & 白占比≥82%` → 远比新门控宽松
- `inpaint_bubbles`（L335）：235 反相二值化 → 连通块筛选 → 3×3 close → 膨胀 `max(3,min(5,.15·size))`
- L457-471：白气泡时**把框内所有暗像素涂 255**（含检测器漏掉的标点/注音）——这是 C6/C12 的兜底，也是 C11「假干净」的来源

---

## 4. 未验证 / 不要过度解读

1. **样本面窄**：主样本 1 章 12 页（同为 1200×836），扩展 10 页混合来源。不等于全量漫画分布；`test1` 这类「文字压在网点/黑底上」的页指标失效（伪真值会把黑底判成墨迹）。
2. **伪真值定义**：墨迹 = 与局部中值纸面最大通道差 >40。深色底、满版网点会高估墨迹，recall/spill 只在「浅底 + 黑/彩字」上可信。
3. **`l4` 的 `loss` 字段不可用作「毁图」指标**：它算的是「掩膜内偏离模态色 >40 的像素占比」，而掩膜内主要就是笔画本身 → 中位 0.47 是正常值。要度量毁图，须改用「掩膜 ∩ 非墨迹 ∩ 偏离 >40」。
4. **`hypothetical: all boxes flat`（med 2.97 / clean 9.6%）被 B 类框污染**，不能当作平涂上限；正确读法是 C10 的 A 类分组数字。
5. **阈值网格是离线近似**：`l3ch_stats.py` 用实测中间量做离线组合，**没有真的替换代码跑**；它回答「哪道闸门在拦」，不回答「改完效果多少」。C10 才是真跑（只换填充策略，掩膜不变）。
6. **P2（LaMa 输出限幅到模态色 ±3）完全未测**，只是候选方案。
7. **旧基线存在轻微不公平**：L2b 已改为「各自框集评估各自输出」，但旧框字号取 `TextBlock.lines` 厚度；实测 size 16 vs 24 会让 before1 的 std 从 0.91 变 0.57（<1 个单位，不改变方向）。

---

## 5. 建议下一步（按杠杆排序，均需用户授权）

| 优先级 | 动作 | 预期收益（已测） | 风险 | 验收指标 |
|---|---|---|---|---|
| P0 | 把 `:238` 的「环带极差」换成「框内非墨迹 p99 偏差 ≤10」+ 暗块占比护栏（换判据，不是调阈值） | A 类 std 3.55→1.85、≤3 44%→94%、残留 34%→8% | 3/106 误判；需用 `l3_ch_rows.json` 回归 | A 类「std≤2 占比」「残留框数」 |
| P1 | 恢复框内小连通块接受规则（`:218-222`）+ 掩膜外扩 2–3px | 直接降残留：A 类 4→0 量级，**B 类 30/54 是主战场** | 误擦标点旁画面；需面积上限 | 残留连通块数（A/B 分开统计） |
| P2 | LaMa 输出对纸面区域限幅到模态色 ±3 | 未测；理论上把 2–5 级噪声压到 1 以内 | 可能压掉浅网点真实纹理 | 先在小样本上比对 std 与目视 |
| P3 | 让 `reconstruct_background` 的 ±3 容差适配 JPEG（当前 0/106） | 平滑底可省一次 LaMa | 需验证不引入色偏 | `repair_strategy` 分布 |

**不建议做的**
- 只把 `collar_ptp` 放宽到 4/8：章样本通过数仍 0；放到 32 才救 29/106（C13），风险收益比差。
- 恢复旧版「整框涂白」来把 std 压到 0.9 以下：会涂掉画面（`test1` 黑底框整块变白），且用 std 验收会奖励这种过度擦除。

---

## 6. 评估口径陷阱（复跑前必读）

1. **端到端必须用各自框集**评估各自输出；混用会系统性低估旧版（实测 before1：1.98 vs 0.91）。
2. **单看 `paper_std` 会奖励过度擦除**：旧版 88%「干净」里有一部分是把框内非文字内容涂掉换来的。验收请用「残留连通块数 + std≤2 占比」双指标。
3. **A/B 类必须分开统计**：B 类框内有画，std 天然高，混进总体会把「保画」惩罚成「不干净」。
4. **旧算法在极端页「看起来更干净」常常是擦过头**（把画面/黑底一起涂白）；`test1` 必须人眼复核。
5. `paper_std` 只统计框内非墨迹像素；掩膜膨胀进纸面会污染该指标，跨算法比较时注意掩膜面积差异（0.520 vs 0.387）。
6. 章样本多数框是白气泡，**总体指标被白底主导**；看纹理子集（60 框）与 size 分组才看得到真实分歧。
7. `l1_rows.json` / `l2b_rows.json` 会被 `tmp/ch_all.py` 覆盖——10 页归档为 `l1_rows_10pages.json`，5 页端到端归档为 `l2b_rows_5pages.json`。

---

## 7. 产物索引（均在 `D:\ComiTrans\tmp\`）

```
erase-eval/l1_rows.json            106 框掩膜层（章样本）
erase-eval/l1_rows_10pages.json    204 框掩膜层（10 页扩展）
erase-eval/l2b_rows.json           12 页 105/106 框端到端（章样本）
erase-eval/l2b_rows_5pages.json    5 页端到端（旧版归档）
erase-eval/l3_ch_rows.json         106 框门控中间量（ring/inner/collar_ptp/safe）
erase-eval/l4_rows.json            104 框路由重放（cur vs flat 双套 std/残留）
erase-eval/l2b-distribution.png    白净度分布图（箱线 + ECDF）
erase-eval/l2-test1.png            极端页三态对比（原图 / 旧版 / 当前）
erase-eval/lama-page-whole-vs-tiled.png  分块 vs 整页
erase-ab/bubble-residual.png       单气泡三态 + 残留像素定位
ch_all.py  eval_l1.py  eval_l1_stats.py  eval_l2.py  eval_l2b.py  l2b_stats.py
eval_l3.py  l3ch_stats.py  eval_l4.py  l4_stats.py  plot_l2b.py
mask_ab.py  erase_ab.py  gate_diag.py  ring_sweep.py  lama_page_ab.py
```

---

## 8. 最终交付形态（2026-11-06 定稿）

用户要的是**修好旧版本的完整程序包**，不是 v2.5.1，也不是补丁。定稿：

- **`release/v2.5.0-hotfix/`** — 唯一交付物，完整一套：
  - `ComiTrans-v2.5.0-hotfix-app.zip` 637 226 746 B（`db635ca8…`）
  - `ComiTrans-v2.5.0-hotfix-models.zip` 485 652 354 B（`eb033920…`，22 个文件、584 467 185 B 原始）
  - `baseline.json`、`README.md`、`SHA256SUMS.txt`
  - 版本号 `2.5.0-hotfix`，模型组合与正式 v2.5.0 一致（Comic Text Detector + Baberu）
  - 空目录解压后 CPU / CUDA 冒烟均 `success=True`、`white_box_fallback=True`、`ocr_backend=baberu`
- **补丁已取消**：`release/v2.5.1/` 的 `ComiTrans-v2.5.0-to-2.5.1-patch.zip` 与 hotfix 的 patch 都已删除。v2.5.1 那套（app + models）保留但**不是本次交付**，它是检测器/OCR 升级线。
- **坑**：Windows PowerShell 5.1 的 `Expand-Archive` 解压 485 MB 模型包会静默漏解（只出 3 个文件）；7-Zip、资源管理器、Python `zipfile.extractall` 均正常。README 已加"模型文件数应为 22"的校验命令。
