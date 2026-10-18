from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'comic-translate-ai/main'))
from punctuation_layout import wrap_vertical_text
from vertical_typesetter import VerticalTypesetter


class ManualLineBreakTests(unittest.TestCase):
    def test_legacy_and_invalid_default_alignment_normalize_to_center(self):
        from comic_translate_core.layout_options import normalize_vertical_alignment
        for value in (None, '', 'unknown', 7):
            self.assertEqual(normalize_vertical_alignment(value), 'center')
        for value in ('top', 'center', 'bottom'):
            self.assertEqual(normalize_vertical_alignment(value), value)

    def typesetter(self):
        return VerticalTypesetter({'dialogue': str(ROOT / 'comic-translate-ai/font_file/CN/special/LXGWWenKai-Regular.ttf')}, 24)

    def test_vertical_hard_breaks_blank_columns_and_line_endings(self):
        self.assertEqual(wrap_vertical_text('甲乙\n丙丁', 8), ['甲乙', '丙丁'])
        self.assertEqual(wrap_vertical_text('\n甲\n\n乙\n', 8), ['', '甲', '', '乙', ''])
        self.assertEqual(wrap_vertical_text('甲\r\n乙\r丙\u2028丁\u2029戊', 8), ['甲', '乙', '丙', '丁', '戊'])
        self.assertEqual(wrap_vertical_text('', 8), [])

    def test_manual_break_takes_precedence_over_automatic_kinsoku(self):
        self.assertEqual(wrap_vertical_text('甲（\n乙）', 2), ['甲（', '乙）'])
        self.assertEqual(wrap_vertical_text('甲乙丙丁\n戊己', 2), ['甲乙', '丙丁', '戊己'])

    def test_horizontal_hard_breaks_still_allow_overflow_wrapping(self):
        setter = self.typesetter()
        font = setter.fonts['dialogue']
        self.assertEqual(setter.wrap_text_horizontal('\n甲乙\n\n丙\n', 1000, font), ['', '甲乙', '', '丙', ''])
        self.assertEqual(setter.wrap_text_horizontal('甲\r\n乙\r丙', 1000, font), ['甲', '乙', '丙'])
        wrapped = setter.wrap_text_horizontal('甲乙丙丁戊己\n庚辛', 50, font)
        self.assertGreater(len(wrapped), 2)
        self.assertEqual(''.join(wrapped), '甲乙丙丁戊己庚辛')
        self.assertEqual(wrapped[-1], '庚辛')

    def test_vertical_columns_move_left_and_keep_blank_column(self):
        setter = self.typesetter()
        setter.draw_text(Image.new('RGB', (400, 600), 'white'), [40, 40, 360, 560],
                         '甲乙\n\n丙丁', 'dialogue', direction=1, target_font_size=32, manual_layout=True)
        cells = setter.last_layout_debug
        self.assertEqual([(v['char'], v['column']) for v in cells], [('甲', 0), ('乙', 0), ('丙', 2), ('丁', 2)])
        self.assertGreater(cells[0]['center_x'], cells[2]['center_x'])
        self.assertEqual(cells[0]['center_y'], cells[2]['center_y'])

    def test_horizontal_renderer_receives_separate_rows_and_empty_row(self):
        setter = self.typesetter()
        with patch.object(setter, '_draw_horizontal_row', wraps=setter._draw_horizontal_row) as draw:
            setter.draw_text(Image.new('RGB', (400, 600), 'white'), [40, 40, 360, 560],
                             '甲乙\n\n丙丁', 'dialogue', direction=0, target_font_size=32, manual_layout=True)
        self.assertEqual([call.args[1] for call in draw.call_args_list], ['甲乙', '', '丙丁'])
        self.assertLess(draw.call_args_list[0].args[5], draw.call_args_list[2].args[5])

    def test_vertical_top_center_bottom_align_columns_without_moving_group(self):
        setter = self.typesetter()
        for alignment in ('top', 'center', 'bottom'):
            with self.subTest(alignment=alignment):
                setter.draw_text(Image.new('RGB', (400, 600), 'white'), [40, 40, 360, 560],
                                 '甲乙\n\n丙丁戊己\n庚', 'dialogue', direction=1,
                                 target_font_size=32, manual_layout=True, vertical_alignment=alignment)
                columns = [[cell for cell in setter.last_layout_debug if cell['column'] == col]
                           for col in (0, 2, 3)]
                self.assertEqual([len(col) for col in columns], [2, 4, 1])
                if alignment == 'top':
                    self.assertEqual(len({col[0]['center_y'] for col in columns}), 1)
                elif alignment == 'bottom':
                    self.assertEqual(len({col[-1]['center_y'] for col in columns}), 1)
                else:
                    self.assertEqual({(col[0]['center_y'] + col[-1]['center_y']) / 2 for col in columns}, {300})
                longest = columns[1]
                self.assertEqual((longest[0]['center_y'] + longest[-1]['center_y']) / 2, 300)
                self.assertGreater(columns[0][0]['center_x'], columns[1][0]['center_x'])

    def test_vertical_default_and_unknown_alignment_preserve_centering(self):
        setter = self.typesetter()
        def render(**kwargs):
            image = Image.new('RGB', (400, 600), 'white')
            setter.draw_text(image, [40, 40, 360, 560], '甲乙\n丙丁戊己', 'dialogue', direction=1,
                             target_font_size=32, manual_layout=True, **kwargs)
            return image.tobytes()
        default = render()
        self.assertEqual(default, render(vertical_alignment='center'))
        self.assertEqual(default, render(vertical_alignment='unknown'))

    def test_vertical_alignment_does_not_change_horizontal_rendering(self):
        setter = self.typesetter()
        images = []
        for alignment in ('top', 'center', 'bottom'):
            image = Image.new('RGB', (400, 600), 'white')
            setter.draw_text(image, [40, 40, 360, 560], '甲乙\n丙丁戊己', 'dialogue', direction=0,
                             target_font_size=32, manual_layout=True, vertical_alignment=alignment)
            images.append(image.tobytes())
        self.assertEqual(images[0], images[1])
        self.assertEqual(images[1], images[2])


if __name__ == '__main__':
    unittest.main()
