"""多模态字体配置：契约不再包含字号（字号由本地排版算法决定）。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MAIN_DIR = ROOT / "comic-translate-ai" / "main"
if str(MAIN_DIR) not in sys.path:
    sys.path.insert(0, str(MAIN_DIR))

from comic_translator_pipeline import ComicTranslatorPipeline  # noqa: E402
import comic_translator_pipeline as pipeline_module  # noqa: E402


def _pipeline(**overrides):
    pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
    pipeline.api_key = "test-key"
    pipeline.api_base_url = "https://example.invalid/v1"
    pipeline.translation_model = "test-model"
    pipeline.multimodal = True
    for name, value in overrides.items():
        setattr(pipeline, name, value)
    return pipeline


class _RecordingOpenAI:
    """Records the request and replays a canned response (including a stray font_size)."""

    captured: dict = {}
    response_content = "{}"

    def __init__(self, **_kwargs):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create),
        )

    def _create(self, **kwargs):
        type(self).captured = kwargs
        message = SimpleNamespace(content=type(self).response_content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


IMAGE = np.zeros((60, 60, 3), dtype=np.uint8)


class MultimodalFontConfigTests(unittest.TestCase):
    def test_prompt_no_longer_requests_font_size(self):
        _RecordingOpenAI.response_content = json.dumps({"items": []})
        with patch.object(pipeline_module, "OpenAI", _RecordingOpenAI):
            _pipeline().configure_fonts(["原文"], ["译文"], IMAGE)
        system_prompt = _RecordingOpenAI.captured["messages"][0]["content"]
        self.assertNotIn("font_size", system_prompt)
        self.assertIn("不要返回字号", system_prompt)

    def test_stray_font_size_from_model_is_ignored(self):
        _RecordingOpenAI.response_content = json.dumps(
            {
                "items": [
                    {
                        "index": 0,
                        "font_style": "handwriting",
                        "font_size": 99,
                        "direction": "vertical",
                    }
                ]
            }
        )
        with patch.object(pipeline_module, "OpenAI", _RecordingOpenAI):
            result = _pipeline().configure_fonts(["原文"], ["译文"], IMAGE)
        self.assertEqual(result[0], {"font_style": "handwriting", "direction": 1})
        self.assertNotIn("font_size", result[0])

    def test_invalid_style_still_falls_back_to_dialogue(self):
        _RecordingOpenAI.response_content = json.dumps(
            {"items": [{"index": 0, "font_style": "not-a-style", "direction": "horizontal"}]}
        )
        with patch.object(pipeline_module, "OpenAI", _RecordingOpenAI):
            result = _pipeline().configure_fonts(["原文"], ["译文"], IMAGE)
        self.assertEqual(result[0], {"font_style": "dialogue", "direction": 0})

    def test_configure_fonts_is_skipped_without_multimodal(self):
        class _Exploding(_RecordingOpenAI):
            def _create(self, **kwargs):  # pragma: no cover - must never run
                raise AssertionError("非多模态模式不得调用字体配置接口")

        with patch.object(pipeline_module, "OpenAI", _Exploding):
            self.assertEqual(_pipeline(multimodal=False).configure_fonts(["原文"], ["译文"], IMAGE), {})


if __name__ == "__main__":
    unittest.main()
