# 白气泡整框涂白兜底 — 第一轮交付（第 1～4 步）

> 2026-11-04 · 只做第 1～4 步；第 5 步（回移 v2.5.0、打包、发行验收）**未开始**，等对照图与数据审完再动。
> 对照机：Windows / 16 逻辑核 / ONNX Runtime CUDA（`WB_DEVICE=cuda`），v4 与 v5 同机同参。

---

## 1. 本轮代码差异

| 文件 | 变更 | 内容 |
|---|---|---|
| `comic_translate_core/text_mask.py` | +132 / −? | 重写 `_white_box_fallback()`：框内种子判定、纸色只取原图未擦像素、长音符按几何放行 |
| `comic_translate_core/mask_debug.py` | +27 / −7 | 分别导出原掩膜 / 兜底区域 / 最终范围；诊断拆成 `metrics`（文字掩膜）与 `metrics_final_scope`（修复范围） |
| `tests/test_text_mask.py` | +88 | 新增 5 个断言：漏检标点、跨框线保护、邻框种子、长音符 vs 速度线、还原范围与相邻框 |

### 1.1 `_white_box_fallback` 的触发条件（改动核心）

草稿的判定链：`len(pixels)>=50` → `light>=0.80` → **`np.any(seeds)`** → 纸色 → 均匀度 → 象限一致性 → 保护区。

新版逐条改动：

| 条件 | 草稿 | 现在 | 原因 |
|---|---|---|---|
| 种子 | `np.any(seeds)`（整块 crop） | `local_seeds = seeds & box`，要求 `>= max(8, size*0.4)` 像素，且**连通块 ≥2 个或面积 ≥ size²·0.5** | crop 的 domain 外扩最多 8px，邻框种子会漏进来；单个杂点也不算文字块 |
| 纸色样本 | `image[inside]`（含笔画） | `free = box & ~dilate(erase,1)`，只取未擦的原始像素 | 笔画投票会把纸色拉灰，也让 `light` 比例失真 |
| 均匀度 | `distance<=20` 全框 75%、P90≤8 | 同上，但统计域改为 `free` | 同上 |
| 象限一致性 | `image[ys,xs][distance<=20]` | 保留（已排除 erase 影响） | — |
| 长音符 | 需 `i in supported` 才算短划线 | `dash_shape` 几何放行：`thin≤max(3,size*.35)`、`long≤max(8,size*2.6)`、`long≥2.5·thin`、`area≤size²·4` | 漏检的「ー」长宽比像画线，会被当保护区留下 |
| 保护区 | 触边 / 大块 / 长条 | 同前，长音符例外只影响 `text_dash` | 更长笔画（速度线）仍保护 |

**实测触发率（122 框，同一检测器、同一框）**：草稿 64 → 收紧后 **100**（+36，**0 框因种子被拒**）。

原因不是放宽，而是换样本域：纸色与均匀度改为在"去掉笔画后的纸面"上统计，原本被文字污染的判据反而更容易通过。合成测试 `test_box_fallback_requires_its_own_seeds` 证明"邻框种子不再触发"这一条是有效的（真实样本里恰好没有"框内无种子"的框，所以 drops=0）。

> **待审点 A**：触发率 52%→82% 会让涂白范围显著变大。若你希望更保守，可把 `seed_pixels` 下限从 `max(8,size*0.4)` 提到 `max(16,size*0.8)`，代价是大框（长竖列）更常不触发。

### 1.2 三掩膜导出（第 3 步）

`python -m comic_translate_core.mask_debug in.png --box x1 y1 x2 y2 --detector seed.png --output out/` 现在写：

- `erase.png` — 普通擦字掩膜（文字）
- `box_fill.png` — 整框兜底区域（无兜底时该文件不生成）
- `final_mask.png` — `max(erase, box_fill)`，与 pipeline 的 `restore_mask` 同口径
- `overlay.png` — 三色叠加：红=原掩膜、蓝=兜底新增、品红=重叠
- `diagnostics.json` — 含 `box_fill_pixels`、`protected_box_pixels`、`final_pixels`

pipeline 侧原本已把 `restore_mask = max(erase, box_fill)` 记入 `current_bubble_restore_regions`，本轮未改（§3 已验证还原是逐像素的）。

### 1.3 合成断言（第 4 步后半）

`tests/test_text_mask.py` 新增 5 例，全部通过（`tests.test_text_mask` 12/12，连同 `test_inpaint_typesetting`、`test_background_reconstruction`、`test_bubble_restore` 一起跑也 OK）：

