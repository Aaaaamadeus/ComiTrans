import math
import traceback
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from punctuation_layout import (
    CENTERED_PUNCTUATION,
    CLOSING_PUNCTUATION,
    OPENING_PUNCTUATION,
    UPPER_RIGHT_PUNCTUATION,
    normalize_cjk_punctuation,
    vertical_form,
    wrap_vertical_text,
)

try:
    from fontTools.ttLib import TTFont
except ImportError:  # 打包异常时仍可排版，只是不做逐字缺字回退。
    TTFont = None


ROTATE_FALLBACK_PUNCTUATION = set("—-…（）【】［］｛｝《》「」『』〔〕～~")
VERTICAL_DASH_CHARS = frozenset("—―")
DEFAULT_RENDER_SCALE = 3
MAX_RENDER_SURFACE_PIXELS = 16_000_000


class VerticalTypesetter:
    def __init__(
        self,
        font_map,
        font_size,
        color=(0, 0, 0),
        render_scale=DEFAULT_RENDER_SCALE,
    ):
        self.fonts = {}
        self.font_map = font_map
        self.font_cache = {}
        self.base_font_size = font_size
        self.color = color
        self.last_font_size = None
        self.last_direction = None
        self.last_render_scale = 1
        self.last_layout_debug = []
        self.render_scale = max(1, int(render_scale))
        self._font_coverage_cache = {}
        self._glyph_visibility_cache = {}

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

    def _font_supports(self, path, char):
        if not path or not char or char.isspace() or TTFont is None:
            return True
        if path not in self._font_coverage_cache:
            try:
                font = TTFont(path, lazy=True, fontNumber=0)
                self._font_coverage_cache[path] = set((font.getBestCmap() or {}).keys())
                font.close()
            except Exception:
                # 无法检查的字体交给 Pillow 尝试，避免把可用字体错误排除。
                self._font_coverage_cache[path] = None
        coverage = self._font_coverage_cache[path]
        if coverage is not None and ord(char) not in coverage:
            return False
        glyph_key = (path, ord(char))
        if glyph_key not in self._glyph_visibility_cache:
            try:
                probe_font = self._load_font_to_cache("_coverage", path, 32)
                self._glyph_visibility_cache[glyph_key] = (
                    probe_font.getmask(char).getbbox() is not None
                )
            except Exception:
                self._glyph_visibility_cache[glyph_key] = True
        return self._glyph_visibility_cache[glyph_key]

    def _font_path_for_char(self, style, char):
        candidates = [
            self.font_map.get(style),
            self.font_map.get("dialogue"),
            self.font_map.get("bold_dialogue"),
            self.font_map.get("serious"),
            self.font_map.get("title"),
        ]
        seen = set()
        for path in candidates:
            if path and path not in seen:
                seen.add(path)
                if self._font_supports(path, char):
                    return path
        return self.font_map.get(style) or self.font_map.get("dialogue")

    def _style_for_text(self, style, text):
        fallback_styles = {
            "handwriting": ("narration", "dialogue"),
            "whisper": ("narration", "thought", "dialogue"),
            "cute": ("narration", "dialogue"),
            "next_preview": ("narration", "dialogue"),
            "radiating": ("bold_dialogue", "dialogue"),
            "sfx": ("bold_dialogue", "dialogue"),
        }
        visible_chars = [char for char in text if not char.isspace()]
        for candidate in (style, *fallback_styles.get(style, ("dialogue",))):
            path = self.font_map.get(candidate)
            if path and all(self._font_supports(path, char) for char in visible_chars):
                return candidate
        return style

    def _get_font_for_char(self, style, size, char):
        path = self._font_path_for_char(style, char)
        if path:
            return self._load_font_to_cache(style, path, size)
        return ImageFont.load_default()

    @staticmethod
    def _stroke_width(style, size, non_bubble=False):
        if style in ("radiating", "bold_dialogue", "sfx", "title"):
            return max(1, min(3, int(round(size * 0.045))))
        if non_bubble:
            return max(1, min(2, int(round(size * 0.035))))
        return 0

    def _make_render_surface(
        self,
        image,
        center_x,
        center_y,
        box_width,
        box_height,
        font_size,
        stroke_width,
    ):
        padding = max(5, int(math.ceil(font_size * 0.22)) + stroke_width)
        left = max(0, int(math.floor(center_x - box_width / 2)) - padding)
        top = max(0, int(math.floor(center_y - box_height / 2)) - padding)
        right = min(image.width, int(math.ceil(center_x + box_width / 2)) + padding)
        bottom = min(image.height, int(math.ceil(center_y + box_height / 2)) + padding)
        width = max(1, right - left)
        height = max(1, bottom - top)

        scale = self.render_scale
        while scale > 1 and width * height * scale * scale > MAX_RENDER_SURFACE_PIXELS:
            scale -= 1
        self.last_render_scale = scale

        surface = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        return surface, ImageDraw.Draw(surface), left, top, scale

    @staticmethod
    def _composite_render_surface(image, surface, left, top, scale):
        if scale > 1:
            surface = surface.resize(
                (max(1, surface.width // scale), max(1, surface.height // scale)),
                Image.Resampling.LANCZOS,
            )
        image.paste(surface, (left, top), surface)

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

            cell_size = self._vertical_cell_size(font)
            char_spacing = self._vertical_char_spacing(font)
            max_column_height = max(
                len(column) * cell_size + max(0, len(column) - 1) * char_spacing
                for column in lines_struct
            )
            if max_column_height > limit:
                return False, 0, lines_struct, spacing
            col_width = cell_size
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
        return char in ROTATE_FALLBACK_PUNCTUATION

    @staticmethod
    def _vertical_cell_size(font):
        return max(1, int(round(getattr(font, "size", 16))))

    @staticmethod
    def _vertical_char_spacing(font):
        return max(1, int(round(getattr(font, "size", 16) * 0.06)))

    @staticmethod
    def _font_advance(font, text):
        if hasattr(font, "getlength"):
            return float(font.getlength(text))
        bbox = font.getbbox(text)
        return float(bbox[2] - bbox[0])

    def _get_char_size(self, char, font):
        """获取字符宽高"""
        if hasattr(font, 'getbbox'):
            bbox = font.getbbox(char)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        else:
            # 兼容旧版 Pillow
            return font.getsize(char)

    @staticmethod
    def _draw_glyph_at_ink_center(
        draw, center_x, center_y, char, font, fill, stroke_width
    ):
        bbox = draw.textbbox(
            (0, 0), char, font=font, stroke_width=stroke_width
        )
        ink_center_x = (bbox[0] + bbox[2]) / 2
        ink_center_y = (bbox[1] + bbox[3]) / 2
        draw.text(
            (center_x - ink_center_x, center_y - ink_center_y),
            char,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill="white",
        )

    @staticmethod
    def _render_tight_glyph(char, font, fill, stroke_width):
        probe = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        probe_draw = ImageDraw.Draw(probe)
        bbox = probe_draw.textbbox(
            (0, 0), char, font=font, stroke_width=stroke_width
        )
        padding = max(2, stroke_width + 2)
        width = max(1, int(math.ceil(bbox[2] - bbox[0])) + padding * 2)
        height = max(1, int(math.ceil(bbox[3] - bbox[1])) + padding * 2)
        glyph = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glyph_draw = ImageDraw.Draw(glyph)
        glyph_draw.text(
            (padding - bbox[0], padding - bbox[1]),
            char,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill="white",
        )
        alpha_bbox = glyph.getchannel("A").getbbox()
        return glyph.crop(alpha_bbox) if alpha_bbox else glyph

    def _draw_vertical_cell(
        self,
        image,
        draw,
        *,
        char,
        font_style,
        font_size,
        center_x,
        center_y,
        cell_size,
        stroke_width,
    ):
        style_path = self.font_map.get(font_style)
        display_char = vertical_form(char)
        use_vertical_form = bool(
            display_char
            and style_path
            and self._font_supports(style_path, display_char)
        )
        if use_vertical_form:
            char_font = self._load_font_to_cache(font_style, style_path, font_size)
        else:
            display_char = char
            char_font = self._get_font_for_char(font_style, font_size, char)

        is_punctuation = (
            use_vertical_form
            or char in UPPER_RIGHT_PUNCTUATION
            or char in CENTERED_PUNCTUATION
            or char in OPENING_PUNCTUATION
            or char in CLOSING_PUNCTUATION
            or self._is_punctuation_to_rotate(char)
        )
        if not is_punctuation:
            self._draw_glyph_at_ink_center(
                draw,
                center_x,
                center_y,
                display_char,
                char_font,
                self.color,
                stroke_width,
            )
            return

        glyph = self._render_tight_glyph(
            display_char, char_font, self.color, stroke_width
        )
        if not use_vertical_form and self._is_punctuation_to_rotate(char):
            glyph = glyph.rotate(-90, expand=True, resample=Image.Resampling.BICUBIC)
            alpha_bbox = glyph.getchannel("A").getbbox()
            if alpha_bbox:
                glyph = glyph.crop(alpha_bbox)

        margin = max(1, int(round(cell_size * 0.08)))
        cell_left = int(round(center_x - cell_size / 2))
        cell_top = int(round(center_y - cell_size / 2))
        cell_right = cell_left + cell_size
        cell_bottom = cell_top + cell_size

        if char in UPPER_RIGHT_PUNCTUATION:
            paste_x = cell_right - margin - glyph.width
            paste_y = cell_top + margin
        elif char in OPENING_PUNCTUATION:
            paste_x = int(round(center_x - glyph.width / 2))
            paste_y = cell_top + margin
        elif char in CLOSING_PUNCTUATION:
            paste_x = int(round(center_x - glyph.width / 2))
            paste_y = cell_bottom - margin - glyph.height
        else:
            paste_x = int(round(center_x - glyph.width / 2))
            paste_y = int(round(center_y - glyph.height / 2))
        image.paste(glyph, (paste_x, paste_y), glyph)

    def _horizontal_runs(self, text, font_style, font_size):
        runs = []
        for char in text:
            font = self._get_font_for_char(font_style, font_size, char)
            if runs and runs[-1][0] is font:
                runs[-1] = (font, runs[-1][1] + char)
            else:
                runs.append((font, char))
        return runs

    def _draw_horizontal_row(
        self,
        draw,
        text,
        font_style,
        font_size,
        center_x,
        center_y,
        stroke_width,
    ):
        runs = self._horizontal_runs(text, font_style, font_size)
        if not runs:
            return
        widths = [self._font_advance(font, run_text) for font, run_text in runs]
        total_width = sum(widths)
        top = float("inf")
        bottom = float("-inf")
        for font, run_text in runs:
            try:
                bbox = draw.textbbox(
                    (0, 0),
                    run_text,
                    font=font,
                    anchor="ls",
                    stroke_width=stroke_width,
                )
            except ValueError:
                bbox = draw.textbbox(
                    (0, 0), run_text, font=font, stroke_width=stroke_width
                )
            top = min(top, bbox[1])
            bottom = max(bottom, bbox[3])
        baseline_y = center_y - (top + bottom) / 2
        current_x = center_x - total_width / 2
        for (font, run_text), width in zip(runs, widths):
            try:
                draw.text(
                    (current_x, baseline_y),
                    run_text,
                    font=font,
                    fill=self.color,
                    anchor="ls",
                    stroke_width=stroke_width,
                    stroke_fill="white",
                )
            except ValueError:
                bbox = draw.textbbox(
                    (0, 0), run_text, font=font, stroke_width=stroke_width
                )
                draw.text(
                    (current_x - bbox[0], center_y - (bbox[1] + bbox[3]) / 2),
                    run_text,
                    font=font,
                    fill=self.color,
                    stroke_width=stroke_width,
                    stroke_fill="white",
                )
            current_x += width

    def wrap_text_horizontal(self, text, max_width, font):
        """【新增】根据宽度自动分行（横排模式）"""
        text = normalize_cjk_punctuation(text)
        lines = []
        current_line = ""
        # 简单的溢出容忍系数
        sample_w = self._font_advance(font, "国")
        overflow_tolerance = sample_w * 0.8

        for i, char in enumerate(text):
            proposed = current_line + char
            proposed_width = self._font_advance(font, proposed)

            # 核心逻辑：当前行宽 + 新字宽 > 最大宽度
            if current_line and proposed_width > max_width:
                # 容忍逻辑：如果是最后一个字，且超出不多，不换行
                is_last_char = (i == len(text) - 1)
                if is_last_char and proposed_width <= max_width + overflow_tolerance:
                    current_line += char
                    break

                lines.append(current_line)
                current_line = char
            else:
                current_line = proposed

        if current_line:
            lines.append(current_line)
        return lines

    def wrap_text_vertical(self, text, max_height, font):
        cell_size = self._vertical_cell_size(font)
        char_spacing = self._vertical_char_spacing(font)
        max_cells = max(1, int((max_height + char_spacing) // (cell_size + char_spacing)))
        return wrap_vertical_text(text, max_cells)

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
            self.last_layout_debug = []
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

            clean_text = normalize_cjk_punctuation(text.replace('\n', ''))
            font_style = self._style_for_text(style, clean_text)
            current_font = self.fonts.get(font_style, self.fonts.get('dialogue'))

            # 简单的字号预处理
            if box_width < self.base_font_size * 2:
                try:
                    new_size = max(12, int(box_width // 2))
                    current_font = self._get_font_object(font_style, new_size)
                except:
                    pass

            preferred_size = None
            if target_font_size and target_font_size > 0:
                if style == "next_preview":
                    pref_ratio = 0.95
                elif style in ("narration", "serious", "thought", "whisper"):
                    pref_ratio = 0.95 if len(clean_text) > 14 else 1.0
                elif direction == 1:
                    pref_ratio = 1.0
                else:
                    pref_ratio = 0.8 if len(clean_text) > 14 else 0.95
                preferred_size = max(10, int(target_font_size * pref_ratio))
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
                is_horizontal = True
            else:
                is_horizontal = box_width > box_height * 1.35
            self.last_direction = "horizontal" if is_horizontal else "vertical"

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
                if style in ("next_preview", "title"):
                    size_cap = int(min(box_width, box_height) * 0.7)
                    estimate_multiplier = 1.3
                    lower_bound = 14
                elif style in ("narration", "serious", "thought", "whisper"):
                    size_cap = int(min(box_width, box_height) * 0.8)
                    if len(clean_text) > 14:
                        size_cap = min(size_cap, int(min(box_width, box_height) * 0.7))
                    estimate_multiplier = 1.4
                    lower_bound = 14
                elif style in ("radiating", "handwriting", "bold_dialogue", "sfx", "cute"):
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
                    if style in ("next_preview", "narration", "title", "sfx"):
                        size_cap = min(size_cap, int(min(box_width, box_height) * 0.6))
                    else:
                        size_cap = min(size_cap, int(min(box_width, box_height) * 0.35))
                pref_cap = None
                if preferred_size:
                    lower_bound = min(lower_bound, max(10, preferred_size))
                    if non_bubble and style in ("next_preview", "narration", "title", "sfx"):
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

                font = self._get_font_object(font_style, mid)

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
                current_font = self._get_font_object(font_style, 12)
                _, _, best_lines_struct, best_col_spacing = self._calculate_layout_fast(
                    clean_text, current_font, constraint_limit, is_horizontal=is_horizontal
                )
            self.last_font_size = best_size
            columns = best_lines_struct
            if not columns:
                return image
            stroke_width = self._stroke_width(style, best_size, non_bubble=non_bubble)
            text_surface, draw, render_left, render_top, render_scale = (
                self._make_render_surface(
                    image,
                    center_x + GLOBAL_OFFSET_X,
                    center_y + GLOBAL_OFFSET_Y,
                    box_width,
                    box_height,
                    best_size,
                    stroke_width,
                )
            )
            scaled_font_size = best_size * render_scale
            scaled_stroke_width = stroke_width * render_scale

            if is_horizontal:
                row_height = max(1, best_size)
                total_height = len(columns) * row_height + (len(columns) - 1) * best_col_spacing
                current_row_center_y = center_y - total_height / 2 + row_height / 2
                for row_text in columns:
                    self._draw_horizontal_row(
                        draw,
                        row_text,
                        font_style,
                        scaled_font_size,
                        (center_x + GLOBAL_OFFSET_X - render_left) * render_scale,
                        (
                            current_row_center_y
                            + GLOBAL_OFFSET_Y
                            - render_top
                        )
                        * render_scale,
                        scaled_stroke_width,
                    )
                    current_row_center_y += row_height + best_col_spacing

            else:
                cell_size = self._vertical_cell_size(current_font)
                char_spacing = self._vertical_char_spacing(current_font)
                total_text_width = (
                    len(columns) * cell_size
                    + (len(columns) - 1) * best_col_spacing
                )
                current_col_center_x = (
                    center_x + total_text_width / 2 - cell_size / 2
                )
                for column_index, col_text in enumerate(columns):
                    col_height = (
                        len(col_text) * cell_size
                        + max(0, len(col_text) - 1) * char_spacing
                    )
                    current_y = center_y - col_height / 2

                    row_index = 0
                    while row_index < len(col_text):
                        char = col_text[row_index]
                        dash_run = 1
                        if char in VERTICAL_DASH_CHARS:
                            while (
                                row_index + dash_run < len(col_text)
                                and col_text[row_index + dash_run] == char
                            ):
                                dash_run += 1

                        if dash_run >= 2:
                            cell_center_x = current_col_center_x + GLOBAL_OFFSET_X
                            for dash_index in range(dash_run):
                                cell_center_y = (
                                    current_y
                                    + dash_index * (cell_size + char_spacing)
                                    + cell_size / 2
                                    + GLOBAL_OFFSET_Y
                                )
                                self.last_layout_debug.append(
                                    {
                                        "char": char,
                                        "center_x": float(cell_center_x),
                                        "center_y": float(cell_center_y),
                                        "cell_size": int(cell_size),
                                        "column": column_index,
                                        "row": row_index + dash_index,
                                    }
                                )

                            dash_margin = cell_size * 0.12
                            dash_span = (
                                dash_run * cell_size
                                + (dash_run - 1) * char_spacing
                            )
                            dash_x = (
                                cell_center_x - render_left
                            ) * render_scale
                            dash_top = (
                                current_y
                                + GLOBAL_OFFSET_Y
                                + dash_margin
                                - render_top
                            ) * render_scale
                            dash_bottom = (
                                current_y
                                + GLOBAL_OFFSET_Y
                                + dash_span
                                - dash_margin
                                - render_top
                            ) * render_scale
                            dash_width = max(
                                1,
                                int(round(best_size * 0.07 * render_scale)),
                            )
                            draw.line(
                                [(dash_x, dash_top), (dash_x, dash_bottom)],
                                fill=self.color,
                                width=dash_width,
                            )
                            current_y += dash_run * (cell_size + char_spacing)
                            row_index += dash_run
                            continue

                        cell_center_x = current_col_center_x + GLOBAL_OFFSET_X
                        cell_center_y = current_y + cell_size / 2 + GLOBAL_OFFSET_Y
                        self.last_layout_debug.append(
                            {
                                "char": char,
                                "center_x": float(cell_center_x),
                                "center_y": float(cell_center_y),
                                "cell_size": int(cell_size),
                                "column": column_index,
                                "row": row_index,
                            }
                        )
                        self._draw_vertical_cell(
                            text_surface,
                            draw,
                            char=char,
                            font_style=font_style,
                            font_size=scaled_font_size,
                            center_x=(cell_center_x - render_left) * render_scale,
                            center_y=(cell_center_y - render_top) * render_scale,
                            cell_size=cell_size * render_scale,
                            stroke_width=scaled_stroke_width,
                        )
                        current_y += cell_size + char_spacing
                        row_index += 1

                    current_col_center_x -= cell_size + best_col_spacing

            self._composite_render_surface(
                image,
                text_surface,
                render_left,
                render_top,
                render_scale,
            )

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
