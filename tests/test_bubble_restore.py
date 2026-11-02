import json
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QFileDialog

from comic_translate_core.restoration import (
    save_original, find_original, original_snapshot_path, make_region,
    decode_region, protected_region,
)
from tests import test_editor_live_preview as fixtures


class BubbleRestoreTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EditorLivePreviewTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.EditorLivePreviewTests.tearDownClass.__func__)
    setUp = fixtures.EditorLivePreviewTests.setUp
    page = fixtures.EditorLivePreviewTests.page
    editor = fixtures.EditorLivePreviewTests.editor

    @staticmethod
    def destroy_editor(editor):
        editor._dirty = False
        fixtures.EditorLivePreviewTests.destroy_editor(editor)

    def page_with_original(self, name='restore'):
        output, layout = self.page(name, two_blocks=True)
        original = Image.new('RGB', (600, 700), '#ffeedd')
        draw = ImageDraw.Draw(original)
        draw.rectangle((115, 110, 150, 160), fill='#192837')
        draw.rectangle((95, 175, 104, 200), fill='#334455')  # padded edge
        draw.rectangle((350, 410, 390, 440), fill='#b12345')
        save_original(output, original)
        return output, layout, original

    def test_restore_one_bubble_preserves_neighbour_and_original_text_settings(self):
        output, _, original = self.page_with_original()
        editor = self.editor(output)
        editor.apply_changes()
        baseline = editor._rendered.copy()
        text = editor.items[0]['text']
        cleaned = editor._cleaned_image.tobytes()
        editor._restore_bubble_btn.click()
        self.assertTrue(editor.items[0]['restore_original'])
        self.assertEqual(editor.items[0]['text'], text)
        self.assertEqual(editor._rendered.crop((100,90,290,340)).tobytes(), original.crop((100,90,290,340)).tobytes())
        self.assertEqual(editor._rendered.getpixel((98,180)), original.getpixel((98,180)))
        self.assertEqual(editor._rendered.crop((330,390,560,620)).tobytes(), baseline.crop((330,390,560,620)).tobytes())
        self.assertEqual(editor._cleaned_image.tobytes(), cleaned)
        self.assertFalse(editor._text_input.isEnabled())
        self.assertTrue(editor._save_btn.isEnabled())
        self.assertTrue(editor.toggle_bubble_original())
        self.assertEqual(editor._rendered.tobytes(), baseline.tobytes())
        self.assertTrue(editor._text_input.isEnabled())
        editor._dirty = False

    def test_save_reopen_restoration_and_restore_processed_result(self):
        output, layout, original = self.page_with_original()
        editor = self.editor(output)
        editor.apply_changes()
        processed = editor._rendered.tobytes()
        self.assertTrue(editor.toggle_bubble_original())
        restored = editor._rendered.tobytes()
        self.assertTrue(editor.save_image())
        self.assertTrue(json.loads(layout.read_text(encoding='utf-8'))[0]['restore_original'])
        reopened = self.editor(output)
        self.assertTrue(reopened.apply_changes())
        self.assertEqual(reopened._rendered.tobytes(), restored)
        self.assertTrue(reopened.toggle_bubble_original())
        self.assertEqual(reopened._rendered.tobytes(), processed)
        self.assertTrue(reopened.save_image())

    def test_bubbles_can_be_restored_independently_across_background_undo(self):
        output, _, original = self.page_with_original()
        editor = self.editor(output)
        editor.apply_changes()
        baseline = editor._rendered.copy()
        editor._accept_background_repair((5,5,50,50), Image.new('RGB', (45,45), '#778899'))
        self.assertTrue(editor.toggle_bubble_original())
        editor.block_list.setCurrentRow(1)
        self.assertTrue(editor.toggle_bubble_original())
        self.assertTrue(editor.undo_background_repair())
        self.assertTrue(editor._dirty)
        self.assertTrue(all(item['restore_original'] for item in editor.items))
        self.assertEqual(editor._rendered.crop((100,90,290,340)).tobytes(), original.crop((100,90,290,340)).tobytes())
        self.assertEqual(editor._rendered.crop((330,390,560,620)).tobytes(), original.crop((330,390,560,620)).tobytes())
        self.assertTrue(editor.toggle_bubble_original())
        self.assertEqual(editor._rendered.crop((330,390,560,620)).tobytes(), baseline.crop((330,390,560,620)).tobytes())
        self.assertTrue(editor.items[0]['restore_original'])
        self.assertEqual(find_original(output), original_snapshot_path(output))

    def test_restore_tracks_original_box_when_translation_was_moved(self):
        output, _, original = self.page_with_original()
        editor = self.editor(output)
        editor._offset_x.setValue(170)
        editor._offset_y.setValue(-40)
        editor.apply_changes()
        self.assertTrue(editor.toggle_bubble_original())
        region = (100,90,290,340)
        self.assertEqual(editor._rendered.crop(region).tobytes(), original.crop(region).tobytes())
        # The moved translated layer disappears in its entirety, too.
        expected = self.editor(output)
        expected.items[0]['text'] = ''
        expected.apply_changes()
        self.assertEqual(editor._rendered.crop((295,60,500,300)).tobytes(), expected._rendered.crop((295,60,500,300)).tobytes())
        editor._dirty = False

    def test_missing_original_cancel_wrong_size_and_link_success(self):
        output, _, original = self.page_with_original()
        original_snapshot_path(output).unlink()
        editor = self.editor(output)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=('', '')):
            self.assertFalse(editor.toggle_bubble_original())
        self.assertFalse(editor.items[0].get('restore_original'))
        wrong = self.root / 'wrong.png'
        Image.new('RGB',(30,30)).save(wrong)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(wrong), '')):
            self.assertFalse(editor.toggle_bubble_original())
        self.assertFalse(original_snapshot_path(output).exists())
        source = self.root / 'source.png'
        original.save(source)
        with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(source), '')):
            self.assertTrue(editor.toggle_bubble_original())
        self.assertTrue(original_snapshot_path(output).is_file())
        self.assertTrue(editor.save_image())

    def test_failed_save_keeps_restoration_draft_and_old_files(self):
        output, layout, _ = self.page_with_original()
        editor = self.editor(output)
        before = output.read_bytes(), layout.read_bytes(), editor.cleaned_path.read_bytes()
        self.assertTrue(editor.toggle_bubble_original())
        with patch('comic_translate_desktop.ui.editor_page.save_editor_files', side_effect=OSError('locked')):
            self.assertFalse(editor.save_image())
        self.assertEqual(before, (output.read_bytes(), layout.read_bytes(), editor.cleaned_path.read_bytes()))
        self.assertTrue(editor._dirty)
        self.assertTrue(editor.items[0]['restore_original'])
        self.assertTrue(editor.save_image())

    def test_restored_region_is_protected_from_manual_repair_and_watermark(self):
        output, layout, original = self.page_with_original()
        editor = self.editor(output)
        editor.config['watermark_enabled'] = True
        editor.items[0]['box'] = [0,0,600,700]
        self.assertTrue(editor.toggle_bubble_original())
        self.assertEqual(editor._rendered.tobytes(), original.tobytes())
        editor._repair_mode.click()
        editor._resize_region_from_canvas((10,10,60,60))
        self.assertFalse(editor._repair_btn.isEnabled())
        self.assertTrue(editor.toggle_bubble_original())
        self.assertTrue(editor._repair_btn.isEnabled())
        editor._dirty = False

    def test_restore_metadata_covers_exact_padded_mask_and_protects_neighbour(self):
        mask = Image.new('L',(80,80))
        mask.paste(255,(0,15,75,30))
        first = {'box':[20,20,60,60], 'original_region':make_region([20,20,60,60],(120,120),(5,5,85,85),mask)}
        second = {'box':[65,20,90,60]}
        bounds, restored = protected_region(first,[first,second],(120,120))
        self.assertEqual(restored.getpixel((10-bounds[0],25-bounds[1])),255)
        self.assertEqual(restored.getpixel((70-bounds[0],25-bounds[1])),0)
        self.assertEqual(restored.getpixel((21-bounds[0],21-bounds[1])),255)
        first['original_region']['box'] = [0,0,999,999]
        with self.assertRaises(ValueError):
            decode_region(first,(120,120))

    def test_jpeg_restoration_saves_lossless_copy_and_keeps_old_files(self):
        output, layout, original = self.page_with_original()
        jpeg = output.with_suffix('.jpg')
        with Image.open(output) as image:
            image.save(jpeg)
        output.unlink()
        before = (jpeg.read_bytes(), layout.read_bytes())
        editor = self.editor(jpeg)
        editor.preview.set_continuous(True)
        self.assertTrue(editor.toggle_bubble_original())
        expected = editor._rendered.tobytes()
        self.assertTrue(editor.save_image(), editor._status.text())
        self.assertEqual((jpeg.read_bytes(), layout.read_bytes()), before)
        self.assertNotEqual(editor.output_path, jpeg)
        self.assertEqual(editor.output_path.suffix, '.png')
        self.assertEqual(list(editor.preview._pages), [str(editor.output_path)])
        self.assertEqual(editor.preview._active_path, str(editor.output_path))
        with Image.open(editor.output_path) as saved:
            self.assertEqual(saved.tobytes(), expected)
        reopened = self.editor(editor.output_path)
        self.assertTrue(reopened.apply_changes())
        self.assertEqual(reopened._rendered.tobytes(), expected)
        self.assertTrue(reopened.toggle_bubble_original())
        self.assertTrue(reopened.save_image())

    def test_new_lossless_copy_commit_failure_removes_partial_files(self):
        from comic_translate_desktop.background_repair import save_editor_files
        import os
        from pathlib import Path
        output, layout, original = self.page_with_original()
        directory = output.parent / 'new-copy'
        targets = [directory / name for name in ('image.png', 'layout.json', 'cleaned.png', 'original.png')]
        replace = os.replace
        def fail_original(source, target):
            if Path(target) == targets[-1]:
                raise PermissionError('locked original')
            return replace(source, target)
        with patch('comic_translate_desktop.background_repair.os.replace', side_effect=fail_original):
            with self.assertRaises(PermissionError):
                save_editor_files(original, targets[0], [], targets[1], original, targets[2], original, targets[3])
        self.assertFalse(any(target.exists() for target in targets))
        self.assertEqual(list(directory.iterdir()), [])

    def test_new_translation_records_original_pixels_and_padded_erase_region(self):
        from comic_translator_pipeline import ComicTranslatorPipeline
        output, layout, original = self.page_with_original()
        original_snapshot_path(output).unlink()
        pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
        pipeline.source_language = 'ja'
        pipeline.multimodal = pipeline.watermark_enabled = False
        pipeline.progress_callback = pipeline.cancel_callback = None
        pipeline.typesetter = self.editor(output).typesetter
        pipeline.inpainter = lambda image, mask: Image.new('RGB', image.size, '#ffeedd')
        pipeline.last_detector_mask = np.zeros((700,600), np.uint8)
        pipeline.last_detector_mask[110:161,115:151] = 255
        pipeline.last_detector_mask[175:201,95:105] = 255
        prepared = dict(img_cv=np.asarray(original)[:, :, ::-1].copy(),
            bubbles_data=[(100,90,290,340,0,'dialogue',24,0)],
            bubble_metadata=[dict(raw='Original', box=[100,90,290,340], style='dialogue',
                direction=0,target_font_size=24,non_bubble=False,source_language='ja')],ocr_texts=['Original'])
        pipeline.finish_comic_page(output, prepared, ['译文'])
        with Image.open(find_original(output)) as saved:
            self.assertEqual(saved.tobytes(), original.tobytes())
        item = json.loads(layout.read_text(encoding='utf-8'))[0]
        bounds, mask = decode_region(item, original.size)
        self.assertLess(bounds[0],100)
        self.assertEqual(mask.getpixel((98-bounds[0],180-bounds[1])),255)
        editor = self.editor(output)
        self.assertTrue(editor.toggle_bubble_original())
        self.assertEqual(editor._rendered.crop((95,90,290,340)).tobytes(), original.crop((95,90,290,340)).tobytes())