1. 漏检圆点被 `box_fill_mask` 100% 覆盖
2. 跨框竖线：兜底覆盖 0，`protected_box_pixels>0`
3. 只有邻框种子（框上方 6px）时 `box_fill_mask is None`
4. 长音符被清除（≥90% 覆盖）；更长的速度线不被兜底涂（0%）
5. 还原：`make_region` 用 `erase ∪ fallback`，`apply_restorations` 逐像素等于原图；相邻两框重叠时各自 detection box 都能还原

---

## 2. 第 1 步：样本固化

`tmp/wb-review/boxes.json`：14 页（12 章页 + `test1` + `test10`）· 122 框 · 检测器固定 `split-detector/detector-v4-s_int8.onnx`。每框记录 box、font_size、md5、以及**框内未被种子覆盖的墨迹连通块**（漏检候选，共 208 个，含坐标/面积/长宽比）。

---

## 3. 第 4 步：四联图与数据

产物在 `tmp/wb-review/compare/`：

- `page-<stem>.png` ×14：原图 | v4 | v5 | 新增涂色区域（红）
- `case-<stem>.png` ×14：该页新增涂色最多的框，放大 2×
- `summary.json`：逐框 `ink_px / ink_left_px / ink_left_blocks / new_dark_px / paper_std / paper_mean / added_px`
- `added_audit.json`：逐框 `p99 / structured / added_glyph / added_line / added_paper / protect_px`
- `gate_compare.json`：草稿 vs 收紧的逐框触发对照

### 3.1 残字与保护（全样本）

| 组 | 框数 | 触发兜底 | 深残留 v4 → v5（px） | 残留连通块 v4 → v5 | 新增涂色 px | 其中压到线 |
|---|---|---|---|---|---|---|
| A 白气泡（p99≤10、结构化≤1%、墨迹密度<0.5） | 57 | 52 | 1499 → **1373** | 24 → **18** | 297 320 | **47（0.02%）** |
| B 框内有画 | 65 | 48 | 154 573 → 153 018 | 333 → **263** | 383 962 | 255（0.07%） |
| 全部 | 122 | 100 | 156 072 → 154 391 | 357 → **281（−21%）** | 681 282 | 302（0.04%） |

> 深残留 = 原图 <170 的位置在输出里仍 <140。**140–170 的浅灰残影不计入**，所以视觉上的"没擦干净"可能比这个数字多。

逐框：**47 改善、0 变差、75 不变**。改动只增不减。

### 3.2 逐页（A 类深残留）

| 页 | v4 | v5 | 残留块 | 新增涂色 |
|---|---|---|---|---|
| 001 | 77 | 77 | 1→1 | 6 619 |
| 002 | 6 | 6 | 0→0 | 28 824 |
| 004 / 009 / 011 | 0/5/0 | 0/5/0 | — | 10 370 / 18 298 / 8 548 |
| 005 | 16 | **3** | 1→0 | 22 533 |
| 006 | 27 | **12** | 1→1 | 38 932 |
| 007 | 10 | **0** | 0→0 | 24 374 |
| 008 | 5 | **0** | 0→0 | 21 455 |
| 010 | 13 | **0** | 1→0 | 35 235 |
| 012 | 8 | **0** | 0→0 | 28 521 |
| test1 | 1299 | 1255 | 19→16 | 27 999 |
| test10 | 33 | **15** | 1→0 | 25 612 |

### 3.3 代表性对照（供你审"原先剩下的字是否真的消失"）

- `case-002.png`：v4 仍留「ちゃん」「かっどう」等**振假名**，v5 全清，左右网点保留 —— 这是本轮最清楚的成功案例
- `case-008.png`：v4 留浅灰字影，v5 干净，气泡外框网点保留
- `case-001.png`：v5 仍有可见残字（该框 `protected_box_pixels=489`，与底部网点相连的笔画被保护）
- `page-003.png`：整页未触发（复杂背景），v4=v5，属预期

---

## 4. 已知缺口（建议第二轮回看）

1. **该触发却未触发 5 框**（纸面 p99≤10 但没涂）：
   `001 (760,52,805,548)` 墨迹密度 0.32、长竖列，`free` 不足 25% 被拒；`test1 (20,1171,76,1687)`、`008 (275,103,340,218)`、`test10 (73,52,492,84)`、`test10 (38,447,68,1054)`。
   其中 001 那个框仍有 77px 残留、test1 那个框 1255px。
2. **A 类仍有 3 框 ≥8px 残留**：`test1 (20,1171,76,1687)`、`001 (760,52,805,548)`、`006 (428,404,540,534)`。
3. **B 类触发 48 框**：自动指标只能证明"没有压到被判为线的连通块"（0.07%），**不能排除网点/色块被涂**。需要你看 B 类四联图的第 3、4 栏确认。
4. **浅灰残影**未纳入指标（只看 <140），`test1` 这类页观感可能比数字差。

