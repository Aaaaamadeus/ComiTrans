import os
import math
import time
import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from dotenv import load_dotenv
load_dotenv()
import cv2
import numpy as np
import torch
import torch.nn as nn
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI
from ultralytics import YOLO
from manga_ocr import MangaOcr
from paddleocr import PaddleOCR
from simple_lama_inpainting import SimpleLama
from paddle.dataset.movielens import user_info
from torchvision import models, transforms

#使用多核单线程时使用
#pipeline = None
#from functools import partial
class FontPredictor:
    def __init__(self, model_path, device='cuda'):
        self.device = torch.device(device if torch.cuda.is_available() else 'cpu')
        # 对应训练代码中的 label_map
        self.class_names = ["radiating", "dialogue", "handwriting","serious"]

        # 重建模型结构 (MobileNetV2 Small)
        self.model = models.mobilenet_v2(weights=None)
        # 修改全连接层以匹配 3 个分类
        in_features = self.model.classifier[1].in_features
        self.model.classifier[1] = nn.Linear(in_features, 4)

        try:
            state_dict = torch.load(model_path, map_location=self.device)
            self.model.load_state_dict(state_dict)
        except Exception as e:
            print(f"字体模型加载失败: {e}")
            import traceback
            traceback.print_exc()

        self.model.to(self.device).eval()

        # 预处理
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

    def predict(self, img_bgr):
        try:
            # OpenCV BGR -> PIL RGB
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            img_tensor = self.transform(pil_img).unsqueeze(0).to(self.device)

            with torch.no_grad():
                outputs = self.model(img_tensor)
                _, preds = torch.max(outputs, 1)
            return self.class_names[preds.item()]
        except:
            return "dialogue"  # 出错默认回退
# 模块 1: 竖排嵌字器 (Vertical Typesetter)
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
        # 字体加载容错处理
        # if os.path.exists(font_path):
        #     try:
        #         self.font = ImageFont.truetype(font_path, font_size)
        #     except Exception as e:
        #         print(f"字体文件损坏，回退默认: {e}")
        #         self.font = ImageFont.load_default()
        # else:
        #     print(f"未找到字体文件: {font_path}，将无法显示中文/日文。请在代码中修改 font_path。")
        #     self.font = ImageFont.load_default()

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

    def draw_text(self, image, box, text, style='dialogue',mask=None):
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
                _, _, best_lines_struct, best_col_spacing = self._calculate_layout_fast(clean_text, current_font,box_height)
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

                    # === [重点] 计算“字心”坐标 ===
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

