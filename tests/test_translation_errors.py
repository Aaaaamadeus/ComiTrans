from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MAIN_DIR = ROOT / "comic-translate-ai" / "main"
if str(MAIN_DIR) not in sys.path:
    sys.path.insert(0, str(MAIN_DIR))

import comic_translator_pipeline as pipeline_module
from comic_translator_pipeline import (
    ComicTranslatorPipeline,
    TranslationError,
    _parse_translation_response,
)

from comic_translate_desktop.worker import BatchWorker


def _pipeline(api_key: str = "", base_url: str = "", model: str = ""):
    pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
    pipeline.api_key = api_key
    pipeline.api_base_url = base_url
    pipeline.translation_model = model
    pipeline.translation_prompt = ""
    pipeline.chinese_names = ""
    pipeline.multimodal = False
    pipeline.progress_callback = None
    return pipeline


class _FakeOpenAI:
    response_content = ""

    def __init__(self, **_kwargs):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )

    def _create(self, **_kwargs):
        message = SimpleNamespace(content=self.response_content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _BalanceError(Exception):
    status_code = 402


class _BalanceFailingOpenAI(_FakeOpenAI):
    def _create(self, **_kwargs):
        raise _BalanceError("Error code: 402 - Insufficient Balance")


class _TruncatedThenCompleteOpenAI(_FakeOpenAI):
    calls = []
    responses = [
        '{"translations": ["呜……", "寒天里淘米……也太冷了吧……！！",',
        '{"translations": ["马上就来", "今年最后一顿饭了啊"]}',
    ]

    def _create(self, **kwargs):
        self.__class__.calls.append(kwargs)
        content = self.__class__.responses[len(self.__class__.calls) - 1]
        message = SimpleNamespace(content=content)
        reason = "length" if len(self.__class__.calls) == 1 else "stop"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason=reason)]
        )


