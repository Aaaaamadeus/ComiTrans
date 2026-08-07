import os
import base64
import sys
import json
import re
import threading
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from openai import OpenAI
from manga_lama import MangaLama
from vertical_typesetter import VerticalTypesetter
from onnx_manga_ocr import OnnxMangaOcr
from onnx_text_detector import OnnxTextDetector
current_dir = os.path.dirname(os.path.abspath(__file__))


class TaskCancelledError(Exception):
    pass


class TranslationError(Exception):
    pass


class ComicTranslatorPipeline:
    def __init__(self,
                 det_model_path,
                 font_map,  # 这里必须指定你的字体文件路径
                 font_size,
                 use_gpu,
                 lama_path,
                 translation_model=None,
                 api_key=None,
                 api_base_url=None,
                 translation_prompt=None,
                 chinese_names=None,
                 multimodal=False,
                 ocr_model_path=None,
                 progress_callback=None,
                 cancel_callback=None):
        self.device = 'cuda' if use_gpu else 'cpu'
        self.translation_model = translation_model
        self.api_key = api_key
        self.api_base_url = api_base_url
        self.translation_prompt = translation_prompt or ""
        self.chinese_names = chinese_names or ""
        self.multimodal = bool(multimodal)
        self.progress_callback = progress_callback
        self.cancel_callback = cancel_callback
        self.ocr_model_path = ocr_model_path or os.path.join(current_dir, "..", "models", "manga-ocr-onnx")
        if not self.translation_model:
             print("[WARNING] Pipeline 初始化时未指定翻译模型")
        print("初始化管线")

        print("[INFO] 加载 Comic Text Detector...")
        self.detector = OnnxTextDetector(model_path=det_model_path, input_size=1024, device=self.device)

        # 2. OCR 模型
        print("[INFO] 加载 Manga-OCR...")
        self.manga_ocr = OnnxMangaOcr(model_dir=self.ocr_model_path, device=self.device)

        # 3. 图像修补
        print("[INFO] 加载 Manga-lama...")
        self.inpainter = MangaLama(lama_path, device=self.device)

        # 4. 嵌字器
        print("初始化嵌字器")
        self.typesetter = VerticalTypesetter(font_map, font_size)

        # 线程锁
        self.lock = threading.Lock()

    def _report_progress(self, stage, message):
        if self.progress_callback:
            try:
                self.progress_callback(stage, message)
            except Exception:
                pass

    def _check_cancelled(self):
        if self.cancel_callback and self.cancel_callback():
            raise TaskCancelledError("任务已取消")

    @staticmethod
    def _looks_like_english_garbage(text: str) -> bool:
        if not text:
            return False
        latin = re.findall(r"[A-Za-z\uff21-\uff3a\uff41-\uff5a]", text)
        if not latin:
            return False
        chars = [c for c in text if not c.isspace()]
        return len(latin) / max(1, len(chars)) >= 0.4

    def detect_bubbles(self, img_cv):
        print("[INFO] 检测气泡中...")
        mask, mask_refined, text_lines = self.detector(img_cv)
        self.last_detector_mask = mask_refined

        bubbles = []
        for line in text_lines:
            # 1. 坐标提取：直接使用 xyxy
            # 根据列表，xyxy 已经包含了你需要的 [x1, y1, x2, y2]
            box = line.xyxy

            # 2. 类型提取：列表中没有 mask_type，我们使用 vertical (横排/竖排)
            # 如果后续逻辑必须叫 mask_type，我们在这里做一个转换
            # 通常 0 代表横排，1 代表竖排
            mask_type = 1 if getattr(line, 'vertical', False) else 0
            detected_font_size = int(getattr(line, 'font_size', -1) or -1)
            detected_label = int(getattr(line, 'label', 0))
            box_width = max(1, int(box[2] - box[0]))
            box_height = max(1, int(box[3] - box[1]))
            # ???????????????????? radiating
            if mask_type == 0 and box_width > box_height * 2.0:
                font_type = 'narration'
            else:
                font_type = 'radiating'
            # ?????????????????????????
            if detected_font_size > 0:
                size_limit = int(box_height * 0.9) if mask_type == 1 else int(box_height * 0.5)
                detected_font_size = max(10, min(detected_font_size, size_limit))

            # 3. 按照你需要的格式存入 (确保转换为整数防止 OpenCV 报错)
            bubbles.append((
                int(box[0]),
                int(box[1]),
                int(box[2]),
                int(box[3]),
                mask_type,
                font_type,
                detected_font_size,
                detected_label,
                getattr(line, 'language', 'unknown'),
            ))

        return bubbles

    def run_ocr(self, img_array, box, method):
        """OCR 识别"""
        x1, y1, x2, y2, *_ = box
        h, w, _ = img_array.shape
        # 边界保护
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        crop_img = img_array[y1:y2, x1:x2]
        if crop_img.size == 0: return ""
        if len(box) > 8 and box[8] == 'eng':
            return ""

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
        # 阈值参数设置（收紧：仅处理真正的纯白气泡，防止将网点纸直接涂白）
        white = mean_val > 230 and std_val < 20
        print(f"亮度:{mean_val:.2f},标准差:{std_val:.2f}->{'白气泡' if white else '复杂背景'}")
        return white

    def _is_simple_bubble_v2(self, roi_img, text_ratio=0.0):
        if roi_img is None or roi_img.size == 0:
            return False
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))
        white_ratio = float(np.mean(gray > 220))
        simple = mean_val > 200 and white_ratio >= 0.6
        print(
            f"亮度:{mean_val:.2f},标准差:{std_val:.2f},白像素占比:{white_ratio:.2f},文字占比:{text_ratio:.2f}"
            f"->{'白气泡' if simple else '复杂背景'}"
        )
        return simple

    def inpaint_bubbles(self, img_cv, boxes):
        """LaMa 去除气泡文字 (生成底图)"""
        print("[INFO] 正在执行图像修补...")
        # 移除了重复的 cv2.imread(img_path)
        h, w = img_cv.shape[:2]
        # 记录ai需要修复的区域
        lama_mask = np.zeros((h, w), dtype=np.uint8)
        # 排版掩膜
        full_layout_mask = np.zeros((h, w), dtype=np.uint8)
        # 用来判断是否存在需要模型的区域
        needs_ai_inpainting = False
        for data in boxes:
            x1, y1, x2, y2 = data[:4]
            if len(data) > 8 and data[8] == 'eng':
                continue
            paddle = 15  # 扩大上下文参考边缘，供 LaMa 获取足够纹理
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

            # 只对筛选后的文字进行膨胀，增强边缘包围，防止遗留抗锯齿的灰色鬼影
            text_mask_union = text_mask.copy()
            text_mask_precise = text_mask.copy()
            text_mask_erase = text_mask.copy()
            if hasattr(self, "last_detector_mask") and self.last_detector_mask is not None:
                detector_roi = self.last_detector_mask[safe_y1:safe_y2, safe_x1:safe_x2]
                if np.count_nonzero(detector_roi) > 0:
                    detector_bool = detector_roi > 0
                    text_mask_union = np.where(detector_bool | (text_mask > 0), 255, 0).astype(np.uint8)
                    text_mask_precise = np.where(detector_bool & (text_mask > 0), 255, 0).astype(np.uint8)
                    # ????????????????/????????????
                    text_mask_erase = np.where(detector_bool, 255, 0).astype(np.uint8)
                    if np.count_nonzero(text_mask_precise) == 0:
                        text_mask_precise = text_mask_union.copy()

            kernel = np.ones((3, 3), np.uint8)
            text_mask_precise_dilated = cv2.dilate(text_mask_precise, kernel, iterations=1)
            text_mask_union_dilated = cv2.dilate(text_mask_union, kernel, iterations=1)
            text_mask_erase_dilated = cv2.dilate(text_mask_erase, kernel, iterations=1)

            layout_kernel = np.ones((5, 5), np.uint8)
            layout_mask_roi = cv2.dilate(text_mask_union, layout_kernel, iterations=2)
            full_layout_mask[safe_y1:safe_y2, safe_x1:safe_x2] = layout_mask_roi

            # 分流处理
            box_x1, box_y1 = max(0, x1), max(0, y1)
            box_x2, box_y2 = min(w, x2), min(h, y2)
            box_roi = img_cv[box_y1:box_y2, box_x1:box_x2]
            offset_x = box_x1 - safe_x1
            offset_y = box_y1 - safe_y1
            inner_text = text_mask_precise_dilated[
                offset_y : offset_y + (box_y2 - box_y1),
                offset_x : offset_x + (box_x2 - box_x1),
            ]
            inner_erase = text_mask_erase_dilated[
                offset_y : offset_y + (box_y2 - box_y1),
                offset_x : offset_x + (box_x2 - box_x1),
            ]
            text_ratio = (
                float(np.count_nonzero(inner_text) / inner_text.size) if inner_text.size else 0.0
            )
            if self._is_simple_bubble_v2(box_roi, text_ratio):
                # 直接涂白
                roi_img[
                    offset_y : offset_y + (box_y2 - box_y1),
                    offset_x : offset_x + (box_x2 - box_x1),
                ][inner_erase == 255] = [255, 255, 255]
            else:
                # 调用模型处理
                needs_ai_inpainting = True
                lama_mask[safe_y1:safe_y2, safe_x1:safe_x2] = text_mask_erase_dilated
        
        # 循环结束后统一生成掩膜图像，避免重复转换
        self.current_mask_image = Image.fromarray(full_layout_mask)
        
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

    def translate_page_batch(self, ocr_texts, image_input):
        if not ocr_texts: return []

        # 使用初始化时传入的配置（来自 config.yaml）
        API_KEY = self.api_key or ""
        API_BASE_URL = self.api_base_url or ""
        
        if not API_KEY or not API_BASE_URL:
            print("[ERROR] 翻译 API 未正确配置。请在 config.yaml 中填写 api_key 和 api_base_url。")
            return None
        
        safe_key = f"{API_KEY[:4]}...{API_KEY[-4:]}" if len(API_KEY) > 8 else "***"
        print(f"[INFO] 使用翻译 API: {API_BASE_URL.split('?')[0]}")
        print(f"[INFO] API Key: {safe_key}")
        
        import urllib.request
        import httpx
        
        proxies = urllib.request.getproxies()
        proxy_url = proxies.get('http') or proxies.get('https')
        http_client = httpx.Client(proxy=proxy_url, timeout=90.0) if proxy_url else httpx.Client(timeout=90.0)

        client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL, http_client=http_client, max_retries=2)

        # 2. 构造带序号的文本清单，方便 AI 对照
        text_list_str = "\n".join([f"[{i}] {text}" for i, text in enumerate(ocr_texts)])

        # 3. 构造 Prompt
        system_prompt = """你是一位专业的日漫汉化组翻译。请结合提供的【整页漫画图片】作为视觉上下文，将给出的【OCR日文列表】翻译成流畅的中文。

【严格要求】：
1. 必须返回一个纯 JSON 字符串数组，格式如：["翻译1", "翻译2", "翻译3"]
2. 数组中的元素数量、顺序必须与输入的 OCR 文本列表完全一致。
3. 如果某行 OCR 是乱码、拟声词或无法翻译，请在对应位置填入空字符串 ""，不要原样保留日文
4. 保持二次元口语风格，不要翻译腔，但是返回的语句需要符合中文的语序
5. 不要使用 Markdown 格式，直接返回数组字符串
6. 最后一句句尾不要带句号
7. 名字不要罗马音，特定名字使用其中文译名"""

        custom_context = []
        if self.translation_prompt.strip():
            custom_context.append(f"【背景设定】\n{self.translation_prompt.strip()}")
        if self.chinese_names.strip():
            names_text = self.chinese_names.strip()
            if "=" in names_text:
                custom_context.append(
                    f"【人名对照】\n以下角色必须使用用户指定的中文名：\n{names_text}"
                )
            else:
                custom_context.append(
                    f"【人名对照】\n以下是用户指定使用的中文名，请根据剧情上下文自动匹配到日文角色并直接使用：\n{names_text}\n"
                    "译文中不得出现这些名字的日文或罗马音。"
                )
        if custom_context:
            system_prompt += "\n\n" + "\n\n".join(custom_context)

        user_prompt = f"请按顺序翻译以下 {len(ocr_texts)} 条日文文本：\n{text_list_str}"

        try:
            # 读取整页图片
            if isinstance(image_input, str):
                with open(image_input, "rb") as image_file:
                    base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            else:
                # 假设是 numpy 数组 (OpenCV 图像)
                _, buffer = cv2.imencode('.jpg', image_input)
                base64_image = base64.b64encode(buffer).decode('utf-8')

            use_image = bool(getattr(self, "multimodal", False))
            response = None
            last_error = None
            for _attempt in range(2):
                content_parts = [{"type": "text", "text": user_prompt}]
                if use_image:
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                        }
                    )
                else:
                    content_parts[0]["text"] = (
                        user_prompt + "\n（本次未附带整页图片，请仅依据文本列表翻译）"
                    )
                try:
                    response = client.chat.completions.create(
                        model=self.translation_model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": content_parts},
                        ],
                        response_format={"type": "json_object"},
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    if use_image and "image_url" in str(exc):
                        print("[WARNING] 当前模型不支持图片上下文，降级为纯文本翻译重试...")
                        use_image = False
                        continue
                    raise
            if response is None:
                raise last_error

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
                        translations.extend(["" for _ in range(len(translations), len(ocr_texts))])
                    else:
                        # 多了就截断
                        translations = translations[:len(ocr_texts)]

                return translations

            except json.JSONDecodeError:
                print(f"JSON解析失败: {content}")
                return None

        except Exception as e:
            print(f"PI请求出错: {e}")
            return None

    def configure_fonts(self, ocr_texts, translated_list, image_input):
        if not self.multimodal or not ocr_texts:
            return {}

        API_KEY = self.api_key or ""
        API_BASE_URL = self.api_base_url or ""
        if not API_KEY or not API_BASE_URL or not self.translation_model:
            return {}

        import urllib.request
        import httpx

        proxies = urllib.request.getproxies()
        proxy_url = proxies.get("http") or proxies.get("https")
        http_client = httpx.Client(proxy=proxy_url, timeout=90.0) if proxy_url else httpx.Client(timeout=90.0)
        client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL, http_client=http_client, max_retries=1)

        try:
            if isinstance(image_input, str):
                with open(image_input, "rb") as image_file:
                    base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            else:
                _, buffer = cv2.imencode(".jpg", image_input)
                base64_image = base64.b64encode(buffer).decode("utf-8")

            text_pairs = "\n".join(
                f"[{i}] 原文: {ocr_texts[i]} | 译文: {translated_list[i] if i < len(translated_list) else ''}"
                for i in range(len(ocr_texts))
            )
            system_prompt = (
                "你是漫画排版字体配置助手。请根据整页漫画画面、原文和译文，为每个文本块返回 JSON，"
                '格式为 {"items": [{"index": 0, "font_style": "dialogue", "font_size": 18, "direction": "vertical"}]}。'
                "font_style 只能取 dialogue、radiating、handwriting、serious 之一；"
                "direction 只能取 vertical 或 horizontal；font_size 为整数像素。"
            )
            user_prompt = f"请为以下文本块配置字体：\n{text_pairs}"
            response = client.chat.completions.create(
                model=self.translation_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                            },
                        ],
                    },
                ],
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content.strip()
            data = json.loads(content)
            items = data.get("items") or data.get("fonts") or []
            result = {}
            for item in items:
                idx = int(item.get("index", -1))
                if idx < 0 or idx >= len(ocr_texts):
                    continue
                style = item.get("font_style", "dialogue")
                if style not in ("dialogue", "radiating", "handwriting", "serious", "narration", "next_preview", "title"):
                    style = "dialogue"
                size = int(item.get("font_size") or 0)
                direction = 1 if str(item.get("direction", "")).lower().startswith("v") else 0
                result[idx] = {
                    "font_style": style,
                    "font_size": size if size > 0 else None,
                    "direction": direction,
                }
            return result
        except Exception as exc:
            print(f"[WARNING] 字体配置 AI 调用失败，使用默认字体: {exc}")
            return {}

    def process_comic_page(self, input_path, output_path):
        if isinstance(output_path, str):
            output_path = Path(output_path)
        print("[INFO] 开始处理漫画页面")
        # 1.读取原始图像 (OpenCV 格式用于裁剪 OCR)
        # Windows 下 cv2.imread 无法可靠读取含中文的路径，改用 imdecode。
        img_data = np.fromfile(str(input_path), dtype=np.uint8)
        img_cv = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
        self._check_cancelled()
        self._report_progress("start", f"开始处理: {os.path.basename(input_path)}")
        if img_cv is None:
            raise FileNotFoundError(f"无法读取文件: {input_path}")

        # 2.检测
        # boxes = self.detect_bubbles(input_path)
        # print(f"检测到{len(boxes)}个气泡")
        bubbles_data = self.detect_bubbles(img_cv)
        self._check_cancelled()
        self._report_progress("detect", f"检测完成，共 {len(bubbles_data)} 个气泡")
        print(f"[INFO] 检测到 {len(bubbles_data)} 个气泡")

        # 暂存数据
        bubble_metadata = []
        ocr_text_only = []

        # 3.OCR 与 翻译 (并行处理数据)
        processed_data = []
        for i, box in enumerate(bubbles_data):
            x1, y1, x2, y2, mask_type, font_type, target_font_size, detected_label, language = box

            raw_text = self.run_ocr(img_cv, box, method='manga-ocr')
            self._check_cancelled()
            if raw_text and self._looks_like_english_garbage(raw_text):
                bubbles_data[i] = box[:8] + ('eng',)
                raw_text = ""
            style = font_type
            if raw_text and re.search(r"次回|つづく|続く|待续|下回|TO BE CONTINUED|次号", raw_text, re.IGNORECASE):
                style = "next_preview"

            bubble_metadata.append({
                "box": box,
                "raw": raw_text,
                "style": style,
                "direction": mask_type,
                "target_font_size": target_font_size,
                "non_bubble": detected_label == 2
                or (mask_type == 0 and (x2 - x1) > (y2 - y1) * 2.0),
            })
            ocr_text_only.append(raw_text)
        self._report_progress("ocr", f"OCR 完成，识别 {len(ocr_text_only)} 条文本")

        # 批处理阶段
        print(f"[INFO] 正在翻译 {len(ocr_text_only)} 条文本...")
        
        translated_list = self.translate_page_batch(ocr_text_only, img_cv)
        translation_failed = translated_list is None
        if translated_list is None:
            raise TranslationError(
                "翻译 API 未打通，请检查 API Key、Base URL 和翻译模型；本次未生成译文"
            )
        self._check_cancelled()
        self._report_progress(
            "translate", "翻译失败，跳过原文嵌入" if translation_failed else "翻译完成"
        )
        
        if translated_list is not None:
            print(f"[INFO] 翻译完成，获取 {len(translated_list)} 条结果")

        font_config = {}
        if self.multimodal:
            font_config = self.configure_fonts(ocr_text_only, translated_list, img_cv)
        
        processed_data = []
        for i, item in enumerate(bubble_metadata):
            if len(bubbles_data[i]) > 8 and bubbles_data[i][8] == 'eng':
                trans_text = ""
            else:
                trans_text = translated_list[i] if i < len(translated_list) else ""
            font_cfg = font_config.get(i, {})

            processed_data.append({
                "box": item['box'],
                "raw": item['raw'],
                "style": font_cfg.get("font_style", item['style']),
                "trans": trans_text,
                "direction": font_cfg.get("direction", item['direction']),
                "target_font_size": font_cfg.get("font_size") or item['target_font_size'],
                "non_bubble": item['non_bubble'],
            })
            
            raw_short = item['raw'][:15] + "..." if len(item['raw']) > 15 else item['raw']
            trans_short = trans_text[:15] + "..." if trans_text and len(trans_text) > 15 else (trans_text or "(无)")
            print(f"   [{i+1}/{len(bubble_metadata)}] {raw_short} -> {trans_short}")

        # 4. 图像修补 (获得干净的 PIL 画布)
        # 这一步会去除原有文字，生成适合嵌字的底图
        final_canvas = self.inpaint_bubbles(img_cv, bubbles_data)
        self._check_cancelled()
        self._report_progress("inpaint", "背景修复完成")

        # 5. 嵌字 (Typesetting)
        cleaned_canvas = final_canvas.copy()
        cleaned_dir = output_path.parent.parent / f"{output_path.parent.name}_cleaned"
        cleaned_dir.mkdir(parents=True, exist_ok=True)
        cleaned_path = cleaned_dir / f"{output_path.stem}_cleaned.png"
        cleaned_canvas.save(cleaned_path)
        layout_dir = output_path.parent.parent / f"{output_path.parent.name}_layout"
        layout_dir.mkdir(parents=True, exist_ok=True)
        layout_path = layout_dir / f"{output_path.stem}_layout.json"
        layout_items = []
        for idx, item in enumerate(processed_data):
            layout_items.append({
                "index": idx,
                "box": [int(v) for v in item["box"][:4]],
                "text": item["trans"],
                "style": item["style"],
                "direction": item["direction"],
                "font_size": item["target_font_size"]
                if isinstance(item["target_font_size"], int) and item["target_font_size"] > 0
                else None,
                "non_bubble": bool(item["non_bubble"]),
                "offset_x": 0,
                "offset_y": 0,
            })
        rendered_sizes = {}
        for idx, item in enumerate(processed_data):
            if item['trans']:
                try:
                    final_canvas = self.typesetter.draw_text(
                        final_canvas,
                        item['box'],
                        item['trans'],
                        item['style'],
                        mask=Image.fromarray(self.last_detector_mask) if hasattr(self, 'last_detector_mask') else None,
                        direction=item['direction'],
                        target_font_size=item['target_font_size'],
                        non_bubble=item['non_bubble'],
                    )
                    rendered_sizes[idx] = getattr(self.typesetter, "last_font_size", None)

                except Exception as e:
                    import traceback
                    print(f"无法执行 draw_text，原因: {e}")
                    traceback.print_exc()
        for item in layout_items:
            item["rendered_font_size"] = rendered_sizes.get(item["index"])
        with open(layout_path, "w", encoding="utf-8") as f:
            json.dump(layout_items, f, ensure_ascii=False, indent=2)
        # 6. 保存
        self._check_cancelled()
        self._report_progress("typeset", "排版完成")
        final_canvas.save(output_path)
        self._report_progress("save", f"已保存: {os.path.basename(output_path)}")
        print(f"处理完成！已保存至: {output_path}")
