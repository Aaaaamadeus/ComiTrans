import cv2
import numpy as np
import torch
from openai import OpenAI
import os
import base64
from ultralytics import YOLO
from manga_ocr import MangaOcr
from paddleocr import PaddleOCR
from simple_lama_inpainting import SimpleLama
from PIL import Image, ImageDraw, ImageFont

# 模块 1: 竖排嵌字器 (Vertical Typesetter)
class VerticalTypesetter:
    def __init__(self, font_path, font_size, color=(0, 0, 0)):
        self.font_path = font_path
        self.base_font_size = font_size
        self.color = color
        
        # 字体加载容错处理
        if os.path.exists(font_path):
            try:
                self.font = ImageFont.truetype(font_path, font_size)
            except Exception as e:
                print(f"字体文件损坏，回退默认: {e}")
                self.font = ImageFont.load_default()
        else:
            print(f"未找到字体文件: {font_path}，将无法显示中文/日文。请在代码中修改 font_path。")
            self.font = ImageFont.load_default()

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

    def draw_text(self, image, box, text):
        """执行竖排绘制"""
        x1, y1, x2, y2 = map(int, box) # 确保坐标是整数
        box_width = x2 - x1
        box_height = y2 - y1
        
        # 简单的字号自适应：如果框特别小，稍微缩小字体
        # 实际生产中可能需要更复杂的二分法查找最佳字号
        current_font = self.font
        if box_width < self.base_font_size * 2:
            try:
                new_size = max(12, box_width // 2)
                current_font = ImageFont.truetype(self.font_path, new_size)
            except:
                pass

        # 1. 文本清洗与分列
        clean_text = text.replace('\n', '') # 去除OCR带来的换行符
        columns = self.wrap_text_vertical(clean_text, box_height, current_font)
        
        if not columns:
            return image

        # 2. 计算整体布局 (用于水平居中)
        char_w_sample, _ = self._get_char_size("国", current_font)
        col_spacing = 5
        total_text_width = len(columns) * char_w_sample + (len(columns) - 1) * col_spacing
        
        # 3. 计算起始 X (居中逻辑)
        center_x = x1 + box_width // 2
        # 竖排是从右向左，起始点是最右侧那一列的左边
        start_x = center_x + total_text_width // 2 - char_w_sample
        
        draw = ImageDraw.Draw(image)
        current_x = start_x
        
        # 4. 逐列绘制
        for col_text in columns:
            # 计算该列总高 (用于垂直居中)
            col_height = 0
            for char in col_text:
                _, h = self._get_char_size(char, current_font)
                col_height += h
            col_height += (len(col_text) - 1) * 2 # 字间距
            
            start_y = y1 + (box_height - col_height) // 2
            current_y = start_y
            
            for char in col_text:
                w, h = self._get_char_size(char, current_font)
                
                if self._is_punctuation_to_rotate(char):
                    # 标点旋转处理
                    temp_size = max(w, h) * 2
                    # 使用 RGBA 创建透明画布
                    txt_img = Image.new('RGBA', (temp_size, temp_size), (255, 255, 255, 0))
                    d = ImageDraw.Draw(txt_img)
                    d.text(((temp_size-w)/2, (temp_size-h)/2), char, font=current_font, fill=self.color)
                    rotated_txt = txt_img.rotate(-90, expand=False, resample=Image.BICUBIC)
                    
                    paste_x = int(current_x + (char_w_sample - temp_size) / 2)
                    paste_y = int(current_y + (h - temp_size) / 2)
                    
                    # 使用 alpha_composite 或 paste(mask=) 进行透明混合
                    image.paste(rotated_txt, (paste_x, paste_y), rotated_txt)
                else:
                    # 普通文字
                    offset_x = (char_w_sample - w) // 2
                    draw.text((current_x + offset_x, current_y), char, font=current_font, fill=self.color)
                
                current_y += h + 2 # 字间距
            
            current_x -= (char_w_sample + col_spacing) # 向左移动
            
        return image

# 模块 2: 漫画处理管线 (Comic Pipeline)
class ComicTranslatorPipeline:
    def __init__(self, 
                 det_model_path,
                 font_path, #这里必须指定你的字体文件路径
                 font_size,
                 use_gpu):
        self.device = 'cuda' if torch.cuda.is_available() and use_gpu else 'cpu'
        print("初始化管线")

        # 1. 气泡检测
        print("加载 YOLOv8 检测模型...")
        self.detector = YOLO(det_model_path)

        # 2. OCR 模型
        print("加载 Manga-OCR...")
        self.manga_ocr = MangaOcr()
        #删除了show_log=False
        print("加载 PaddleOCR...")
        self.paddle_ocr = PaddleOCR(use_angle_cls=True, lang="ch")

        # 3. 图像修补
        print("加载 LaMa Inpainting...")
        self.inpainter = SimpleLama()
        
        # 4. 嵌字器
        print("初始化嵌字器")
        self.typesetter = VerticalTypesetter(font_path, font_size)

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
            result = self.paddle_ocr.ocr(crop_img, cls=True)
            if result and result[0]:
                return "".join([line[1][0] for line in result[0]])
        return ""

    def inpaint_bubbles(self, img_path, boxes):
        """LaMa 去除气泡文字 (生成底图)"""
        print("正在执行图像修补...")
        # 读取为 RGB PIL 用于 LaMa
        img_pil = Image.open(img_path).convert("RGB")
        w, h = img_pil.size
        
        # 创建 Mask (numpy 格式 L 模式)
        mask_np = np.zeros((h, w), dtype=np.uint8)
        
        # 适当缩小 mask 范围，只涂抹中间，避免把气泡边框也擦了
        # 这里为了演示，简单涂抹整个检测框
        padding = 0 
        for (x1, y1, x2, y2) in boxes:
            cv2.rectangle(mask_np, (x1+padding, y1+padding), (x2-padding, y2-padding), 255, -1)

        mask_pil = Image.fromarray(mask_np)
        
        # SimpleLama 输入 PIL，返回 PIL
        clean_img_pil = self.inpainter(img_pil, mask_pil)
        return clean_img_pil

    def translate_with_image(self, text,image_path):
        """翻译接口"""
        #改为中转模式
        BASE_URL = "https://中转服务商/v1"
        API_KEY = "Your_API_Key"
        if not text.strip(): return ""
        client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL
        )
        # 构造Prompt：
        system_prompt = """
        你是一位专业的日漫汉化组翻译，结合文字
        请将用户的日文文本翻译成地道、流畅的中文。
        要求：
        1. 保持二次元口语风格，不要翻译腔
        2. 如果遇到拟声词，请根据语境意译或保留
        3. 直接输出翻译后的内容，不要加引号，不要带任何解释
        """

        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            response = client.chat.completions.create(
                model="gemini-1.5-flash-latest",
                messages=[
                    {"role": "system","content": f"{system_prompt}"},
                    {"role": "user",
                        "content": [
                            {"type": "text", "text": f"原文OCR参考：{text}"},
                            {"type": "image_url","image_url":
                                {"url": f"data:image/jpeg;base64,{base64_image}"}
                             }
                        ]
                    }
                ]
            )
            return response.choices[0].message.content.strip()
        except Exception as a:
            print(f"翻译出错{a}")
            exit()
        return f"{text}"

    def process_comic_page(self, input_path, output_path):
        # 1. 读取原始图像 (OpenCV 格式用于裁剪 OCR)
        img_cv = cv2.imread(input_path)
        if img_cv is None:
            raise FileNotFoundError(f"无法读取文件: {input_path}")

        # 2. 检测
        boxes = self.detect_bubbles(input_path)
        print(f"检测到 {len(boxes)} 个气泡")

        # 3. OCR 与 翻译 (并行处理数据)
        processed_data = []
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = map(int, box)
            crop_img = img_cv[y1:y2, x1:x2]
            # 先用 manga-ocr，如果太短或失败则用 paddle
            raw_text = self.run_ocr(img_cv, box, method='manga-ocr')
            if len(raw_text) < 2:
                raw_text = self.run_ocr(img_cv, box, method='paddle')
            temp_bubble_path = "temp_bubble.jpg"
            cv2.imwrite(temp_bubble_path, crop_img)
            trans_text = self.translate_with_image(raw_text, image_path=temp_bubble_path)
            
            processed_data.append({
                "box": box,
                "raw": raw_text,
                "trans": trans_text
            })
            print(f"   [{i}] 原文: {raw_text} -> 译文: {trans_text}")

        # 4. 图像修补 (获得干净的 PIL 画布)
        # 这一步会去除原有文字，生成适合嵌字的底图
        final_canvas = self.inpaint_bubbles(input_path, boxes)

        # 5. 嵌字 (Typesetting)
        print("正在进行竖排嵌字...")
        for item in processed_data:
            if item['trans']:
                # 在干净的画布上绘制
                final_canvas = self.typesetter.draw_text(
                    final_canvas, 
                    item['box'], 
                    item['trans']
                )

        # 6. 保存
        final_canvas.save(output_path)
        print(f"处理完成！已保存至: {output_path}")


# 主程序入口
if __name__ == "__main__":
    # 配置区：请修改为你本地的路径
    # 准备一张测试图片
    TEST_IMAGE = "test_page.jpg" 
    # 准备中文字体
    FONT_PATH = "./font.ttf"  
    
    # 检查文件是否存在
    if not os.path.exists(TEST_IMAGE):
        print(f"找不到测试图片 {TEST_IMAGE}，请先准备一张图片。")
    else:
        try:
            # 初始化管线
            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            pipeline = ComicTranslatorPipeline(
                det_model_path= os.path.join(BASE_DIR, 'models','ogkalucomic-speech-bubble-detector-yolov8m', 'comic-speech-bubble-detector.pt'),
                font_path=FONT_PATH,
                font_size=20,  # 基础字号
                use_gpu=True   # 是否使用 GPU
            )
            
            # 运行处理
            pipeline.process_comic_page(TEST_IMAGE, "final_translated_page.jpg")
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"运行过程中发生错误: {e}")
