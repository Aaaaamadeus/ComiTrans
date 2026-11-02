import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from comic_translate_desktop import config
from comic_translate_desktop.pdf_project import (create_pdf_project, write_project_metadata,
    publish_pdf_project, load_pdf_project, project_link_path)
from comic_translate_desktop.pdf_utils import render_pdf_pages, PdfProcessingError
from comic_translate_desktop.ui.editor_page import EditorPage
from tests.qt_utils import destroy_widget


class PdfEditorTests(unittest.TestCase):
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
        config.save_ai_config({'watermark_enabled': False})
        self.pdf = self.root / '漫画_translated.pdf'
        self.directory = self.make_project()
        publish_pdf_project(self.pdf, self.directory)

    def make_project(self):
        directory = create_pdf_project(self.pdf)
        sizes = [(216.0, 360.0), (360.0, 216.0)]
        write_project_metadata(directory, '漫画.pdf', sizes)
        for i, (width, height) in enumerate(sizes, 1):
            stem = f'page_{i:04d}'
            image = Image.new('RGB', (int(width), int(height)), '#ffeedd')
            for folder, name in [('translated', f'{stem}.png'),
                                 ('translated_cleaned', f'{stem}_cleaned.png')]:
                (directory / folder).mkdir(exist_ok=True)
                image.save(directory / folder / name)
            (directory / 'translated_layout').mkdir(exist_ok=True)
            (directory / 'translated_layout' / f'{stem}_layout.json').write_text(json.dumps([
                dict(text='原译文', source_text='原文', box=[20, 20, 190, 180],
                     style='dialogue', direction=0, font_size=24, rendered_font_size=24)
            ]), encoding='utf-8')
        return directory

    def editor(self):
        editor = EditorPage()
        self.addCleanup(self.close_editor, editor)
        self.assertTrue(editor.load_page(self.pdf))
        editor.resize(1100, 740)
        editor.show()
        self.app.processEvents()
        return editor

    @staticmethod
    def close_editor(editor):
        if editor._export_worker is not None:
            editor._export_worker.requestInterruption()
            editor._export_worker.wait(5000)
            QApplication.processEvents()
        for _ in range(500):
            if not any(job.busy for job in (editor._page_jobs, editor._save_jobs, editor._import_jobs)):
                break
            QTest.qWait(10)
        editor._dirty = False
        destroy_widget(editor)

    def wait_export(self, editor):
        for _ in range(500):
            if editor._export_worker is None and not editor._save_jobs.busy:
                return
            QTest.qWait(10)
        self.fail('PDF export did not finish')

    def test_bubble_restore_uses_project_source_and_exports_original_pixels(self):
        from PIL import ImageDraw
        from comic_translate_core.restoration import save_original, original_snapshot_path
        source = self.directory / 'source' / 'page_0001.png'
        source.parent.mkdir(exist_ok=True)
        original = Image.new('RGB', (216,360), '#ffeedd')
        ImageDraw.Draw(original).rectangle((35,40,90,130),fill='#16324b')
        original.save(source)
        source_bytes, pdf_bytes = source.read_bytes(), self.pdf.read_bytes()
        editor = self.editor()
        self.assertEqual(save_original(editor.output_path, original, source), source)
        self.assertFalse(original_snapshot_path(editor.output_path).exists())
        self.assertTrue(editor.toggle_bubble_original(), editor._status.text())
        self.assertTrue(editor.save_image())
        exported = self.root / 'restored.pdf'
        self.assertTrue(editor.export_pdf(exported))
        self.wait_export(editor)
        self.assertTrue(exported.is_file(), editor._status.text())
        pages = list(render_pdf_pages(exported, self.root / 'restored-pages', dpi=72))
        with Image.open(pages[0].image_path) as page:
            self.assertEqual(page.convert('RGB').crop((20,20,190,180)).tobytes(), original.crop((20,20,190,180)).tobytes())
        reopened = self.editor()
        self.assertTrue(reopened.items[0]['restore_original'])
        self.assertTrue(reopened.apply_changes())
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(self.pdf.read_bytes(), pdf_bytes)

    def test_reprocessing_pdf_page_refreshes_a_previously_linked_original(self):
        from comic_translate_core.restoration import save_original, find_original
        source = self.directory / 'source' / 'page_0001.png'
        source.parent.mkdir(exist_ok=True)
        original = Image.new('RGB', (216,360), '#aabbcc')
        original.save(source)
        output = self.directory / 'translated' / source.name
        save_original(output, Image.new('RGB', original.size, '#112233'))
        save_original(output, original, source)
        with Image.open(find_original(output)) as linked:
            self.assertEqual(linked.tobytes(), original.tobytes())

    def test_edit_reopen_and_export_preserves_original_pdf_and_other_pages(self):
        editor = self.editor()
        self.assertEqual(editor.page_list.count(), 2)
        project = load_pdf_project(self.pdf)
        second = project.images[1].read_bytes()
        before = self.pdf.read_bytes()
        editor._text_input.setPlainText('修改后的译文')
        output = self.root / 'exported.pdf'
        self.assertTrue(editor.export_pdf(output), editor._status.text())
        self.wait_export(editor)
        self.assertTrue(output.is_file(), editor._status.text())
        self.assertEqual(self.pdf.read_bytes(), before)
        self.assertEqual(project.images[1].read_bytes(), second)
        reopened = self.editor()
        self.assertEqual(reopened._text_input.toPlainText(), '修改后的译文')
        rendered = render_pdf_pages(output, self.root / 'check', dpi=72)
        self.assertEqual([(p.width_points, p.height_points) for p in rendered], project.page_sizes)
        with Image.open(rendered[0].image_path) as image:
            self.assertLess(image.convert('L').getextrema()[0], 100)

    def test_completed_pdf_result_opens_editor_with_all_pages(self):
        from comic_translate_desktop.ui.main_window import MainWindow
        with patch.object(MainWindow, '_start_warmup'), patch.object(config, 'PROJECT_ROOT', self.root):
            window = MainWindow()
        self.addCleanup(destroy_widget, window)
        source = self.root / 'source.pdf'
        shutil.copy2(self.pdf, source)
        window._add_paths([source])
        window.file_list.setCurrentRow(0)
        window._on_image_done(str(source), str(self.pdf))
        self.assertTrue(window._edit_result_btn.isEnabled())
        window._edit_result_btn.click()
        self.assertIs(window.tabs.currentWidget(), window.editor_page)
        for _ in range(300):
            if not window.editor_page.page_io_busy:
                break
            QTest.qWait(10)
        self.assertEqual(window.editor_page.page_list.count(), 2)
        self.assertTrue(window.editor_page._export_pdf_btn.isEnabled())

    def test_publish_failure_restores_pdf_and_index_and_keeps_new_pages(self):
        old_pdf, old_index = self.pdf.read_bytes(), project_link_path(self.pdf).read_bytes()
        directory = self.make_project()
        replace = os.replace
        def fail_index(source, target):
            if Path(target) == project_link_path(self.pdf):
                raise PermissionError('locked index')
            return replace(source, target)
        with patch('comic_translate_desktop.pdf_project.os.replace', side_effect=fail_index):
            with self.assertRaises(PermissionError):
                publish_pdf_project(self.pdf, directory)
        self.assertEqual(self.pdf.read_bytes(), old_pdf)
        self.assertEqual(project_link_path(self.pdf).read_bytes(), old_index)
        self.assertTrue((directory / 'translated/page_0001.png').exists())

    def test_failed_update_keeps_saved_edits_and_original_pdf(self):
        editor = self.editor()
        before = self.pdf.read_bytes()
        editor._text_input.setPlainText('保存后重试')
        with patch('comic_translate_desktop.pdf_export.build_pdf_from_images', side_effect=PermissionError('locked')):
            self.assertTrue(editor.export_pdf(self.root / 'failed.pdf'))
            self.wait_export(editor)
        self.assertFalse((self.root / 'failed.pdf').exists())
        self.assertEqual(self.pdf.read_bytes(), before)
        self.assertFalse(editor._dirty)
        self.assertEqual(self.editor()._text_input.toPlainText(), '保存后重试')

    def test_retranslation_does_not_replace_open_image_project(self):
        editor = self.editor()
        editor._text_input.setPlainText('旧版草稿')
        publish_pdf_project(self.pdf, self.make_project())
        before = self.pdf.read_bytes()
        self.assertTrue(editor.export_pdf(self.root / 'old-project.pdf'))
        self.wait_export(editor)
        self.assertFalse(editor._dirty)
        self.assertEqual(self.pdf.read_bytes(), before)
        self.assertEqual(json.loads((self.directory / 'translated_layout/page_0001_layout.json').read_text(encoding='utf-8'))[0]['text'], '旧版草稿')

    def test_project_can_move_with_pdf_and_rejects_missing_files_and_escape(self):
        moved = self.root / 'moved'
        moved.mkdir()
        shutil.copy2(self.pdf, moved / self.pdf.name)
        shutil.copy2(project_link_path(self.pdf), moved / project_link_path(self.pdf).name)
        shutil.copytree(self.directory, moved / self.directory.name)
        project = load_pdf_project(moved / self.pdf.name)
        self.assertEqual(project.directory.parent, moved)
        (project.directory / 'translated_layout/page_0002_layout.json').unlink()
        with self.assertRaises(PdfProcessingError):
            load_pdf_project(moved / self.pdf.name)
        project_link_path(self.pdf).write_text(json.dumps({'version': 1, 'project_dir': '../outside'}))
        with self.assertRaises(PdfProcessingError):
            load_pdf_project(self.pdf)

    def test_strip_scroll_select_edit_cancel_and_save(self):
        editor = self.editor()
        editor._strip_toggle.setChecked(True)
        QTest.qWait(60)
        preview = editor.preview
        project = load_pdf_project(self.pdf)
        second = preview._pages[str(project.images[1])][0]
        preview._strip_scroll.ensureWidgetVisible(second)
        QTest.qWait(50)
        QTest.mouseClick(second, Qt.LeftButton, pos=second.rect().center())
        for _ in range(300):
            if not editor._page_jobs.busy:
                break
            QTest.qWait(10)
        self.assertEqual(editor.output_path, project.images[1])
        self.assertIs(preview._label, second)
        editor._text_input.setPlainText('长条中编辑第二页')
        QTest.qWait(60)
        scroll = preview._strip_scroll.verticalScrollBar().value()
        editor._size_spin.setValue(26)
        QTest.qWait(60)
        self.assertEqual(preview._strip_scroll.verticalScrollBar().value(), scroll)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
            self.assertFalse(editor.load_page(project.images[0]))
        for _ in range(300):
            if not editor._page_jobs.busy:
                break
            QTest.qWait(10)
        self.assertEqual(editor.output_path, project.images[1])
        self.assertTrue(editor.save_image())
        editor._strip_toggle.setChecked(False)
        self.assertEqual(editor._text_input.toPlainText(), '长条中编辑第二页')
        self.assertIs(preview._label, preview._single_label)

    def test_strip_background_selection_uses_page_local_coordinates(self):
        editor = self.editor()
        editor._strip_toggle.setChecked(True)
        project = load_pdf_project(self.pdf)
        editor.load_page(project.images[1])
        editor.preview.set_zoom(1.5)
        editor._repair_mode.setChecked(True)
        QTest.qWait(50)
        label = editor.preview._label
        rect = label.page_rect()
        from PySide6.QtCore import QPoint
        start = QPoint(round(rect.x() + 30 * 1.5), round(rect.y() + 25 * 1.5))
        end = QPoint(round(rect.x() + 100 * 1.5), round(rect.y() + 75 * 1.5))
        QTest.mousePress(label, Qt.LeftButton, pos=start)
        QTest.mouseMove(label, end)
        QTest.mouseRelease(label, Qt.LeftButton, pos=end)
        self.assertEqual(editor._repair_box, (30, 25, 100, 75))
        editor._strip_toggle.setChecked(False)
        self.assertEqual(editor.preview._label.region, (30, 25, 100, 75))

    def test_strip_only_keeps_visible_previews_and_active_page(self):
        editor = self.editor()
        project = load_pdf_project(self.pdf)
        for number in range(3, 35):
            path = project.images[0].parent / f'page_{number:04d}.png'
            shutil.copy2(project.images[0], path)
            editor._add_page(path)
        editor._strip_toggle.setChecked(True)
        QTest.qWait(70)
        last_key = next(reversed(editor.preview._pages))
        self.assertIsNone(editor.preview._pages[last_key][0])
        bar = editor.preview._strip_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        for _ in range(200):
            last = editor.preview._pages[last_key][0]
            if last is not None and not last.pixmap().isNull():
                break
            QTest.qWait(10)
        self.assertFalse(editor.preview._pages[last_key][0].pixmap().isNull())
        labels = [pair[0] for pair in editor.preview._pages.values() if pair[0] is not None]
        self.assertLessEqual(len(labels), 5)
        self.assertEqual(editor.output_path, project.images[0])

    def test_image_save_and_page_switch_never_build_pdf(self):
        editor = self.editor()
        before = self.pdf.read_bytes()
        with patch('comic_translate_desktop.pdf_export.build_pdf_from_images') as build:
            editor._text_input.setPlainText('仅保存图片')
            self.assertTrue(editor.save_image())
            self.assertTrue(editor.load_page(load_pdf_project(self.pdf).images[1]))
            build.assert_not_called()
        self.assertEqual(self.pdf.read_bytes(), before)

    def test_register_pdf_does_not_decode_all_pages(self):
        editor = EditorPage()
        self.addCleanup(self.close_editor, editor)
        with patch('comic_translate_desktop.ui.editor_page.QPixmap') as pixmap:
            editor._register_pdf(self.pdf)
            pixmap.assert_not_called()
        self.assertEqual(editor.page_list.count(), 2)
        self.assertTrue(editor.page_list.item(1).icon().isNull())

    def test_project_opens_as_images_without_pdf_or_index(self):
        self.pdf.unlink()
        project_link_path(self.pdf).unlink()
        editor = EditorPage()
        self.addCleanup(self.close_editor, editor)
        self.assertTrue(editor.load_page(self.directory / 'project.json'))
        self.assertEqual(editor.page_list.count(), 2)
        self.assertTrue(editor.export_pdf(self.root / 'independent.pdf'))
        self.wait_export(editor)
        self.assertTrue((self.root / 'independent.pdf').exists())

    def test_plain_images_can_export_without_editing_metadata(self):
        editor = EditorPage()
        self.addCleanup(self.close_editor, editor)
        source = self.root / 'plain.png'
        Image.new('RGB', (600, 900), '#123456').save(source)
        self.assertTrue(editor.load_page(source))
        self.assertTrue(editor.export_pdf(self.root / 'plain.pdf'))
        self.wait_export(editor)
        self.assertTrue((self.root / 'plain.pdf').is_file(), editor._status.text())
        pages = render_pdf_pages(self.root / 'plain.pdf', self.root / 'plain-rendered', dpi=200)
        with Image.open(pages[0].image_path) as image:
            self.assertEqual(image.size, (600, 900))

    def test_export_flushes_typed_font_size_before_saving(self):
        editor = self.editor()
        editor._size_spin.setKeyboardTracking(False)
        editor._size_spin.lineEdit().setText('33')
        self.assertTrue(editor.export_pdf(self.root / 'typed-size.pdf'))
        self.wait_export(editor)
        saved = json.loads((self.directory / 'translated_layout/page_0001_layout.json').read_text(encoding='utf-8'))
        self.assertEqual(saved[0]['font_size'], 33)

    def test_export_runs_off_ui_thread_and_can_cancel_without_losing_images(self):
        import threading
        from PySide6.QtCore import QTimer
        editor = self.editor()
        editor._text_input.setPlainText('先保存图片再导出')
        ui_thread = threading.get_ident()
        calls, ticks = [], []
        gate = threading.Event()
        def slow_build(*args, cancel_callback, **kwargs):
            calls.append(threading.get_ident())
            while not gate.wait(.01):
                cancel_callback()
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(5)
        self.addCleanup(timer.stop)
        self.addCleanup(gate.set)
        before = self.pdf.read_bytes()
        with patch('comic_translate_desktop.pdf_export.build_pdf_from_images', side_effect=slow_build):
            self.assertTrue(editor.export_pdf(self.pdf))
            for _ in range(300):
                if calls:
                    break
                QTest.qWait(10)
            self.assertTrue(ticks)
            self.assertTrue(calls)
            self.assertNotEqual(calls[0], ui_thread)
            self.assertFalse(editor.save_image())
            editor._cancel_pdf_export()
            self.wait_export(editor)
        self.assertEqual(self.pdf.read_bytes(), before)
        self.assertFalse(editor._dirty)
        self.assertEqual(self.editor()._text_input.toPlainText(), '先保存图片再导出')


if __name__ == '__main__':
    unittest.main()