---

## 5. 复跑

```powershell
# 1) 样本（只读检测器，~1 分钟）
& .venv\Scripts\python.exe tmp\wb_samples.py
# 2) 触发率对照（草稿 vs 收紧）
& .venv\Scripts\python.exe tmp\wb_gate_compare.py
# 3) 四联图 + 逐框统计（可续跑；GPU 约 1 分钟，CPU 约 7 分钟）
$env:WB_DEVICE='cuda'; & .venv\Scripts\python.exe tmp\wb_compare.py
# 4) 新增涂色归因 + 报告表
& .venv\Scripts\python.exe tmp\wb_added_audit.py
& .venv\Scripts\python.exe tmp\wb_report_data.py
```

---

## 6. 下一步（等审）

第 5 步按你的顺序执行：两版各用自己的检测器复测 → 重建 v2.5.1 程序包 / v2.5.0 完整包 / 相对正式 v2.5.0 的补丁 → `smoke_test.py` 增加"故意漏掉标点种子"的样例（现有 `jpeg_paper_fill` 只覆盖旧平涂分支）→ 空目录验证 CPU / CUDA / 补丁安装 → 更新 SHA256。

---

## 7. 第二轮：档 2 + 三道安全网（已落地）

### 7.1 改动

`_white_box_fallback` 增加三个旋钮，全部收在同一个函数里：

| 安全网 | 实现 | 作用 |
|---|---|---|
| ① `free_share` 分级 | `free/box ≥25%` 走原判据；`10%≤share<25%` 额外要求 `light ≥0.95`、纸色每通道 ≥252、纸色极差 ≤4；`<10%` 直接拒绝 | 纸色只由不足 1/4 的纸面估计时，必须接近纯白才敢整框涂 |
| ② 只对 plain 框放宽保护 | `plain = p99(distance[free]) ≤10 且 墨迹密度<0.5`；只有 plain 框才把"紧凑字形块"从保护区移出（`area ≤ size²·4`、`thin ≤ size·1.2`、`long ≤ size·2.4`） | 有画的框保持严格规则；长笔画（速度线）仍保护 |
| ③ 保护区占比否决 | `protect/box >30%` 且非 plain → 放弃整框涂白 | 框内画太多时不冒险；plain 例外，因为"边框贴字"会推高占比但仍是白气泡 |

诊断新增 `box_fill_dial`（`strict`/`loose`）与 `box_fill_plain`，便于回归时区分走的哪条路。

### 7.2 效果（同一 122 框样本）

| 组 | 触发 | 深残留 v4 → v5 | 残留块 v4 → v5 | 新增涂色 | 压到线 |
|---|---|---|---|---|---|
| A 白气泡 57 框 | 55 | 1499 → **41（−97.3%）** | 24 → **1** | 307 044 | 55（0.02%） |
| B 有画 65 框 | 46 | 154 573 → 153 110 | 333 → 266 | 374 698 | 255（0.07%） |
| 全部 122 框 | 101 | 156 072 → 153 151 | 357 → **267** | 681 742 | 310（0.045%） |

- `test1` 整页 A 类残留 1299 → **0**（19 块 → 0）
- `001` 77 → **0**
- A 类中已无任何框残留 ≥8 px（第一轮有 3 个）
- 未触发仅剩 2 框（`test10 (73,52)`、`test10 (38,447)`），两者 v4/v5 残留本来都是 0，无影响

端到端复测（001 / test1 / 004 / 011）：相对上一轮严格档，差异像素 19 286 / 26 141 / 4 020 / 0。

### 7.3 已知副作用

1. **004 页掩膜反而小了 4 510 px**：一个框 `protect/box >30%` 且非 plain，被安全网 ③ 拒绝。这是设计内的保守，但意味着"文字紧贴大块画"的框仍不会整框涂白。
2. **B 类触发从 48 降到 46**，同样来自 ③。
3. **"文字与长画线粘连"的框**：整块被并成一个连通块 → 判为线 → 保护 → 占比超限 → 放弃兜底。合成用例 `test_long_vowel_mark_is_cleared_but_a_speed_line_is_protected` 已把线移到字形上方，避免该形态掩盖真正的长音符判定。

### 7.4 测试

`tests.test_text_mask`（12）+ `test_inpaint_typesetting` + `test_background_reconstruction` + `test_bubble_restore` 共 **36 tests OK**。

### 7.5 对照图

`tmp/wb-review/dial2/<page>.png`：原图 | 严格档 | 档2+安全网 | 两者差异（红）。已出 001 / test1 / 004 / 011 四页。

---

## 8. 第 5 步：打包与验收（已完成）

### 8.1 冒烟样例（构建前加入）