class TranslationErrorTests(unittest.TestCase):
    def test_translation_request_progress_has_no_undefined_identifiers(self):
        _FakeOpenAI.response_content = '{"translations": ["你好"]}'
        pipeline = _pipeline("sk-secret-value", "https://example.invalid/v1", "demo-model")
        progress_events = []
        pipeline.progress_callback = lambda stage, message: progress_events.append(
            (stage, message)
        )

        with patch.object(pipeline_module, "OpenAI", _FakeOpenAI):
            result = pipeline.translate_page_batch(
                ["こんにちは"], np.zeros((2, 2, 3), dtype=np.uint8)
            )

        self.assertEqual(result, ["你好"])
        self.assertIn(
            ("translate", "正在请求翻译 API: demo-model，1 条文本"),
            progress_events,
        )

    def test_recovers_only_complete_items_from_truncated_json(self):
        content = '{"translations": ["呜……", "寒天里淘米……也太冷了吧……！！", "未完成'
        items, complete = _parse_translation_response(content)
        self.assertFalse(complete)
        self.assertEqual(items, ["呜……", "寒天里淘米……也太冷了吧……！！"])

    def test_truncated_response_continues_only_missing_suffix(self):
        _TruncatedThenCompleteOpenAI.calls = []
        pipeline = _pipeline("sk-secret-value", "https://example.invalid/v1", "demo-model")
        source = ["うう", "寒い", "すぐ行く", "今年最後"]
        with patch.object(pipeline_module, "OpenAI", _TruncatedThenCompleteOpenAI):
            result = pipeline.translate_page_batch(
                source, np.zeros((2, 2, 3), dtype=np.uint8)
            )

        self.assertEqual(
            result,
            ["呜……", "寒天里淘米……也太冷了吧……！！", "马上就来", "今年最后一顿饭了啊"],
        )
        self.assertEqual(len(_TruncatedThenCompleteOpenAI.calls), 2)
        second_prompt = _TruncatedThenCompleteOpenAI.calls[1]["messages"][1]["content"][0]["text"]
        self.assertIn("[2] すぐ行く", second_prompt)
        self.assertNotIn("[0] うう", second_prompt)
        self.assertEqual(_TruncatedThenCompleteOpenAI.calls[0]["max_tokens"], 8192)

    def test_blank_page_does_not_require_api(self):
        self.assertEqual(
            _pipeline().translate_page_batch([], np.zeros((1, 1, 3), dtype=np.uint8)),
            [],
        )

    def test_missing_configuration_raises_actionable_error(self):
        with self.assertRaisesRegex(TranslationError, "API Key.*Base URL.*翻译模型"):
            _pipeline().translate_page_batch(
                ["こんにちは"], np.zeros((2, 2, 3), dtype=np.uint8)
            )

    def test_invalid_json_preserves_actual_failure(self):
        _FakeOpenAI.response_content = "not json"
        pipeline = _pipeline("sk-secret-value", "https://example.invalid/v1", "demo-model")
        with patch.object(pipeline_module, "OpenAI", _FakeOpenAI):
            with self.assertRaisesRegex(TranslationError, "不是合法 JSON.*not json"):
                pipeline.translate_page_batch(
                    ["こんにちは"], np.zeros((2, 2, 3), dtype=np.uint8)
                )

    def test_http_402_is_reported_as_fatal_balance_error(self):
        pipeline = _pipeline("sk-secret-value", "https://example.invalid/v1", "demo-model")
        with patch.object(pipeline_module, "OpenAI", _BalanceFailingOpenAI):
            with self.assertRaisesRegex(TranslationError, "余额不足") as caught:
                pipeline.translate_page_batch(
                    ["こんにちは"], np.zeros((2, 2, 3), dtype=np.uint8)
                )
        self.assertTrue(caught.exception.fatal)

    def test_worker_does_not_call_finish_after_translation_failure(self):
        class FailingPipeline:
            finish_calls = 0

            def prepare_comic_page(self, _path):
                return {
                    "ocr_texts": ["こんにちは"],
                    "img_cv": np.zeros((2, 2, 3), dtype=np.uint8),
                }

            def translate_page_batch(self, _texts, _image):
                raise TranslationError("鉴权失败，请检查 API Key")

            def finish_comic_page(self, _output, _prepared, _translations):
                self.finish_calls += 1

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / "page.png"
            Image.new("RGB", (20, 20), "white").save(source)
            fake = FailingPipeline()
            worker = BatchWorker(
                [source],
                root / "output",
                {
                    "api_key": "sk-secret-value",
                    "api_base_url": "https://example.invalid/v1",
                    "translation_model": "demo-model",
                    "max_workers": 1,
                    "pdf_dpi": 96,
                },
                pipeline=fake,
            )
            failures = []
            logs = []
            results = []
            worker.image_failed.connect(lambda name, message: failures.append((name, message)))
            worker.log.connect(logs.append)
            worker.finished.connect(lambda success, failed: results.append((success, failed)))

            worker.run()

            self.assertEqual(fake.finish_calls, 0)
            self.assertEqual(results, [(0, 1)])
            self.assertEqual(failures, [("page.png", "鉴权失败，请检查 API Key")])
            self.assertFalse(any("finish_comic_page" in line for line in logs))
            self.assertFalse(any("翻译 API 未打通" in line for line in logs))

    def test_fatal_api_error_stops_scheduling_remaining_files(self):
        class FailingPipeline:
            translate_calls = 0
            finish_calls = 0

            def prepare_comic_page(self, _path):
                return {
                    "ocr_texts": ["こんにちは"],
                    "img_cv": np.zeros((2, 2, 3), dtype=np.uint8),
                }

            def translate_page_batch(self, _texts, _image):
                self.translate_calls += 1
                raise TranslationError("账户余额不足", fatal=True)

            def finish_comic_page(self, _output, _prepared, _translations):
                self.finish_calls += 1

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            sources = []
            for index in range(3):
                source = root / f"page_{index}.png"
                Image.new("RGB", (20, 20), "white").save(source)
                sources.append(source)
            fake = FailingPipeline()
            worker = BatchWorker(
                sources,
                root / "output",
                {
                    "api_key": "sk-secret-value",
                    "api_base_url": "https://example.invalid/v1",
                    "translation_model": "demo-model",
                    "max_workers": 1,
                    "pdf_dpi": 96,
                },
                pipeline=fake,
            )
            results = []
            worker.finished.connect(lambda success, failed: results.append((success, failed)))

            worker.run()

            self.assertEqual(fake.translate_calls, 1)
            self.assertEqual(fake.finish_calls, 0)
            self.assertEqual(results, [(0, 3)])


if __name__ == "__main__":
    unittest.main()
