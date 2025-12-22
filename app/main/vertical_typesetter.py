import math
import traceback
import numpy as np
from PIL import Image, ImageDraw, ImageFont

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

    def _calculate_layout_fast(self, text, font, box_h, line_spacing=4):
        lines_structure = []  # 只存每行有几个字，不存具体字符串
        current_line_count = 0
        current_height = 0

        for char in text:
            w, h = self._get_char_size(char, font)
            if current_height + h > box_h:
                if current_line_count > 0: lines_structure.append(current_line_count)
                current_line_count = 1
                current_height = h + line_spacing
            else:
                current_line_count += 1
                current_height += h + line_spacing

        if current_line_count > 0: lines_structure.append(current_line_count)
        if not lines_structure: return False, 0, [], 0

        sample_w, _ = self._get_char_size("国", font)
        col_spacing = int(sample_w * 0.2)
        total_width = len(lines_structure) * sample_w + (len(lines_structure) - 1) * col_spacing
        return True, total_width, lines_structure, col_spacing

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

    def wrap_text_vertical(self, text, max_height, font):
        """根据高度自动分列"""
        lines = []
        current_line = ""
        current_height = 0
        line_spacing = 4

        for char in text:
            w, h = self._get_char_size(char, font)
            if current_height + h > max_height:
                lines.append(current_line)
                current_line = char
                current_height = h + line_spacing
            else:
                current_line += char
                current_height += h + line_spacing

        if current_line:
            lines.append(current_line)
        return lines

    def draw_text(self, image, box, text, style='dialogue', mask=None):
        """执行竖排绘制 (使用绝对居中算法 anchor='mm')"""
        try:
            x1, y1, x2, y2 = map(int, box)

            scale_ratio = 0.6

            GLOBAL_OFFSET_X = -6  # 正数向右，负数向左
            GLOBAL_OFFSET_Y = 16  # 正数向下，负数向上

            raw_width = x2 - x1
            raw_height = y2 - y1
            box_width = int(raw_width * scale_ratio)
            box_height = int(raw_height * scale_ratio)

            # 气泡几何中心点
            center_x = x1 + raw_width // 2

            base_font = self.fonts.get(style, self.fonts.get('dialogue'))
            current_font = base_font

            # 简单的字号预处理
            if box_width < self.base_font_size * 2:
                try:
                    new_size = max(12, box_width // 2)
                    font_path = self.font_map.get(style, self.font_map.get('dialogue'))
                    if font_path:
                        current_font = ImageFont.truetype(font_path, new_size)
                except:
                    pass

            clean_text = text.replace('\n', '')
            available_area = 0
            if mask is not None:
                try:
                    # 1. 裁剪出当前气泡区域的 mask
                    crop_box = (x1, y1, x2, y2)
                    bubble_mask = mask.crop(crop_box)
                    # 2. 统计非零(白色)像素数量
                    # 稍微缩小一点范围以模拟 padding (比如只统计 80% 的像素)
                    import numpy as np
                    mask_arr = np.array(bubble_mask)
                    # 统计值 > 0 的像素点个数
                    pixel_count = np.count_nonzero(mask_arr)
                    available_area = pixel_count * 0.7
                except Exception as e:
                    print(f"Mask 计算失败: {e}")
                    available_area = 0
            if available_area == 0:
                available_area = (box_width * box_height)
            columns = self.wrap_text_vertical(clean_text, box_height, current_font)
            if not columns: return image
            # 智能寻找最佳字号
            try:
                import math
                # 原公式: box_width * box_height
                estimated_size = int(math.sqrt(available_area / (len(clean_text) + 1) / 1.3))

                # 限制最大字号 (不能超过盒子宽度的 80%)
                max_allowed_size = min(box_width, box_height)
                start_size = min(max_allowed_size, max(12, estimated_size + 4))
            except:
                start_size = 24

            best_size = 12
            best_lines_struct = []
            best_col_spacing = 5

            for size in range(start_size, 11, -2):
                font = self._get_font_object(style, size)
                valid, layout_w, lines_struct, col_sp = self._calculate_layout_fast(clean_text, font, box_height)

                if valid and layout_w <= box_width:
                    best_size = size
                    best_lines_struct = lines_struct
                    best_col_spacing = col_sp
                    current_font = font
                    break

            if current_font is None:
                current_font = self._get_font_object(style, 12)
                _, _, best_lines_struct, best_col_spacing = self._calculate_layout_fast(clean_text, current_font,
                                                                                        box_height)
            # 还原文本列表
            columns = []
            char_ptr = 0
            for count in best_lines_struct:
                columns.append(clean_text[char_ptr: char_ptr + count])
                char_ptr += count
            if not columns:
                return image
            draw = ImageDraw.Draw(image)

            # 获取标准字宽 (作为格子的宽度)
            sample_w, _ = self._get_char_size("国", current_font)

            # 计算整个文本块的总宽度
            total_text_width = len(columns) * sample_w + (len(columns) - 1) * best_col_spacing

            # B. 计算第一列（最右边那一列）的中心 X 坐标
            # 逻辑：盒子中心 + (总宽的一半) - (半个字宽)
            # 这样保证整个文本块是关于 center_x 对称的
            current_col_center_x = center_x + (total_text_width // 2) - (sample_w // 2)

            for col_text in columns:
                # 计算该列总高
                col_height = 0
                for char in col_text:
                    _, h = self._get_char_size(char, current_font)
                    col_height += h
                col_height += (len(col_text) - 1) * 2  # 行内字间距

                # 计算该列起始 Y (垂直居中)
                start_y = y1 + (box_height - col_height) // 2
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
                        # 在小画布里也是用 mm 居中
                        d.text((temp_size / 2, temp_size / 2), char, font=current_font, fill=self.color, anchor='mm')
                        rotated_txt = txt_img.rotate(-90, expand=False, resample=Image.BICUBIC)

                        # 粘贴到绝对中心 (paste 需要左上角坐标，所以减去半径)
                        paste_x = target_center_x - temp_size // 2
                        paste_y = target_center_y - temp_size // 2
                        image.paste(rotated_txt, (paste_x, paste_y), rotated_txt)
                    else:
                        # 普通文字：直接使用 anchor='mm' 让 Python 帮你对齐
                        draw.text(
                            (target_center_x, target_center_y),
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

            # 调试框 (取消注释可查看排版范围)
            # draw.rectangle(box, outline="red", width=3)
            # draw.line([(center_x, y1), (center_x, y2)], fill="blue", width=2)

            return image

        except Exception as e:
            import traceback
            print(f"【严重错误】draw_text 崩溃: {e}")
            traceback.print_exc()
            return image