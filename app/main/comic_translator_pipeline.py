import os
import base64
import json
import threading
import cv2
import numpy as np
import torch
from PIL import Image
from openai import OpenAI
from ultralytics import YOLO
from manga_ocr import MangaOcr
from loguru import logger
from manga_lama import MangaLama
from font_predictor import FontPredictor
from vertical_typesetter import VerticalTypesetter

class ComicTranslatorPipeline:
    def __init__(self,
                 det_model_path,
                 font_map,  # 这里必须指定你的字体文件路径
                 font_size,
                 cls_model_path,
                 use_gpu,
                 lama_path):
        self.device = 'cuda' if torch.cuda.is_available() and use_gpu else 'cpu'
        print("初始化管线")

        # 1. 气泡检测
        print("加载 YOLOv8 检测模型...")
        self.detector = YOLO(det_model_path)

        # 2. OCR 模型
        print("加载 Manga-OCR...")
        logger.disable("manga_ocr")
        self.manga_ocr = MangaOcr()

        # 3. 图像修补
        print("加载 Manga-lama...")
        self.inpainter = MangaLama(lama_path, device=self.device)

        # 4. 嵌字器
        print("初始化嵌字器")
        self.typesetter = VerticalTypesetter(font_map, font_size)

        # 5. 字体分类器
        print("初始化字体分类器")
        self.font_classifier = FontPredictor(cls_model_path, device=self.device)
        self.typesetter = VerticalTypesetter(font_map, font_size)

        # 线程锁
        self.lock = threading.Lock()

    def detect_bubbles(self, image_path):
        """YOLOv8 检测"""
        print(f"检测气泡中")
        results = self.detector(image_path, device=self.device)
        bubbles = []
        for result in results:
            boxes = result.boxes.xyxy.cpu().numpy()
            for box in boxes:
                bubbles.append(tuple(map(int, box)))  # 转换为整数元组
        return bubbles

    def run_ocr(self, img_array, box, method):
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
        # elif method == 'paddle':
        #     #ocr线程锁
        #     with self.lock:
        #         result = self.paddle_ocr.ocr(crop_img)
        #     if result and result[0]:
        #         return "".join([line[1][0] for line in result[0]])
        return ""

    def is_simple_bubble(self, roi_img):
        # 判断是否存在气泡
        if roi_img is None or roi_img.size == 0:
            return False
        # 转换成灰度
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        # 计算均值和标准差
        mean, std = cv2.meanStdDev(gray)
        mean_val = mean[0][0]
        std_val = std[0][0]
        # 阈值参数设置
        white = mean_val > 160 and std_val < 90
        print(f"亮度:{mean_val:.2f},标准差:{std_val:.2f}->{'白气泡' if white else '复杂背景'}")
        return white

    def inpaint_bubbles(self, img_path, boxes):
        """LaMa 去除气泡文字 (生成底图)"""
        print(f"正在执行图像修补...")
        # opencv格式
        img_cv = cv2.imread(img_path)
        h, w = img_cv.shape[:2]
        # 记录ai需要修复的区域
        lama_mask = np.zeros((h, w), dtype=np.uint8)
        # 排版掩膜
        full_layout_mask = np.zeros((h, w), dtype=np.uint8)
        # 用来判断是否存在需要模型的区域
        needs_ai_inpainting = False
        for (x1, y1, x2, y2) in boxes:
            paddle = 2
            safe_x1 = max(0, x1 - paddle)
            safe_y1 = max(0, y1 - paddle)
            safe_x2 = min(w, x2 + paddle)
            safe_y2 = min(h, y2 + paddle)
            if safe_x2 <= safe_x1 or safe_y2 <= safe_y1:
                continue
            # 引用切片
            roi_img = img_cv[safe_y1:safe_y2, safe_x1:safe_x2]
            # 生成掩膜，提取黑色文字
            gray_roi = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
            # 二值化
            _, initial_mask = cv2.threshold(gray_roi, 235, 255, cv2.THRESH_BINARY_INV)
            # 查找所有黑色连通块
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(initial_mask, connectivity=8)
            # 创建mask只掩盖字
            text_mask = np.zeros_like(initial_mask)

            for i in range(1, num_labels):
                x, y, w_box, h_box, area = stats[i]
                # 边界触碰检测
                is_touching_border = (x <= 1) or (y <= 1) or (x + w_box >= w - 1) or (y + h_box >= h - 1)
                if is_touching_border:
                    continue
                # 筛选规则
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

            # 只对筛选后的文字进行膨胀
            kernel = np.ones((2, 2), np.uint8)
            text_mask_dilated = cv2.dilate(text_mask, kernel, iterations=1)

            layout_kernel = np.ones((5, 5), np.uint8)
            layout_mask_roi = cv2.dilate(text_mask, layout_kernel, iterations=3)
            full_layout_mask[safe_y1:safe_y2, safe_x1:safe_x2] = layout_mask_roi
            self.current_mask_image = Image.fromarray(full_layout_mask)

            # 分流处理
            if self.is_simple_bubble(roi_img):
                # 直接涂白
                roi_img[text_mask_dilated == 255] = [255, 255, 255]
            else:
                # 调用模型处理
                needs_ai_inpainting = True
                lama_mask[safe_y1:safe_y2, safe_x1:safe_x2] = text_mask_dilated
        # 将opencv格式转为PIL格式
        img_cv_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
        img_pil_final = Image.fromarray(img_cv_rgb)
        if needs_ai_inpainting:
            print(f"存在复杂背景，调用lama模型修复...")
            mask_pil = Image.fromarray(lama_mask)
            # lama接收
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
        print(f"开始")
        # 1.读取原始图像 (OpenCV 格式用于裁剪 OCR)
        img_cv = cv2.imread(input_path)
        if img_cv is None:
            raise FileNotFoundError(f"无法读取文件: {input_path}")

        # 2.检测
        boxes = self.detect_bubbles(input_path)
        print(f"检测到{len(boxes)}个气泡")

        # 暂存数据
        bubble_metadata = []
        ocr_text_only = []

        # 3.OCR 与 翻译 (并行处理数据)
        processed_data = []
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = map(int, box)
            crop_img = img_cv[y1:y2, x1:x2]
            font_style = self.font_classifier.predict(crop_img)
            raw_text = self.run_ocr(img_cv, box, method='manga-ocr')

            bubble_metadata.append({
                "box": box,
                "raw": raw_text,
                "style": font_style
            })
            ocr_text_only.append(raw_text)

        # 批处理阶段
        print(f"正在批量翻译 {len(ocr_text_only)} 条文本...")
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
        # 6. 保存
        final_canvas.save(output_path)
        print(f"处理完成！已保存至: {output_path}")
