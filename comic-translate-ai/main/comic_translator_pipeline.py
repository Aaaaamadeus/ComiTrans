import os
from copy import copy
import base64
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from openai import OpenAI
from manga_lama import MangaLama
from comic_translate_core.errors import TaskCancelledError, TranslationError, TypesettingError
from comic_translate_core.pipeline_settings import TranslationSettings
from comic_translate_core.translation import TranslationClient
from comic_translate_core.translation_format import (
    ResponseFormatCapabilities, TranslationFormatError, validate_translations,
    parse_translation_response as _parse_translation_response,
)
from comic_translate_core.background_reconstruction import reconstruct_background
from comic_translate_core.restoration import make_region, original_snapshot_path, pdf_original_path
from comic_translate_core.page_store import PageWriteTransaction
from comic_translate_core.text_mask import AdaptiveTextMask, MaskRequest, validate_result
from vertical_typesetter import VerticalTypesetter
from comic_translate_core.languages import source_language, source_language_name
from comic_translate_core.chinese import (
    ChineseConversionError, convert_chinese, normalize_target_language, target_language_name,
)
from comic_translate_core.ocr import create_ocr, recognize_regions
from comic_translate_core.layout_options import normalize_text_color, normalize_vertical_alignment
from comic_translate_core.watermark import apply_watermark
from onnx_text_detector import OnnxTextDetector
import font_probe
from text_style import (
    FONT_STYLES,
    choose_font_style,
    choose_layout_direction,
    estimate_text_emphasis,
    measure_source_lines,
)


# 关闭"思考/推理"的请求参数。实测（docs/FONT_STYLE_STRATEGY.md §4.15）：
# 同一道小题 completion 从 62 降到 2；字体判别从 1.5k~2k 降到 5，且不再出现空响应。
# 注意：OpenAI SDK 会拒绝未知的关键字参数，必须经 extra_body 透传；
# 接口若不认识该参数（400），调用处会去掉它重试，保证兼容性。
THINKING_DISABLED = {"thinking": {"type": "disabled"}}
PROBE_MAX_TOKENS = 512


