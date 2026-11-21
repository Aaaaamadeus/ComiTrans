import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from comic_translate_desktop import config
from comic_translate_desktop.background_repair import save_editor_files
from comic_translate_desktop.cbz import build_cbz_from_images
from comic_translate_desktop.pdf_project import load_pdf_project
from comic_translate_desktop.ui.editor_page import EditorPage
from comic_translate_desktop.ui.retranslate_dialog import RetranslateDialog
from comic_translate_desktop.ui.transcript_dialog import TranscriptDialog
from comic_translate_desktop.worker import BatchWorker
from tests.qt_utils import destroy_widget
from tests.test_pdf_translation import _CopyPipeline


class TranslationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(self.root))
        self.enterContext(patch.object(config, 'CONFIG_PATH', self.root / 'config.yaml'))
        self.enterContext(patch.object(config, 'PROJECT_ROOT', self.root))
        config.save_ai_config({'watermark_enabled': False})

    def wait_for(self, condition):
        for _ in range(400):
            if condition():
                return
            QTest.qWait(10)
        self.fail('Timed out waiting for the workflow')

    def make_page(self, name, source):
        output, cleaned, layouts = (self.root / folder
                                     for folder in ('pages', 'pages_cleaned', 'pages_layout'))
        for directory in (output, cleaned, layouts):
            directory.mkdir(exist_ok=True)
        image = Image.new('RGB', (260, 320), '#f0eae2')
        path = output / f'{name}.png'
        image.save(path)
        image.save(cleaned / f'{name}_cleaned.png')
        layout = layouts / f'{name}_layout.json'
        layout.write_text(json.dumps([
            dict(source_text=source, text='魔石', style='dialogue', box=[20, 30, 145, 100],
                 mask_box=[20, 30, 145, 100], direction=0, font_size=18,
                 rendered_font_size=18, manual_layout=False),
            dict(source_text='二番目', text='第二句', style='dialogue', box=[40, 160, 175, 240],
                 mask_box=[40, 160, 175, 240], direction=0, font_size=18)
        ], ensure_ascii=False), encoding='utf-8')
        return path, layout

    def make_editor(self, path):
        editor = EditorPage()
        def close():
            editor._dirty = False
            destroy_widget(editor)
        self.addCleanup(close)
        self.assertTrue(editor.load_page(path), editor._status.text())
        return editor

    def test_book_search_preview_and_replacement_across_pages(self):
        first, first_layout = self.make_page('page_1', '第一原文')
        second, second_layout = self.make_page('page_2', '魔法の石')
        editor = self.make_editor(first)
        editor._add_page(second)
        original = second.read_bytes()
        dialog = TranscriptDialog(lambda jobs, loaded, failed: editor._index_transcript(
            jobs, loaded, failed, None), editor._replace_transcript, editor)
        self.addCleanup(destroy_widget, dialog)
        self.wait_for(lambda: not dialog._busy)
        dialog.search.setText('魔法')
        self.assertEqual(dialog.model.rowCount(), 1)
        self.assertEqual(dialog.model.rows[0][0].path, second)
        dialog.search.setText('魔石')
        dialog.replace.setText('魔晶')
        dialog.preview_button.click()
        self.assertEqual([value for _entry, value in dialog.model.rows], ['魔晶', '魔晶'])
        self.assertEqual(second.read_bytes(), original)
        dialog.apply_button.click()
        self.wait_for(lambda: not dialog._busy)
        for layout in (first_layout, second_layout):
            translated = json.loads(layout.read_text(encoding='utf-8'))
            self.assertEqual([item['text'] for item in translated], ['魔晶', '第二句'])
            self.assertFalse(translated[0]['manual_layout'])
        self.assertNotEqual(second.read_bytes(), original)
        editor.request_page(first, block=1)
        self.wait_for(lambda: editor.output_path == first and editor._loaded_row == 1)
        self.assertEqual(editor._text_input.toPlainText(), '第二句')

    def test_candidate_preview_only_changes_page_after_apply(self):
        first, layout = self.make_page('page_1', '誤認識')
        editor = self.make_editor(first)

        def select_candidate(dialog):
            dialog.source.setPlainText('正しい原文')
            dialog.instruction.setText('短一点')
            dialog.request_button.click()
            self.wait_for(dialog.apply_button.isEnabled)
            self.assertFalse(dialog.candidate_image.pixmap().isNull())
            self.assertEqual(editor.items[0]['text'], '魔石')
            self.assertEqual(editor.items[0]['source_text'], '誤認識')
            return int(RetranslateDialog.Accepted)

        with patch('comic_translate_desktop.bubble_translation.retranslate_bubble',
                   return_value='魔晶现身') as translate, patch.object(RetranslateDialog, 'exec', select_candidate):
            editor.open_retranslation()
        self.assertEqual(translate.call_args.args[2:4], ('正しい原文', '短一点'))
        self.assertEqual(editor._text_input.toPlainText(), '魔晶现身')
        self.assertTrue(editor.save_image(), editor._status.text())
        saved = json.loads(layout.read_text(encoding='utf-8'))[0]
        self.assertEqual(saved['source_text'], '正しい原文')
        self.assertEqual(saved['ocr_raw_text'], '誤認識')
        self.assertEqual(saved['text'], '魔晶现身')
        self.assertFalse(saved['manual_layout'])

    def test_replacement_failure_keeps_committed_pages_and_the_failed_draft(self):
        first, first_layout = self.make_page('page_1', '最初')
        second, second_layout = self.make_page('page_2', '次')
        editor = self.make_editor(first)
        editor._add_page(second)
        dialog = TranscriptDialog(lambda jobs, loaded, failed: editor._index_transcript(
            jobs, loaded, failed, None), editor._replace_transcript, editor)
        self.addCleanup(destroy_widget, dialog)
        self.wait_for(lambda: not dialog._busy)
        dialog.search.setText('魔石')
        dialog.replace.setText('魔晶')
        dialog.preview_button.click()

        def save(rendered, output, *args):
            if output == second:
                raise OSError('test save failure')
            save_editor_files(rendered, output, *args)

        with patch('comic_translate_desktop.ui.editor_page.save_editor_files', side_effect=save):
            dialog.apply_button.click()
            self.wait_for(lambda: not dialog._busy)
        self.assertIn('test save failure', dialog.status.text())
        self.assertEqual(json.loads(first_layout.read_text(encoding='utf-8'))[0]['text'], '魔晶')
        self.assertEqual(json.loads(second_layout.read_text(encoding='utf-8'))[0]['text'], '魔石')
        self.assertTrue(editor._dirty)
        self.assertEqual(editor._text_input.toPlainText(), '魔晶')

    def test_cbz_batch_order_reopen_resume_and_editor_export(self):
        source = self.root / '漫画.CBZ'
        expected_colors = {'10': (10, 20, 30), '2': (200, 150, 100), '1': (90, 80, 70)}
        with ZipFile(source, 'w') as archive:
            for number, rgb in expected_colors.items():
                stream = io.BytesIO()
                Image.new('RGB', (30 + int(number), 50), rgb).save(stream, format='PNG')
                archive.writestr(f'pages/p{number}.png', stream.getvalue())
            archive.writestr('pages/metadata.txt', b'metadata')
            archive.writestr('../outside.png', b'not a page')
        output_dir = self.root / 'translated'
        worker = BatchWorker([source], output_dir, {'resume_enabled': True}, pipeline=_CopyPipeline())
        results = []
        worker.finished.connect(lambda good, bad: results.append((good, bad)))
        worker.run()
        self.assertEqual(results, [(1, 0)])
        output = output_dir / '漫画_translated.cbz'
        project = load_pdf_project(output)
        with ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), ['page_0001.png', 'page_0002.png', 'page_0003.png'])
            for name, number, image in zip(archive.namelist(), ('1', '2', '10'), project.images):
                self.assertEqual(archive.read(name), image.read_bytes())
                with Image.open(image) as saved:
                    self.assertEqual(saved.getpixel((0, 0)), expected_colors[number])
                    self.assertEqual(saved.size, (30 + int(number), 50))
        worker = BatchWorker([source], output_dir, {'resume_enabled': True}, pipeline=_CopyPipeline())
        with patch.object(_CopyPipeline, 'prepare_comic_page', side_effect=AssertionError('already complete')):
            worker.finished.connect(lambda good, bad: results.append((good, bad)))
            worker.run()
        self.assertEqual(results, [(1, 0), (1, 0)])
        editor = self.make_editor(output)
        self.assertEqual(editor.page_list.count(), 3)
        target = self.root / 'edited.cbz'
        self.assertTrue(editor.export_cbz(target))
        self.wait_for(lambda: editor._export_worker is None)
        with ZipFile(target) as archive:
            self.assertEqual([archive.read(name) for name in archive.namelist()],
                             [path.read_bytes() for path in project.images])

    def test_cancelled_cbz_export_keeps_existing_file(self):
        image, _layout = self.make_page('page_1', '')
        target = build_cbz_from_images([image], self.root / 'edited.cbz')
        before = target.read_bytes()
        def cancelled():
            raise InterruptedError()
        with self.assertRaises(InterruptedError):
            build_cbz_from_images([image, image], target, cancel_callback=cancelled)
        self.assertEqual(target.read_bytes(), before)
