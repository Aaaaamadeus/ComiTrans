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
from comic_translate_core.languages import source_language, source_language_name
from comic_translate_core.ocr import create_ocr, recognize_regions
from onnx_text_detector import OnnxTextDetector
from text_style import (
    FONT_STYLES,
    choose_font_style,
    choose_layout_direction,
    estimate_text_emphasis,
)


def _parse_translation_response(content):
    """返回（完整译文条目, JSON 是否完整），并恢复截断前的完整字符串。"""
    cleaned = (content or "").replace("```json", "").replace("```", "").strip()
    if not cleaned:
        return [], False

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = None
    else:
        if isinstance(data, dict):
            data = data.get("translations")
        if isinstance(data, list):
            return ["" if item is None else str(item) for item in data], True
        return [], True

    match = re.search(r'"translations"\s*:\s*\[', cleaned)
    if match:
        cursor = match.end()
    elif cleaned.startswith("["):
        cursor = 1
    else:
        return [], False

    decoder = json.JSONDecoder()
    recovered = []
    while cursor < len(cleaned):
        while cursor < len(cleaned) and cleaned[cursor] in " \t\r\n,":
            cursor += 1
        if cursor >= len(cleaned) or cleaned[cursor] == "]":
            break
        try:
            item, cursor = decoder.raw_decode(cleaned, cursor)
        except json.JSONDecodeError:
            break
        recovered.append("" if item is None else str(item))
    return recovered, False


current_dir = os.path.dirname(os.path.abspath(__file__))


def _unique_ocr_lines(polygons):
    """Suppress detector fragments contained within a larger text line."""
    candidates = [np.asarray(points, dtype=np.float32).reshape(4, 2) for points in polygons]
    candidates.sort(key=lambda points: abs(cv2.contourArea(points)), reverse=True)
    kept = []
    for points in candidates:
        area = abs(cv2.contourArea(points))
        if area < 1:
            continue
        if any(cv2.intersectConvexConvex(points, other)[0] / area >= 0.85 for other in kept):
            continue
        kept.append(points)
    return sorted(kept, key=lambda points: (float(points[:, 1].min()), float(points[:, 0].min())))


class TaskCancelledError(Exception):
    pass


