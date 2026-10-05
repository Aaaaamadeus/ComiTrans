# 纯字标水印审批第二版

状态：等待审批，未添加应用功能。

按用户反馈去掉图标、缩小字标；在漫画右下角展示 ComiTrans 字标，目标宽度约为页面的 14%。使用原版 Skribble 字标作为参考。效果图由内置 image_gen 工具生成，仅用于审批视觉方向，不作为最终导出或精确透明度测量依据。

预览文件：manga-text-only-v2.png

审批后实现设置开关，默认关闭。

## 生成提示词

Use case: compositing. Edit input image 1, the portrait manga page, by adding ONLY a small text-only ComiTrans overlay at the lower-right corner. Input image 2 is the exact wordmark artwork to insert. Preserve the hand-drawn Skribble letter shapes, exact spelling and capitalization 'ComiTrans' from input 2. Do not include any mascot, character icon, logo symbol, badge, surrounding rectangle, or additional words with the overlay. Remove the white backing of the wordmark when inserting, but the FINAL OUTPUT MUST BE A FULLY OPAQUE FLATTENED MANGA PAGE with solid white paper and every output pixel alpha 255. The final output is the complete manga page itself, portrait aspect ratio matching input 1, no presentation board, no headings, no frames, no comparison panels or enlargement inset. Preserve input 1's exact panels, characters, all existing Chinese and Japanese lettering, food, screen tones, page edges and original credit in the bottom right. Do not alter or remove existing attribution. Overlay size: visible text width about 14 percent of page width, about 170 pixels on the original 1220-pixel-wide page, preserving the source text's width-to-height ratio. Position: right edge inset 2 percent of page width, bottom of the new text around 4 percent of page height above the page bottom, in the available area beneath the rightmost speech balloon and just above the existing attribution; avoid overlapping speech text and existing attribution. Appearance: subtle neutral-gray text, approximately 30 percent opacity, with a very fine white contour of no more than 1 pixel at original page scale for readability over screen tones. All transparency should be baked into the opaque final page. No shadow, no glow, no gradient, no fog, no title, no icon. Make no other changes to the manga. Keep the complete page visible and uncropped. The goal is a realistic small quiet brand signature on the manga for design approval.

