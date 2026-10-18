from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MAIN_DIR = ROOT / "comic-translate-ai" / "main"
if str(MAIN_DIR) not in sys.path:
    sys.path.insert(0, str(MAIN_DIR))

from punctuation_layout import (
    FORBIDDEN_COLUMN_END,
    FORBIDDEN_COLUMN_START,
    normalize_cjk_punctuation,
    tokenize_punctuation,
    vertical_form,
    wrap_vertical_text,
)
from vertical_typesetter import VerticalTypesetter


class PunctuationNormalizationTests(unittest.TestCase):
    def test_cjk_ellipsis_is_a_logical_token(self):
        tokens = tokenize_punctuation("等等...真的？！")
        self.assertIn("…", [token.text for token in tokens])
        self.assertNotIn(".", [token.text for token in tokens])
        self.assertIn("？！", [token.text for token in tokens])

    def test_six_dots_become_two_cell_chinese_ellipsis(self):
        tokens = tokenize_punctuation("等等......真的")
        ellipsis = next(token for token in tokens if token.text == "……")
        self.assertEqual(ellipsis.cells, 2)

    def test_double_em_dash_stays_a_two_cell_token(self):
        tokens = tokenize_punctuation("甲——乙")
        dash = next(token for token in tokens if token.text == "——")
        self.assertEqual(dash.cells, 2)

    def test_entire_punctuation_run_is_one_token_including_alternate_forms(self):
        for run in ('…………', '————', '――', '—―︱', '…⋯︙', '‥︰'):
            with self.subTest(run=run):
                tokens = tokenize_punctuation('甲' + run + '乙')
                self.assertEqual([token.text for token in tokens], ['甲', run, '乙'])
                self.assertEqual(tokens[1].cells, len(run))

    def test_numbers_urls_and_english_punctuation_are_preserved(self):
        source = "时间 9:05，价格 3.14 元。URL https://example.com..."
        normalized = normalize_cjk_punctuation(source)
        self.assertIn("9:05", normalized)
        self.assertIn("3.14", normalized)
        self.assertIn("https://example.com...", normalized)
        self.assertEqual(normalize_cjk_punctuation("Hello..."), "Hello...")
        self.assertEqual(normalize_cjk_punctuation("中文 (test)"), "中文 (test)")

    def test_ascii_punctuation_next_to_cjk_is_normalized(self):
        self.assertEqual(
            normalize_cjk_punctuation("真的?! (小声),别来!"),
            "真的？！ （小声），别来！",
        )


class VerticalKinsokuTests(unittest.TestCase):
    def test_continuous_punctuation_is_not_split_at_column_boundary(self):
        for run in ('……', '…………', '——', '————', '――', '—―︱', '…⋯︙', '‥︰'):
            for capacity in (1, 2, 3, 4, 5):
                with self.subTest(run=run, capacity=capacity):
                    columns = wrap_vertical_text('甲乙' + run + '丙丁', capacity)
                    self.assertEqual(''.join(columns), '甲乙' + run + '丙丁')
                    self.assertEqual(sum(run in column for column in columns), 1)

    def test_explicit_break_between_punctuation_still_starts_a_new_column(self):
        self.assertEqual(wrap_vertical_text('……\n……', 8), ['……', '……'])
        self.assertEqual(wrap_vertical_text('——\n――', 8), ['——', '――'])

    def test_closing_punctuation_never_starts_a_column(self):
        columns = wrap_vertical_text("甲乙，丙丁。戊", 2)
        self.assertTrue(columns)
        self.assertTrue(all(column[0] not in FORBIDDEN_COLUMN_START for column in columns))
        self.assertFalse(any(not column for column in columns))

    def test_opening_punctuation_never_ends_a_column(self):
        columns = wrap_vertical_text("甲（乙）丙「丁」", 2)
        self.assertTrue(all(column[-1] not in FORBIDDEN_COLUMN_END for column in columns))

    def test_vertical_forms_cover_common_punctuation(self):
        for char in "，。、：；！？…—（）【】《》「」『』":
            self.assertIsNotNone(vertical_form(char), char)


class PunctuationRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cn = ROOT / "comic-translate-ai" / "font_file" / "CN"
        cls.font_map = {
            "dialogue": str(cn / "SourceHanSansSC-Medium-2.otf"),
            "thought": str(cn / "SourceHanSerifCN-Regular-1.otf"),
            "narration": str(cn / "special" / "LXGWWenKai-Regular.ttf"),
            "radiating": str(cn / "special" / "SmileySans-Oblique.ttf"),
            "bold_dialogue": str(cn / "SourceHanSansSC-Heavy-2.otf"),
        }

    def _typesetter(self):
        return VerticalTypesetter(self.font_map, 24)

    def test_vertical_punctuation_uses_equal_cell_advance(self):
        typesetter = self._typesetter()
        image = Image.new("RGB", (420, 760), "white")
        typesetter.draw_text(
            image,
            [150, 30, 270, 720],
            "字，字。字！字？字：字；字、字",
            "dialogue",
            direction=1,
            target_font_size=32,
        )
        cells = [item for item in typesetter.last_layout_debug if item["column"] == 0]
        self.assertGreater(len(cells), 8)
        advances = np.diff([item["center_y"] for item in cells])
        self.assertLessEqual(float(np.ptp(advances)), 1.0)

        gray = np.asarray(image.convert("L"))
        for item in cells:
            half = item["cell_size"] // 2 + 3
            x = int(round(item["center_x"]))
            y = int(round(item["center_y"]))
            crop = gray[max(0, y - half):y + half + 1, max(0, x - half):x + half + 1]
            self.assertTrue(np.any(crop < 160), item["char"])

    def test_all_styles_and_sizes_render_punctuation_without_crashing(self):
        samples = (
            "“真的……可以吗？”",
            "（小声）别、别过来！",
            "第一，准备；第二，开始。",
            "你好——世界！？",
        )
        for style in ("dialogue", "thought", "narration", "radiating"):
            for size in (12, 16, 24, 36):
                with self.subTest(style=style, size=size):
                    typesetter = self._typesetter()
                    image = Image.new("RGB", (500, 850), "white")
                    typesetter.draw_text(
                        image,
                        [150, 30, 350, 810],
                        samples[size % len(samples)],
                        style,
                        direction=1,
                        target_font_size=size,
                    )
                    self.assertIsNotNone(image.getbbox())
                    self.assertTrue(np.any(np.asarray(image.convert("L")) < 160))

    def test_horizontal_baseline_preserves_numeric_punctuation(self):
        typesetter = self._typesetter()
        image = Image.new("RGB", (900, 260), "white")
        text = "时间 9:05，价格 3.14 元……真的？！"
        typesetter.draw_text(
            image,
            [40, 60, 860, 200],
            text,
            "dialogue",
            direction=0,
            target_font_size=36,
        )
        self.assertEqual(normalize_cjk_punctuation(text), text)
        self.assertEqual(typesetter.last_direction, "horizontal")
        self.assertTrue(np.any(np.asarray(image.convert("L")) < 160))

    def test_dialogue_rendering_uses_supersampling_without_hard_outline(self):
        typesetter = self._typesetter()
        image = Image.new("RGB", (540, 260), "white")
        typesetter.draw_text(
            image,
            [40, 50, 500, 210],
            "圆润自然的漫画对白",
            "dialogue",
            direction=0,
            target_font_size=26,
        )

        self.assertEqual(typesetter.last_render_scale, 3)
        self.assertEqual(typesetter._stroke_width("dialogue", 26), 0)
        self.assertGreater(typesetter._stroke_width("dialogue", 26, non_bubble=True), 0)
        gray = np.asarray(image.convert("L"))
        self.assertTrue(np.any((gray > 0) & (gray < 255)))

    def test_vertical_double_em_dash_is_one_continuous_long_line(self):
        typesetter = self._typesetter()
        image = Image.new("RGB", (260, 420), "white")
        typesetter.draw_text(
            image,
            [90, 40, 170, 380],
            "——",
            "dialogue",
            direction=1,
            target_font_size=40,
        )

        gray = np.asarray(image.convert("L"))
        ys, xs = np.nonzero(gray < 180)
        self.assertGreater(ys.size, 0)
        width = int(xs.max() - xs.min() + 1)
        height = int(ys.max() - ys.min() + 1)
        self.assertGreater(height, width * 8)
        occupied_rows = np.any(gray[ys.min():ys.max() + 1] < 220, axis=1)
        self.assertGreater(float(occupied_rows.mean()), 0.97)

        dash_cells = [item for item in typesetter.last_layout_debug if item["char"] == "—"]
        self.assertEqual(len(dash_cells), 2)
        midpoint_y = int(round((dash_cells[0]["center_y"] + dash_cells[1]["center_y"]) / 2))
        midpoint_x = int(round(dash_cells[0]["center_x"]))
        self.assertLess(int(gray[midpoint_y, midpoint_x]), 100)

    @staticmethod
    def occupied_row_bands(image):
        occupied = np.any(np.asarray(image.convert('L')) < 180, axis=1)
        edges = np.flatnonzero(np.diff(np.r_[False, occupied, False]))
        return edges.reshape(-1, 2)

    def test_ellipsis_dots_are_even_across_character_boundaries_and_fonts(self):
        fonts = (*self.font_map.values(),
                 str(ROOT / 'comic-translate-ai/font_file/TC/01-GenSenRounded/GenSenRounded2TW-R.otf'),
                 str(ROOT / 'comic-translate-ai/font_file/Manga/SweiB2Sans/SweiB2SansCJKtc-Black.ttf'))
        for path in fonts:
            for text, count in (('……', 6), ('…⋯︙', 9), ('‥︰', 4)):
                for size in (12, 24, 48):
                    with self.subTest(font=path, text=text, size=size):
                        setter = VerticalTypesetter({'dialogue': path}, size)
                        image = Image.new('RGB', (300, 400), 'white')
                        setter.draw_text(image, [40, 20, 260, 380], text, 'dialogue',
                                         direction=1, target_font_size=size, manual_layout=True)
                        bands = self.occupied_row_bands(image)
                        self.assertEqual(len(bands), count)
                        centers = bands.mean(axis=1)
                        self.assertLessEqual(float(np.ptp(np.diff(centers))), 1.5)
                        self.assertEqual({cell['column'] for cell in setter.last_layout_debug}, {0})

    def test_alternate_and_mixed_dashes_render_as_one_unbroken_vertical_line(self):
        for text in ('―', '――', '︱︱', '—―︱', '————'):
            for effect in ('auto', 'outlined', 'hollow'):
                with self.subTest(text=text, effect=effect):
                    setter = self._typesetter()
                    image = Image.new('RGB', (300, 400), 'white')
                    setter.draw_text(image, [40, 20, 260, 380], text, 'dialogue',
                                     direction=1, target_font_size=40, manual_layout=True,
                                     text_effect=effect)
                    bands = self.occupied_row_bands(image)
                    self.assertEqual(len(bands), 1)
                    gray = np.asarray(image.convert('L'))
                    ys, xs = np.nonzero(gray < 180)
                    self.assertGreater(int(ys.max() - ys.min()), int(xs.max() - xs.min()) * 2)
                    self.assertEqual(''.join(cell['char'] for cell in setter.last_layout_debug), text)

    def test_automatic_fit_moves_whole_runs_together_within_box(self):
        for run in ('…………', '————', '――――'):
            with self.subTest(run=run):
                setter = self._typesetter()
                image = Image.new('RGB', (300, 300), 'white')
                setter.draw_text(image, [40, 70, 260, 230], '甲乙' + run + '丙丁',
                                 'dialogue', direction=1, target_font_size=40)
                cells = [cell for cell in setter.last_layout_debug if cell['char'] in run]
                self.assertEqual(len(cells), len(run))
                self.assertEqual(len({cell['column'] for cell in cells}), 1)
                self.assertGreaterEqual(min(cell['center_y'] - cell['cell_size'] / 2 for cell in cells),
                                        setter.last_layout_box[1])
                self.assertLessEqual(max(cell['center_y'] + cell['cell_size'] / 2 for cell in cells),
                                     setter.last_layout_box[3])


if __name__ == "__main__":
    unittest.main()