`comic_translate_desktop/smoke_test.py` 新增 `white_box_fallback` 检查：白气球 + `Hi` 种子 + 一个**不参与种子**的圆点，断言 `box_fill_mask` 覆盖该圆点、`box_fill_color` 非空。旧的 `jpeg_paper_fill` 只验证平涂分支，无法证明整框兜底进了包。新键已并入 `result['success']`。

### 8.2 产物

| 文件 | 大小 | SHA256 |
|---|---|---|
| `release/v2.5.1/ComiTrans-v2.5.1-app.zip` | 637 229 000 | `e050944b…af5bae` |
| `release/v2.5.1/ComiTrans-v2.5.1-models.zip` | 255 117 495 | `29ed3734…80498a`（沿用，未重打） |
| `release/v2.5.1/ComiTrans-v2.5.0-to-2.5.1-patch.zip` | 21 242 620 | `ac53b095…7d7310` |
| `release/v2.5.1/baseline.json` | — | build `a48a50eb…` |

`docs/releases/v2.5.1/` 的 `SHA256SUMS.txt` 与 `release/` 副本逐字节一致；补丁行已追加。CHANGELOG 与 `release-page.md` 同步了本轮改动的用户向描述。

### 8.3 验收结果

| 场景 | 结果 |
|---|---|
| dist 直接冒烟（CPU） | `success=True`，`white_box_fallback=True`，`jpeg_paper_fill=True` |
| dist 直接冒烟（CUDA） | `success=True`，`gpu_active=True`，detector/inpainting/lines 均 CUDA，OCR CPU |
| 补丁应用到**官方 v2.5.0**（`build_id 6c0ddf10`） | `Updated to 2.5.1. Build: a48a50eb…`，自动备份到 `.comitrans-update/` |
| 补丁后冒烟（CPU / CUDA） | 均 `success=True`、`white_box_fallback=True` |
| 两个 ZIP 解压到空目录后冒烟（CPU） | `success=True`，`white_box_fallback=True`，`missing_glyphs=[]` |

CUDA 冒烟依赖本机 `%LOCALAPPDATA%\ComiTrans\gpu-runtime\bin`（cudart/cudnn 9），与发布包不带 DLL 的策略一致。

### 8.4 补齐：v2.5.0 完整包与 `build_app.ps1`

**v2.5.0 完整包已补做**（`release/v2.5.0-hotfix/`，版本字符串 `2.5.0-hotfix`，与 v2.5.1 同源）：

| 文件 | 大小 | SHA256 |
|---|---|---|
| `ComiTrans-v2.5.0-hotfix-app.zip` | 637 226 746 | `db635ca8…0ac100` |
| `ComiTrans-v2.5.0-hotfix-patch.zip` | 21.24 MB | `00493869…0fa19b` |

补丁 base 是**官方 v2.5.0**（`6c0ddf10`），target 是 hotfix 包（`7ad86210`）。在还原的官方 v2.5.0 目录上实测：`Updated to 2.5.0-hotfix. Build: 7ad86210…`，安装后冒烟 `success=True`、`white_box_fallback=True`。新增 `docs/RELEASE-v2.5.0-hotfix.md` 供包内 README 使用（`collect_app` 要求该文件存在）。

**`build_app.ps1` 之前失败的真实原因**（不是脚本逻辑损坏）：

1. 本机只有 **Windows PowerShell 5.1**（没有 pwsh 7）。脚本是无 BOM 的 UTF-8 且含中文，5.1 按 GBK 解码 → 中文字节破坏引号配对 → 报 `from` 关键字错误。
2. 修法一：给文件加 **UTF-8 BOM**（5.1 与 7 都能正确解码）。
3. 修法二：`$ErrorActionPreference` 由 `Stop` 改为 `Continue`——PyInstaller 把进度写到 stderr，5.1 会把它当 `NativeCommandError`，在 `Stop` 下直接中断；脚本每步都检查 `$LASTEXITCODE`，所以 `Continue` 不会漏掉真失败。

修完后 `.\build_app.ps1` 实测跑通（exit 0，`dist\ComiTrans` 重建成功）。

> 维护提醒：本仓库的 `.ps1` 若含中文必须带 BOM。用会重写文件的编辑器改动后要重新确认 BOM，否则 5.1 下会再次解析失败。

### 8.5 仍未完成

- v2.5.0-hotfix 只做了 CPU 冒烟；同源代码在 v2.5.1 上 CUDA 已通过，未单独复测 hotfix 的 CUDA。
- `dist\ComiTrans` 最后一次重建（23:04，2.5.1）与 `release\v2.5.1` 里的 app.zip（22:45 构建）内容同源但非逐字节可复现；已发布的 zip 未重打。
