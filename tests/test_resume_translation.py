import json
import os
import tempfile
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtWidgets import QApplication

from comic_translate_desktop.checkpoints import DocumentCheckpoint
from comic_translate_desktop.pdf_project import load_pdf_project
from comic_translate_desktop.pdf_utils import build_pdf_from_images
from comic_translate_desktop.worker import BatchWorker
from tests.test_pdf_translation import _CopyPipeline


class RecordingPipeline(_CopyPipeline):
    def __init__(self, *, fail_translate='', fail_finish='', on_translate=None):
        self.prepared = []
        self.requests = []
        self.finished = []
        self.fail_translate = fail_translate
        self.fail_finish = fail_finish
        self.on_translate = on_translate

    def prepare_comic_page(self, path):
        self.prepared.append(Path(path).name)
        return {'ocr_texts': [Path(path).name], 'img_cv': path}

    def translate_page_batch(self, texts, image):
        name = Path(image).name
        self.requests.append(name)
        if name == self.fail_translate:
            raise RuntimeError('temporary network failure')
        if self.on_translate:
            self.on_translate()
        return ['译文'] * len(texts)

    def finish_comic_page(self, output_path, prepared, translations):
        name = Path(prepared['img_cv']).name
        if name == self.fail_finish:
            raise RuntimeError('render failure')
        super().finish_comic_page(output_path, prepared, translations)
        self.finished.append(name)


class ResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = []
        for number in range(1, 6):
            path = self.root / f'{number}.png'
            Image.new('RGB', (120, 160), 'white').save(path)
            self.sources.append(path)
        self.pdf = self.root / 'book.pdf'
        build_pdf_from_images(self.sources, [(120, 160)] * 5, self.pdf)
        self.output = self.root / 'output'
        self.config = dict(api_key='secret-not-in-checkpoint', api_base_url='https://example.invalid',
                           translation_model='demo', pdf_dpi=96, max_workers=2)

    def run_worker(self, pipeline, files=None, config=None):
        worker = BatchWorker(files or [self.pdf], self.output, config or self.config, pipeline=pipeline)
        summary, progress = [], []
        worker.finished.connect(lambda good, bad: summary.append((good, bad)))
        worker.page_progress.connect(lambda done, total: progress.append((done, total)))
        worker.run()
        return summary, progress

    def test_network_failure_restart_skips_completed_page_and_reuses_project(self):
        first = RecordingPipeline(fail_translate='page_0002.png')
        summary, _ = self.run_worker(first)
        self.assertEqual(summary, [(0, 1)])
        directory = next(self.output.glob('*_edit_*'))
        self.assertTrue((directory / 'translated/page_0001.png').exists())
        second = RecordingPipeline()
        cached = directory / 'source/page_0002.png'
        cached_stamp = cached.stat().st_mtime_ns
        summary, progress = self.run_worker(second)
        self.assertEqual(cached.stat().st_mtime_ns, cached_stamp)
        self.assertEqual(summary, [(1, 0)])
        self.assertEqual(progress[0], (len(first.finished), 5))
        self.assertNotIn('page_0001.png', second.prepared)
        paid = set(first.requests) - {'page_0002.png'}
        self.assertTrue(paid.isdisjoint(second.requests))
        self.assertIn('page_0002.png', second.requests)
        self.assertEqual(load_pdf_project(self.output / 'book_translated.pdf').directory, directory)
        third = RecordingPipeline()
        summary, progress = self.run_worker(third)
        self.assertEqual(summary, [(1, 0)])
        self.assertEqual(third.requests, [])
        self.assertEqual(progress[0], (5, 5))

    def test_finished_page_buffers_are_released_before_reusing_a_prefetch_slot(self):
        class Prepared(dict):
            pass

        pipeline = RecordingPipeline()
        prepare = pipeline.prepare_comic_page
        finish = pipeline.finish_comic_page
        references, live_before_prepare, live_before_finish = [], [], []

        def tracked_prepare(path):
            live_before_prepare.append(sum(ref() is not None for ref in references))
            prepared = Prepared(prepare(path))
            references.append(weakref.ref(prepared))
            return prepared

        def tracked_finish(output, prepared, translations):
            live_before_finish.append(sum(ref() is not None for ref in references))
            finish(output, prepared, translations)

        with patch.object(pipeline, 'prepare_comic_page', tracked_prepare), \
             patch.object(pipeline, 'finish_comic_page', tracked_finish):
            self.assertEqual(self.run_worker(pipeline)[0], [(1, 0)])
        self.assertEqual(len(live_before_prepare), 5)
        self.assertLessEqual(max(live_before_prepare), 1)
        self.assertLessEqual(max(live_before_finish), 2)
        self.assertTrue(all(ref() is None for ref in references))

    def test_render_failure_reuses_paid_translation_after_restart(self):
        first = RecordingPipeline(fail_finish='page_0001.png')
        self.run_worker(first)
        second = RecordingPipeline()
        self.assertEqual(self.run_worker(second)[0], [(1, 0)])
        self.assertIn('page_0001.png', second.finished)
        self.assertNotIn('page_0001.png', second.requests)
        self.assertTrue(set(first.finished).isdisjoint(second.prepared))
        self.assertTrue(set(first.requests).isdisjoint(second.requests))

    def test_cancel_after_translation_keeps_response_for_next_run(self):
        pipeline = RecordingPipeline()
        worker = BatchWorker([self.pdf], self.output, dict(self.config, max_workers=1), pipeline=pipeline)
        pipeline.on_translate = worker.stop
        worker.run()
        self.assertEqual(pipeline.finished, [])
        second = RecordingPipeline()
        self.assertEqual(self.run_worker(second)[0], [(1, 0)])
        self.assertNotIn('page_0001.png', second.requests)
        self.assertIn('page_0001.png', second.finished)

    def test_image_batch_skips_successes_retries_failed_file(self):
        summary, _ = self.run_worker(RecordingPipeline(fail_translate='2.png'), self.sources)
        self.assertEqual(summary, [(4, 1)])
        pipeline = RecordingPipeline()
        self.assertEqual(self.run_worker(pipeline, self.sources)[0], [(5, 0)])
        self.assertEqual(pipeline.requests, ['2.png'])

    def test_api_key_and_concurrency_change_can_resume_but_language_change_cannot(self):
        self.run_worker(RecordingPipeline())
        pipeline = RecordingPipeline()
        self.run_worker(pipeline, config=dict(self.config, api_key='replacement-secret', max_workers=1))
        self.assertEqual(pipeline.requests, [])
        pipeline = RecordingPipeline()
        self.run_worker(pipeline, config=dict(self.config, target_language='zh-Hant'))
        self.assertEqual(len(pipeline.requests), 5)
        for path in (self.output / '.comitrans-resume').glob('*.json'):
            self.assertNotIn('secret', path.read_text(encoding='utf-8'))

    def test_force_restart_and_changed_source_do_not_skip(self):
        self.run_worker(RecordingPipeline(), self.sources[:1])
        pipeline = RecordingPipeline()
        self.run_worker(pipeline, self.sources[:1], dict(self.config, resume_enabled=False))
        self.assertEqual(pipeline.requests, ['1.png'])
        Image.new('RGB', (120, 160), 'black').save(self.sources[0])
        pipeline = RecordingPipeline()
        self.run_worker(pipeline, self.sources[:1])
        self.assertEqual(pipeline.requests, ['1.png'])

    def test_missing_result_recovers_from_translation_cache(self):
        self.run_worker(RecordingPipeline())
        project = load_pdf_project(self.output / 'book_translated.pdf')
        project.images[2].unlink()
        pipeline = RecordingPipeline()
        self.assertEqual(self.run_worker(pipeline)[0], [(1, 0)])
        self.assertEqual(pipeline.prepared, ['page_0003.png'])
        self.assertEqual(pipeline.requests, [])

    def test_corrupt_checkpoint_starts_fresh_and_failed_write_keeps_old_checkpoint(self):
        self.run_worker(RecordingPipeline())
        path = next((self.output / '.comitrans-resume').glob('*.json'))
        path.write_text('{broken', encoding='utf-8')
        pipeline = RecordingPipeline()
        self.assertEqual(self.run_worker(pipeline)[0], [(1, 0)])
        self.assertEqual(len(pipeline.requests), 5)
        before = path.read_bytes()
        checkpoint = DocumentCheckpoint(self.pdf, self.output / 'book_translated.pdf', self.config)
        with patch('comic_translate_desktop.checkpoints.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                checkpoint.save_translation(1, ['raw'], ['translated'])
        self.assertEqual(path.read_bytes(), before)
        self.assertIsNone(checkpoint.translation(1, ['different OCR']))

    def test_resume_preference_is_on_by_default_and_survives_window_restart(self):
        from comic_translate_desktop import config
        from comic_translate_desktop.ui.main_window import MainWindow
        from tests.qt_utils import destroy_widget
        with patch.object(config, 'CONFIG_PATH', self.root / 'config.yaml'), \
                patch.object(config, 'PROJECT_ROOT', self.root), patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
            try:
                self.assertTrue(window._resume_enabled.isChecked())
                window._resume_enabled.setChecked(False)
                self.assertFalse(config.load_ai_config()['resume_enabled'])
                reopened = MainWindow()
                try:
                    self.assertFalse(reopened._resume_enabled.isChecked())
                    reopened._resume_enabled.setChecked(True)
                    self.assertTrue(config.load_ai_config()['resume_enabled'])
                finally:
                    destroy_widget(reopened)
            finally:
                destroy_widget(window)


if __name__ == '__main__':
    unittest.main()
