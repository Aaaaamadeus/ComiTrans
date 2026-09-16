from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox
from comic_translate_desktop.ui.log_panel import LogPanel
from comic_translate_desktop.ui.step_panel import StepPanel, DONE, RUNNING, PENDING, SKIPPED, FAILED, CANCELLED
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
        self.addCleanup(panel.close)
        return panel

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
        panel.resize(700, 76)
        panel.show()
        self.addCleanup(panel.close)

        def event(stage, state):
            panel.consume_event(dict(page_id='1:1', page_label='第 1 页', stage=stage, state=state, message=stage))

        event('start', 'running')
        self.assertEqual(panel.progress_fraction, 0)
        event('detect', 'done')
        self.assertEqual(panel.progress_fraction, 2 / 7)
        self.app.processEvents()
        # This point lies on the connector, away from the circles and labels.
        before = panel.grab().toImage().pixelColor(275, 12).lightness()
        event('ocr', 'done')
        self.app.processEvents()
        after = panel.grab().toImage().pixelColor(275, 12).lightness()
        self.assertGreater(before, 150)
        self.assertLess(after, 40)
        event('translate', 'running')
        self.assertEqual(panel.progress_fraction, 3 / 7)
        event('translate', 'skipped')
        self.assertEqual(panel.progress_fraction, 4 / 7)
        for stage in ('inpaint', 'typeset', 'save'):
            event(stage, 'done')
        self.assertEqual(panel.progress_fraction, 1)
        event('inpaint', 'running')
        event('translate', 'done')
        self.assertEqual(panel.progress_fraction, 1)
        self.assertEqual(panel._states['translate'], SKIPPED)
        self.assertEqual(panel._states['inpaint'], DONE)

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
        editor.load_page(missing)
        self.assertIsNone(editor._rendered)
        self.assertFalse(editor._save_btn.isEnabled())

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


if __name__ == '__main__':
    unittest.main()