# 模块 2: 漫画处理管线 (Comic Pipeline)
class ComicTranslatorPipeline:
    def __init__(self, 
                 det_model_path,
                 font_map, #这里必须指定你的字体文件路径
                 font_size,
                 cls_model_path,
                 use_gpu):
        self.device = 'cuda' if torch.cuda.is_available() and use_gpu else 'cpu'
        print("初始化管线")

        # 1. 气泡检测
        print("加载 YOLOv8 检测模型...")
        self.detector = YOLO(det_model_path)
        print("成功！")

        # 2. OCR 模型
        print("加载 Manga-OCR...")
        self.manga_ocr = MangaOcr()
        print("成功！")

        #删除了show_log=False
        print("加载 PaddleOCR...")
        self.paddle_ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        print("成功！")

        # 3. 图像修补
        print("加载 LaMa Inpainting...")
        self.inpainter = SimpleLama()
        print("成功！")
        
        # 4. 嵌字器
        print("初始化嵌字器")
        self.typesetter = VerticalTypesetter(font_map, font_size)
        print("成功！")

        # 5. 字体分类器
        print("初始化字体分类器器")
        self.font_classifier = FontPredictor(cls_model_path, device=self.device)
        self.typesetter = VerticalTypesetter(font_map, font_size)
        print("成功！")

        # 线程锁
        self.lock = threading.Lock()

    def detect_bubbles(self, image_path):
        """YOLOv8 检测"""
        print("检测气泡中")
        results = self.detector(image_path, device=self.device)
        bubbles = []
        for result in results:
            boxes = result.boxes.xyxy.cpu().numpy()
            for box in boxes:
                bubbles.append(tuple(map(int, box))) # 转换为整数元组
        return bubbles

    def run_ocr(self, img_array, box, method='manga-ocr'):
        """OCR 识别"""
        x1, y1, x2, y2 = box
        h, w, _ = img_array.shape
        # 边界保护
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        crop_img = img_array[y1:y2, x1:x2]
        if crop_img.size == 0: return ""

        if method == 'manga-ocr':
            # 必须转为 RGB PIL
            pil_crop = Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB))
            return self.manga_ocr(pil_crop)
        elif method == 'paddle':
            #ocr线程锁
            with self.lock:
                result = self.paddle_ocr.ocr(crop_img)
            if result and result[0]:
                return "".join([line[1][0] for line in result[0]])
        return ""

    def is_simple_bubble(self, roi_img):
        #判断是否存在气泡
        if roi_img is None or roi_img.size == 0:
            return False
        #转换成灰度
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        #计算均值和标准差
        mean,std = cv2.meanStdDev(gray)
        mean_val = mean[0][0]
        std_val = std[0][0]
        #阈值参数设置
        white = mean_val > 160 and std_val < 90
        print(f"亮度:{mean_val:.2f},标准差:{std_val:.2f}->{'白气泡' if white else '复杂背景'}")
        return white

    def inpaint_bubbles(self, img_path, boxes):
        """LaMa 去除气泡文字 (生成底图)"""
        print("正在执行图像修补...")
        #opencv格式
        img_cv = cv2.imread(img_path)
        h,w = img_cv.shape[:2]
        #记录ai需要修复的区域
        lama_mask = np.zeros((h, w), dtype=np.uint8)
        # 排版掩膜
        full_layout_mask = np.zeros((h, w), dtype=np.uint8)
        #用来判断是否存在需要模型的区域
        needs_ai_inpainting = False
        for (x1, y1, x2, y2) in boxes:
            paddle = 1
            safe_x1 = max(0, x1 - paddle)
            safe_y1 = max(0, y1 - paddle)
            safe_x2 = min(w, x2 + paddle)
            safe_y2 = min(h, y2 + paddle)
            if safe_x2 <= safe_x1 or safe_y2 <= safe_y1:
                continue
            #引用切片
            roi_img = img_cv[safe_y1:safe_y2, safe_x1:safe_x2]
            #生成掩膜，提取黑色文字
            gray_roi = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
            #二值化
            _, initial_mask = cv2.threshold(gray_roi, 200, 255, cv2.THRESH_BINARY_INV)
            #查找所有黑色连通块
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(initial_mask, connectivity=8)
            #创建mask只掩盖字
            text_mask = np.zeros_like(initial_mask)

            for i in range(1, num_labels):
                x, y, w_box, h_box, area = stats[i]
                #边界触碰检测
                is_touching_border = (x <= 1) or (y <= 1) or (x + w_box >= w - 1) or (y + h_box >= h - 1)
                if is_touching_border:
                    continue
                #筛选规则
                # 比较面积和长宽，基于 h/w
                # 如果一个块的面积超过了“当前切片”总面积的 50%
                if area > (h * w) * 0.5:
                    continue
                # 如果一个块的宽或高占据了“当前切片”的 90% 以上
                if w_box > w * 0.9 or h_box > h * 0.9:
                    continue
                # 去除微小噪点
                if area < 5:
                     continue
                # 将通过筛选的画到mask上
                text_mask[labels == i] = 255

            #只对筛选后的文字进行膨胀
            kernel = np.ones((2, 2), np.uint8)
            text_mask_dilated = cv2.dilate(text_mask, kernel, iterations=1)

            layout_kernel = np.ones((5, 5), np.uint8)
            layout_mask_roi = cv2.dilate(text_mask, layout_kernel, iterations=3)
            full_layout_mask[safe_y1:safe_y2, safe_x1:safe_x2] = layout_mask_roi
            self.current_mask_image = Image.fromarray(full_layout_mask)

            #分流处理
            if self.is_simple_bubble(roi_img):
                #直接涂白
                roi_img[text_mask_dilated == 255] = [255,255,255]
            else:
                #调用模型处理
                needs_ai_inpainting = True
                lama_mask[safe_y1:safe_y2, safe_x1:safe_x2] = text_mask_dilated
        #将opencv格式转为PIL格式
        img_cv_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
        img_pil_final = Image.fromarray(img_cv_rgb)
        if needs_ai_inpainting:
            print("存在复杂背景，调用lama模型修复...")
            mask_pil = Image.fromarray(lama_mask)
            #lama接收
            img_pil_final = self.inpainter(img_pil_final, mask_pil)
        else:
            print("无复杂背景，已全部处理")
        return img_pil_final

    def translate_page_batch(self, ocr_texts, image_path):
        # 0. 边界检查：如果这页没字，直接返回空
        if not ocr_texts: return []

        # 1. 准备 API
        BASE_URL = "http://43.133.176.18:8000/v1"
        API_KEY = os.getenv("API_KEY")
        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

        # 2. 构造带序号的文本清单，方便 AI 对照
        text_list_str = "\n".join([f"[{i}] {text}" for i, text in enumerate(ocr_texts)])

        # 3. 构造 Prompt：强制要求返回纯 JSON 数组
        system_prompt = """
        你是一位专业的日漫汉化组翻译。
        请结合提供的【整页漫画图片】作为视觉上下文，将给出的【OCR日文列表】翻译成流畅的中文。

        【严格要求】：
        1. 必须返回一个纯 JSON 字符串数组，格式如：["翻译1", "翻译2", "翻译3"]
        2. 数组中的元素数量、顺序必须与输入的 OCR 文本列表完全一致。
        3. 如果某行 OCR 是乱码或无需翻译，请在对应位置填入空字符串 "" 或原样保留，不要跳过。
        4. 保持二次元口语风格，不要翻译腔，但是返回的语句需要符合中文的语序
        5. 不要使用 Markdown 格式（如 ```json），直接返回数组字符串。
        6. 最后一句句尾不要带句号
        7. 名字不要罗马音，特定名字使用其中文译名
        """

        user_prompt = f"请按顺序翻译以下 {len(ocr_texts)} 条日文文本：\n{text_list_str}"

        try:
            # 读取整页图片
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')

            response = client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",
                     "content": [
                         {"type": "text", "text": user_prompt},
                         {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                     ]
                     }
                ],
                # 如果模型支持 json_object 模式最好开启，不支持也没关系，prompt 已经约束了
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content.strip()

            # 4. 清洗与解析数据
            # 去除可能存在的 markdown 标记
            content = content.replace("```json", "").replace("```", "").strip()

            try:
                data = json.loads(content)
                # 兼容处理：有时候模型会返回 {"translations": [...]} 有时候直接返回 [...]
                if isinstance(data, list):
                    translations = data
                elif isinstance(data, dict):
                    # 尝试取字典里的第一个列表值
                    translations = list(data.values())[0] if data else []
                else:
                    translations = []

                # 5. 数量对齐检查
                # 如果 AI 返回的数量不对，程序后续会崩，所以必须在这里兜底
                if len(translations) != len(ocr_texts):
                    print(f"数量不匹配 (发:{len(ocr_texts)} vs 收:{len(translations)})，尝试自动补齐")
                    if len(translations) < len(ocr_texts):
                        # 少了就补空
                        translations.extend([ocr_texts[i] for i in range(len(translations), len(ocr_texts))])
                    else:
                        # 多了就截断
                        translations = translations[:len(ocr_texts)]

                return translations

            except json.JSONDecodeError:
                print(f"JSON解析失败: {content}")
                return ocr_texts  # 失败返回原文

        except Exception as e:
            print(f"PI请求出错: {e}")
            return ocr_texts

    def process_comic_page(self, input_path, output_path):
        t_name = threading.current_thread().name
        print(f"{t_name}开始")
        # 1. 读取原始图像 (OpenCV 格式用于裁剪 OCR)
        img_cv = cv2.imread(input_path)
        if img_cv is None:
            raise FileNotFoundError(f"无法读取文件: {input_path}")

        # 2. 检测
        boxes = self.detect_bubbles(input_path)
        print(f"{t_name}检测到 {len(boxes)} 个气泡")

        # 暂存数据
        bubble_metadata = []
        ocr_text_only = []

        # 3. OCR 与 翻译 (并行处理数据)
        processed_data = []
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = map(int, box)
            crop_img = img_cv[y1:y2, x1:x2]
            font_style = self.font_classifier.predict(crop_img)
            # 先用 manga-ocr，如果太短或失败则用 paddle
            raw_text = self.run_ocr(img_cv, box, method='manga-ocr')
            if len(raw_text) < 2:
                raw_text = self.run_ocr(img_cv, box, method='paddle')
            # thread_id = threading.get_ident()
            # temp_bubble_path = f"page/bubble_page/temp_bubble_{thread_id}.jpg"
            # cv2.imwrite(temp_bubble_path, crop_img)
            # trans_text = self.translate_with_image(raw_text, image_path=temp_bubble_path)
            # #清除临时文件
            # if os.path.exists(temp_bubble_path):
            #     os.remove(temp_bubble_path)
            # processed_data.append({
            #     "box": box,
            #     "raw": raw_text,
            #     "trans": trans_text
            # })
            # print(f"   [{i}] 原文: {raw_text} -> 译文: {trans_text}")
            bubble_metadata.append({
                "box": box,
                "raw": raw_text,
                "style": font_style
            })
            ocr_text_only.append(raw_text)

        # 批处理阶段
        print(f"{t_name} 正在批量翻译 {len(ocr_text_only)} 条文本...")
        # 调用新写的批量函数，传入整页路径 input_path
        translated_list = self.translate_page_batch(ocr_text_only, input_path)
        # 重组数据
        processed_data = []
        for i, item in enumerate(bubble_metadata):
            # 从翻译结果列表中取值
            trans_text = translated_list[i]

            processed_data.append({
                "box": item['box'],
                "raw": item['raw'],
                "style": item['style'],
                "trans": trans_text
            })
            print(f"   [{i}] 原文: {item['raw']} -> 译文: {trans_text}")

        # 4. 图像修补 (获得干净的 PIL 画布)
        # 这一步会去除原有文字，生成适合嵌字的底图
        final_canvas = self.inpaint_bubbles(input_path, boxes)

        # 5. 嵌字 (Typesetting)
        for item in processed_data:
            if item['trans']:
                try:
                    final_canvas = self.typesetter.draw_text(
                        final_canvas,
                        item['box'],
                        item['trans'],
                        mask=self.current_mask_image
                    )

                except Exception as e:
                    import traceback
                    print(f"无法执行 draw_text，原因: {e}")
                    traceback.print_exc()

        # 保存逻辑
        print("[DEBUG] 正在保存图片...")
        final_canvas.save(output_path)
        print(f"[DEBUG] 处理结束，保存至: {output_path}")
        # print("正在进行竖排嵌字...")
        # for item in processed_data:
        #     if item['trans']:
        #         # 在干净的画布上绘制
        #         final_canvas = self.typesetter.draw_text(
        #             final_canvas,
        #             item['box'],
        #             item['trans'],
        #             mask=self.current_mask_image
        #         )
        #
        # # 6. 保存
        # final_canvas.save(output_path)
        # print(f"处理完成！已保存至: {output_path}")

