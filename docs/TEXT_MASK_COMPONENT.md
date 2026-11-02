# 文字掩膜组件

`comic_translate_core.text_mask` 只依赖 NumPy、OpenCV，不加载检测、OCR、翻译、LaMa 或 Qt。自动翻译通过同一个接口生成擦除掩膜和排版掩膜；精修中用户手动画出的背景修补选区仍代表“整个选区重绘”，不擅自变成文字选区。

## 输入与输出

- `MaskRequest.image`：原分辨率 `uint8` BGR 图片裁片；实现不得修改输入。
- `text_box`：裁片局部坐标 `(x1, y1, x2, y2)`，右、下边界不包含。
- `detector_mask`：可选，同尺寸 `uint8` 检测器掩膜，非零为文字种子。
- `font_size`：原图像素字号，控制边缘扩张范围。
- `MaskResult.erase_mask`：同尺寸二值 `uint8`，255 为需要替换的像素。
- `layout_mask`：独立的排版占位掩膜；不用于擦字。
- `fill_color`：确认是纯色时返回 BGR 整数三元组；`None` 表示交给纹理修复。
- `diagnostics`：算法版本、背景一致程度、修复分流、掩膜面积等可序列化数据。
- 可选的 `source_outline_ratio` 表示识别出的白色描边宽度占原文字号的比例，范围为 `(0, 0.3]`。默认为 `None`。只有检测到足够多的笔画边缘被局部白边包围时，才把比例交给嵌字器。

调用边界用 `validate_result` 检查尺寸、类型、二值范围和底色。流水线向组件传入只读副本，每个检测框都基于同一原图计算；多个框的掩膜取并集。`current_erase_mask`、`current_mask_image`、`last_mask_diagnostics` 可供调用方检查实际使用的掩膜。

## 默认算法

1. 从检测框外估计背景色，再检查笔画旁的实际像素。只有待擦区域紧邻的底色均匀且与背景估计相符时才平涂。白纸边缘包围有色文字底时，另用检测笔画附近的样本判断。
2. 纯色区域使用颜色距离补齐字形、抗锯齿边缘与漏检标点，排除连到裁片边界或过大的结构。
3. 纹理区域同时提取明、暗局部笔画和颜色残差；有检测器种子时只保留种子附近相连的候选，限制最大扩张距离，避免沿相连头发或分镜线蔓延。
4. 对深色笔画周围的白描边，检查白色区域是否局限在检测笔画附近并包围笔画。通过检查的描边仅计入擦除掩膜，新增面积记录在 `extra_outline_pixels`。延伸至裁片外的白底和高光不参与描边扩张。
5. 重复细小点状成分阻止直接纯色填补。网点与渐变先尝试下述局部重建，复杂画面使用 LaMa 原分辨率重叠分块。

擦字调度另外调用独立的 `background_reconstruction.reconstruct_background`：

- 对平滑彩色背景拟合颜色平面，用全部未掩盖像素校验，每通道最大残差不超过 3/255 才接受。
- 对规则网点寻找 2–64 像素的整数重复周期，先抽样筛选、再检查全部可比的未掩盖像素；每个待修补像素必须有至少两个相符的原生像素来源，且差异不超过 3/255。
- 缺少周边支持、掩膜触边、不规则纹理或裁片超过 100 万像素时，不冒险拟合，退回 LaMa 原分辨率分块。额外分析不会缩放图像。流水线的诊断记录包含 `repair_strategy`，标明 `flat`、`colour-plane`、`periodic-texture` 或 `lama`。

这仍是基于检测器的图像算法，不是语义分割模型。文字和头发同色且相连、检测器漏字、复杂网点或大面积文字覆盖时，不能保证自动恢复原画；缺少种子时只作保守的连通域筛选。合成测试用于验证边界和分流，不代表所有实漫上的质量结论。无需以降分辨率换取内存。

## 独立测试

在项目根目录运行（坐标相对于输入图片）：

```powershell
.venv\Scripts\python.exe -m comic_translate_core.mask_debug page.png --box 100 200 400 600 --font-size 24 --detector detector.png --output tmp\mask-check
```

输出 `erase.png`、`layout.png`、`overlay.png` 与 `diagnostics.json`。不调用 API 或修复模型，也不改动输入图片。`--detector` 可省略；提供同尺寸人工标注 `--reference-mask truth.png` 后，会报告 IoU、精确率和召回率。擦除掩膜包含有意扩张的抗锯齿边缘，比较时应统一标注标准。

## 替换实现

实现 `generate(request: MaskRequest) -> MaskResult`，再将对象通过 `ComicTranslatorPipeline(..., text_mask_generator=MyMask())` 注入，或在调用前设置 `pipeline.text_mask_generator`。组件与推理后端解耦，不需要修改擦字调度代码。

独立工具支持 `--provider my_package:MyMask`，加载已安装/可导入的可信实现，便于用同一图片和标注对比多个算法。该参数会执行指定 Python 模块，请只指定你准备测试的代码。

运行回归：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_text_mask tests.test_background_reconstruction tests.test_inpaint_typesetting tests.test_lama_tiling
```

新算法用于后续处理的页面；断点续传仍保留已完成页面。要用新算法重新处理已完成页，需要关闭断点续传重新运行，或在精修中修补相应区域。
