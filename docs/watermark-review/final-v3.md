# 最终水印方向

用户定稿调整：只保留小号 Skribble 字标，文字为 `@ComiTrans`，位置向页面右下角下移。设置开关默认关闭。

实际渲染结果：`runtime-manga.png`（使用应用渲染函数，保留原漫画像素，仅叠加字标）。82 项回归测试通过，含 8 项水印测试，覆盖配置默认值与持久化、自动处理和管线复用、PDF 每页输出、精修草稿与重复保存。

视觉提案由内置 image_gen 生成：`manga-final-v3.png`。实际功能直接使用应用随附 Skribble 字体渲染，页面宽度约 14%，右边距为短边 2%，下边距为短边 1.6%，不重绘漫画内容。自动处理图片、PDF 每页与精修保存共用同一渲染函数。关闭时保留原输出行为，干净底图不添加水印。

## 最终效果图提示词（内置工具）

Edit input image 1, the manga with a small ComiTrans signature near the lower-right corner. Make ONLY these two changes to that added signature: (1) add an @ immediately before it so it reads exactly '@ComiTrans', in matching handwritten style; (2) move the signature DOWN by about 25 pixels at this page size, so its bottom is about 20 pixels above the bottom edge. Preserve the current small lettering size and right alignment, with right inset about 20 pixels. Input image 2 is the exact original Skribble ComiTrans letter artwork for reference: match it, and add a stylistically matching @. Do not add a character icon or symbol besides @. Keep its gray-black semi-transparent appearance with subtle white contour. Preserve the entire manga page, all speech text, layout and illustrations. Preserve the existing separate white Chinese attribution near the bottom, do not remove or cover it. Avoid collision: if needed keep the new @ComiTrans just to the right of that existing attribution on the white margin while preserving page-right inset. Erase the previous added ComiTrans at its old position so there is only ONE new @ComiTrans. Return ONLY the complete portrait manga page with this small adjusted text, no headings or presentation frames. The final image must be fully opaque, white paper background and alpha 255 everywhere, with text transparency baked into the opaque page. No other changes.