#使用多核单线程时使用
# def init_worker(base_dir, font_path):
#     global pipeline
#     pipeline = ComicTranslatorPipeline(
#         det_model_path=os.path.join(base_dir, 'models', 'ogkalucomic-speech-bubble-detector-yolov8m',
#                                     'comic-speech-bubble-detector.pt'),
#         font_path=font_path,
#         font_size=20,
#         use_gpu=False
#     )
# Linux专用模块(多核单线程)
# def init_pipeline_linux(base_dir, font_path):
#     global pipeline
#     pipeline = ComicTranslatorPipeline(
#         det_model_path=os.path.join(base_dir, 'models', 'ogkalucomic-speech-bubble-detector-yolov8m',
#                                     'comic-speech-bubble-detector.pt'),
#         font_path=font_path,
#         font_size=20,
#         use_gpu=False
#     )
def run_worker_thread(pipeline_instance, user_input, output_name):
    # 使用多核单线程时使用
    #global pipeline
    global_pipeline.process_comic_page(user_input, f"page/test_page_output/{output_name}")
    return f"处理完成: {user_input}"

# 主程序入口
if __name__ == "__main__":
    # 字体
    FONT_MAP = {
        "dialogue": "./font_file/CN/SourceHanSerifCN-Regular-1.otf",# 1.  正常对话 (宋体)
        "radiating": "./font_file/CN/SourceHanSansSC-Heavy-2.otf",  # 0.  喊叫/冲击 (黑体)
        "handwriting": "./font_file/CN/setofont.ttf",               # 2.  心理/手写 (娃娃体)
        "serious": "./font_file/CN/SourceHanSansSC-Medium-2.otf"    # 3 . 严肃
    }

    try:
        # 初始化管线
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        # 使用多核单线程时使用
        # if os.name == 'posix':
        #     init_pipeline_linux(BASE_DIR, FONT_PATH)
        #     worker_init_fn = None
        # else:
        #     worker_init_fn = partial(init_worker, BASE_DIR, FONT_PATH)
        #max_processes = max(1, (os.cpu_count() or 4) - 1)
        det_path = os.path.join(BASE_DIR, 'models', 'ogkalucomic-speech-bubble-detector-yolov8m','comic-speech-bubble-detector.pt')
        cls_model = os.path.join(BASE_DIR,'models', 'manga-font-mobilnet', 'manga_font_mobilnet.pth')
        print("正在加载模型...")
        global_pipeline = ComicTranslatorPipeline(
            det_model_path=det_path,
            font_map=FONT_MAP,
            font_size=16,
            cls_model_path=cls_model,
            use_gpu=True
        )
        # 预热 YOLO 模型
        # 进行一次空跑
        dummy_img = np.zeros((640, 640, 3), dtype=np.uint8)
        # 调用检测器跑一次
        global_pipeline.detector(dummy_img, verbose=False)
        max_workers =  1 #int(input("请输入加载图数"))
        print(f"最大并发数: {max_workers}")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            print("等待任务...")
            #if input("按任意键继续") == "^*":
            #    start1 = time.time()
            for i in [9]: #range(1,max_workers+1):
                the_page = f"page/test_page/test{i}.jpg"
                TEST_IMAGE = the_page
                user_input = TEST_IMAGE
                if not os.path.exists(user_input):
                    print(f"test{i}.jpg文件不存在，请检查路径")
                    continue
                # 提交任务
                if os.path.exists(user_input):
                    output_name = f"translated_{os.path.basename(user_input)}"
                    executor.submit(run_worker_thread,global_pipeline,user_input, output_name)

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"运行过程中发生错误: {e}")
