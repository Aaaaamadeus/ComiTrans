import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QSettings, QSize, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from comic_translate_desktop import config
from comic_translate_desktop.editor_jobs import LatestJobQueue, read_page
from comic_translate_desktop.ui.editor_page import EditorPage, save_editor_files
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.strip_preview import StripPreview
from tests.qt_utils import destroy_widget


class LargeEditorTests(unittest.TestCase):
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
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = patch.object(config, 'CONFIG_PATH', self.root / 'config.yaml')
        patcher.start()
        self.addCleanup(patcher.stop)
        QSettings().clear()
        config.save_ai_config({'watermark_enabled': True})

    def wait(self, condition):
        for _ in range(600):
            if condition():
                return
            QTest.qWait(10)
        self.fail('Background work did not finish')

    def page(self, name):
        output = self.root / 'translated' / f'{name}.png'
        cleaned = self.root / 'translated_cleaned' / f'{name}_cleaned.png'
        layout = self.root / 'translated_layout' / f'{name}_layout.json'
        for path in (output, cleaned, layout):
            path.parent.mkdir(exist_ok=True)
        for path in (output, cleaned):
            Image.new('RGB', (800, 1200), '#decba0').save(path)
        layout.write_text(json.dumps([dict(text='测试文字', box=[100, 100, 300, 400],
            mask_box=[100, 100, 300, 400], style='dialogue', direction=1,
            font_size=24, rendered_font_size=24)]), encoding='utf-8')
        return output, layout

    def editor(self):
        editor = EditorPage()
        def cleanup():
            self.wait(lambda: not any(q.busy for q in (editor._page_jobs, editor._save_jobs, editor._import_jobs)))
            editor._dirty = False
            destroy_widget(editor)
        self.addCleanup(cleanup)
        return editor

    def window(self):
        with patch.object(MainWindow, '_start_warmup'), patch.object(config, 'PROJECT_ROOT', self.root):
            window = MainWindow()
        self.addCleanup(destroy_widget, window)
        return window

    def test_latest_queue_is_bounded_and_delivers_only_latest_result_on_gui_thread(self):
        # Match the editor's QObject ownership. Immediate Python destruction of
        # an unparented receiver can race QRunnable's native signal teardown.
        queue = LatestJobQueue(self.app)
        self.addCleanup(queue.deleteLater)
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        calls, results = [], []
        ui = threading.get_ident()
        def read(n):
            calls.append((n, threading.get_ident()))
            if n == 0:
                started.set()
                gate.wait(5)
            return n
        for n in range(20):
            queue.submit(lambda n=n: read(n), lambda result: results.append((result, threading.get_ident())), self.fail)
            if n == 0:
                self.wait(started.is_set)
        self.assertIsNotNone(queue._pending)
        gate.set()
        self.wait(lambda: not queue.busy)
        self.assertEqual([n for n, _ in calls], [0, 19])
        self.assertTrue(all(thread != ui for _, thread in calls))
        self.assertEqual(results, [(19, ui)])

    def test_save_snapshot_keeps_new_edits_dirty_and_preserves_native_pixels(self):
        output, layout = self.page('a')
        editor = self.editor()
        editor.load_page(output)
        editor._text_input.setPlainText('第一版')
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(5)
        self.addCleanup(timer.stop)
        def write(*args):
            started.set()
            gate.wait(5)
            return save_editor_files(*args)
        with patch('comic_translate_desktop.ui.editor_page.save_editor_files', side_effect=write):
            self.assertTrue(editor.request_save())
            snapshot = editor._saving_image.tobytes()
            self.wait(started.is_set)
            editor._text_input.setPlainText('第二版')
            editor.apply_changes()
            self.assertEqual(editor._saving_image.tobytes(), snapshot)
            QTest.qWait(30)
            self.assertTrue(ticks)
            gate.set()
            self.wait(lambda: not editor._save_jobs.busy)
        self.assertTrue(editor._dirty)
        self.assertEqual(json.loads(layout.read_text(encoding='utf-8'))[0]['text'], '第一版')
        self.assertTrue(editor.request_save())
        self.wait(lambda: not editor._save_jobs.busy)
        self.assertFalse(editor._dirty)
        self.assertEqual(json.loads(layout.read_text(encoding='utf-8'))[0]['text'], '第二版')
        with Image.open(output) as result:
            self.assertEqual(result.size, (800, 1200))
            self.assertEqual(result.tobytes(), editor._rendered.tobytes())

    def test_page_load_does_not_overwrite_new_edits_and_discards_stale_navigation(self):
        first, _ = self.page('a')
        second, _ = self.page('b')
        third, _ = self.page('c')
        editor = self.editor()
        editor.load_page(first)
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)
        def read(*args):
            started.set()
            gate.wait(5)
            return read_page(*args)
        with patch('comic_translate_desktop.ui.editor_page.read_page', side_effect=read):
            editor.request_page(second)
            self.wait(started.is_set)
            editor.request_page(third)
            editor._text_input.setPlainText('加载中继续编辑')
            gate.set()
            self.wait(lambda: not editor._page_jobs.busy)
        self.assertEqual(editor.output_path, first)
        self.assertTrue(editor._dirty)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Discard):
            editor.request_page(second)
            editor.request_page(third)
        self.wait(lambda: not editor._page_jobs.busy)
        self.assertEqual(editor.output_path, third)

    def test_virtual_strip_bounds_widgets_and_scrolls_beyond_qt_widget_height_limit(self):
        preview = StripPreview()
        self.addCleanup(destroy_widget, preview)
        preview.resize(600, 500)
        preview.show()
        with patch.object(preview._thumbnail_loader, 'request'):
            for n in range(1000):
                preview.add_page(self.root / f'{n}.png', QSize(3000, 10000))
            preview.set_continuous(True)
            preview.set_zoom(2)
            QTest.qWait(30)
            bar = preview._strip_scroll.verticalScrollBar()
            self.assertGreater(bar.maximum(), 16777215)
            for part in (0, .2, .5, .7, 1):
                bar.setValue(round(bar.maximum() * part))
                QTest.qWait(5)
                self.assertLessEqual(len(preview._canvas_keys) + len(preview._spares), 6)
            self.assertIsNotNone(preview._pages[str(self.root / '999.png')][0])

    def test_large_project_registration_yields_between_batches(self):
        from comic_translate_desktop.pdf_project import PdfProject
        output, _ = self.page('first')
        images = [output] + [self.root / f'fake_{n}.png' for n in range(999)]
        project = PdfProject(self.root, images, [(800, 1200)] * len(images))
        sizes = {str(path): QSize(800, 1200) for path in images}
        editor = self.editor()
        counts = []
        timer = QTimer()
        timer.timeout.connect(lambda: counts.append(editor.page_list.count()))
        timer.start(1)
        self.addCleanup(timer.stop)
        with patch('comic_translate_desktop.ui.editor_page.read_project_pages', return_value=(project, sizes)):
            editor.request_import([self.root / 'project.json'])
            self.wait(lambda: not editor.page_io_busy)
        self.assertEqual(editor.page_list.count(), 1000)
        self.assertTrue(any(0 < count < 1000 for count in counts))
        self.assertEqual(editor.output_path, output)

    def test_local_render_matches_full_render_including_overlaps_and_watermark(self):
        output, _ = self.page('a')
        editor = self.editor()
        editor.load_page(output)
        editor.items.append(dict(editor.items[0], text='重叠文字', mask_box=[150, 110, 350, 420]))
        editor.render()
        editor._text_input.setPlainText('甲乙')
        editor.apply_changes()
        regions = editor._last_render_regions
        self.assertLess(sum((r[2]-r[0])*(r[3]-r[1]) for r in regions), 800*1200//2)
        incremental = editor._rendered.tobytes()
        editor._layer_cache.clear()
        editor.render()
        self.assertEqual(editor._rendered.tobytes(), incremental)
        # Exercise watermark overlap and removal without accumulating alpha.
        editor.items[0]['mask_box'] = [650, 1060, 790, 1190]
        editor.items[0]['text'] = '新'
        editor.render()
        editor.items[0]['text'] = ''
        editor.render()
        incremental = editor._rendered.tobytes()
        editor._layer_cache.clear()
        editor.render()
        self.assertEqual(editor._rendered.tobytes(), incremental)

    def test_restored_region_geometry_uses_full_composition(self):
        from comic_translate_core.restoration import save_original
        output, _ = self.page('restored')
        save_original(output, Image.new('RGB', (800, 1200), '#183754'))
        editor = self.editor()
        editor.load_page(output)
        editor.items[0]['restore_original'] = True
        editor.items.append(dict(editor.items[0], restore_original=False, text='相邻气泡',
                                 mask_box=[250, 120, 500, 420], box=[250, 120, 500, 420]))
        editor.render()
        editor.items[1]['mask_box'] = [180, 120, 470, 420]
        editor.render()
        self.assertEqual(editor._last_render_regions, [(0, 0, 800, 1200)])

    def test_narrow_window_and_focus_do_not_overwrite_panel_preferences(self):
        editor = self.editor()
        editor.resize(1400, 800)
        editor.show()
        QTest.qWait(20)
        self.assertEqual(editor._desired_panels, [True, True])
        editor.resize(850, 650)
        QTest.qWait(20)
        self.assertFalse(editor._pages_toggle.isChecked())
        editor._pages_toggle.click()
        self.assertTrue(editor._pages_panel.isVisible())
        self.assertFalse(editor._properties_panel.isVisible())
        editor._focus_btn.click()
        editor.save_ui_state()
        self.assertTrue(QSettings().value('ui/editorPages', type=bool))
        self.assertTrue(QSettings().value('ui/editorProperties', type=bool))
        editor._focus_btn.click()
        editor.resize(1400, 800)
        QTest.qWait(20)
        self.assertTrue(editor._pages_panel.isVisible())
        self.assertTrue(editor._properties_panel.isVisible())
        editor._pages_toggle.click()
        editor.resize(850, 650)
        editor.resize(1400, 800)
        QTest.qWait(20)
        self.assertFalse(editor._pages_panel.isVisible())

    def test_preferences_flush_when_collapsed_and_failure_can_retry_without_losing_draft(self):
        window = self.window()
        window._pref_toggle.setChecked(True)
        previous = window.config.get('translation_prompt')
        window._prompt_input.setPlainText('新的翻译规则')
        with patch('comic_translate_desktop.ui.main_window.save_ai_config', side_effect=OSError('locked')):
            window._pref_toggle.setChecked(False)
            self.assertTrue(window._pref_save_error)
            self.assertEqual(window.config.get('translation_prompt'), previous)
            self.assertEqual(window._prompt_input.toPlainText(), '新的翻译规则')
            self.assertIn('未保存', window._pref_toggle.text())
        window._pref_retry.click()
        self.assertFalse(window._pref_save_error)
        self.assertEqual(window.config['translation_prompt'], '新的翻译规则')
        self.assertFalse(window._pref_save_timer.isActive())
        window._pref_toggle.setChecked(True)
        window.resize(850, 620)
        window.show()
        QTest.qWait(20)
        self.assertTrue(window._pref_toggle.isChecked())
        self.assertTrue(window.preview_tabs.isVisible())
        self.assertGreater(window.preview_tabs.height(), 100)
