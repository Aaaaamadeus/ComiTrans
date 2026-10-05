"""多模态字体选择（A′）：本地候选 + 模型 1-of-3 判别。

覆盖两层：
1. `font_probe` 的纯函数（路由、候选、许可表、精确率门控、解析、拼图）；
2. `configure_fonts` 的端到端行为（用假 OpenAI 客户端，不外网）。
"""
from __future__ import annotations

import json
import sys
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

import font_probe  # noqa: E402
import comic_translator_pipeline as pipeline_module  # noqa: E402
from comic_translator_pipeline import ComicTranslatorPipeline  # noqa: E402

CN = ROOT / "comic-translate-ai" / "font_file" / "CN"
FONT_MAP = {
    "dialogue": str(CN / "special" / "LXGWWenKai-Regular.ttf"),
    "narration": str(CN / "special" / "LXGWWenKai-Regular.ttf"),
    "bold_dialogue": str(CN / "SourceHanSansSC-Heavy-2.otf"),
    "title": str(CN / "SourceHanSansSC-Heavy-2.otf"),
    "serious": str(CN / "SourceHanSerifCN-Regular-1.otf"),
    "thought": str(CN / "SourceHanSerifCN-Regular-1.otf"),
    "tegaki_851": str(CN / "special" / "851tegaki_zatsu_normal_0883.ttf"),
    "handwriting": str(CN / "setofont.ttf"),
    "lxgw_marker": str(CN / "special" / "LXGWMarkerGothic-Regular.ttf"),
    "sfx": str(CN / "special" / "SmileySans-Oblique.ttf"),
}
IMAGE = np.full((260, 260, 3), 255, dtype=np.uint8)


def _pipeline(**overrides):
    pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
    pipeline.api_key = "test-key"
    pipeline.api_base_url = "https://example.invalid/v1"
    pipeline.translation_model = "test-model"
    pipeline.multimodal = True
    pipeline.multimodal_font_probe = True
    pipeline.disable_thinking = True
    pipeline.font_probe_samples = 1
    pipeline.typesetter = SimpleNamespace(font_map=dict(FONT_MAP))
    pipeline.font_probe_workers = 1
    for name, value in overrides.items():
        setattr(pipeline, name, value)
    return pipeline


def _block(style, text="今日はいい天気ですね", box=(20, 20, 180, 240), direction=1):
    return {"box": list(box), "raw": text, "style": style, "direction": direction}


