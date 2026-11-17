from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from tests.qt_utils import destroy_widget
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox
from comic_translate_desktop.ui.log_panel import LogPanel
from comic_translate_desktop.ui.step_panel import StepPanel, DONE, RUNNING, PENDING, SKIPPED, FAILED, CANCELLED, READY
from comic_translate_desktop.ui.theme import apply_theme
from comic_translate_desktop.ui.editor_page import EditorPage
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.worker import BatchWorker, QtTextStream, _DocumentJob, _PageJob


class DesktopUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.settings_dir = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings_dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.settings_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def log_panel(self):
        panel = LogPanel(self.root / 'app.log')
        panel.resize(900, 250)
        panel.show()
        self.app.processEvents()
        self.addCleanup(destroy_widget, panel)
        return panel

    def test_copy_report_reads_current_config_and_errors_from_failure_dialog(self):
        from comic_translate_desktop import config
        from comic_translate_desktop.diagnostics import Diagnostics
        from comic_translate_desktop.ui.error_log_page import ErrorLogPage

        with patch.object(config, "CONFIG_PATH", self.root / "config.yaml"), patch.object(config, "PROJECT_ROOT", self.root):
            diagnostics = Diagnostics()
            page = ErrorLogPage(diagnostics)
            self.addCleanup(destroy_widget, page)
            config.save_ai_config({"translation_model": "deepseek-flash"})
            diagnostics.add_error("HTTPS client initialization failed")
            self.assertNotIn("deepseek-flash", page.prompt_view.toPlainText())
            with patch("comic_translate_desktop.ui.error_log_page.QApplication.clipboard") as clipboard:
                page.copy_prompt()
                copied = clipboard.return_value.setText.call_args.args[0]
            self.assertIn("deepseek-flash", copied)
            self.assertIn("HTTPS client initialization failed", copied)

    def test_live_log_retains_selection_and_only_resumes_on_request(self):
        panel = self.log_panel()
        for index in range(60):
            panel.append(f'第 {index} 页：日本語、中文与完整长路径')
        panel.flush_all()
        self.app.processEvents()
        self.assertTrue(panel.following)
        cursor = panel.view.textCursor()
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.NextWord, QTextCursor.KeepAnchor)
        panel.view.setTextCursor(cursor)
        panel.view.verticalScrollBar().setValue(0)
        selected = panel.view.textCursor().selectedText()
        self.assertFalse(panel.following)
        for index in range(10):
            panel.append(f'追加记录 {index}')
        panel.flush_all()
        self.app.processEvents()
        self.assertEqual(panel.view.textCursor().selectedText(), selected)
        self.assertEqual(panel.view.verticalScrollBar().value(), 0)
        self.assertEqual(panel.unseen, 10)
        panel.toggle_follow()
        self.assertTrue(panel.following)
        self.assertEqual(panel.view.verticalScrollBar().value(), panel.view.verticalScrollBar().maximum())

    def test_multiline_records_are_bounded_and_final_error_is_preserved(self):
        panel = self.log_panel()
        for index in range(5100):
            panel.append(f'事件 {index}\n堆栈续行 {index}')
        panel.append('[失败] 最终错误\n完整堆栈')
        panel.flush_all()
        self.assertEqual(len(panel.records), 5000)
        self.assertEqual(panel.view.document().blockCount(), 5000)
        self.assertIn('事件 101\n堆栈续行 101', panel.filtered_text())
        self.assertNotIn('事件 100\n', panel.filtered_text())
        self.assertIn('最终错误', panel.view.toPlainText())
        self.assertFalse(panel.pending)

    def test_fast_log_reveal_keeps_complete_record_and_unicode_clusters(self):
        panel = self.log_panel()
        message = '中文ab\u0301后续文字逐字出现\n日本語と長いパス / chapter_01.png'
        panel.append(message)
        panel.timer.stop()
        panel.flush()
        first = panel.view.toPlainText().split('\t', 2)[-1]
        self.assertEqual(first, '中文ab\u0301')
        self.assertEqual(panel.records[-1][2], message)
        self.assertIn(message, panel.filtered_text())
        panel.flush()
        second = panel.view.toPlainText().split('\t', 2)[-1]
        self.assertTrue(second.startswith(first))
        self.assertGreater(len(second), len(first))
        self.assertLess(len(second), len(message))
        self.assertEqual(panel.view.document().blockCount(), 1)
        panel.flush_all()
        self.assertEqual(panel.view.toPlainText().split('\t', 2)[-1], message)
        self.assertFalse(panel._reveal_queue)
        self.assertFalse(panel.timer.isActive())

    def test_selecting_partial_log_keeps_selection_and_copy_contains_full_text(self):
        panel = self.log_panel()
        message = '当前日志' + '继续输出可复制内容。' * 10
        panel.append(message)
        panel.timer.stop()
        panel.flush()
        cursor = panel.view.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.movePosition(QTextCursor.PreviousCharacter, QTextCursor.KeepAnchor, 2)
        panel.view.setTextCursor(cursor)
        selected = cursor.selectedText()
        self.assertFalse(panel.following)
        panel.flush()
        self.assertFalse(panel._reveal_queue)
        self.assertEqual(panel.view.textCursor().selectedText(), selected)
        self.assertIn(message, panel.view.toPlainText())
        cursor = panel.view.textCursor()
        cursor.clearSelection()
        panel.view.setTextCursor(cursor)
        panel.copy_logs()
        self.assertIn(message, self.app.clipboard().text())

    def test_log_reveal_accelerates_backlog_and_error_flushes_partial_tail(self):
        panel = self.log_panel()
        for index in range(100):
            panel.append(f'第{index}条：' + '批量输出' * 4)
        panel.timer.stop()
        panel.flush()
        initial = panel._remaining_chars
        for _ in range(6):
            panel.flush()
        self.assertLess(panel._remaining_chars, initial - 6 * panel.CHARS_PER_FRAME)
        panel.append('[失败] 最终错误必须立即完整显示\n完整堆栈')
        panel.flush()
        self.assertFalse(panel.pending)
        self.assertFalse(panel._reveal_queue)
        self.assertEqual(panel._remaining_chars, 0)
        self.assertEqual(panel.view.document().blockCount(), 101)
        self.assertTrue(panel.view.toPlainText().endswith('完整堆栈'))

    def test_filtered_view_evicts_old_matches_and_search_pauses_follow(self):
        panel = self.log_panel()
        panel.level.setCurrentText('ERROR')
        panel.append('[失败] 旧错误')
        panel.flush_all()
        for index in range(5000):
            panel.append(f'正常消息 {index}')
        panel.flush_all()
        self.assertNotIn('旧错误', panel.view.toPlainText())
        panel.level.setCurrentIndex(0)
        panel.search.setText('正常消息 4999')
        panel._refilter()
        self.assertFalse(panel.following)
        self.assertIn('正常消息 4999', panel.view.toPlainText())
        self.assertNotIn('正常消息 4998', panel.view.toPlainText())
        panel.font_size.setValue(18)
        fragment = panel.view.document().firstBlock().begin().fragment()
        self.assertEqual(fragment.charFormat().font().pixelSize(), 18)

    def test_stage_events_keep_parallel_pages_separate_and_preserve_skips(self):
        panel = StepPanel()
        def event(page, stage, state):
            panel.consume_event(dict(page_id=page, page_label=page, stage=stage, state=state, message=stage))
        event('1:1', 'detect', 'done')
        event('1:2', 'start', 'running')
        self.assertEqual(panel._states['detect'], PENDING)
        event('1:1', 'translate', 'skipped')
        self.assertEqual(panel._states['detect'], DONE)
        self.assertEqual(panel._states['translate'], SKIPPED)
        event('1:1', 'save', 'done')
        self.assertEqual(panel._states['translate'], SKIPPED)
        self.assertEqual(panel._pages['1:2']['start'], RUNNING)

    def test_node_track_advances_only_after_completion_and_keeps_skipped_nodes(self):
        panel = StepPanel()
        panel.resize(760, 112)
        panel.show()
        self.addCleanup(destroy_widget, panel)

        def event(stage, state):
            panel.consume_event(dict(page_id='1:1', page_label='第 1 页', stage=stage, state=state, message=stage))

        event('start', 'running')
        self.assertEqual(panel.progress_fraction, 0)
        event('detect', 'done')
        self.assertEqual(panel.progress_fraction, 2 / 7)
        event('ocr', 'done')
        self.assertEqual(panel.progress_fraction, 3 / 7)
        self.app.processEvents()
        # Both fork nodes are rendered on parallel rows in the same column.
        tr_rect = panel._node_rects['translate']
        in_rect = panel._node_rects['inpaint']
        self.assertLess(tr_rect.bottom(), in_rect.top())
        self.assertAlmostEqual(tr_rect.left(), in_rect.left(), delta=1.0)
        before_tr = panel.grab().toImage().pixelColor(int(tr_rect.center().x()), int(tr_rect.top() + 2)).lightness()
        event('translate', 'running')
        event('inpaint', 'running')
        self.assertEqual(panel.progress_fraction, 3 / 7)
        self.app.processEvents()
        active_tr = panel.grab().toImage().pixelColor(int(tr_rect.center().x()), int(tr_rect.top() + 2)).lightness()
        active_in = panel.grab().toImage().pixelColor(int(in_rect.center().x()), int(in_rect.top() + 2)).lightness()
        self.assertGreater(before_tr, 200)
        self.assertLess(active_tr, 50)
        self.assertLess(active_in, 50)
        # Parallel inpaint completing before translate cannot advance past join.
        event('inpaint', 'done')
        event('typeset', 'done')
        self.assertEqual(panel.progress_fraction, 4 / 7)
        event('translate', 'skipped')
        self.assertEqual(panel.progress_fraction, 6 / 7)
        event('save', 'done')
        self.assertEqual(panel.progress_fraction, 1)
        event('inpaint', 'running')
        event('translate', 'done')
        self.assertEqual(panel.progress_fraction, 1)
        self.assertEqual(panel._states['translate'], SKIPPED)
        self.assertEqual(panel._states['inpaint'], DONE)

    def test_workflow_visualizer_tracks_parallel_lanes_repair_ready_resumed_and_dark_theme(self):
        panel = StepPanel()
        panel.resize(960, 112)
        panel.show()
        self.addCleanup(destroy_widget, panel)
        self.addCleanup(lambda: apply_theme(self.app, 'light'))

        panel.consume_workflow_event({
            'type': 'plan',
            'max_workers': 4,
            'retain_context': True,
            'context_entries': 2,
            'pages': [
                {'page_id': '1:1', 'page_label': 'book.pdf 第 1/4 页', 'resumed': True},
                {'page_id': '1:2', 'page_label': 'book.pdf 第 2/4 页', 'resumed': False},
                {'page_id': '1:3', 'page_label': 'book.pdf 第 3/4 页', 'resumed': False},
                {'page_id': '1:4', 'page_label': 'book.pdf 第 4/4 页', 'resumed': False},
            ],
        })
        self.assertEqual(panel._resumed_count(), 1)
        # Page 2 enters fork, repair finishes first -> READY at join while translate still runs.
        for stage, state in (('start', 'running'), ('detect', 'done'), ('ocr', 'done'),
                             ('translate', 'running'), ('inpaint', 'running')):
            panel.consume_event(dict(page_id='1:2', page_label='book.pdf 第 2/4 页',
                                     stage=stage, state=state, message=stage))
        panel.consume_workflow_event({'type': 'repair_ready', 'page_id': '1:2', 'page_label': 'book.pdf 第 2/4 页'})
        # Page 3 simultaneously enters detection on the preparation lane.
        panel.consume_event(dict(page_id='1:3', page_label='book.pdf 第 3/4 页',
                                 stage='start', state='running', message='start'))
        panel.consume_event(dict(page_id='1:3', page_label='book.pdf 第 3/4 页',
                                 stage='detect', state='running', message='detect'))
        views = panel._compute_stage_views()
        self.assertEqual(views['detect'].state, RUNNING)
        self.assertEqual(views['detect'].badge, 'P3')
        self.assertEqual(views['ocr'].state, DONE)
        self.assertEqual(views['translate'].state, RUNNING)
        self.assertEqual(views['translate'].badge, 'P2')
        self.assertEqual(views['inpaint'].state, READY)
        self.assertEqual(views['inpaint'].badge, 'P2')
        self.assertEqual(views['typeset'].state, PENDING)

        # Page 2 finishes translation, joins branches, and updates context count.
        panel.consume_event(dict(page_id='1:2', page_label='book.pdf 第 2/4 页',
                                 stage='translate', state='done', message='翻译完成'))
        panel.consume_workflow_event({'type': 'context', 'page_id': '1:2', 'context_entries': 3})
        panel.consume_workflow_event({'type': 'join', 'page_id': '1:2', 'page_label': 'book.pdf 第 2/4 页'})
        views = panel._compute_stage_views()
        self.assertEqual(views['typeset'].state, RUNNING)
        self.assertEqual(views['typeset'].badge, 'P2')
        self.assertEqual(panel._context_entries, 3)

        # Failed stage keeps sibling ready/done state intact when mark_failed() is also called.
        panel.consume_event(dict(page_id='1:3', page_label='book.pdf 第 3/4 页',
                                 stage='inpaint', state='running', message='repair'))
        panel.consume_workflow_event({'type': 'repair_ready', 'page_id': '1:3', 'page_label': 'book.pdf 第 3/4 页'})
        panel.consume_event(dict(page_id='1:3', page_label='book.pdf 第 3/4 页',
                                 stage='translate', state='failed', message='402'))
        panel.mark_failed()
        views = panel._compute_stage_views()
        self.assertEqual(views['translate'].state, FAILED)
        self.assertEqual(views['inpaint'].state, READY)

        # PDF publishing stage and dark theme rendering check.
        panel.consume_workflow_event({'type': 'publish', 'document_name': 'book.pdf', 'state': 'running'})
        self.assertEqual(panel._compute_stage_views()['save'].badge, 'PDF')
        apply_theme(self.app, 'dark')
        self.app.processEvents()
        dark_img = panel.grab().toImage()
        self.assertLess(dark_img.pixelColor(20, 10).lightness(), 40)
        panel.set_compact(True)
        self.assertEqual(panel.height(), 66)
        self.app.processEvents()

        # Queued fallback tiles reflect terminal phase when no explicit plan arrived.
        fallback_panel = StepPanel()
        fallback_panel.set_queued_files(2, ['a.png', 'b.png'])
        self.assertEqual(fallback_panel._classify_page_tile('q:1', 0, False)[0], 'queued')
        fallback_panel.mark_done()
        self.assertEqual(fallback_panel._classify_page_tile('q:1', 0, False)[0], 'done')
        destroy_widget(fallback_panel)

    def test_worker_emits_workflow_plan_repair_ready_join_and_context_events(self):
        from tests.test_resume_translation import RecordingPipeline

        sources = []
        for idx in range(2):
            path = self.root / f'p{idx}.png'
            Image.new('RGB', (48, 64), 'white').save(path)
            sources.append(path)

        class ForkPipeline(RecordingPipeline):
            def repair_comic_page(self, prepared):
                return {'repaired': True}

            def finish_comic_page(self, output_path, prepared, translations):
                prepared.pop('repaired', None)
                super().finish_comic_page(output_path, prepared, translations)

        worker = BatchWorker(sources, self.root / 'output', {'max_workers': 2}, pipeline=ForkPipeline())
        events = []
        worker.workflow_event.connect(events.append, Qt.DirectConnection)
        worker.run()
        types = [event['type'] for event in events]
        self.assertIn('plan', types)
        self.assertIn('repair_ready', types)
        self.assertIn('join', types)
        self.assertIn('context', types)
        plan = next(event for event in events if event['type'] == 'plan')
        self.assertEqual(len(plan['pages']), 2)
        self.assertEqual(plan['max_workers'], 2)

    def test_node_track_stops_at_failure_and_does_not_combine_parallel_pages(self):
        panel = StepPanel()
        def event(page, stage, state):
            panel.consume_event(dict(page_id=page, page_label=page, stage=stage, state=state, message=stage))
        event('1:1', 'save', 'done')
        self.assertEqual(panel.progress_fraction, 0)
        event('1:1', 'detect', 'done')
        event('1:1', 'ocr', 'done')
        event('1:1', 'translate', 'failed')
        self.assertEqual(panel.progress_fraction, 3 / 7)
        self.assertEqual(panel._states['translate'], FAILED)
        event('1:2', 'start', 'running')
        self.assertEqual(panel.progress_fraction, 0)
        panel.mark_cancelled()
        self.assertEqual(panel.progress_fraction, 0)
        self.assertEqual(panel._states['start'], CANCELLED)
        self.assertEqual(panel._pages['1:1']['translate'], FAILED)

    def fixture_page(self, name='page'):
        output = self.root / 'output' / f'{name}.png'
        cleaned = self.root / 'output_cleaned' / f'{name}_cleaned.png'
        layout = self.root / 'output_layout' / f'{name}_layout.json'
        for file in (output, cleaned, layout):
            file.parent.mkdir(exist_ok=True)
        for file in (output, cleaned):
            Image.new('RGB', (200, 300), '#ffeedd').save(file)
        layout.write_text(json.dumps([dict(text='译文', source_text='日本語', box=[20, 20, 80, 180], style='dialogue', font_size=18, direction=1, offset_x=0, offset_y=0, source_language='ja', custom_metadata='keep')], ensure_ascii=False), encoding='utf-8')
        return output, layout

    def test_settings_draft_survives_navigation_and_preserves_ocr_values(self):
        from comic_translate_desktop import config
        with patch.object(config, 'CONFIG_PATH', self.root / 'defaults.yaml'), \
             patch.object(config, 'PROJECT_ROOT', self.root), \
             patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
            self.addCleanup(destroy_widget, window)
            page = window.api_config_page
            window._show_api_config()
            page._model_input.setText('draft-translation-model')
            page._key_input.setText('draft-key')
            page._source_language.setCurrentIndex(page._source_language.findData('custom'))
            page._custom_language.setText('fr')
            page._custom_url.setText('https://example.invalid/ocr')
            page._custom_timeout.setValue(90)
            page._watermark_check.setChecked(True)
            page._sections.setCurrentIndex(2)
            window.tabs.setCurrentWidget(window.translate_tab)
            window._show_api_config()
            values = page.values()
            self.assertEqual(values['translation_model'], 'draft-translation-model')
            self.assertEqual(values['api_key'], 'draft-key')
            self.assertEqual(values['custom_source_language'], 'fr')
            self.assertEqual(values['custom_ocr_url'], 'https://example.invalid/ocr')
            self.assertEqual(values['custom_ocr_timeout'], 90)
            self.assertEqual(values['ocr_backend'], 'custom')
            self.assertTrue(values['watermark_enabled'])
            self.assertIn('未保存', page._save_status.text())
            self.assertTrue(window._settings_btn.isChecked())
            self.assertFalse(window._nav_auto.isChecked())

    def test_startup_keeps_model_loading_out_of_window_creation(self):
        from comic_translate_desktop import config
        with patch.object(config, 'CONFIG_PATH', self.root / 'defaults.yaml'), \
             patch.object(config, 'PROJECT_ROOT', self.root), \
             patch.object(MainWindow, '_start_warmup') as warmup:
            window = MainWindow()
            self.addCleanup(destroy_widget, window)
            self.assertFalse(window._warmup_timer.isActive())
            window.show()
            self.app.processEvents()
            self.assertTrue(window._warmup_timer.isActive())
        warmup.assert_not_called()
        self.assertIsNone(window.warmup_worker)

    def test_compact_settings_and_diagnosis_keep_primary_actions_visible(self):
        from comic_translate_desktop import config
        with patch.object(config, 'CONFIG_PATH', self.root / 'defaults.yaml'), \
             patch.object(config, 'PROJECT_ROOT', self.root), \
             patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
            self.addCleanup(destroy_widget, window)
            window.resize(820, 480)
            window.show()
            for page, button in ((window.api_config_page, window.api_config_page._save_btn),
                                 (window.error_log_page, window.error_log_page._send_btn)):
                window.tabs.setCurrentWidget(page)
                if page is window.error_log_page:
                    page._sections.setCurrentIndex(1)
                self.app.processEvents()
                self.assertTrue(button.isVisible())
                self.assertTrue(window.rect().contains(button.mapTo(window, button.rect().topLeft())))
                self.assertTrue(window.rect().contains(button.mapTo(window, button.rect().bottomRight())))

    def test_editor_loading_and_noop_save_preserve_image_and_layout(self):
        output, layout = self.fixture_page()
        original_image, original_layout = output.read_bytes(), layout.read_bytes()
        editor = EditorPage()
        self.assertTrue(editor.load_page(output))
        self.assertEqual(editor._source_text.toPlainText(), '日本語')
        self.assertTrue(editor.save_image())
        self.assertEqual(output.read_bytes(), original_image)
        self.assertEqual(layout.read_bytes(), original_layout)
        self.assertEqual(editor.preview._original.toImage().pixelColor(0, 0).name(), '#ffeedd')

    def test_canvas_focus_preserves_draft_and_restores_sidebar_preferences(self):
        output, layout = self.fixture_page()
        editor = EditorPage()
        self.addCleanup(destroy_widget, editor)
        editor.load_page(output)
        editor._pages_toggle.setChecked(True)
        editor._properties_toggle.setChecked(True)
        editor._text_input.setPlainText('仍在编辑的译文')
        original_image, original_layout = output.read_bytes(), layout.read_bytes()
        editor._focus_btn.setChecked(True)
        self.assertTrue(editor._dirty)
        self.assertFalse(editor._pages_toggle.isChecked())
        self.assertFalse(editor._properties_toggle.isChecked())
        editor.save_ui_state()
        self.assertTrue(QSettings().value('ui/editorPages', False, type=bool))
        self.assertTrue(QSettings().value('ui/editorProperties', False, type=bool))
        editor._focus_btn.setChecked(False)
        self.assertTrue(editor._pages_toggle.isChecked())
        self.assertTrue(editor._properties_toggle.isChecked())
        self.assertEqual(editor._text_input.toPlainText(), '仍在编辑的译文')
        self.assertEqual(output.read_bytes(), original_image)
        self.assertEqual(layout.read_bytes(), original_layout)
        # This test leaves no persisted panel state for the following tests.
        QSettings().remove('ui/editorPages')
        QSettings().remove('ui/editorProperties')

    def test_editor_keeps_draft_on_navigation_and_reports_real_save_failure(self):
        output, layout = self.fixture_page()
        second, _ = self.fixture_page('second')
        editor = EditorPage()
        editor.load_page(output)
        editor._text_input.setPlainText('修改后的译文')
        editor.load_page(output)
        self.assertTrue(editor._dirty)
        self.assertEqual(editor._text_input.toPlainText(), '修改后的译文')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Cancel):
            self.assertFalse(editor.load_page(second))
        self.assertEqual(editor.output_path, output)
        with patch.object(Path, 'write_text', side_effect=OSError('只读目录')):
            self.assertFalse(editor.save_image())
        self.assertTrue(editor._dirty)
        self.assertIn('保存失败', editor._status.text())
        self.assertTrue(editor.save_image())
        saved = json.loads(layout.read_text(encoding='utf-8'))
        self.assertEqual(saved[0]['text'], '修改后的译文')
        self.assertEqual(saved[0]['custom_metadata'], 'keep')
        self.assertFalse(editor._dirty)
        missing = self.root / 'missing.png'
        previous = editor._rendered
        self.assertFalse(editor.load_page(missing))
        self.assertIs(editor._rendered, previous)
        self.assertTrue(editor._save_btn.isEnabled())

    def test_parallel_worker_events_use_thread_local_page_identity(self):
        worker = BatchWorker([], self.root, {})
        barrier = threading.Barrier(2)
        class Pipeline:
            def translate_page_batch(_self, texts, image):
                barrier.wait(timeout=5)
                worker._emit_stage('translate', f'正在请求 {image}')
                return texts
        worker._pipeline = Pipeline()
        events = []
        worker.stage_event.connect(events.append, Qt.DirectConnection)
        threads = []
        for index in (1, 2):
            doc = _DocumentJob(index, self.root / f'{index}.png', self.root / f'out{index}.png', False)
            page = _PageJob(doc, doc.source_path, doc.output_path)
            thread = threading.Thread(target=worker._translate_page, args=(page, {'ocr_texts': ['原文'], 'img_cv': index}))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        requests = [event for event in events if event['state'] == 'running']
        self.assertEqual({(event['page_id'], event['message']) for event in requests}, {('1:1', '正在请求 1'), ('2:1', '正在请求 2')})
        self.assertTrue(all(event['task_id'] == worker.task_id for event in events))

    def test_stream_keeps_interleaved_thread_fragments_in_their_own_lines(self):
        lines = []
        stream = QtTextStream(lines.append)
        barrier = threading.Barrier(2)
        def write(label):
            stream.write(label)
            barrier.wait(timeout=5)
            stream.write('完成\n')
        threads = [threading.Thread(target=write, args=(label,)) for label in ('A', 'B')]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        stream.flush()
        self.assertCountEqual(lines, ['A完成', 'B完成'])

    def test_stop_waits_for_terminal_event_and_flushes_final_summary(self):
        output, _ = self.fixture_page()
        with patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
        window._add_paths([output])
        worker = BatchWorker([output], self.root, {}, parent=window)
        window.worker = worker
        window._active_task_id = worker.task_id
        worker.finished.connect(window._on_finished)
        window.step_panel.start_file('当前页面')
        with patch.object(worker, 'isRunning', return_value=True):
            window._stop_translation()
        self.assertIn('正在停止', window.status_label.text())
        self.assertEqual(window.step_panel._states['start'], RUNNING)
        worker.finished.emit(0, 0)
        self.assertIsNone(window.worker)
        self.assertIn('已取消', window.status_label.text())
        self.assertIn('已停止', window.log_view.toPlainText())
        self.assertFalse(window._log_panel.pending)
        window.close()

    def test_old_task_events_do_not_change_current_progress(self):
        with patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
        window.worker = BatchWorker([], self.root, {}, parent=window)
        initial = window.stage_label.text()
        window._on_stage_event(dict(task_id='old-task', message='迟到消息'))
        self.assertEqual(window.stage_label.text(), initial)
        window.worker = None
        window.close()

    def test_optional_font_styles_stay_in_sync_across_ui_config_and_ai(self):
        """编辑器可选风格、配置键、AI 白名单三处必须完全一致，缺一处就会静默回退。"""
        import sys
        from pathlib import Path

        from comic_translate_desktop.config import FONT_DEFAULTS, FONT_KEYS
        from comic_translate_desktop.ui.editor_page import STYLE_LABELS

        main_dir = Path(__file__).resolve().parents[1] / 'comic-translate-ai' / 'main'
        if str(main_dir) not in sys.path:
            sys.path.insert(0, str(main_dir))
        from text_style import FONT_STYLES

        self.assertEqual(set(STYLE_LABELS), set(FONT_KEYS))
        self.assertEqual(set(FONT_KEYS), set(FONT_DEFAULTS))
        self.assertEqual(set(FONT_DEFAULTS), set(FONT_STYLES))

        editor = EditorPage()
        offered = {editor._style_combo.itemData(index) for index in range(editor._style_combo.count())}
        self.assertTrue(set(STYLE_LABELS) <= offered)
        for style in ('seto', 'tegaki_851', 'lxgw_marker'):
            self.assertIn(style, offered)
        editor.deleteLater()


if __name__ == '__main__':
    unittest.main()
