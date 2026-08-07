import math
import traceback
import numpy as np
from PIL import Image, ImageDraw, ImageFont


UPRIGHT_VERTICAL_PUNCTUATION = set("，。！？；：、")


class VerticalTypesetter:
    def __init__(self, font_map, font_size, color=(0, 0, 0)):
        self.fonts = {}
        self.font_map = font_map
        self.font_cache = {}
        self.base_font_size = font_size
        self.color = color

        # 预加载所有字体
        # font_map 格式: {'dialogue': 'a.ttf', 'radiating': 'b.ttf', ...}
        for style, path in font_map.items():
            try:
                self._load_font_to_cache(style, path, font_size)
                self.fonts[style] = self.font_cache.get((path, font_size))
            except:
                print(f"字体加载失败: {path}")
                self.fonts[style] = ImageFont.load_default()

        # 兼容旧代码引用 self.font 的地方，默认给 dialogue
        self.default_font = self.fonts.get('dialogue', ImageFont.load_default())

    def _load_font_to_cache(self, style, path, size):
        key = (path, size)
        if key not in self.font_cache:
            try:
                self.font_cache[key] = ImageFont.truetype(path, size)
            except:
                self.font_cache[key] = ImageFont.load_default()
        return self.font_cache[key]

    def _get_font_object(self, style, size):
        path = self.font_map.get(style, self.font_map.get('dialogue'))
        if path:
            return self._load_font_to_cache(style, path, size)
        return ImageFont.load_default()

    def _calculate_layout_fast(self, text, font, limit, is_horizontal=False, spacing=None):
        if spacing is None:
            # 动态间距：字号的 25% (最小 2px)
            spacing = max(1, int(font.size * 0.1))

        lines_struct = []
        layout_size = 0

        if not is_horizontal:
            lines_struct = self.wrap_text_vertical(text, limit, font)
            if not lines_struct:
                return False, 0, [], spacing

            # 计算总宽度：列数 * 字宽 + 间距
            # 假设字宽等于字号
            col_width = font.size
            layout_size = len(lines_struct) * col_width + (len(lines_struct) - 1) * spacing

        else:
            lines_struct = self.wrap_text_horizontal(text, limit, font)
            if not lines_struct:
                return False, 0, [], spacing

            row_height = font.size
            layout_size = len(lines_struct) * row_height + (len(lines_struct) - 1) * spacing

        return True, layout_size, lines_struct, spacing

    def _is_punctuation_to_rotate(self, char):
        """判断是否需要旋转的标点符号"""
        rotate_chars = ['—', '-', '…', '...', '(', ')', '（', '）', '【', '】', '[', ']', '{', '}', '《', '》', '～', '~']
        return char in rotate_chars

    def _get_char_size(self, char, font):
        """获取字符宽高"""
        if hasattr(font, 'getbbox'):
            bbox = font.getbbox(char)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        else:
            # 兼容旧版 Pillow
            return font.getsize(char)

    def wrap_text_horizontal(self, text, max_width, font):
        """【新增】根据宽度自动分行（横排模式）"""
        lines = []
        current_line = ""
        current_width = 0
        # 简单的溢出容忍系数
        sample_w, _ = self._get_char_size("国", font)
        overflow_tolerance = sample_w * 0.8

        for i, char in enumerate(text):
            w, h = self._get_char_size(char, font)

            # 核心逻辑：当前行宽 + 新字宽 > 最大宽度
            if current_width + w > max_width:
                # 容忍逻辑：如果是最后一个字，且超出不多，不换行
                is_last_char = (i == len(text) - 1)
                if is_last_char and (current_width + w <= max_width + overflow_tolerance):
                    current_line += char
                    break

                lines.append(current_line)
                current_line = char
                current_width = w
            else:
                current_line += char
                current_width += w

        if current_line:
            lines.append(current_line)
        return lines

    def wrap_text_vertical(self, text, max_height, font):
        """
        根据高度自动分列
        1. 加入避头逻辑 (防止标点在列首)
        2. 加入溢出容忍 (如果只剩一个字符且超出不多，不换列)
        """
        lines = []
        current_line = ""
        current_height = 0
        line_spacing = 4

        # 获取标准字号作为参考（用于计算容忍度）
        sample_w, sample_h = self._get_char_size("国", font)
        # 容忍度：允许最后一列超出 max_height 的比例（0.8 表示允许超出一个小标点或大半个字）
        overflow_tolerance = sample_h * 0.8

        # 避头符号
        punctuations_avoid_start = "，。！？；：、）》】」』”’"

        for i, char in enumerate(text):
            w, h = self._get_char_size(char, font)

            if current_height + h > max_height:

                # --- 溢出容忍逻辑 ---
                is_last_char = (i == len(text) - 1)
                if is_last_char and (current_height + h <= max_height + overflow_tolerance):
                    current_line += char
                    break

                # --- 避头逻辑 ---
                if char in punctuations_avoid_start and len(current_line) > 1:
                    last_char = current_line[-1]
                    current_line = current_line[:-1]
                    lines.append(current_line)
                    current_line = last_char + char
                    lw, lh = self._get_char_size(last_char, font)
                    current_height = lh + line_spacing + h + line_spacing
                else:
                    lines.append(current_line)
                    current_line = char
                    current_height = h + line_spacing
            else:
                # 高度充足，正常累加
                current_line += char
                current_height += h + line_spacing

        if current_line:
            lines.append(current_line)
        return lines

    def draw_text(
        self,
        image,
        box,
        text,
        style,
        mask=None,
        direction=0,
        target_font_size=None,
        non_bubble=False,
    ):
        """执行竖排绘制 (使用绝对居中算法 anchor='mm')"""
        try:
            x1, y1, x2, y2 = map(int, box[:4])

            scale_ratio = 0.9

            GLOBAL_OFFSET_X = 0
            GLOBAL_OFFSET_Y = 0   # 移除之前的 +5 硬补偿，因为接下来使用绝对几何中心

            raw_width = x2 - x1
            raw_height = y2 - y1

            # 气泡物理几何中心（始终基于最原始的框保持不动）
            center_x = x1 + raw_width // 2
            center_y = y1 + raw_height // 2

            # --- 智能气泡外扩算法 ---
            # 解决日语瘦长包围盒限制中文排版空间的问题
            if raw_height > raw_width * 1.5:
                # 瘦长型气泡：推测存在横白边，放宽宽度
                expanded_width = int(raw_height * 0.8)
                raw_width = max(raw_width, expanded_width)
            elif raw_width > raw_height * 1.5:
                # 宽扁型气泡：放宽高度
                expanded_height = int(raw_width * 0.8)
                raw_height = max(raw_height, expanded_height)
            else:
                # 近方形气泡：各个方向按比例扩展以吃满白区
                raw_width = int(raw_width * 1.2)
                raw_height = int(raw_height * 1.2)

            box_width = int(raw_width * scale_ratio)
            box_height = int(raw_height * scale_ratio)

            if non_bubble:
                raw_width = x2 - x1
                raw_height = y2 - y1
                box_width = int(raw_width * scale_ratio)
                box_height = int(raw_height * scale_ratio)

            base_font = self.fonts.get(style, self.fonts.get('dialogue'))
            current_font = base_font

            # 简单的字号预处理
            if box_width < self.base_font_size * 2:
                try:
                    new_size = max(12, int(box_width // 2))
                    current_font = self._get_font_object(style, new_size)
                except:
                    pass

            clean_text = text.replace('\n', '')
            preferred_size = None
            if target_font_size and target_font_size > 0:
                if style == "next_preview":
                    pref_ratio = 0.8
                elif style == "narration":
                    pref_ratio = 0.95 if len(clean_text) > 14 else 1.0
                elif direction == 1:
                    pref_ratio = 0.8 if len(clean_text) > 14 else 0.95
                else:
                    pref_ratio = 0.55 if len(clean_text) > 14 else 0.7
                preferred_size = max(10, int(target_font_size * pref_ratio))
                if direction == 1:
                    preferred_size = max(preferred_size, int(box_height * 0.25))
            available_area = 0
            mask_center = None
            if mask is not None:
                try:
                    # 1. 裁剪出当前扩充后气泡区域的 mask (保证能够抓取到真实泡泡的边缘)
                    expanded_x1 = max(0, center_x - raw_width // 2)
                    expanded_y1 = max(0, center_y - raw_height // 2)
                    expanded_x2 = center_x + raw_width // 2
                    expanded_y2 = center_y + raw_height // 2
                    
                    crop_box = (expanded_x1, expanded_y1, expanded_x2, expanded_y2)
                    bubble_mask = mask.crop(crop_box)
                    # 2. 统计非零(白色)像素数量
                    # 稍微缩小一点范围以模拟 padding (比如只统计 80% 的像素)
                    mask_arr = np.array(bubble_mask)
                    # 统计值 > 0 的像素点个数
                    ys, xs = np.nonzero(mask_arr)
                    if xs.size > 0:
                        mask_area = int((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1))
                        available_area = mask_area * 0.9
                        mask_center = (
                            expanded_x1 + int((xs.min() + xs.max()) // 2),
                            expanded_y1 + int((ys.min() + ys.max()) // 2),
                        )
                except Exception as e:
                    print(f"Mask 计算失败: {e}")
                    available_area = 0
            if available_area == 0:
                available_area = (box_width * box_height)
            # ??????????????????????????
            if mask_center is not None:
                center_x, center_y = mask_center
            columns = self.wrap_text_vertical(clean_text, box_height, current_font)
            if not columns: return image
            # 智能寻找最佳字号
            # 自动判断排版方向
            # 宽高比 > 1.5 则横排，否则竖排
            if direction == 1:
                is_horizontal = False
            elif direction == 0:
                # ???????????????????????????? 1.5 ???????
                is_horizontal = box_width > box_height * 1.1
            else:
                is_horizontal = box_width > box_height * 1.5

            # 智能预估起点
            try:
                # 恢复至初版的保守字号预估，提供充沛的留白
                text_len = len(clean_text)
                density = 4.0 if text_len > 14 else 2.2
                if is_horizontal:
                    density *= 1.3
                else:
                    density *= 0.75
                estimated_size = int(math.sqrt(available_area / (text_len + 1) / density))
                max_allowed_size = min(box_width, box_height)
                
                # 恢复至初版极其严格的极限值封锁（基础值的 1.5 倍）
                if style == "next_preview":
                    size_cap = int(min(box_width, box_height) * 0.7)
                    estimate_multiplier = 1.3
                    lower_bound = 14
                elif style == "narration":
                    size_cap = int(min(box_width, box_height) * 0.8)
                    if len(clean_text) > 14:
                        size_cap = min(size_cap, int(min(box_width, box_height) * 0.7))
                    estimate_multiplier = 1.4
                    lower_bound = 14
                elif style in ("radiating", "handwriting"):
                    if is_horizontal:
                        size_cap = int(min(box_width, box_height) * 0.6)
                    else:
                        size_cap = int(min(box_width, box_height) * 0.95)
                    estimate_multiplier = 1.5
                    lower_bound = 16
                else:
                    size_cap = int(min(box_width, box_height) * 0.5)
                    if len(clean_text) > 14:
                        size_cap = min(size_cap, int(min(box_width, box_height) * 0.4))
                    estimate_multiplier = 1.2
                    lower_bound = 12
                if non_bubble:
                    if style in ("next_preview", "narration"):
                        size_cap = min(size_cap, int(min(box_width, box_height) * 0.6))
                    else:
                        size_cap = min(size_cap, int(min(box_width, box_height) * 0.35))
                pref_cap = None
                if preferred_size:
                    lower_bound = min(lower_bound, max(10, preferred_size))
                    if non_bubble and style in ("next_preview", "narration"):
                        pref_cap = preferred_size
                    else:
                        pref_cap = int(preferred_size * 0.9) if non_bubble else preferred_size
                    size_cap = min(size_cap, pref_cap)
                upper_bound = min(
                    max_allowed_size,
                    max(lower_bound, size_cap, int(estimated_size * estimate_multiplier)),
                )
                if pref_cap:
                    upper_bound = min(upper_bound, pref_cap)
            except:
                upper_bound = min(24, preferred_size) if preferred_size else 24
                lower_bound = 12

            # 二分查找最佳字号
            best_size = 12
            best_lines_struct = []
            best_col_spacing = 2
            current_font = None

            low = lower_bound
            high = upper_bound

            constraint_limit = box_width if is_horizontal else box_height  # 传给函数的限制
            check_limit = box_height if is_horizontal else box_width  # 用于检查结果的限制

            while low <= high:
                mid = (low + high) // 2
                if mid % 2 != 0: mid -= 1
                if mid < lower_bound: mid = lower_bound

                font = self._get_font_object(style, mid)

                valid, calculated_size, lines_struct, sp = self._calculate_layout_fast(
                    clean_text, font, constraint_limit, is_horizontal=is_horizontal
                )

                if valid and calculated_size <= check_limit:
                    best_size = mid
                    best_lines_struct = lines_struct
                    best_col_spacing = sp
                    current_font = font
                    low = mid + 2
                else:
                    high = mid - 2

            # 保底逻辑
            if current_font is None:
                best_size = 12
                current_font = self._get_font_object(style, 12)
                _, _, best_lines_struct, best_col_spacing = self._calculate_layout_fast(
                    clean_text, current_font, constraint_limit, is_horizontal=is_horizontal
                )
            columns = best_lines_struct
            if not columns:
                return image
            draw = ImageDraw.Draw(image)

            # 获取标准字宽 (作为格子的宽度)
            sample_w, sample_h = self._get_char_size("国", current_font)



            # 计算整个文本块的总宽度
            total_text_width = len(columns) * sample_w + (len(columns) - 1) * best_col_spacing

            current_col_center_x = center_x + (total_text_width // 2) - (sample_w // 2)

            if is_horizontal:

                total_height = len(columns) * sample_h + (len(columns) - 1) * best_col_spacing

                current_row_center_y = center_y - (total_height // 2) + (sample_h // 2)

                for row_text in columns:
                    row_width = 0
                    for char in row_text:
                        w, _ = self._get_char_size(char, current_font)
                        row_width += w

                    current_x = center_x - (row_width // 2)

                    for char in row_text:
                        w, h = self._get_char_size(char, current_font)

                        target_center_x = int(current_x + w // 2) + GLOBAL_OFFSET_X
                        target_center_y = int(current_row_center_y) + GLOBAL_OFFSET_Y

                        draw.text(
                            (target_center_x, target_center_y),
                            char,
                            font=current_font,
                            fill=self.color,
                            anchor='mm',
                            stroke_width=1,
                            stroke_fill='white'
                        )
                        current_x += w  # 指针右移

                    current_row_center_y += (sample_h + best_col_spacing)

            else:
                for col_text in columns:
                    # 计算该列总高
                    col_height = 0
                    for char in col_text:
                        _, h = self._get_char_size(char, current_font)
                        col_height += h
                    col_height += (len(col_text) - 1) * 2  # 行内字间距

                    # 新算法：绝对几何中心对齐 (从物理中心往上推算起点，防下坠防偏移)
                    start_y = center_y - (col_height // 2)
                    current_y = start_y

                    for char in col_text:
                        w, h = self._get_char_size(char, current_font)

                        # 目标 X = 当前列的中心线
                        # 目标 Y = 当前高度 + 半个字高
                        target_center_x = int(current_col_center_x) + GLOBAL_OFFSET_X
                        target_center_y = int(current_y + h // 2) + GLOBAL_OFFSET_Y

                        if self._is_punctuation_to_rotate(char):
                            # 标点旋转处理
                            temp_size = max(sample_w, h) * 2
                            txt_img = Image.new('RGBA', (temp_size, temp_size), (255, 255, 255, 0))
                            d = ImageDraw.Draw(txt_img)
                            # 在小画布里也是用 mm 居中，并加上与正常文字一样的白边描边
                            d.text((temp_size / 2, temp_size / 2), char, font=current_font, fill=self.color, anchor='mm', stroke_width=1, stroke_fill='white')
                            rotated_txt = txt_img.rotate(-90, expand=False, resample=Image.BICUBIC)

                            # 粘贴到绝对中心 (paste 需要左上角坐标，所以减去半径)
                            paste_x = target_center_x - temp_size // 2
                            paste_y = target_center_y - temp_size // 2
                            image.paste(rotated_txt, (paste_x, paste_y), rotated_txt)
                        else:
                            punct_offset = (
                                int(sample_w * 0.25)
                                if char in UPRIGHT_VERTICAL_PUNCTUATION
                                else 0
                            )
                            draw.text(
                                (target_center_x + punct_offset, target_center_y),
                                char,
                                font=current_font,
                                fill=self.color,
                                anchor='mm',
                                stroke_width=1,
                                stroke_fill='white'  # 和fill颜色一致就是"加粗"，改成 "white" 就是"白边"
                            )

                        current_y += h + 2  # 移动到下一个字的顶部

                    # 移到下一列 (向左移动一个标准字宽 + 间距)
                    current_col_center_x -= (sample_w + best_col_spacing)

            # #调试框 (取消注释可查看排版范围)
            #         debug_box = box[:4]
            #
            #         dbg_outline = "yellow"
            #         if style == 'radiating':
            #             dbg_outline = "red"
            #         elif style != 'dialogue':
            #             dbg_outline = "cyan"
            #         draw.rectangle([x1, y1, x2, y2], outline="red", width=2)
            #
            #         margin_x = (raw_width - box_width) // 2
            #         margin_y = (raw_height - box_height) // 2
            #         draw.rectangle([x1 + margin_x, y1 + margin_y, x2 - margin_x, y2 - margin_y], outline="yellow",width=2)
            #         draw.line([(center_x, y1), (center_x, y2)], fill="blue", width=1)
            #         # 诊断代码：画一个覆盖全图的大 X，检查 draw 对象的坐标系是否正常
            #         w, h = image.size
            #         draw.line([(0, 0), (w, h)], fill="green", width=5)
            #         draw.line([(w, 0), (0, h)], fill="green", width=5)
            #
            #         # 检查当前 box 是否超出了图片边界
            #         if x2 > w or y2 > h:
            #             print(f"检测框坐标 {x2, y2} 超出了图片尺寸 {w, h}！")

            return image

        except Exception as e:
            import traceback
            print(f"【严重错误】draw_text 崩溃: {e}")
            traceback.print_exc()
            return image
