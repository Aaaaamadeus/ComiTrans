from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image, ImageChops
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from comic_translate_desktop import config
from comic_translate_desktop.font_library import available_fonts, font_directory, font_reference, import_font
from comic_translate_desktop.ui.font_picker import TranslationFontPicker
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.worker import BatchWorker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(config.MAIN_DIR))
from vertical_typesetter import VerticalTypesetter


class CustomFontTests(unittest.TestCase):
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
        for key, value in (('PROJECT_ROOT', self.root), ('CONFIG_PATH', self.root / 'config.yaml')):
            setting = patch.object(config, key, value)
            setting.start()
            self.addCleanup(setting.stop)
        self.source = self.root / 'original.ttf'
        shutil.copyfile(ROOT / 'assets/ui/fonts/Skribble.ttf', self.source)

    def selected_config(self):
        info = import_font(self.source)
        return info, config.save_ai_config({'translation_font': font_reference(info.path)})

    def window(self):
        with patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
        self.addCleanup(window.close)
        return window

    def test_import_copies_deduplicates_and_survives_original_removal(self):
        imported = import_font(self.source)
        renamed = self.root / 'renamed.otf'
        shutil.copyfile(self.source, renamed)
        duplicate = import_font(renamed)
        self.assertEqual(imported.path, duplicate.path)
        self.assertEqual(imported.path.read_bytes(), self.source.read_bytes())
        self.assertEqual(len(list(font_directory().iterdir())), 1)
        self.source.unlink()
        self.assertIn(imported, available_fonts())

    def test_invalid_font_does_not_create_library_files(self):
        corrupt = self.root / 'bad.ttf'
        corrupt.write_bytes(b'not a font')
        with self.assertRaises(Exception):
            import_font(corrupt)
        self.assertFalse(font_directory().exists())

    def test_reimport_repairs_a_replaced_library_copy(self):
        imported = import_font(self.source)
        shutil.copyfile(ROOT / 'assets/ui/fonts/AaJinRiHuaQing-ChunLanMaoKun.ttf', imported.path)
        repaired = import_font(self.source)
        self.assertEqual(repaired.path, imported.path)
        self.assertEqual(repaired.path.read_bytes(), self.source.read_bytes())

    def test_default_font_round_trip_and_restore_keep_original_style_choices(self):
        original = str(config.AI_ROOT / config.FONT_DEFAULTS['serious'])
        config.save_ai_config({'font_dialogue': original})
        imported, selected = self.selected_config()
        self.assertTrue(selected['translation_font_active'])
        self.assertEqual(set(selected['font_map'].values()), {str(imported.path)})
        self.assertEqual(config.load_yaml(config.CONFIG_PATH)['translation_font'], font_reference(imported.path))
        restored = config.save_ai_config({'translation_font': ''})
        self.assertEqual(restored['font_map']['dialogue'], original)
        self.assertEqual(restored['font_map'], restored['style_font_map'])

    def test_imported_reference_survives_moving_app_and_config(self):
        imported, selected = self.selected_config()
        moved = self.root / 'moved-app'
        moved.mkdir()
        shutil.copytree(font_directory(), moved / 'user_fonts')
        shutil.copyfile(config.CONFIG_PATH, moved / 'config.yaml')
        with patch.object(config, 'PROJECT_ROOT', moved), patch.object(config, 'CONFIG_PATH', moved / 'config.yaml'):
            loaded = config.load_ai_config()
            self.assertTrue(loaded['translation_font_active'])
            self.assertEqual(loaded['font_map']['dialogue'], str(moved / 'user_fonts' / imported.path.name))

    def test_missing_font_falls_back_and_is_visible_as_unavailable(self):
        loaded = config.save_ai_config({'translation_font': 'user_fonts/missing.ttf'})
        self.assertFalse(loaded['translation_font_active'])
        self.assertEqual(loaded['font_map'], loaded['style_font_map'])
        picker = TranslationFontPicker(loaded)
        self.addCleanup(picker.close)
        self.assertIn('不可用', picker.combo.currentText())
        self.assertIn('回退', picker.status.text())
        self.assertFalse(picker.preview.pixmap().isNull())

    def test_custom_latin_glyphs_and_chinese_fallback_render_together(self):
        imported, selected = self.selected_config()
        typesetter = VerticalTypesetter(selected['font_map'], 28, fallback_fonts=selected['font_fallbacks'])
        self.assertEqual(typesetter._font_path_for_char('dialogue', 'A'), str(imported.path))
        chinese = typesetter._font_path_for_char('dialogue', '漫')
        self.assertNotEqual(chinese, str(imported.path))
        self.assertTrue(typesetter._font_supports(chinese, '漫'))
        custom = Image.new('RGB', (500, 140), 'white')
        automatic = custom.copy()
        typesetter.draw_text(custom, [10, 10, 490, 130], '漫画 ABC', 'dialogue', direction=0, target_font_size=28)
        VerticalTypesetter(selected['style_font_map'], 28).draw_text(
            automatic, [10, 10, 490, 130], '漫画 ABC', 'dialogue', direction=0, target_font_size=28)
        self.assertIsNotNone(ImageChops.difference(custom, Image.new('RGB', custom.size, 'white')).getbbox())
        self.assertIsNotNone(ImageChops.difference(custom, automatic).getbbox())

    def test_worker_updates_fonts_without_reloading_models_or_ai_override(self):
        original = config.load_ai_config()
        imported, selected = self.selected_config()
        selected['multimodal_font_probe'] = True
        typesetter = VerticalTypesetter(original['font_map'], 16, fallback_fonts=original['font_fallbacks'])
        detector, ocr, inpainter = object(), object(), object()
        pipeline = SimpleNamespace(typesetter=typesetter, detector=detector, ocr=ocr, inpainter=inpainter)
        worker = BatchWorker([], self.root / 'output', selected, pipeline=pipeline)
        worker._apply_api_config(pipeline, selected)
        worker._configure_pipeline(pipeline)
        self.assertEqual(config.config_fingerprint(original), config.config_fingerprint(selected))
        self.assertEqual(pipeline.typesetter.font_map['dialogue'], str(imported.path))
        self.assertIsNot(pipeline.typesetter, typesetter)
        self.assertEqual((pipeline.detector, pipeline.ocr, pipeline.inpainter), (detector, ocr, inpainter))
        self.assertFalse(pipeline.multimodal_font_probe)

    def test_workbench_selection_persists_and_keeps_unsaved_editor_text(self):
        window = self.window()
        self.assertTrue(window.translate_tab.isAncestorOf(window._font_picker))
        self.assertFalse(window.api_config_page.isAncestorOf(window._font_picker))
        page = self.root / 'output' / 'page.png'
        clean = self.root / 'output_cleaned'
        layouts = self.root / 'output_layout'
        for folder in (page.parent, clean, layouts):
            folder.mkdir()
        Image.new('RGB', (400, 600), 'white').save(page)
        shutil.copyfile(page, clean / 'page_cleaned.png')
        (layouts / 'page_layout.json').write_text(json.dumps([
            dict(text='旧译文', source_text='原文', box=[40, 50, 360, 280], style='dialogue',
                 font_size=26, direction=0, custom_metadata='keep')]), encoding='utf-8')
        editor = window.editor_page
        editor.load_page(page)
        editor._text_input.setPlainText('未保存的草稿 ABC')
        before = page.read_bytes()
        imported = window._font_picker.import_paths([self.source])[0]
        self.assertEqual(editor._text_input.toPlainText(), '未保存的草稿 ABC')
        self.assertEqual(editor.items[0]['text'], '未保存的草稿 ABC')
        self.assertEqual(editor.items[0]['custom_metadata'], 'keep')
        self.assertTrue(editor._dirty)
        self.assertEqual(page.read_bytes(), before)
        self.assertEqual(editor.typesetter.font_map['dialogue'], str(imported.path))
        restarted = self.window()
        self.assertEqual(restarted._font_picker.combo.currentData(), font_reference(imported.path))
        self.assertEqual(restarted.editor_page.typesetter.font_map['dialogue'], str(imported.path))
        # Avoid a discard dialog when this isolated fixture window closes.
        editor._dirty = False

    def test_import_batch_keeps_valid_font_and_reports_invalid_file(self):
        picker = TranslationFontPicker(config.load_ai_config())
        self.addCleanup(picker.close)
        invalid = self.root / 'bad.ttf'
        invalid.write_bytes(b'bad font')
        selections = []
        picker.selection_changed.connect(selections.append)
        imported = picker.import_paths([invalid, self.source])
        self.assertEqual(len(imported), 1)
        self.assertEqual(selections, [font_reference(imported[0].path)])
        self.assertIn('bad.ttf', picker.status.text())
        self.assertIn('未导入', picker.status.text())

    def test_library_font_choice_persists_default_and_is_visible_in_both_search_boxes(self):
        imported = import_font(self.source)
        reference = font_reference(imported.path)
        window = self.window()
        with patch('comic_translate_desktop.ui.font_library_dialog.FontLibraryDialog') as library:
            library.return_value.exec.return_value = 1
            library.return_value.reference = reference
            window._font_picker._open_library()
        self.assertEqual(window._font_picker.combo.currentData(), reference)
        self.assertEqual(config.load_yaml(config.CONFIG_PATH)['translation_font'], reference)
        self.assertGreaterEqual(window.editor_page._style_combo.findData(reference), 0)
        self.assertEqual(window.editor_page.typesetter.font_map['dialogue'], str(imported.path))

    def test_config_save_failure_keeps_previous_selection_and_error_visible(self):
        window = self.window()
        with patch('comic_translate_desktop.ui.main_window.save_ai_config', side_effect=OSError('配置不可写')):
            imported = window._font_picker.import_paths([self.source])
        self.assertEqual(len(imported), 1)
        self.assertTrue(imported[0].path.exists())
        self.assertEqual(window._font_picker.combo.currentData(), '')
        self.assertFalse(window.config['translation_font_active'])
        self.assertIn('字体选择未保存', window._font_picker.status.text())
        self.assertIn('配置不可写', window._font_picker.status.text())


if __name__ == '__main__':
    unittest.main()
