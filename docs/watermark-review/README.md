# 水印效果审批草案

当前定稿：根据用户反馈去掉图标，将小号字标下移并改为 `@ComiTrans`。应用功能已按此版本实现，设置开关默认关闭。下文保留首版设计记录；首版图标组合已被替代。

效果图：`proposal.png`。使用内置 image_gen 工具生成，用于审批组合和视觉方向，图中文字、透明度及描边仅为概念示意，不是最终像素规格。

拟采用应用原图标 `assets/ComiTrans.ico` 和左上角字标所用的 `assets/ui/fonts/Skribble.ttf`，灰度化后横向组合。最终实现应使用原始资源以保留准确形状，整体降低不透明度并加细白描边。建议放在输出页右下角。审批后添加设置开关，默认关闭。

参考图位于 `tmp/watermark-review`，只有图标格式转换与原字体渲染，不影响应用代码。

## 最终修正提示词（内置工具）

Edit this graphic presentation ONLY to fix its background display. It currently has an unintended alpha channel that makes the diagram invisible on black. The deliverable must be an ENTIRELY OPAQUE, flat, printed graphic sheet. Composite the top 74% of the supplied image on a flat solid WHITE opaque background. Composite the horizontal strip from 74% down to 97% on a flat solid dark charcoal #303030 opaque background, remaining bottom margin solid white. Flatten ALL transparency to that backing so every output pixel has alpha 255. Preserve all the source shapes, Chinese labels, exact 'ComiTrans' lettering, relative size, three rows, and positions. Title and all labels dark black on white and easy to read. Crisp flat colors. No blur, no gradient, no mist, no shadow, no glow, no background removal, no transparency. Treat this as a final opaque SCREENSHOT of a design sheet. Do not change the design or redraw the characters.
