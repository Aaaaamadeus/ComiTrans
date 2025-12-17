import os
import time
import base64
from functools import partial
from concurrent.futures import ProcessPoolExecutor
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from dotenv import load_dotenv
load_dotenv()
import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI
from ultralytics import YOLO
from manga_ocr import MangaOcr
from paddleocr import PaddleOCR
from simple_lama_inpainting import SimpleLama
from paddle.dataset.movielens import user_info
pipeline = None

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
        self.typesetter = VerticalTypesetter(font_path, font_size)
        print("成功！")

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
            result = self.paddle_ocr.ocr(crop_img)
            if result and result[0]:
                return "".join([line[1][0] for line in result[0]])
        return ""

    #气泡背景判断函数，决定是否调用lama模型进行背景填充
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
        #用来判断是否存在需要模型的区域
        needs_ai_inpainting = False
        for (x1, y1, x2, y2) in boxes:
            paddle = 2
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

    def translate_with_image(self, text,image_path):
        """翻译接口"""
        #改为中转模式
        BASE_URL = "https://api.ohmygpt.com/v1"
        API_KEY = os.getenv("API_KEY")
        if not text.strip(): return ""
        client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL
        )
        # 构造Prompt：
        system_prompt = """
        你是一位专业的日漫汉化组翻译，结合文字
        请将用户的日文文本翻译成地流畅的中文。
        要求：
        1. 保持二次元口语风格，不要过度本土化！保持日漫汉化的习惯！不要翻译腔
        2. 如果遇到拟声词，请根据语境意译或保留
        3. 直接输出翻译后的内容，不要加引号，不要带任何解释，不要最后一句末尾的句号
        4. 姓名输出不要为罗马音
        """

        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            response = client.chat.completions.create(
                model="gemini-2.5-flash",
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


def init_worker(base_dir, font_path):
    global pipeline
    pipeline = ComicTranslatorPipeline(
        det_model_path=os.path.join(base_dir, 'models', 'ogkalucomic-speech-bubble-detector-yolov8m',
                                    'comic-speech-bubble-detector.pt'),
        font_path=font_path,
        font_size=20,
        use_gpu=False
    )
# Linux专用模块
def init_pipeline_linux(base_dir, font_path):
    global pipeline
    pipeline = ComicTranslatorPipeline(
        det_model_path=os.path.join(base_dir, 'models', 'ogkalucomic-speech-bubble-detector-yolov8m',
                                    'comic-speech-bubble-detector.pt'),
        font_path=font_path,
        font_size=20,
        use_gpu=False
    )
def run_worker(user_input, output_name):
    global pipeline
    pipeline.process_comic_page(user_input, output_name)
    return f"处理完成: {user_input}"

# 主程序入口
if __name__ == "__main__":
    # 字体
    FONT_PATH = "./font_file/font.ttf"
    try:
        # 初始化管线
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        if os.name == 'posix':
            init_pipeline_linux(BASE_DIR, FONT_PATH)
            worker_init_fn = None
        else:
            worker_init_fn = partial(init_worker, BASE_DIR, FONT_PATH)

#       max_processes = max(1, (os.cpu_count() or 4) - 1)
        max_processes = max(1,2)
        print(f"最大并发数: {max_processes}")
        with ProcessPoolExecutor(max_workers=max_processes,initializer=worker_init_fn) as executor:
            print("输入图片路径，按Enter开始处理。输入'exit'退出。")
            while True:
                TEST_IMAGE = input("请输入测试图片路径")
                user_input = TEST_IMAGE
                if user_input.strip().lower() == 'exit':
                    print("正在等待所有后台进程结束...")
                    break
                if not user_input.strip():
                    continue
                if not os.path.exists(user_input):
                    print("文件不存在，请检查路径")
                    continue
                # 提交任务
                base_name = os.path.basename(user_input)
                output_name = f"translated_{base_name}"
                executor.submit(run_worker, user_input, output_name)

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"运行过程中发生错误: {e}")
