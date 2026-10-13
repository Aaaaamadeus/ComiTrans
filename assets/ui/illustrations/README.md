# ComiTrans 工作室插画

两张图片已接入真实 Qt 界面，作为空状态中的插画素材。导航、按钮、表单、列表、章节标题与专注模式由 Qt 控件和主题实现。

| 文件 | 原始尺寸 | 使用位置 |
| --- | --- | --- |
| `studio-import-v1.png` | 1536 × 1024，RGBA | 自动处理空预览：原稿册、翻页与墨水笔 |
| `studio-editor-v1.png` | 1522 × 1033，RGBA | 精修空画布和译图等待区：手稿、放大镜与笔 |

两图均为透明 PNG，保留生成工具的原始文件。`ui/preview.py` 中的 `MangaIllustration` 用 Qt 保持比例绘制于 300 × 210 逻辑像素区域；加载真实漫画后切换为作品预览，小尺寸窗口隐藏插画以保留操作空间。插画不拦截鼠标，不叠加至用户原稿或导出的漫画。

`ComiTrans.spec` 已将整个 `assets/ui` 纳入打包资源。

## 生成记录

- 生成方式：内置 `image_gen.imagegen` 工具，2026-10-08。
- 参数：`transparent_background=true`，两张均为独立新图。
- 以下是实际使用的完整提示词。

### studio-import-v1.png

```text
Use case: illustration-story. Asset type: original atmospheric illustration for the empty import state in ComiTrans, a monochrome manga translation desktop studio. Create a polished, spacious black-and-white Japanese manga editorial ink illustration of an open manga manuscript book with gently curling pages, a few elegant floating loose manuscript sheets, a dip pen and a small ink bottle. The book pages contain crisp original comic panel art: a tiny city rooftop silhouette, a leaf and a sun, and empty speech bubbles, with no characters and no writing. Fine confident linework with varied line weight and a few deep black accents; sparse controlled screentone and hatching only inside the illustrated objects. The composition should feel immersive, artistic and light, with curved page motion and ample breathing room rather than a rectangular interface or boxed icon. Self-contained landscape composition, objects together around the centre, all silhouettes fully contained with generous transparent margins; readable when displayed around 320 by 210 logical pixels. True transparent background. Ink black, paper white and a few neutral gray halftones only. No text, no lettering, no logo, no watermark, no UI, no outer frame, no colour, no gradient, no glow, no blurry shadows, no aged paper, no decorative particles across the background. This is a finished production illustration asset, not an application mockup.
```

### studio-editor-v1.png

```text
Use case: illustration-story. Asset type: original monochrome editorial illustration for the empty typesetting and proofreading workspace in ComiTrans. Create a polished Japanese manga ink illustration of a gently curved manuscript page with an elegant magnifying glass hovering over an empty speech bubble and a fine nib pen resting nearby. The manuscript has three tasteful original manga panels containing a small city rooftop silhouette, a leaf, a sun and blank speech bubbles, without human characters. The magnifying glass and curling page make a graceful open, organic composition, not a rectangular UI icon. Confident delicate linework, varied line weight, a few rich ink accents, restrained screentone and fine hatching inside the objects. Spacious, artistic, tranquil comic studio mood, visually consistent with an open-manga-book illustration. Self-contained landscape composition, all objects contained with generous transparent margins, clear at around 280 by 190 logical pixels. True transparent background. Black ink, white paper and neutral gray screentone only. No text, lettering, logo, watermark, UI controls, outer frame, colour, gradients, glow, blurry shadows or aged paper. Finished production asset, not a mockup.
```