def _rgb_image(bgr):
    """Decode BGR bytes directly into an owned PIL image, also for sliced crops."""
    height, width = bgr.shape[:2]
    return Image.frombytes("RGB", (width, height), np.ascontiguousarray(bgr), "raw", "BGR")


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
                 multimodal_font_probe=False,
                 disable_thinking=True,
                 font_probe_samples=3,
                 ocr_model_path=None,
                 baberu_ocr_model_path=None,
                 ocr_backend="auto",
                 progress_callback=None,
                 cancel_callback=None,
                 ocr_config=None,
                 watermark_enabled=True,
                 fallback_fonts=None,
                 target_language="zh-Hans",
                 vertical_alignment="center",
                 text_color=None,
                 text_mask_generator=None):
        self._translation_capabilities = ResponseFormatCapabilities()
        self.device = 'cuda' if use_gpu else 'cpu'
        self.translation_model = translation_model
        self.api_key = api_key
        self.api_base_url = api_base_url
        self.translation_prompt = translation_prompt or ""
        self.target_language = normalize_target_language(target_language)
        self.vertical_alignment = normalize_vertical_alignment(vertical_alignment)
        self.text_color = normalize_text_color(text_color)
        self.chinese_names = chinese_names or ""
        self.multimodal = bool(multimodal)
        # 实验功能：AI 参与字体族判别。默认关闭——实测在真实漫画页上判定不稳定且每块
        # 需要数千 reasoning token，见 docs/FONT_STYLE_STRATEGY.md §4.14。
        self.multimodal_font_probe = bool(multimodal_font_probe)
        # 关闭思考模式：实测翻译 completion 从 214 降到 51、耗时减半，译文质量相当（§4.15）
        self.disable_thinking = bool(disable_thinking)
        # 字体判别的多采样投票次数（≥2 时过半才采纳，用于收敛单次判定的抖动）
        self.font_probe_samples = int(font_probe_samples or 1)
        self.watermark_enabled = bool(watermark_enabled)
        self.progress_callback = progress_callback
        self.cancel_callback = cancel_callback
        self.text_mask_generator = text_mask_generator or AdaptiveTextMask()
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
        print(f"[INFO] 源语言: {self.source_language_name} → {target_language_name(self.target_language)}；OCR: {self.ocr_backend_active}")

        # 3. 图像修补
        print("[INFO] 加载 Manga-lama...")
        self.inpainter = MangaLama(lama_path, device=self.device, cancel_callback=self._check_cancelled)

        # 4. 嵌字器
        print("初始化嵌字器")
        self.typesetter = VerticalTypesetter(font_map, font_size, fallback_fonts=fallback_fonts)

    def _report_progress(self, stage, message):
        if self.progress_callback:
            try:
                self.progress_callback(stage, message)
            except Exception:
                pass

    def _check_cancelled(self):
        if getattr(self, "cancel_callback", None) and self.cancel_callback():
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

    def inpaint_bubbles(self, img_cv, boxes):
        """Build masks independently, then fill flat colours or repair textures."""
        height, width = img_cv.shape[:2]
        canvas = _rgb_image(img_cv)
        lama_mask = None
        layout_mask = np.zeros((height, width), np.uint8)
        erase_mask = np.zeros((height, width), np.uint8)
        generator = getattr(self, 'text_mask_generator', None) or AdaptiveTextMask()
        detector = getattr(self, 'last_detector_mask', None)
        self.last_mask_diagnostics = []
        self.current_bubble_restore_regions = {}
        self.current_outline_ratios = {}
        for data in boxes:
            if self._preserve_english(data):
                continue
            if getattr(self, 'cancel_callback', None):
                self._check_cancelled()
            x1, y1, x2, y2 = map(int, data[:4])
            left, top = max(0, x1 - 15), max(0, y1 - 15)
            right, bottom = min(width, x2 + 15), min(height, y2 + 15)
            if right <= left or bottom <= top or x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height:
                continue
            # Copies isolate replacement components from original pixels and
            # neighbouring regions; every mask sees the untouched source page.
            crop = img_cv[top:bottom, left:right].copy()
            crop.setflags(write=False)
            seed = detector[top:bottom, left:right].copy() if detector is not None else None
            if seed is not None:
                seed.setflags(write=False)
            size = int(data[6]) if len(data) > 6 and data[6] else 16
            request = MaskRequest(crop, (x1-left, y1-top, x2-left, y2-top), seed, size)
            result = validate_result(generator.generate(request), crop.shape[:2])
            box_key = (x1, y1, x2, y2)
            if result.source_outline_ratio is not None:
                self.current_outline_ratios[box_key] = result.source_outline_ratio
            self.current_bubble_restore_regions[box_key] = make_region(
                data[:4], (width, height), (left, top, right, bottom), Image.fromarray(result.erase_mask))
            diagnostics = dict(result.diagnostics)
            self.last_mask_diagnostics.append(diagnostics)
            layout_mask[top:bottom, left:right] |= result.layout_mask
            erase_mask[top:bottom, left:right] |= result.erase_mask
            if result.fill_color is None:
                reconstruction = reconstruct_background(crop, result.erase_mask)
                if reconstruction is None:
                    diagnostics['repair_strategy'] = 'lama'
                    if lama_mask is None:
                        lama_mask = np.zeros((height, width), np.uint8)
                    lama_mask[top:bottom, left:right] |= result.erase_mask
                else:
                    rebuilt, diagnostics['repair_strategy'] = reconstruction
                    canvas.paste(_rgb_image(rebuilt), (left, top), Image.fromarray(result.erase_mask))
            else:
                diagnostics['repair_strategy'] = 'flat'
                canvas.paste(tuple(reversed(result.fill_color)), (left, top, right, bottom),
                             Image.fromarray(result.erase_mask))
        self.current_mask_image = Image.fromarray(layout_mask)
        self.current_erase_mask = Image.fromarray(erase_mask)
        if lama_mask is not None and np.any(lama_mask):
            canvas = self.inpainter(canvas, Image.fromarray(lama_mask))
        return canvas

    def translate_page_batch(self, ocr_texts, image_input):
        if not hasattr(self, '_translation_capabilities'):
            self._translation_capabilities = ResponseFormatCapabilities()
        client = TranslationClient(
            TranslationSettings.from_pipeline(self), self._translation_capabilities,
            client_factory=OpenAI, convert_text=convert_chinese,
            report_progress=self._report_progress, check_cancelled=self._check_cancelled,
        )
        return client.translate(ocr_texts, image_input)

    def configure_fonts(self, bubble_metadata, image_input):
        """A′：本地生成三个候选，模型只做 1-of-3 判别；字号与方向都归本地。

        依据 docs/FONT_STYLE_STRATEGY.md §4.12 的实测：开放式分类只有 39%~57%，
        三候选比对 5/5；候选一多就崩。因此这里把模型的决策面压到「选 A/B/C/none」，
        并且结果还要过精确率门控与本地许可表（font_probe.resolve_style）。
        """
        if not self.multimodal or not getattr(self, "multimodal_font_probe", False) or not bubble_metadata:
            return {}

        API_KEY = self.api_key or ""
        API_BASE_URL = self.api_base_url or ""
        if not API_KEY or not API_BASE_URL or not self.translation_model:
            return {}

        font_map = getattr(getattr(self, "typesetter", None), "font_map", None) or {}
        specs = font_probe.candidate_specs(font_map)
        if not specs:
            print("[WARNING] 字体候选不完整（需要黑体/宋体/手写各一），跳过多模态字体判别")
            return {}

        if isinstance(image_input, str):
            img_data = np.fromfile(str(image_input), dtype=np.uint8)
            image = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
        else:
            image = image_input
        if image is None:
            return {}

        targets = [
            (index, item)
            for index, item in enumerate(bubble_metadata)
            if font_probe.should_probe(item.get("style"), item.get("raw"))
        ]
        if not targets:
            return {}

        import urllib.request
        import httpx

        proxies = urllib.request.getproxies()
        proxy_url = proxies.get("http") or proxies.get("https")
        http_client = httpx.Client(proxy=proxy_url, timeout=90.0) if proxy_url else httpx.Client(timeout=90.0)
        client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL, http_client=http_client, max_retries=1)

        workers = max(1, min(int(getattr(self, "font_probe_workers", 4) or 1), len(targets)))
        samples = max(1, min(int(getattr(self, "font_probe_samples", 3) or 1), 5))
        result: dict[int, dict] = {}

        def probe(index, item):
            box = [int(value) for value in (item.get("box") or [])[:4]]
            if len(box) < 4:
                return
            x1, y1, x2, y2 = box
            crop = image[max(0, y1):max(1, y2), max(0, x1):max(1, x2)]
            if crop.size == 0:
                return
            crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            sheet = font_probe.build_probe_sheet(
                Image.fromarray(crop_rgb),
                str(item.get("raw") or ""),
                specs,
                direction=int(item.get("direction", 1)),
                glyph_px=int(item.get("target_font_size") or 0) or None,
            )
            buffer = io.BytesIO()
            sheet.save(buffer, format="JPEG", quality=88)
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
            # 判别调用一律关闭思考：实测（docs §4.15）单块 completion 从 1.5k~2k 降到 5，
            # 且不再出现"思考吃满预算、返回空"的失败；同时限制输出，避免跑飞。
            votes: list[str | None] = []
            elapsed_total = 0.0
            for _sample in range(samples):
                started = time.time()
                response = client.chat.completions.create(
                    model=self.translation_model,
                    messages=[
                        {"role": "system", "content": font_probe.probe_prompt()},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "请判断这一块原图的字体最接近哪个候选。"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                                },
                            ],
                        },
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=PROBE_MAX_TOKENS,
                    extra_body=dict(THINKING_DISABLED),
                )
                elapsed_total += time.time() - started
                _letter, family = font_probe.parse_pick(response.choices[0].message.content)
                votes.append(family)
            family = font_probe.pick_majority(votes)
            print(f"[INFO] 字体候选判别 块{index}: {votes} -> family={family or '-'} "
                  f"({elapsed_total:.1f}s, {samples} 次采样)")
            if not font_probe.accept_family(family):
                return
            role = str(item.get("style") or "dialogue")
            style = font_probe.resolve_style(role, family)
            if style not in FONT_STYLES:
                return
            result[index] = {"font_style": style, "family": family}

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(probe, index, item) for index, item in targets]
                for future in futures:
                    try:
                        future.result()
                    except Exception as exc:  # 单个块失败只影响该块
                        print(f"[WARNING] 字体候选判别失败，保留本地判定: {exc}")
        except Exception as exc:
            print(f"[WARNING] 字体候选判别整体失败，全部保留本地判定: {exc}")
            return {}
        finally:
            http_client.close()

        print(f"[INFO] 字体候选判别：{len(result)}/{len(targets)} 块采纳了模型选择")
        return result

    def fork_preparation(self):
        """Share model weights, but isolate page-local detection/OCR state."""
        context = copy(self)
        context.last_detector_mask = None
        context._ocr_blocks = {}
        context._last_ocr_result = None
        return context

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

        # 3. OCR 与本地排版元数据
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
            block = getattr(self, "_ocr_blocks", {}).get(tuple(box[:4]))
            evidence = measure_source_lines(getattr(block, "lines", ()))
            if evidence is not None:
                direction, glyph_size = evidence
                # Use the median line thickness to reject inflated block sizes.
                if target_font_size <= 0 or target_font_size > glyph_size * 1.4:
                    target_font_size = max(10, glyph_size)
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
        try:
            validate_translations(translated_list, len(ocr_text_only))
        except TranslationFormatError as exc:
            raise TranslationError(f'译文校验失败，已停止擦字和嵌字：{exc}') from exc
        self._report_progress("translate", "翻译完成")
        
        print(f"[INFO] 翻译完成，获取 {len(translated_list)} 条结果")

        font_config = {}
        if self.multimodal:
            # A′：本地候选 + 模型 1-of-3 判别；字号与方向不再由模型决定。
            font_config = self.configure_fonts(bubble_metadata, img_cv)
        
        processed_data = []
        for i, item in enumerate(bubble_metadata):
            is_eng = self._preserve_english(bubbles_data[i])
            if is_eng or not item['raw'].strip():
                trans_text = ""
            else:
                trans_text = translated_list[i]
                if not trans_text and item['raw']:
                    print(f"  [??] 第 {i + 1} 块译文为空，跳过嵌字: {item['raw'][:20]}")
            font_cfg = font_config.get(i, {})

            processed_data.append({
                "box": item['box'],
                "raw": item['raw'],
                "style": font_cfg.get("font_style", item['style']),
                "trans": trans_text,
                "direction": font_cfg.get("direction", item['direction']),
                # 字号一律使用检测器建议值，多模态不再参与字号决策。
                "target_font_size": item['target_font_size'],
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
        self.current_bubble_restore_regions = {}
        final_canvas = self.inpaint_bubbles(img_cv, erase_boxes)
        # A neighbouring translated bubble's padding can overlap a preserved region.
        for item in processed_data:
            if not item['trans']:
                x1, y1, x2, y2 = item['box'][:4]
                region = (max(0, x1), max(0, y1), min(final_canvas.width, x2), min(final_canvas.height, y2))
                if region[2] > region[0] and region[3] > region[1]:
                    left, top, right, bottom = region
                    final_canvas.paste(_rgb_image(img_cv[top:bottom, left:right]), (left, top))
        self._check_cancelled()
        self._report_progress("inpaint", "背景修复完成")

        # 5. 嵌字 (Typesetting)
        with PageWriteTransaction(output_path) as store:
            cleaned_dir = output_path.parent.parent / f"{output_path.parent.name}_cleaned"
            cleaned_path = cleaned_dir / f"{output_path.stem}_cleaned.png"
            final_canvas.save(store.stage(cleaned_path))
            layout_dir = output_path.parent.parent / f"{output_path.parent.name}_layout"
            layout_path = layout_dir / f"{output_path.stem}_layout.json"
            layout_items = []
            for idx, item in enumerate(processed_data):
                box_key = tuple(map(int, item['box'][:4]))
                original_region = self.current_bubble_restore_regions.get(box_key)
                if original_region is None:
                    try:
                        original_region = make_region(item['box'][:4], final_canvas.size)
                    except ValueError:
                        # Invalid/empty detections cannot be restored; do not fail
                        # a successfully translated page for optional metadata.
                        original_region = None
                layout_items.append({
                    "index": idx,
                    "source_text": bubble_metadata[idx]["raw"],
                    "original_region": original_region,
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
                    "vertical_alignment": normalize_vertical_alignment(getattr(self, 'vertical_alignment', 'center')),
                    "text_color": normalize_text_color(getattr(self, 'text_color', None)),
                    "offset_x": 0,
                    "offset_y": 0,
                })
                ratio = getattr(self, 'current_outline_ratios', {}).get(box_key)
                if ratio is not None and item['trans']:
                    layout_items[-1].update(text_effect='outlined', source_outline_ratio=ratio)
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
                            vertical_alignment=layout_items[idx]['vertical_alignment'],
                            text_color=layout_items[idx]['text_color'],
                            text_effect=layout_items[idx].get('text_effect', 'auto'),
                            source_outline_ratio=layout_items[idx].get('source_outline_ratio'),
                        )
                        rendered_sizes[idx] = getattr(self.typesetter, "last_font_size", None)
                        region = getattr(self.typesetter, "last_layout_box", None)
                        if region is not None:
                            layout_items[idx]["mask_box"] = list(region)

                    except TaskCancelledError:
                        raise
                    except Exception as exc:
                        raise TypesettingError(f'第 {idx + 1} 个气泡嵌字失败：{exc}') from exc
            for item in layout_items:
                item["rendered_font_size"] = rendered_sizes.get(item["index"])
            with open(store.stage(layout_path), "w", encoding="utf-8") as f:
                json.dump(layout_items, f, ensure_ascii=False, indent=2)
            # 6. 保存
            self._check_cancelled()
            self._report_progress("typeset", "排版完成")
            final_canvas = apply_watermark(final_canvas, enabled=getattr(self, "watermark_enabled", True), in_place=True)
            final_canvas.save(store.stage(output_path))
            original_path = original_snapshot_path(output_path)
            pdf_source = pdf_original_path(output_path)
            input_path = prepared.get('input_path')
            reuse_pdf_source = (pdf_source is not None and pdf_source.is_file() and input_path
                                and Path(input_path).resolve() == pdf_source.resolve()
                                and not original_path.exists())
            if not reuse_pdf_source:
                _rgb_image(img_cv).save(store.stage(original_path), format='PNG')
            self._check_cancelled()
            store.commit()
        self._report_progress("save", f"已保存: {os.path.basename(output_path)}")
        print(f"处理完成！已保存至: {output_path}")

    def process_comic_page(self, input_path, output_path):
        prepared = self.prepare_comic_page(input_path)
        translated_list = self.translate_page_batch(prepared["ocr_texts"], prepared["img_cv"])
        self.finish_comic_page(output_path, prepared, translated_list)