class _ScriptedOpenAI:
    """按顺序回放 {"pick": ...}；记录每次请求，便于断言。"""

    picks: list[str] = []
    calls: list[dict] = []

    def __init__(self, **_kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        type(self).calls.append(kwargs)
        index = min(len(type(self).calls), len(type(self).picks)) - 1
        content = json.dumps({"pick": type(self).picks[index]})
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @classmethod
    def reset(cls, picks):
        cls.picks = list(picks)
        cls.calls = []


class FontProbePureTests(unittest.TestCase):
    def test_routing_only_covers_body_and_handwriting_roles(self):
        for role in font_probe.ROUTED_ROLES:
            self.assertTrue(font_probe.should_probe(role, "原文"), role)
        for role in font_probe.DECORATIVE_ROLES:
            self.assertFalse(font_probe.should_probe(role, "原文"), role)
        self.assertFalse(font_probe.should_probe("dialogue", "   "))

    def test_candidate_specs_need_all_three_families(self):
        specs = font_probe.candidate_specs(FONT_MAP)
        self.assertEqual([letter for letter, _, _ in specs], ["A", "B", "C"])
        self.assertEqual([family for _, family, _ in specs], ["gothic", "mincho", "handwriting"])
        incomplete = dict(FONT_MAP)
        incomplete.pop("serious")
        incomplete.pop("thought")
        self.assertEqual(font_probe.candidate_specs(incomplete), [])

    def test_local_permission_table_keeps_role_when_family_unknown(self):
        self.assertEqual(font_probe.resolve_style("dialogue", "gothic"), "lxgw_marker")
        self.assertEqual(font_probe.resolve_style("narration", "mincho"), "serious")
        self.assertEqual(font_probe.resolve_style("bold_dialogue", "gothic"), "bold_dialogue")
        self.assertEqual(font_probe.resolve_style("bold_dialogue", "handwriting"), "handwriting")
        self.assertEqual(font_probe.resolve_style("dialogue", None), "dialogue")
        self.assertEqual(font_probe.resolve_style("dialogue", "not-a-family"), "dialogue")

    def test_precision_gate_rejects_uncalibrated_families(self):
        self.assertTrue(font_probe.accept_family("gothic"))
        self.assertFalse(font_probe.accept_family("brush"))  # 未校准 → 不采纳
        self.assertFalse(font_probe.accept_family(None))
        with patch.dict(font_probe.PRECISION_GATE, {"gothic": 0.4}):
            self.assertFalse(font_probe.accept_family("gothic"))

    def test_parse_pick_accepts_letters_and_rejects_everything_else(self):
        self.assertEqual(font_probe.parse_pick('{"pick":"A"}'), ("A", "gothic"))
        self.assertEqual(font_probe.parse_pick('```json\n{"pick": " c "}\n```'), ("C", "handwriting"))
        self.assertEqual(font_probe.parse_pick('{"pick":"none"}'), (None, None))
        self.assertEqual(font_probe.parse_pick('{"pick":"Z"}'), (None, None))
        self.assertEqual(font_probe.parse_pick(""), (None, None))
        self.assertEqual(font_probe.parse_pick("字体是黑体"), (None, None))

    def test_probe_prompt_never_names_a_font_family(self):
        prompt = font_probe.probe_prompt()
        for word in ("黑体", "宋体", "手写", "marker", "文楷", "font_style", "font_size"):
            self.assertNotIn(word, prompt)
        self.assertIn('"pick":"A"', prompt)
        self.assertIn("none", prompt)
        # 字号必须被显式禁止，而不是留给模型自由发挥
        self.assertIn("不要输出字号", prompt)

    def test_sheet_stacks_original_and_three_candidates(self):
        crop = Image.new("RGB", (120, 180), "black")
        specs = font_probe.candidate_specs(FONT_MAP)
        sheet = font_probe.build_probe_sheet(
            crop, "今日はいい天気ですね", specs, direction=1, glyph_px=48
        )
        self.assertLess(sheet.convert("L").getextrema()[0], 60)  # 原图块内容是黑的
        # 四格竖向堆叠：高度至少 4 个面板 + 3 个间隔
        self.assertGreaterEqual(sheet.height, 4 * 52 + font_probe.PANEL_GAP * 3)
        self.assertGreater(sheet.width, 0)

    def test_candidates_are_rendered_at_the_original_glyph_size(self):
        """候选与原图必须同尺寸，否则模型会比大小而不是比字形。"""
        crop = Image.new("RGB", (120, 180), "white")
        specs = font_probe.candidate_specs(FONT_MAP)
        small = font_probe.build_probe_sheet(crop, "あいうえおか", specs, direction=1, glyph_px=22)
        large = font_probe.build_probe_sheet(crop, "あいうえおか", specs, direction=1, glyph_px=48)
        # 22px 的字号会触发等比放大，48px 不会；两者都不应是同一张图
        self.assertNotEqual(small.size, large.size)

    def test_horizontal_and_vertical_sheets_both_render_ink(self):
        crop = Image.new("RGB", (200, 90), "white")
        specs = font_probe.candidate_specs(FONT_MAP)
        for direction in (0, 1):
            sheet = font_probe.build_probe_sheet(crop, "今日はいい天気", specs, direction=direction)
            self.assertLess(sheet.convert("L").getextrema()[0], 200, f"direction={direction} 没有画出字")


class ConfigureFontsTests(unittest.TestCase):
    def test_routed_blocks_take_the_model_pick_through_the_local_table(self):
        metadata = [
            _block("dialogue"),      # A=gothic → lxgw_marker
            _block("handwriting"),   # C=handwriting → handwriting
            _block("sfx"),           # 装饰类：不外发
        ]
        _ScriptedOpenAI.reset(["A", "C"])
        with patch.object(pipeline_module, "OpenAI", _ScriptedOpenAI):
            result = _pipeline().configure_fonts(metadata, IMAGE)
        self.assertEqual(result[0]["font_style"], "lxgw_marker")
        self.assertEqual(result[0]["family"], "gothic")
        self.assertEqual(result[1]["font_style"], "handwriting")
        self.assertNotIn(2, result)
        self.assertEqual(len(_ScriptedOpenAI.calls), 2)

    def test_contract_carries_no_font_size_or_style_name(self):
        _ScriptedOpenAI.reset(["B"])
        with patch.object(pipeline_module, "OpenAI", _ScriptedOpenAI):
            result = _pipeline().configure_fonts([_block("dialogue")], IMAGE)
        self.assertEqual(set(result[0]), {"font_style", "family"})
        sent = json.dumps(_ScriptedOpenAI.calls[0], ensure_ascii=False, default=str)
        self.assertNotIn("font_size", sent)
        self.assertNotIn("font_style", sent)  # 契约里连风格名都不出现

    def test_decorative_roles_never_reach_the_model(self):
        metadata = [_block(role) for role in font_probe.DECORATIVE_ROLES]
        _ScriptedOpenAI.reset(["A"] * len(metadata))
        with patch.object(pipeline_module, "OpenAI", _ScriptedOpenAI):
            result = _pipeline().configure_fonts(metadata, IMAGE)
        self.assertEqual(result, {})
        self.assertEqual(_ScriptedOpenAI.calls, [])

    def test_none_pick_and_model_failure_keep_the_local_decision(self):
        _ScriptedOpenAI.reset(["none"])
        with patch.object(pipeline_module, "OpenAI", _ScriptedOpenAI):
            self.assertEqual(_pipeline().configure_fonts([_block("dialogue")], IMAGE), {})

        class _Failing(_ScriptedOpenAI):
            def _create(self, **kwargs):
                raise RuntimeError("API down")

        with patch.object(pipeline_module, "OpenAI", _Failing):
            self.assertEqual(_pipeline().configure_fonts([_block("dialogue")], IMAGE), {})

    def test_missing_candidate_fonts_skips_the_whole_step(self):
        partial = dict(FONT_MAP)
        partial.pop("tegaki_851")
        partial.pop("handwriting")
        _ScriptedOpenAI.reset(["A"])
        with patch.object(pipeline_module, "OpenAI", _ScriptedOpenAI):
            pipeline = _pipeline()
            pipeline.typesetter = SimpleNamespace(font_map=partial)
            self.assertEqual(pipeline.configure_fonts([_block("dialogue")], IMAGE), {})
        self.assertEqual(_ScriptedOpenAI.calls, [])

    def test_configure_fonts_is_skipped_without_multimodal(self):
        class _Exploding(_ScriptedOpenAI):
            def _create(self, **kwargs):  # pragma: no cover - 不应被调用
                raise AssertionError("非多模态模式不得调用字体判别接口")

        with patch.object(pipeline_module, "OpenAI", _Exploding):
            result = _pipeline(multimodal=False).configure_fonts([_block("dialogue")], IMAGE)
        self.assertEqual(result, {})

    def test_probe_call_disables_thinking_and_bounds_output(self):
        """判别调用必须关思考并限制输出：实测思考会吃满预算并返回空。"""
        _ScriptedOpenAI.reset(["A"])
        with patch.object(pipeline_module, "OpenAI", _ScriptedOpenAI):
            _pipeline().configure_fonts([_block("dialogue")], IMAGE)
        sent = _ScriptedOpenAI.calls[0]
        # OpenAI SDK 会拒绝未知关键字参数，必须走 extra_body 透传
        self.assertEqual(sent.get("extra_body"), {"thinking": {"type": "disabled"}})
        self.assertEqual(sent.get("max_tokens"), pipeline_module.PROBE_MAX_TOKENS)

    def test_multi_sample_voting_needs_a_majority(self):
        """三次采样两票一致才采纳；三票分散则弃权保留本地判定。"""
        with patch.object(pipeline_module, "OpenAI", _ScriptedOpenAI):
            _ScriptedOpenAI.reset(["A", "A", "C"])
            agreed = _pipeline(font_probe_samples=3).configure_fonts([_block("dialogue")], IMAGE)
            self.assertEqual(agreed[0]["font_style"], "lxgw_marker")
            self.assertEqual(len(_ScriptedOpenAI.calls), 3)

            _ScriptedOpenAI.reset(["A", "B", "C"])
            scattered = _pipeline(font_probe_samples=3).configure_fonts([_block("dialogue")], IMAGE)
            self.assertEqual(scattered, {})
            self.assertEqual(len(_ScriptedOpenAI.calls), 3)


class PickMajorityTests(unittest.TestCase):
    def test_majority_rules(self):
        self.assertEqual(font_probe.pick_majority(["gothic", "gothic", "handwriting"]), "gothic")
        self.assertEqual(font_probe.pick_majority(["gothic", "gothic"]), "gothic")
        self.assertEqual(font_probe.pick_majority(["gothic"]), "gothic")
        self.assertIsNone(font_probe.pick_majority(["gothic", "mincho", "handwriting"]))
        # 有效票不足样本数一半（模型多次没给出可解析结果）时弃权
        self.assertIsNone(font_probe.pick_majority(["gothic", None, None]))
        self.assertIsNone(font_probe.pick_majority(["mincho", "mincho", None, None, None]))
        self.assertIsNone(font_probe.pick_majority([]))

    def test_font_probe_is_off_by_default_even_in_multimodal_mode(self):
        """实测真实页面上判定不稳定且昂贵，因此默认关闭，只做翻译。"""
        class _Exploding(_ScriptedOpenAI):
            def _create(self, **kwargs):  # pragma: no cover - 不应被调用
                raise AssertionError("字体判别默认关闭时不得调用接口")

        with patch.object(pipeline_module, "OpenAI", _Exploding):
            result = _pipeline(multimodal_font_probe=False).configure_fonts([_block("dialogue")], IMAGE)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
