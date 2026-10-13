from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image, ImageChops
from PySide6.QtCore import QSettings, Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from comic_translate_desktop import config
from comic_translate_desktop.font_library import font_reference, import_font
from comic_translate_desktop.ui.editor_page import EditorPage


class EditorLivePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.preferences = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.preferences.name)

    @classmethod
    def tearDownClass(cls):
        cls.preferences.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        setting = patch.object(config, 'CONFIG_PATH', self.root / 'config.yaml')
        setting.start()
        self.addCleanup(setting.stop)

    def page(self, name='page', *, legacy=False, two_blocks=False):
        output = self.root / 'output' / f'{name}.png'
        cleaned = self.root / 'output_cleaned' / f'{name}_cleaned.png'
        layout = self.root / 'output_layout' / f'{name}_layout.json'
        for path in (output, cleaned, layout):
            path.parent.mkdir(exist_ok=True)
        image = Image.new('RGB', (600, 700), '#ffeedd')
        image.save(output)
        image.save(cleaned)
        item = dict(text='故事从这里开始，继续向前。', source_text='物語の始まり。',
                    box=[100, 90, 290, 340], style='dialogue', direction=0,
                    font_size=24, rendered_font_size=24, offset_x=0, offset_y=0,
                    custom_metadata='keep')
        if not legacy:
            item['mask_box'] = [100, 90, 290, 340]
        items = [item]
        if two_blocks:
            items.append(dict(item, text='第二个文本块', box=[330, 390, 560, 620],
                              mask_box=[330, 390, 560, 620], font_size=20, rendered_font_size=20))
        layout.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
        return output, layout

    def editor(self, output):
        editor = EditorPage()
        editor.load_page(output)
        self.addCleanup(editor.close)
        return editor

    def wait_preview(self, editor):
        QTest.qWait(100)
        self.assertFalse(editor._preview_timer.isActive())
        self.assertFalse(editor._preview_dirty, editor._status.text())
        self.assertIsNotNone(editor._rendered)

    @staticmethod
    def ink_box(image):
        return ImageChops.difference(image, Image.new('RGB', image.size, '#ffeedd')).getbbox()

    def test_font_size_updates_pixels_automatically_and_honors_single_pixel_changes(self):
        output, layout = self.page()
        before_output, before_layout = output.read_bytes(), layout.read_bytes()
        editor = self.editor(output)
        editor._size_spin.setValue(31)
        self.wait_preview(editor)
        first = editor._rendered.copy()
        self.assertEqual(editor.items[0]['rendered_font_size'], 31)
        editor._size_spin.setValue(32)
        self.wait_preview(editor)
        self.assertEqual(editor.items[0]['rendered_font_size'], 32)
        self.assertIsNotNone(ImageChops.difference(first, editor._rendered).getbbox())
        self.assertEqual(output.read_bytes(), before_output)
        self.assertEqual(layout.read_bytes(), before_layout)

    def test_manual_font_style_overrides_translation_default_and_restores_after_save(self):
        default = config.AI_ROOT / config.FONT_DEFAULTS['bold_dialogue']
        config.save_ai_config({'translation_font': font_reference(default)})
        output, layout = self.page()
        editor = self.editor(output)
        editor.apply_changes()
        before = editor._rendered.copy()
        editor._style_combo.setCurrentIndex(editor._style_combo.findData('serious'))
        self.wait_preview(editor)
        self.assertIsNotNone(ImageChops.difference(before, editor._rendered).getbbox())
        self.assertTrue(editor.save_image())
        self.assertEqual(json.loads(layout.read_text(encoding='utf-8'))[0]['font_reference'],
                         font_reference(config.AI_ROOT / config.FONT_DEFAULTS['serious']))
        restored = self.editor(output)
        restored.apply_changes()
        self.assertEqual(restored._rendered.tobytes(), editor._rendered.tobytes())
        restored._style_combo.setCurrentIndex(restored._style_combo.findData(''))
        self.wait_preview(restored)
        self.assertNotIn('font_reference', restored.items[0])
        self.assertEqual(restored._rendered.tobytes(), before.tobytes())

    def test_manual_font_keeps_supported_characters_when_some_glyphs_need_fallback(self):
        latin = Path(__file__).resolve().parents[1] / 'assets/ui/fonts/Skribble.ttf'
        config.save_ai_config({'font_handwriting': str(latin)})
        output, _ = self.page()
        editor = self.editor(output)
        editor._text_input.setPlainText('漫画 ABC')
        editor._style_combo.setCurrentIndex(editor._style_combo.findData('handwriting'))
        self.wait_preview(editor)
        from vertical_typesetter import VerticalTypesetter
        expected = editor._cleaned_image.copy()
        explicit = VerticalTypesetter({style: str(latin) for style in config.FONT_KEYS}, 16,
                                      fallback_fonts=editor.config['font_fallbacks'])
        explicit.draw_text(expected, editor._mask_box(editor.items[0]), '漫画 ABC', 'handwriting',
                           direction=0, target_font_size=24, manual_layout=True)
        self.assertEqual(editor._rendered.tobytes(), expected.tobytes())
        chosen = editor._typesetter_for_item(editor.items[0])
        self.assertEqual(chosen._font_path_for_char('handwriting', 'A'), str(latin))
        chinese = chosen._font_path_for_char('handwriting', '漫')
        self.assertNotEqual(chinese, str(latin))
        self.assertTrue(chosen._font_supports(chinese, '漫'))
        with patch.object(chosen, '_get_font_for_char', wraps=chosen._get_font_for_char) as glyph_font:
            editor._layer_cache.clear()
            editor.render()
        self.assertIn('handwriting', [call.args[0] for call in glyph_font.call_args_list])
        self.assertNotIn('narration', [call.args[0] for call in glyph_font.call_args_list])

    def test_imported_font_is_local_to_block_and_survives_default_changes_and_reload(self):
        with patch.object(config, 'PROJECT_ROOT', self.root):
            source = self.root / 'original.ttf'
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'assets/ui/fonts/Skribble.ttf', source)
            imported = import_font(source)
            reference = font_reference(imported.path)
            output, layout = self.page(two_blocks=True)
            editor = self.editor(output)
            editor._text_input.setPlainText('漫画 ABC')
            index = editor._style_combo.findData(reference)
            self.assertGreaterEqual(index, 0)
            editor._style_combo.setCurrentIndex(index)
            editor.block_list.setCurrentRow(1)
            self.wait_preview(editor)
            self.assertEqual(editor.items[0]['font_reference'], reference)
            self.assertNotIn('font_reference', editor.items[1])
            first_layer = editor._layer_cache[0][1].tobytes()
            second_layer = editor._layer_cache[1][1].tobytes()
            updated = config.save_ai_config({'translation_font': font_reference(config.AI_ROOT / config.FONT_DEFAULTS['bold_dialogue'])})
            editor.set_translation_fonts(updated)
            self.assertEqual(editor._layer_cache[0][1].tobytes(), first_layer)
            self.assertNotEqual(editor._layer_cache[1][1].tobytes(), second_layer)
            self.assertTrue(editor.save_image())
            self.assertEqual(json.loads(layout.read_text(encoding='utf-8'))[0]['font_reference'], reference)
            source.unlink()
            restored = self.editor(output)
            self.assertEqual(restored._style_combo.currentData(), reference)
            restored.apply_changes()
            self.assertEqual(restored._rendered.tobytes(), editor._rendered.tobytes())

    def test_missing_saved_font_is_visible_and_can_be_replaced_without_losing_text(self):
        output, layout = self.page()
        items = json.loads(layout.read_text(encoding='utf-8'))
        items[0]['font_reference'] = 'user_fonts/missing.ttf'
        layout.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
        editor = self.editor(output)
        self.assertIn('不可用', editor._style_combo.currentText())
        self.assertIn('回退', editor._style_combo.toolTip())
        self.assertFalse(editor._style_combo.model().item(editor._style_combo.currentIndex()).isEnabled())
        editor._style_combo.setCurrentIndex(editor._style_combo.findData('serious'))
        self.wait_preview(editor)
        self.assertEqual(editor.items[0]['text'], items[0]['text'])
        self.assertTrue(editor.save_image())
        self.assertNotEqual(editor.items[0]['font_reference'], 'user_fonts/missing.ttf')

    def test_font_search_text_does_not_change_the_page_before_a_real_selection(self):
        output, layout = self.page()
        editor = self.editor(output)
        original = output.read_bytes(), layout.read_bytes()
        editor._style_combo.lineEdit().setText('查找字体的关键词')
        QTest.qWait(100)
        self.assertFalse(editor._dirty)
        self.assertFalse(editor._preview_timer.isActive())
        self.assertNotIn('font_reference', editor.items[0])
        self.assertEqual((output.read_bytes(), layout.read_bytes()), original)

    def test_font_library_choice_applies_only_to_current_editor_block(self):
        output, _ = self.page(two_blocks=True)
        editor = self.editor(output)
        reference = font_reference(config.AI_ROOT / config.FONT_DEFAULTS['bold_dialogue'])
        with patch('comic_translate_desktop.ui.font_library_dialog.FontLibraryDialog') as library:
            library.return_value.exec.return_value = 1
            library.return_value.reference = reference
            editor._open_font_library()
        self.wait_preview(editor)
        self.assertEqual(editor.items[0]['font_reference'], reference)
        self.assertNotIn('font_reference', editor.items[1])

    def test_xy_offsets_move_preview_by_the_exact_number_of_pixels(self):
        output, _ = self.page()
        editor = self.editor(output)
        editor._size_spin.setValue(30)
        self.wait_preview(editor)
        initial = self.ink_box(editor._rendered)
        editor._offset_x.setValue(17)
        self.wait_preview(editor)
        horizontal = self.ink_box(editor._rendered)
        self.assertEqual(horizontal, tuple(value + (17 if i % 2 == 0 else 0) for i, value in enumerate(initial)))
        editor._offset_y.setValue(13)
        self.wait_preview(editor)
        self.assertEqual(self.ink_box(editor._rendered), tuple(value + (13 if i % 2 else 0) for i, value in enumerate(horizontal)))

    def test_mask_resizing_changes_wrapping_and_survives_save_and_reload(self):
        output, layout = self.page()
        editor = self.editor(output)
        editor._size_spin.setValue(27)
        self.wait_preview(editor)
        initial = editor._rendered.copy()
        editor._mask_width.setValue(100)
        editor._mask_height.setValue(300)
        self.wait_preview(editor)
        self.assertEqual(editor.preview._label.region, (145, 65, 245, 365))
        self.assertEqual(editor.typesetter.last_layout_box, [145.0, 65.0, 245.0, 365.0])
        self.assertIsNotNone(ImageChops.difference(initial, editor._rendered).getbbox())
        self.assertTrue(editor.save_image())
        saved = json.loads(layout.read_text(encoding='utf-8'))[0]
        self.assertEqual((saved['mask_width'], saved['mask_height']), (100, 300))
        self.assertEqual(saved['box'], [100, 90, 290, 340])
        self.assertEqual(saved['custom_metadata'], 'keep')
        restored = self.editor(output)
        self.assertEqual((restored._mask_width.value(), restored._mask_height.value()), (100, 300))
        self.assertEqual(restored._size_spin.value(), 27)
        restored.apply_changes()
        self.assertEqual(restored._rendered.tobytes(), editor._rendered.tobytes())

    def test_immediate_save_flushes_pending_inputs_and_exports_current_pixels_without_guide(self):
        output, layout = self.page()
        editor = self.editor(output)
        editor._size_spin.setKeyboardTracking(False)
        editor._size_spin.lineEdit().setText('43')
        editor._offset_x.setValue(29)
        editor._offset_y.setValue(-17)
        editor._mask_width.setValue(240)
        self.assertTrue(editor._preview_timer.isActive())
        self.assertTrue(editor.save_image())
        self.assertFalse(editor._preview_timer.isActive())
        with Image.open(output) as saved:
            self.assertEqual(saved.tobytes(), editor._rendered.tobytes())
        item = json.loads(layout.read_text(encoding='utf-8'))[0]
        self.assertEqual((item['font_size'], item['rendered_font_size'], item['offset_x'], item['offset_y']), (43, 43, 29, -17))
        rendered = editor._rendered.tobytes()
        editor._show_mask.setChecked(False)
        self.assertIsNone(editor.preview._label.region)
        self.assertFalse(editor._dirty)
        self.assertEqual(editor._rendered.tobytes(), rendered)
        self.assertEqual(editor.preview._original.toImage().pixelColor(0, 0).name(), '#ffeedd')

    def test_pending_preview_keeps_edits_attached_to_their_text_block(self):
        output, _ = self.page(two_blocks=True)
        editor = self.editor(output)
        editor._size_spin.setValue(35)
        editor._offset_x.setValue(-12)
        editor.block_list.setCurrentRow(1)
        self.wait_preview(editor)
        self.assertEqual(editor.items[0]['font_size'], 35)
        self.assertEqual(editor.items[0]['offset_x'], -12)
        self.assertEqual(editor.items[1]['font_size'], 20)
        self.assertEqual(editor.items[1]['offset_x'], 0)
        editor.block_list.setCurrentRow(0)
        self.assertEqual(editor._size_spin.value(), 35)

    def test_hot_preview_reuses_other_blocks_and_matches_a_full_render(self):
        output, _ = self.page(two_blocks=True)
        editor = self.editor(output)
        editor._size_spin.setValue(30)
        self.wait_preview(editor)
        with patch.object(editor.typesetter, 'draw_text', wraps=editor.typesetter.draw_text) as draw:
            editor._size_spin.setValue(31)
            self.wait_preview(editor)
        self.assertEqual(draw.call_count, 1)
        cached = editor._rendered.tobytes()
        editor._layer_cache.clear()
        editor.render()
        self.assertEqual(editor._rendered.tobytes(), cached)
        editor._text_input.setPlainText('')
        self.wait_preview(editor)
        erased = editor._rendered.tobytes()
        self.assertNotEqual(erased, cached)
        editor._layer_cache.clear()
        editor.render()
        self.assertEqual(editor._rendered.tobytes(), erased)

    def test_discarding_a_page_cancels_its_pending_preview(self):
        first, _ = self.page('first')
        second, _ = self.page('second')
        original = second.read_bytes()
        editor = self.editor(first)
        editor._offset_x.setValue(50)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            self.assertTrue(editor.load_page(second))
        QTest.qWait(100)
        self.assertIsNone(editor._rendered)
        self.assertFalse(editor._dirty)
        self.assertEqual(editor._offset_x.value(), 0)
        self.assertEqual(second.read_bytes(), original)

    def test_failed_hot_preview_cannot_save_stale_pixels_and_can_be_retried(self):
        output, layout = self.page()
        editor = self.editor(output)
        editor._size_spin.setValue(28)
        self.wait_preview(editor)
        originals = output.read_bytes(), layout.read_bytes()
        with patch.object(editor.typesetter, 'draw_text', side_effect=RuntimeError('排版失败')):
            editor._size_spin.setValue(38)
            QTest.qWait(100)
            self.assertIn('预览失败', editor._status.text())
            self.assertTrue(editor._preview_dirty)
            self.assertFalse(editor.save_image())
        self.assertEqual((output.read_bytes(), layout.read_bytes()), originals)
        self.assertTrue(editor._dirty)
        self.assertTrue(editor.save_image())
        self.assertEqual(editor.items[0]['rendered_font_size'], 38)

    def test_legacy_layout_recovers_region_without_changing_files_on_open(self):
        output, layout = self.page(legacy=True)
        originals = output.read_bytes(), layout.read_bytes()
        editor = self.editor(output)
        self.assertTrue(editor.items[0]['mask_box'])
        self.assertTrue(editor.save_image())
        self.assertEqual((output.read_bytes(), layout.read_bytes()), originals)
        editor._mask_width.setValue(editor._mask_width.value() + 20)
        self.wait_preview(editor)
        self.assertTrue(editor.save_image())
        self.assertIn('mask_box', json.loads(layout.read_text(encoding='utf-8'))[0])

    def test_new_pipeline_region_reproduces_original_typesetting_in_editor(self):
        import numpy as np
        from comic_translator_pipeline import ComicTranslatorPipeline
        output, layout = self.page()
        image = Image.new('RGB', (600, 700), '#ffeedd')
        pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
        pipeline.source_language = 'en'
        pipeline.multimodal = pipeline.watermark_enabled = False
        pipeline.progress_callback = pipeline.cancel_callback = None
        probe = EditorPage()
        self.addCleanup(probe.close)
        pipeline.typesetter = probe.typesetter
        pipeline.inpaint_bubbles = lambda *_: image.copy()
        mask = Image.new('L', image.size, 0)
        from PIL import ImageDraw
        ImageDraw.Draw(mask).rectangle([150, 110, 250, 210], fill=255)
        pipeline.current_mask_image = mask
        prepared = dict(img_cv=np.asarray(image)[:, :, ::-1],
                        bubbles_data=[(100, 90, 290, 340, 0, 'dialogue', 24, 0)],
                        bubble_metadata=[dict(raw='Beginning', box=[100, 90, 290, 340],
                                              style='dialogue', direction=0, target_font_size=24,
                                              non_bubble=False, source_language='en')],
                        ocr_texts=['Beginning'])
        pipeline.finish_comic_page(output, prepared, ['故事从这里开始。'])
        item = json.loads(layout.read_text(encoding='utf-8'))[0]
        self.assertEqual(item['mask_box'], pipeline.typesetter.last_layout_box)
        self.assertEqual(item['rendered_font_size'], pipeline.typesetter.last_font_size)
        editor = self.editor(output)
        self.assertTrue(editor.apply_changes())
        with Image.open(output) as original:
            self.assertEqual(editor._rendered.tobytes(), original.tobytes())

    def test_manual_render_preserves_odd_sized_region_center_and_auto_size_option(self):
        output, _ = self.page()
        editor = self.editor(output)
        for direction in (0, 1):
            with self.subTest(direction=direction):
                editor._direction_combo.setCurrentIndex(editor._direction_combo.findData(direction))
                editor._mask_width.setValue(191)
                editor._mask_height.setValue(251)
                editor._size_spin.setValue(7)
                self.wait_preview(editor)
                self.assertEqual(editor.items[0]['rendered_font_size'], 7)
                box = editor.typesetter.last_layout_box
                self.assertEqual(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), (195, 215))
        editor._size_spin.setValue(0)
        self.wait_preview(editor)
        self.assertGreater(editor.items[0]['rendered_font_size'], 0)
        self.assertEqual(editor.items[0]['font_size'], 0)

    def canvas_editor(self, output, zoom=1):
        editor = self.editor(output)
        editor.resize(1400, 900)
        editor.show()
        editor.preview.set_zoom(zoom)
        self.app.processEvents()
        return editor

    def drag_mask(self, editor, handle, dx, dy, *, release=True):
        canvas = editor.preview._label
        start = canvas.region_rect().center() if handle == 'move' else canvas._region_handles()[handle]
        page = canvas.page_rect()
        end = start + QPointF(dx * page.width() / canvas.image_size.width(),
                              dy * page.height() / canvas.image_size.height())
        QTest.mouseMove(canvas, start.toPoint())
        QTest.mousePress(canvas, Qt.LeftButton, pos=start.toPoint())
        self.assertIsNotNone(canvas._region_drag)
        QTest.mouseMove(canvas, end.toPoint(), delay=10)
        if release:
            QTest.mouseRelease(canvas, Qt.LeftButton, pos=end.toPoint())
        return canvas, end.toPoint()

    def test_all_eight_handles_resize_freely_and_keep_the_opposite_edge_fixed(self):
        output, _ = self.page()
        editor = self.canvas_editor(output)
        cases = {
            'nw': (-20, -15, (80, 75, 290, 340)),
            'ne': (20, -15, (100, 75, 310, 340)),
            'sw': (-20, 15, (80, 90, 290, 355)),
            'se': (20, 15, (100, 90, 310, 355)),
            'n': (0, -15, (100, 75, 290, 340)),
            's': (0, 15, (100, 90, 290, 355)),
            'w': (-20, 0, (80, 90, 290, 340)),
            'e': (20, 0, (100, 90, 310, 340)),
        }
        for handle, (dx, dy, expected) in cases.items():
            with self.subTest(handle=handle):
                editor._resize_region_from_canvas((100, 90, 290, 340))
                canvas, _ = self.drag_mask(editor, handle, dx, dy)
                self.assertEqual(canvas.region, expected)
                self.assertEqual(editor._mask_width.value(), expected[2] - expected[0])
                self.assertEqual(editor._mask_height.value(), expected[3] - expected[1])
                self.assertFalse(editor._preview_dirty)

    def test_drag_updates_hot_preview_before_release_and_saves_exact_geometry(self):
        output, layout = self.page()
        original = output.read_bytes()
        editor = self.canvas_editor(output)
        canvas, end = self.drag_mask(editor, 'se', 61, 33, release=False)
        self.wait_preview(editor)
        self.assertEqual(canvas.region, (100, 90, 351, 373))
        self.assertIsNotNone(canvas._region_drag)
        self.assertEqual(output.read_bytes(), original)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=end)
        self.assertTrue(editor.save_image())
        with Image.open(output) as saved:
            self.assertEqual(saved.tobytes(), editor._rendered.tobytes())
        data = json.loads(layout.read_text(encoding='utf-8'))[0]
        self.assertEqual((data['mask_width'], data['mask_height']), (251, 283))
        self.assertEqual(data['box'], [100, 90, 290, 340])
        restored = self.editor(output)
        self.assertEqual(restored.preview._label.region, (100, 90, 351, 373))

    def test_drag_coordinate_mapping_works_at_half_normal_and_double_zoom(self):
        for zoom in (.5, 1, 2):
            with self.subTest(zoom=zoom):
                output, _ = self.page(f'zoom-{zoom}')
                editor = self.canvas_editor(output, zoom)
                canvas, _ = self.drag_mask(editor, 'se', 40, 30)
                self.assertEqual(canvas.region, (100, 90, 330, 370))

    def test_focus_canvas_drag_and_scrolling_keep_image_coordinates(self):
        output, _ = self.page()
        editor = self.canvas_editor(output, 2)
        editor._focus_btn.setChecked(True)
        self.app.processEvents()
        editor.preview._scroll.horizontalScrollBar().setValue(80)
        editor.preview._scroll.verticalScrollBar().setValue(120)
        self.app.processEvents()
        canvas, _ = self.drag_mask(editor, 'se', 35, 25)
        self.assertEqual(canvas.region, (100, 90, 325, 365))
        self.assertEqual(editor._mask_width.value(), 225)
        self.assertFalse(editor._properties_panel.isVisible())

    def test_region_body_drag_moves_without_resizing_and_escape_restores_shape(self):
        output, _ = self.page()
        editor = self.canvas_editor(output)
        canvas, _ = self.drag_mask(editor, 'move', 37, -21)
        self.assertEqual(canvas.region, (137, 69, 327, 319))
        self.assertEqual((editor._offset_x.value(), editor._offset_y.value()), (37, -21))
        self.assertEqual((editor._mask_width.value(), editor._mask_height.value()), (190, 250))
        self.drag_mask(editor, 'nw', -10, -10, release=False)
        QTest.keyClick(canvas, Qt.Key_Escape)
        self.assertEqual(canvas.region, (137, 69, 327, 319))
        self.assertIsNone(canvas._region_drag)

    def test_drag_handles_enforce_minimum_size_and_page_bounds(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent
        output, _ = self.page()
        editor = self.canvas_editor(output)
        canvas = editor.preview._label
        for handle, delta, expected in (
            ('w', QPointF(1000, 0), (289, 90, 290, 340)),
            ('se', QPointF(1000, 1000), (100, 90, 600, 700)),
        ):
            editor._resize_region_from_canvas((100, 90, 290, 340))
            start = canvas._region_handles()[handle]
            QTest.mousePress(canvas, Qt.LeftButton, pos=start.toPoint())
            event = QMouseEvent(QEvent.MouseMove, start + delta, start + delta,
                                Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
            self.app.sendEvent(canvas, event)
            self.assertEqual(canvas.region, expected)
            canvas.cancel_region_drag()

    def test_hiding_mask_or_switching_blocks_cancels_drag_without_editing_new_block(self):
        output, _ = self.page(two_blocks=True)
        editor = self.canvas_editor(output)
        canvas, end = self.drag_mask(editor, 'se', 20, 10, release=False)
        editor.block_list.setCurrentRow(1)
        self.assertIsNone(canvas._region_drag)
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=end)
        self.assertEqual(editor.items[0]['mask_width'], 210)
        self.assertEqual(editor.items[1]['offset_x'], 0)
        self.assertNotIn('mask_width', editor.items[1])
        self.drag_mask(editor, 'nw', 10, 10, release=False)
        editor._show_mask.setChecked(False)
        self.assertIsNone(canvas._region_drag)
        self.assertIsNone(canvas.region)

    def test_read_only_preview_has_no_drag_handles_or_region_edits(self):
        output, _ = self.page()
        editor = self.canvas_editor(output)
        canvas = editor.preview._label
        editor.preview.set_region((100, 90, 290, 340))
        start = canvas.region_rect().bottomRight().toPoint()
        edits = []
        canvas.region_edited.connect(edits.append)
        QTest.mousePress(canvas, Qt.LeftButton, pos=start)
        QTest.mouseMove(canvas, start + QPointF(30, 20).toPoint())
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=start)
        self.assertEqual(edits, [])
        self.assertEqual(canvas.region, (100, 90, 290, 340))

    def test_losing_mouse_capture_or_changing_zoom_ends_the_drag(self):
        from PySide6.QtCore import QEvent
        output, _ = self.page()
        editor = self.canvas_editor(output)
        canvas, _ = self.drag_mask(editor, 'se', 10, 10, release=False)
        self.app.sendEvent(canvas, QEvent(QEvent.UngrabMouse))
        self.assertIsNone(canvas._region_drag)
        canvas.cancel_region_drag()
        self.drag_mask(editor, 'se', 10, 10, release=False)
        editor.preview.set_zoom(.5)
        self.assertIsNone(canvas._region_drag)
        self.drag_mask(editor, 'se', 10, 10, release=False)
        canvas.hide()
        self.assertIsNone(canvas._region_drag)


if __name__ == '__main__':
    unittest.main()