class TranslationError(Exception):
    def __init__(self, message, *, fatal=False):
        super().__init__(message)
        self.fatal = bool(fatal)


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
                 baberu_ocr_model_path=None,
                 ocr_backend="auto",
                 progress_callback=None,
                 cancel_callback=None,
                 ocr_config=None):
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
        self.baberu_ocr_model_path = baberu_ocr_model_path or os.path.join(
            current_dir, "..", "models", "baberu-ocr"
        )
        self.ocr_backend_requested = str(ocr_backend or "auto").strip().lower()
        self.ocr_config = {
            "source_language": "ja", "ocr_backend": self.ocr_backend_requested,
            "ocr_model": self.ocr_model_path, "baberu_ocr_model": self.baberu_ocr_model_path,
            "korean_ocr_model": str(Path(current_dir).parent / "models/ppocr/korean_PP-OCRv5_rec_mobile.onnx"),
            "english_ocr_model": str(Path(current_dir).parent / "models/ppocr/en_PP-OCRv5_rec_mobile.onnx"),
            **(ocr_config or {}),
        }
        self.source_language = source_language(self.ocr_config)
        self.source_language_name = source_language_name(self.ocr_config)
        if not self.translation_model:
             print("[WARNING] Pipeline 初始化时未指定翻译模型")
        print("初始化管线")

        print("[INFO] 加载 Comic Text Detector...")
        self.detector = OnnxTextDetector(model_path=det_model_path, input_size=1024, device=self.device)

        self.ocr_engine = create_ocr(self.ocr_config, self.device)
        self.ocr_backend_active = self.ocr_engine.name
        self.ocr = getattr(self.ocr_engine, "recognizer", None)
        self.manga_ocr = self.ocr if self.ocr_backend_active == "manga-ocr" else None
        print(f"[INFO] 源语言: {self.source_language_name} → 中文；OCR: {self.ocr_backend_active}")

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
        # Detector language labels only distinguish Japanese/English and cannot classify Korean.
        self._ocr_blocks = {tuple(int(v) for v in line.xyxy): line for line in text_lines}

        bubbles = []
        for line in text_lines:
            # 1. 坐标提取：直接使用 xyxy
            # 根据列表，xyxy 已经包含了你需要的 [x1, y1, x2, y2]
            box = line.xyxy

            # 2. 类型提取：列表中没有 mask_type，我们使用 vertical (横排/竖排)
            # 如果后续逻辑必须叫 mask_type，我们在这里做一个转换
            # 通常 0 代表横排，1 代表竖排
            detected_font_size = int(getattr(line, 'font_size', -1) or -1)
            detected_label = int(getattr(line, 'label', 0))
            box_width = max(1, int(box[2] - box[0]))
            box_height = max(1, int(box[3] - box[1]))
            mask_type = choose_layout_direction(
                bool(getattr(line, 'vertical', False)), box_width, box_height
            )
            # 普通对话保持正文体，强调/音效体在 OCR 后结合文本和笔画强度判断。
            font_type = (
                'narration'
                if mask_type == 0 and box_width > box_height * 2.0
                else 'dialogue'
            )
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

        detected_font_size = int(box[6]) if len(box) > 6 and int(box[6]) > 0 else 16
        padding = max(2, min(16, int(round(detected_font_size * 0.25))))
        crop_img = img_array[
            max(0, y1 - padding):min(h, y2 + padding),
            max(0, x1 - padding):min(w, x2 + padding),
        ]
        if crop_img.size == 0: return ""
        if self._preserve_english(box):
            return ""

        pil_crop = Image.fromarray(cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB))
        lines = []
        block = getattr(self, "_ocr_blocks", {}).get(tuple(box[:4]))
        if self.ocr_engine.uses_lines and block is not None:
            # Rectify each detector polygon, sorted top-to-bottom for Korean/English.
            polygons = _unique_ocr_lines(block.lines)
            for polygon in polygons:
                self._check_cancelled()
                points = np.asarray(polygon, dtype=np.float32).reshape(4, 2)
                # Line polygons may clip edge punctuation and anti-aliased strokes.
                horizontal = points[1] - points[0]
                vertical = points[3] - points[0]
                margin = max(2.0, min(12.0, float(np.linalg.norm(vertical)) * 0.2))
                horizontal = horizontal / max(1.0, float(np.linalg.norm(horizontal))) * margin
                vertical = vertical / max(1.0, float(np.linalg.norm(vertical))) * margin
                points += np.asarray([-horizontal - vertical, horizontal - vertical,
                                      horizontal + vertical, -horizontal + vertical])
                points[:, 0] = np.clip(points[:, 0], 0, w - 1)
                points[:, 1] = np.clip(points[:, 1], 0, h - 1)
                line_w = int(max(np.linalg.norm(points[1] - points[0]), np.linalg.norm(points[2] - points[3])))
                line_h = int(max(np.linalg.norm(points[3] - points[0]), np.linalg.norm(points[2] - points[1])))
                if line_w < 2 or line_h < 2:
                    continue
                dest = np.float32([[0, 0], [line_w - 1, 0], [line_w - 1, line_h - 1], [0, line_h - 1]])
                matrix = cv2.getPerspectiveTransform(points, dest)
                rectified = cv2.warpPerspective(img_array, matrix, (line_w, line_h), borderMode=cv2.BORDER_REPLICATE)
                lines.append(Image.fromarray(cv2.cvtColor(rectified, cv2.COLOR_BGR2RGB)))
        result = recognize_regions(self.ocr_engine, pil_crop, self.source_language, lines, self._check_cancelled)
        self._last_ocr_result = result
        return result.text

    def _preserve_english(self, box):
        return (getattr(self, "source_language", "ja") == "ja"
                and getattr(self, "ocr_backend_active", "baberu") != "自定义 OCR"
                and len(box) > 8 and box[8] == "eng")

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

    def _is_simple_bubble_v2(self, roi_img, erase_mask=None):
        if roi_img is None or roi_img.size == 0:
            return False
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        background = gray.reshape(-1)
        text_ratio = 0.0
        if erase_mask is not None and erase_mask.shape == gray.shape:
            mask_bool = erase_mask > 0
            text_ratio = float(np.mean(mask_bool))
            available = gray[~mask_bool]
            if available.size >= max(16, gray.size * 0.05):
                background = available
        mean_val = float(np.mean(background))
        std_val = float(np.std(background))
        white_ratio = float(np.mean(background > 225))
        # 必须依据“去掉文字后的背景”判断。直接把原文字纳入统计，会把粗体
        # 或大字号的纯白气泡误判成复杂背景，LaMa 随后容易留下浅色鬼影。
        simple = mean_val > 232 and white_ratio >= 0.82
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
            if self._preserve_english(data):
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
            roi_h, roi_w = gray_roi.shape
            # 二值化
            _, initial_mask = cv2.threshold(gray_roi, 235, 255, cv2.THRESH_BINARY_INV)
            # 查找所有黑色连通块
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(initial_mask, connectivity=8)
            # 创建mask只掩盖字
            text_mask = np.zeros_like(initial_mask)

            for i in range(1, num_labels):
                x, y, w_box, h_box, area = stats[i]
                # 边界触碰检测
                is_touching_border = (
                    x <= 1
                    or y <= 1
                    or x + w_box >= roi_w - 1
                    or y + h_box >= roi_h - 1
                )
                if is_touching_border:
                    continue
                # 筛选规则
                # 比较面积和长宽，基于 h/w
                # 如果一个块的面积超过了“当前切片”总面积的 50%
                if area > (roi_h * roi_w) * 0.5:
                    continue
                # 如果一个块的宽或高占据了“当前切片”的 90% 以上
                if w_box > roi_w * 0.9 or h_box > roi_h * 0.9:
                    continue
                # 去除微小噪点
                if area < 2:
                    continue
                # 将通过筛选的画到mask上
                text_mask[labels == i] = 255

            # 只对筛选后的文字进行膨胀，增强边缘包围，防止遗留抗锯齿的灰色鬼影
            text_mask_union = text_mask.copy()
            text_mask_erase = text_mask.copy()
            if hasattr(self, "last_detector_mask") and self.last_detector_mask is not None:
                detector_roi = self.last_detector_mask[safe_y1:safe_y2, safe_x1:safe_x2]
                if np.count_nonzero(detector_roi) > 0:
                    detector_bool = detector_roi > 0
                    detected_size = int(data[6]) if len(data) > 6 and int(data[6]) > 0 else 16
                    proximity_radius = max(4, min(8, round(detected_size * 0.25)))
                    proximity_kernel = cv2.getStructuringElement(
                        cv2.MORPH_ELLIPSE,
                        (proximity_radius * 2 + 1, proximity_radius * 2 + 1),
                    )
                    detector_near = cv2.dilate(
                        detector_bool.astype(np.uint8), proximity_kernel, iterations=1
                    ) > 0
                    # 检测器掩膜通常只覆盖字形中心，直接使用会留下灰边和半截笔画。
                    # 仅补入检测器邻域内的深色连通像素，既补全完整字形，又避免误擦
                    # 气泡轮廓、分镜线和邻近画面。
                    nearby_dark_text = (text_mask > 0) & detector_near
                    text_mask_union = np.where(
                        detector_bool | nearby_dark_text, 255, 0
                    ).astype(np.uint8)
                    text_mask_erase = text_mask_union.copy()

            detected_size = int(data[6]) if len(data) > 6 and int(data[6]) > 0 else 16
            erase_radius = max(3, min(5, round(detected_size * 0.15)))
            erase_kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (erase_radius * 2 + 1, erase_radius * 2 + 1),
            )
            text_mask_erase_closed = cv2.morphologyEx(
                text_mask_erase,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
            )
            text_mask_erase_dilated = cv2.dilate(
                text_mask_erase_closed, erase_kernel, iterations=1
            )
            raw_dark_dilated = cv2.dilate(
                initial_mask, erase_kernel, iterations=1
            )

            layout_kernel = np.ones((5, 5), np.uint8)
            layout_mask_roi = cv2.dilate(text_mask_union, layout_kernel, iterations=2)
            layout_target = full_layout_mask[safe_y1:safe_y2, safe_x1:safe_x2]
            cv2.bitwise_or(layout_target, layout_mask_roi, dst=layout_target)

            # 分流处理
            box_x1, box_y1 = max(0, x1), max(0, y1)
            box_x2, box_y2 = min(w, x2), min(h, y2)
            box_roi = img_cv[box_y1:box_y2, box_x1:box_x2]
            offset_x = box_x1 - safe_x1
            offset_y = box_y1 - safe_y1
            inner_erase = text_mask_erase_dilated[
                offset_y : offset_y + (box_y2 - box_y1),
                offset_x : offset_x + (box_x2 - box_x1),
            ]
            simple_background = self._is_simple_bubble_v2(box_roi, inner_erase)
            if not simple_background:
                simple_background = self._is_simple_bubble_v2(
                    roi_img, text_mask_erase_dilated
                )
            if simple_background:
                # 纯白背景内可以安全使用完整深色连通字形，解决检测器完全漏掉
                # 某个笔画/标点时仅扩大检测掩膜仍无法清除的问题。
                inner_simple_erase = raw_dark_dilated[
                    offset_y : offset_y + (box_y2 - box_y1),
                    offset_x : offset_x + (box_x2 - box_x1),
                ]
                # 检测器边框有时会截掉最外侧笔画或注音。先清除扩展区内与
                # 检测掩膜相连的字形，再在检测框内补清所有深色笔画；前者
                # 解决框外残边，后者解决检测掩膜内部漏笔画。
                roi_img[text_mask_erase_dilated > 0] = [255, 255, 255]
                roi_img[
                    offset_y : offset_y + (box_y2 - box_y1),
                    offset_x : offset_x + (box_x2 - box_x1),
                ][inner_simple_erase > 0] = [255, 255, 255]
            else:
                # 调用模型处理
                needs_ai_inpainting = True
                lama_target = lama_mask[safe_y1:safe_y2, safe_x1:safe_x2]
                cv2.bitwise_or(lama_target, text_mask_erase_dilated, dst=lama_target)
        
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
        # 空白页不需要访问翻译 API。此前空白页会在后续排版阶段被误报成
        # “API 未打通”，对 PDF 中常见的封面/插页尤其不友好。
        if not any(text.strip() for text in ocr_texts):
            return [""] * len(ocr_texts)

        # 使用初始化时传入的配置（来自 config.yaml）
        API_KEY = self.api_key or ""
        API_BASE_URL = self.api_base_url or ""
        
        missing = []
        if not API_KEY:
            missing.append("API Key")
        if not API_BASE_URL:
            missing.append("Base URL")
        if not self.translation_model:
            missing.append("翻译模型")
        if missing:
            message = f"翻译 API 配置不完整：缺少{'、'.join(missing)}"
            print(f"[ERROR] {message}")
            self._report_progress("translate", message)
            raise TranslationError(message, fatal=True)
        safe_key = f"{API_KEY[:4]}...{API_KEY[-4:]}" if len(API_KEY) > 8 else "***"
        print(f"[INFO] 使用翻译 API: {API_BASE_URL.split('?')[0]}")
        print(f"[INFO] API Key: {safe_key}")
        import time as _time
        _t0 = _time.time()
        self._report_progress("translate", f"正在请求翻译 API: {self.translation_model}，{len(ocr_texts)} 条文本")
        
        import urllib.request
        import httpx
        
        proxies = urllib.request.getproxies()
        proxy_url = proxies.get('http') or proxies.get('https')
        http_client = httpx.Client(proxy=proxy_url, timeout=90.0) if proxy_url else httpx.Client(timeout=90.0)

        # 3. 构造 Prompt
        language_name = getattr(self, "source_language_name", "日语")
        system_prompt = """你是专业的漫画翻译助手，将源语言文本翻译成简体中文。输入是按漫画阅读顺序排列的 OCR 文本。

输入示例：
[0] 原文条目一
[1] 原文条目二
[2] ……

输出要求：
只返回合法 JSON，格式必须为：
{"translations": ["译文1", "译文2", "译文3"]}
不要输出 Markdown 代码块、说明文字或其他字段。

翻译规则：
1. translations 数组必须与输入数量、顺序完全一致。
2. 译文应自然、简洁，符合中文漫画对白习惯，不要逐字硬译。
3. 保留说话人的语气、敬语、称呼和情绪强度。
4. OCR 为空、纯符号或明显无法识别时返回空字符串，不得臆造内容。
5. 拟声词优先使用自然的中文拟声表达。
6. 人名和术语在整页内保持一致。
7. 不得在译文中加入解释、注释、序号或引号。"""

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
                    f"【人名对照】\n以下是用户指定使用的中文名，请根据剧情上下文自动匹配到原文角色并直接使用：\n{names_text}\n"
                    "译文中不得出现这些名字的原文或音译拼写。"
                )
        if custom_context:
            system_prompt += "\n\n" + "\n\n".join(custom_context)

        system_prompt += f"\n本次源语言：{language_name}；目标语言：简体中文。"

        try:
            client = OpenAI(
                api_key=API_KEY,
                base_url=API_BASE_URL,
                http_client=http_client,
                max_retries=2,
            )
            use_image = bool(getattr(self, "multimodal", False))
            base64_image = ""
            if use_image:
                # 只有多模态模式才编码整页图，纯文本翻译避免无谓的 CPU 与内存开销。
                if isinstance(image_input, str):
                    with open(image_input, "rb") as image_file:
                        base64_image = base64.b64encode(image_file.read()).decode("utf-8")
                else:
                    success, buffer = cv2.imencode(".jpg", image_input)
                    if not success:
                        raise TranslationError("无法编码多模态翻译所需的页面图片")
                    base64_image = base64.b64encode(buffer).decode("utf-8")

            translations = []
            remaining = list(ocr_texts)
            last_content = ""
            last_finish_reason = ""
            send_max_tokens = True

            # 服务端可能在输出 token 达到上限时截断 JSON。保留已经完整输出的
            # 数组元素，并只续译尚未返回的后缀，避免重复翻译或静默补空。
            for continuation_attempt in range(3):
                start_index = len(translations)
                text_list_str = "\n".join(
                    f"[{start_index + i}] {text}" for i, text in enumerate(remaining)
                )
                user_prompt = (
                    f"请严格按顺序将以下 {len(remaining)} 条{language_name}文本译成简体中文，返回 "
                    f'{{"translations": [...]}}，数组只能包含本次列出的 {len(remaining)} 条译文：\n'
                    f"{text_list_str}"
                )
                if continuation_attempt:
                    user_prompt = (
                        "上次响应被截断或数量不足。请从以下条目继续，务必输出完整闭合的 JSON。\n"
                        + user_prompt
                    )

                response = None
                last_error = None
                for _request_attempt in range(3):
                    content_parts = [{"type": "text", "text": user_prompt}]
                    if use_image:
                        content_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                            }
                        )
                    else:
                        content_parts[0]["text"] += "\n（本次未附带整页图片，请仅依据文本列表翻译）"
                    try:
                        request_options = dict(
                            model=self.translation_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": content_parts},
                            ],
                            response_format={"type": "json_object"},
                        )
                        if send_max_tokens:
                            request_options["max_tokens"] = 8192
                        response = client.chat.completions.create(**request_options)
                        break
                    except Exception as exc:
                        last_error = exc
                        if use_image and "image_url" in str(exc):
                            print("[WARNING] 当前模型不支持图片上下文，降级为纯文本翻译重试...")
                            use_image = False
                            continue
                        if send_max_tokens and "max_tokens" in str(exc).lower():
                            print("[WARNING] 当前接口不支持 max_tokens 参数，移除该参数后重试...")
                            send_max_tokens = False
                            continue
                        raise
                if response is None:
                    raise last_error

                choice = response.choices[0]
                last_finish_reason = str(getattr(choice, "finish_reason", "") or "")
                last_content = (choice.message.content or "").strip()
                items, json_complete = _parse_translation_response(last_content)
                accepted = items[:len(remaining)]
                if accepted:
                    translations.extend(accepted)
                    remaining = remaining[len(accepted):]

                if not remaining:
                    self._report_progress(
                        "translate",
                        f"翻译 API 返回 {len(translations)} 条结果，耗时 {_time.time() - _t0:.1f}s",
                    )
                    return translations

                reason = f"，finish_reason={last_finish_reason}" if last_finish_reason else ""
                status = "JSON 被截断" if not json_complete else "返回数量不足"
                print(
                    f"[WARNING] 翻译{status}{reason}；已收到 {len(translations)}/{len(ocr_texts)} 条，继续请求剩余内容"
                )
                if continuation_attempt < 2:
                    self._report_progress(
                        "translate",
                        f"翻译响应{status}，正在续译剩余 {len(remaining)} 条（第 {continuation_attempt + 2}/3 次）",
                    )

            preview = last_content.replace("\r", " ").replace("\n", " ")[:160]
            reason = f"，finish_reason={last_finish_reason}" if last_finish_reason else ""
            if translations:
                message = (
                    f"翻译响应连续 3 次被截断或数量不足（已收到 {len(translations)}/{len(ocr_texts)} 条{reason}）："
                    f"{preview or '空响应'}"
                )
            else:
                message = (
                    f"翻译响应不是合法 JSON（连续 3 次解析失败{reason}）："
                    f"{preview or '空响应'}"
                )
            raise TranslationError(message)

        except TranslationError:
            raise
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code in (401, 403):
                hint = "鉴权失败，请检查 API Key"
            elif status_code == 402:
                hint = "账户余额不足，请充值或更换有额度的 API Key"
            elif status_code == 404:
                hint = "接口或模型不存在，请检查 Base URL 和翻译模型"
            elif status_code == 429:
                hint = "请求过于频繁或额度不足"
            elif status_code and status_code >= 500:
                hint = "翻译服务暂时不可用"
            else:
                hint = "请检查网络、Base URL 和翻译模型"
            detail = " ".join(str(exc).split())[:300]
            if API_KEY:
                detail = detail.replace(API_KEY, "***")
            message = f"翻译 API 请求失败：{hint}"
            if detail:
                message += f"（{detail}）"
            print(f"[ERROR] {message}")
            self._report_progress("translate", message)
            raise TranslationError(
                message, fatal=status_code in (401, 402, 403, 404)
            ) from exc
        finally:
            http_client.close()

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
                f"font_style 只能取 {', '.join(FONT_STYLES)} 之一；"
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
                if style not in FONT_STYLES:
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

    def prepare_comic_page(self, input_path):
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

            self._last_ocr_result = None
            self._check_cancelled()
            raw_text = self.run_ocr(img_cv, box, method='auto')
            self._check_cancelled()
            if (getattr(self, "source_language", "ja") == "ja"
                    and getattr(self, "ocr_backend_active", "baberu") != "自定义 OCR"
                    and raw_text and self._looks_like_english_garbage(raw_text)):
                bubbles_data[i] = box[:8] + ('eng',)
                raw_text = ""
            box_width = max(1, x2 - x1)
            box_height = max(1, y2 - y1)
            direction = choose_layout_direction(
                mask_type == 1, box_width, box_height, raw_text
            )
            non_bubble = detected_label == 2 or (
                direction == 0 and box_width > box_height * 2.0
            )
            crop = img_cv[
                max(0, y1):min(img_cv.shape[0], y2),
                max(0, x1):min(img_cv.shape[1], x2),
            ]
            emphasis = estimate_text_emphasis(crop, target_font_size)
            style = choose_font_style(
                raw_text,
                direction=direction,
                width=box_width,
                height=box_height,
                non_bubble=non_bubble,
                emphasis=emphasis,
            )

            bubble_metadata.append({
                "box": box,
                "raw": raw_text,
                "style": style,
                "direction": direction,
                "target_font_size": target_font_size,
                "non_bubble": non_bubble,
                "emphasis": round(emphasis, 3),
                "source_language": getattr(self, "source_language", "ja"),
                "ocr_backend": getattr(self, "ocr_backend_active", ""),
                "ocr_confidence": getattr(self._last_ocr_result, "confidence", None),
            })
            ocr_text_only.append(raw_text)
        self._report_progress("ocr", f"OCR 完成，识别 {len(ocr_text_only)} 条文本")
        return {
            "img_cv": img_cv,
            "bubbles_data": bubbles_data,
            "bubble_metadata": bubble_metadata,
            "ocr_texts": ocr_text_only,
            "input_path": str(input_path),
            "mask": self.last_detector_mask.copy()
            if hasattr(self, "last_detector_mask") and self.last_detector_mask is not None
            else None,
        }

    def finish_comic_page(self, output_path, prepared, translated_list):
        img_cv = prepared["img_cv"]
        bubbles_data = prepared["bubbles_data"]
        bubble_metadata = prepared["bubble_metadata"]
        ocr_text_only = prepared["ocr_texts"]
        if isinstance(output_path, str):
            output_path = Path(output_path)
        self.last_detector_mask = prepared.get("mask")


        # 批处理阶段
        print(f"[INFO] 正在翻译 {len(ocr_text_only)} 条文本...")
        
        if translated_list is None:
            raise TranslationError(
                "翻译阶段未返回结果，已停止排版以避免生成错误文件"
            )
        self._check_cancelled()
        self._report_progress("translate", "翻译完成")
        
        print(f"[INFO] 翻译完成，获取 {len(translated_list)} 条结果")

        font_config = {}
        if self.multimodal:
            font_config = self.configure_fonts(ocr_text_only, translated_list, img_cv)
        
        processed_data = []
        for i, item in enumerate(bubble_metadata):
            is_eng = self._preserve_english(bubbles_data[i])
            if is_eng or not item['raw'].strip():
                trans_text = ""
            else:
                trans_text = translated_list[i] if i < len(translated_list) else ""
                if not trans_text and item['raw']:
                    print(f"  [??] 第 {i + 1} 块译文为空，跳过嵌字: {item['raw'][:20]}")
            font_cfg = font_config.get(i, {})

            processed_data.append({
                "box": item['box'],
                "raw": item['raw'],
                "style": font_cfg.get("font_style", item['style']),
                "trans": trans_text,
                "direction": font_cfg.get("direction", item['direction']),
                "target_font_size": font_cfg.get("font_size") or item['target_font_size'],
                "non_bubble": item['non_bubble'],
                "emphasis": item.get('emphasis', 0.0),
            })
            
            raw_short = item['raw'][:15] + "..." if len(item['raw']) > 15 else item['raw']
            trans_short = trans_text[:15] + "..." if trans_text and len(trans_text) > 15 else (trans_text or "(无)")
            print(f"   [{i+1}/{len(bubble_metadata)}] {raw_short} -> {trans_short}")

        # 4. 图像修补 (获得干净的 PIL 画布)
        # 这一步会去除原有文字，生成适合嵌字的底图
        # Empty/failed OCR or empty translation must leave the source pixels intact.
        erase_boxes = [box for box, item in zip(bubbles_data, processed_data) if item['trans']]
        original_canvas = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
        final_canvas = self.inpaint_bubbles(img_cv, erase_boxes)
        # A neighbouring translated bubble's padding can overlap a preserved region.
        for item in processed_data:
            if not item['trans']:
                x1, y1, x2, y2 = item['box'][:4]
                region = (max(0, x1), max(0, y1), min(final_canvas.width, x2), min(final_canvas.height, y2))
                if region[2] > region[0] and region[3] > region[1]:
                    final_canvas.paste(original_canvas.crop(region), region[:2])
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
                "source_text": bubble_metadata[idx]["raw"],
                "source_language": bubble_metadata[idx].get("source_language", "ja"),
                "ocr_backend": bubble_metadata[idx].get("ocr_backend", ""),
                "ocr_confidence": bubble_metadata[idx].get("ocr_confidence"),
                "box": [int(v) for v in item["box"][:4]],
                "text": item["trans"],
                "style": item["style"],
                "direction": item["direction"],
                "font_size": item["target_font_size"]
                if isinstance(item["target_font_size"], int) and item["target_font_size"] > 0
                else None,
                "non_bubble": bool(item["non_bubble"]),
                "emphasis": item.get("emphasis", 0.0),
                "rendered_font_size": None,
                "offset_x": 0,
                "offset_y": 0,
            })
        rendered_sizes = {}
        layout_mask = getattr(self, "current_mask_image", None)
        if layout_mask is None and hasattr(self, "last_detector_mask"):
            layout_mask = Image.fromarray(self.last_detector_mask)
        for idx, item in enumerate(processed_data):
            if item['trans']:
                try:
                    final_canvas = self.typesetter.draw_text(
                        final_canvas,
                        item['box'],
                        item['trans'],
                        item['style'],
                        # 使用擦字阶段补全并合并过的掩膜计算文字中心，避免窄框、
                        # 相邻框被原始检测器的缺口带偏。
                        mask=layout_mask,
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

    def process_comic_page(self, input_path, output_path):
        prepared = self.prepare_comic_page(input_path)
        translated_list = self.translate_page_batch(prepared["ocr_texts"], prepared["img_cv"])
        self.finish_comic_page(output_path, prepared, translated_list)
