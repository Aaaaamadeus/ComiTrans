from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "comic-translate-ai/main"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from comic_translate_core.languages import effective_ocr_backend, validate_ocr_config
from comic_translate_core.ocr import CustomOcr, OcrError, OcrResult, create_ocr, recognize_regions
from comic_translate_core.onnx_ppocr import OnnxPPOcr
from comic_translate_desktop import config as app_config
from comic_translate_desktop.worker import BatchWorker
import comic_translator_pipeline as pipeline_module
from comic_translator_pipeline import ComicTranslatorPipeline, TaskCancelledError


def bare_pipeline(language="en"):
    pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
    pipeline.source_language = language
    pipeline.source_language_name = {"en": "英语", "ko": "韩语", "ja": "日语"}.get(language, "法语")
    pipeline.ocr_backend_active = "ppocr" if language != "ja" else "baberu"
    pipeline.progress_callback = pipeline.cancel_callback = None
    pipeline.api_key, pipeline.api_base_url, pipeline.translation_model = "test-key", "https://example.invalid/v1", "test"
    pipeline.translation_prompt, pipeline.chinese_names = "", "主角"
    pipeline.multimodal = False
    return pipeline


class LanguageConfigTests(unittest.TestCase):
    def test_old_config_defaults_to_japanese(self):
        with patch.object(app_config, "load_yaml", return_value={}):
            config = app_config.load_ai_config()
        self.assertEqual(config["source_language"], "ja")
        self.assertEqual(effective_ocr_backend(config), "auto")
        self.assertEqual(validate_ocr_config(config), [])

    def test_language_routes_and_incompatible_backends(self):
        for language in ("en", "ko"):
            self.assertEqual(effective_ocr_backend({"source_language": language}), "ppocr")
            self.assertTrue(validate_ocr_config({"source_language": language, "ocr_backend": "baberu"}))
        self.assertTrue(validate_ocr_config({"source_language": "ja", "ocr_backend": "unknown"}))
        self.assertTrue(validate_ocr_config({"source_language": "custom", "custom_source_language": "../bad"}))

    def test_missing_models_only_checks_selected_language(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.onnx"
            path.touch()
            config = dict(detector_model=str(path), lama_model=str(path), source_language="en", english_ocr_model=str(path))
            self.assertEqual(app_config.missing_models(config), [])
            config.update(source_language="ko", korean_ocr_model=str(path.parent / "missing.onnx"))
            errors = app_config.missing_models(config)
            self.assertEqual(len(errors), 1)
            self.assertIn("korean_ocr_model", errors[0])

    def test_custom_ocr_requires_no_japanese_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.onnx"
            path.touch()
            config = dict(detector_model=str(path), lama_model=str(path), source_language="custom",
                          custom_source_language="fr", custom_ocr_url="http://localhost:9000/ocr")
            self.assertEqual(app_config.missing_models(config), [])

    def test_config_roundtrip_and_fingerprint_invalidates_ocr(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(app_config, "CONFIG_PATH", Path(temporary) / "config.yaml"):
            first = app_config.save_ai_config({"source_language": "en"})
            second = app_config.save_ai_config({"source_language": "custom", "custom_source_language": "fr",
                                               "custom_ocr_url": "http://localhost/ocr", "custom_ocr_api_key": "one"})
            self.assertEqual(second["custom_source_language"], "fr")
            self.assertNotEqual(app_config.config_fingerprint(first), app_config.config_fingerprint(second))
            changed = dict(second, custom_ocr_api_key="two")
            self.assertNotEqual(app_config.config_fingerprint(second), app_config.config_fingerprint(changed))

    def test_worker_snapshots_config(self):
        config = {"source_language": "en"}
        worker = BatchWorker([], Path("."), config)
        config["source_language"] = "ko"
        self.assertEqual(worker._config["source_language"], "en")


class CustomOcrTests(unittest.TestCase):
    def config(self, **kwargs):
        return dict(source_language="custom", custom_source_language="fr", custom_ocr_url="http://localhost/ocr",
                    custom_ocr_api_key="ocr-only-key", **kwargs)

    def client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_http_contract_preserves_spaces_and_uses_independent_key(self):
        def handle(request):
            self.assertEqual(request.headers["Authorization"], "Bearer ocr-only-key")
            data = json.loads(request.content)
            self.assertEqual(data["language"], "fr")
            self.assertEqual(data["mime_type"], "image/png")
            image = Image.open(io.BytesIO(base64.b64decode(data["image_base64"])))
            self.assertEqual(image.size, (23, 17))
            return httpx.Response(200, json={"text": "BONJOUR LE MONDE\nSALUT", "confidence": 0.94})
        client = self.client(handle)
        with patch("comic_translate_core.ocr.httpx.Client", return_value=client):
            result = create_ocr(self.config()).recognize(Image.new("RGB", (23, 17)), "fr")
        self.assertEqual(result.text, "BONJOUR LE MONDE\nSALUT")
        self.assertEqual(result.backend, "自定义 OCR")
        self.assertEqual(result.confidence, 0.94)

    def test_http_errors_do_not_leak_body_or_key(self):
        client = self.client(lambda _request: httpx.Response(401, text="secret-body ocr-only-key"))
        with patch("comic_translate_core.ocr.httpx.Client", return_value=client):
            with self.assertRaises(OcrError) as caught:
                CustomOcr(self.config()).recognize(Image.new("RGB", (2, 2)), "fr")
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("ocr-only-key", str(caught.exception))

    def test_invalid_json_and_scores_fail_instead_of_returning_empty_text(self):
        for data in ({}, {"text": 4}, {"text": "hello", "confidence": True}, {"text": "hello", "confidence": 1.1}):
            client = self.client(lambda _request: httpx.Response(200, json=data))
            with self.subTest(data=data), patch("comic_translate_core.ocr.httpx.Client", return_value=client):
                with self.assertRaises(OcrError):
                    CustomOcr(self.config()).recognize(Image.new("RGB", (2, 2)), "fr")

    def test_timeout_has_actionable_error(self):
        def handle(request):
            raise httpx.ReadTimeout("private request", request=request)
        client = self.client(handle)
        with patch("comic_translate_core.ocr.httpx.Client", return_value=client):
            with self.assertRaisesRegex(OcrError, "ReadTimeout"):
                CustomOcr(self.config()).recognize(Image.new("RGB", (2, 2)), "fr")

    def test_openai_vision_contract(self):
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Bonjour !"))])
        config = self.config(custom_ocr_protocol="openai", custom_ocr_model="vision-ocr")
        with patch("openai.OpenAI", return_value=client) as factory:
            result = create_ocr(config).recognize(Image.new("RGB", (5, 5)), "fr")
        self.assertEqual(result.text, "Bonjour !")
        self.assertEqual(factory.call_args.kwargs["api_key"], "ocr-only-key")
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "vision-ocr")
        self.assertTrue(request["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_line_aggregation_and_cancellation(self):
        engine = Mock(name="unused")
        engine.name, engine.uses_lines = "ppocr", True
        engine.recognize.side_effect = [OcrResult("HELLO WORLD", "en", "ppocr", .9), OcrResult("SECOND LINE", "en", "ppocr", .8)]
        image = Image.new("RGB", (2, 2))
        result = recognize_regions(engine, image, "en", [image, image])
        self.assertEqual(result.text, "HELLO WORLD\nSECOND LINE")
        check = Mock(side_effect=TaskCancelledError("cancelled"))
        engine.recognize.reset_mock()
        with self.assertRaises(TaskCancelledError):
            recognize_regions(engine, image, "en", [image], check)
        engine.recognize.assert_not_called()


class PipelineLanguageTests(unittest.TestCase):
    def test_japanese_english_preservation_does_not_apply_to_other_languages(self):
        box = (1, 1, 20, 20, 0, "dialogue", 16, 0, "eng")
        self.assertTrue(bare_pipeline("ja")._preserve_english(box))
        for language in ("en", "ko", "fr"):
            self.assertFalse(bare_pipeline(language)._preserve_english(box))
        pipeline = bare_pipeline("ja")
        pipeline.ocr_backend_active = "自定义 OCR"
        self.assertFalse(pipeline._preserve_english(box))

    def test_prompts_use_selected_language_including_continuation(self):
        for language, text in (("en", "HELLO"), ("ko", "안녕하세요"), ("fr", "Bonjour")):
            pipeline = bare_pipeline(language)
            client = Mock()
            client.chat.completions.create.side_effect = [
                SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"translations":["你好"]}'))]),
                SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"translations":["再见"]}'))]),
            ]
            with self.subTest(language=language), patch.object(pipeline_module, "OpenAI", return_value=client):
                self.assertEqual(pipeline.translate_page_batch([text, text], np.zeros((2, 2, 3), np.uint8)), ["你好", "再见"])
            for call in client.chat.completions.create.call_args_list:
                messages = call.kwargs["messages"]
                self.assertIn(pipeline.source_language_name, messages[0]["content"])
                self.assertIn(pipeline.source_language_name, messages[1]["content"][0]["text"])
                self.assertNotIn("日文", str(messages))

    def test_all_empty_ocr_does_not_request_translation(self):
        with patch.object(pipeline_module, "OpenAI") as api:
            self.assertEqual(bare_pipeline().translate_page_batch(["", "  "], None), ["", ""])
        api.assert_not_called()

    def test_english_is_kept_through_prepare_and_empty_result_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "page.png"
            image = Image.new("RGB", (100, 100), "white")
            ImageDraw.Draw(image).rectangle((20, 20, 70, 40), fill="black")
            image.save(path)
            pipeline = bare_pipeline()
            box = (10, 10, 80, 60, 0, "dialogue", 16, 0, "eng")
            pipeline.detect_bubbles = Mock(return_value=[box])
            pipeline.run_ocr = Mock(return_value="HELLO WORLD")
            pipeline.typesetter = Mock()
            prepared = pipeline.prepare_comic_page(path)
            self.assertEqual(prepared["ocr_texts"], ["HELLO WORLD"])
            self.assertEqual(prepared["bubble_metadata"][0]["source_language"], "en")
            output = root / "output.png"
            pipeline.finish_comic_page(output, prepared, [""])
            self.assertTrue(np.array_equal(np.asarray(image), np.asarray(Image.open(output))))
            pipeline.typesetter.draw_text.assert_not_called()

    def test_english_inpaint_is_no_longer_skipped(self):
        pipeline = bare_pipeline()
        image = np.full((100, 140, 3), 255, np.uint8)
        image[30:50, 30:70] = 0
        result = pipeline.inpaint_bubbles(image, [(20, 20, 90, 70, 0, "dialogue", 16, 0, "eng")])
        self.assertTrue(np.all(np.asarray(result)[30:50, 30:70] == 255))


class PPOcrTests(unittest.TestCase):
    def test_nested_detector_fragments_are_not_recognized_twice(self):
        polygons = [
            [[0, 40], [100, 40], [100, 60], [0, 60]],
            [[20, 5], [30, 5], [30, 15], [20, 15]],
            [[0, 0], [100, 0], [100, 20], [0, 20]],
        ]
        result = pipeline_module._unique_ocr_lines(polygons)
        self.assertEqual(len(result), 2)
        np.testing.assert_array_equal(result[0], polygons[2])
        np.testing.assert_array_equal(result[1], polygons[0])

    def test_ctc_blank_repetition_and_spaces(self):
        ocr = OnnxPPOcr.__new__(OnnxPPOcr)
        ocr.characters = ["", "A", "B", " "]
        ocr.input = SimpleNamespace(name="x")
        ids = [1, 1, 0, 1, 3, 3, 2, 0]
        logits = np.zeros((1, len(ids), 4), np.float32)
        for i, token in enumerate(ids):
            logits[0, i, token] = .95
        ocr.session = Mock()
        ocr.session.run.return_value = [logits]
        ocr.preprocess = Mock(return_value=np.zeros((1, 3, 48, 320)))
        text, confidence = ocr.recognize(Image.new("RGB", (10, 10)))
        self.assertEqual(text, "AA B")
        self.assertAlmostEqual(confidence, .95)

    def test_preprocess_channels_shape_and_normalization(self):
        ocr = OnnxPPOcr.__new__(OnnxPPOcr)
        ocr.height = 48
        ocr.input = SimpleNamespace(shape=[None, 3, 48, None])
        tensor = ocr.preprocess(Image.new("RGB", (100, 48), "red"))
        self.assertEqual(tensor.shape, (1, 3, 48, 320))
        np.testing.assert_array_equal(tensor[0, :, 0, 0], [-1, -1, 1])
        self.assertTrue(np.all(tensor[:, :, :, 100:] == 0))

    def test_real_models_when_installed(self):
        fonts = Path("C:/Windows/Fonts")
        models = ROOT / "comic-translate-ai/models/ppocr"
        if not (fonts / "malgun.ttf").is_file() or not (models / "korean_PP-OCRv5_rec_mobile.onnx").is_file():
            self.skipTest("Optional local models / Korean font are not installed")
        for language, text, font in (("en", "HELLO WORLD!", "arial.ttf"), ("korean", "안녕하세요", "malgun.ttf")):
            with self.subTest(language=language):
                ocr = OnnxPPOcr(str(models / f"{language}_PP-OCRv5_rec_mobile.onnx"))
                image = Image.new("RGB", (420, 75), "white")
                ImageDraw.Draw(image).text((15, 10), text, fill="black", font=ImageFont.truetype(str(fonts / font), 40))
                actual, score = ocr.recognize(image)
                self.assertEqual(actual, text)
                self.assertGreater(score, .85)

    def test_real_detector_multiline_crops_keep_edge_punctuation(self):
        from onnx_text_detector import OnnxTextDetector
        config = app_config.load_ai_config()
        fonts = Path("C:/Windows/Fonts")
        required = (config["detector_model"], config["korean_ocr_model"], config["english_ocr_model"], fonts / "malgun.ttf", fonts / "arial.ttf")
        if not all(Path(path).is_file() for path in required):
            self.skipTest("Optional local detector/OCR models and fonts are not installed")
        detector = OnnxTextDetector(config["detector_model"], input_size=1024, device="cpu")
        with tempfile.TemporaryDirectory() as temporary:
            for language, text, font in (("en", "HELLO WORLD!\nHOW ARE YOU?", "arial.ttf"), ("ko", "안녕하세요\n감사합니다", "malgun.ttf")):
                with self.subTest(language=language):
                    image = Image.new("RGB", (700, 500), "white")
                    draw = ImageDraw.Draw(image)
                    draw.ellipse((50, 50, 650, 450), outline="black", width=3)
                    draw.multiline_text((160, 170), text, font=ImageFont.truetype(str(fonts / font), 40), fill="black", spacing=24)
                    path = Path(temporary) / "page.png"
                    image.save(path)
                    pipeline = bare_pipeline(language)
                    pipeline.detector = detector
                    pipeline.ocr_engine = create_ocr({**config, "source_language": language, "ocr_backend": "auto"})
                    prepared = pipeline.prepare_comic_page(path)
                    actual = "\n".join(prepared["ocr_texts"])
                    self.assertEqual(actual, text)
                    self.assertTrue(all(item["ocr_confidence"] is not None for item in prepared["bubble_metadata"]))


class LanguageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_custom_form_roundtrip_and_clear_key(self):
        from comic_translate_desktop.ui.api_config_page import ApiConfigPage
        page = ApiConfigPage({"source_language": "custom", "custom_source_language": "fr", "custom_ocr_api_key": "secret"})
        self.assertEqual(page.values()["ocr_backend"], "custom")
        self.assertEqual(page.values()["custom_source_language"], "fr")
        page._custom_key.clear()
        self.assertEqual(page.values()["custom_ocr_api_key"], "")
        page._source_language.setCurrentIndex(page._source_language.findData("ko"))
        self.assertEqual(page._ocr_backend.findData("baberu"), -1)
        page.deleteLater()

    def test_main_language_switch_persists_and_invalidates_pipeline(self):
        from comic_translate_desktop.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as temporary, patch.object(app_config, "CONFIG_PATH", Path(temporary) / "config.yaml"), \
                patch.object(MainWindow, "_start_warmup"), patch.object(MainWindow, "_append_log"):
            window = MainWindow()
            window.pipeline = object()
            window._source_language.setCurrentIndex(window._source_language.findData("ko"))
            self.assertIsNone(window.pipeline)
            self.assertEqual(app_config.load_ai_config()["source_language"], "ko")
            self.assertEqual(window.api_config_page.values()["source_language"], "ko")
            window.api_config_page._source_language.setCurrentIndex(window.api_config_page._source_language.findData("en"))
            window._save_api_config()
            self.assertEqual(window._source_language.currentData(), "en")
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
