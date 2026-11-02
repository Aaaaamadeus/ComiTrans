import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from PySide6.QtWidgets import QApplication

from comic_translate_core.errors import TaskCancelledError, TranslationError
from comic_translate_core.inference_control import InferenceGate, run_inference
from comic_translate_core.page_prefetch import PagePrefetch
from comic_translate_desktop.checkpoints import DocumentCheckpoint
from comic_translate_desktop.worker import BatchWorker
from tests.test_pdf_translation import _CopyPipeline
from tests.test_translation_errors import ComicTranslatorPipeline


class PrefetchTests(unittest.TestCase):
    def test_translation_starts_without_batch_barrier_and_pages_remain_ordered(self):
        second_translated = threading.Event()
        first_finishing = threading.Event()
        prepared = []
        def prepare(page):
            prepared.append(page)
            return {'page': page}
        def translate(page, payload):
            if page == 0:
                self.assertTrue(second_translated.wait(3))
            if page == 1:
                second_translated.set()
                self.assertTrue(first_finishing.wait(3))
            return [str(payload['page'])]
        results = []
        with PagePrefetch(range(4), prepare, translate, capacity=2,
                          cancelled=lambda: False, close_preparation=lambda: None) as pages:
            for page, payload, future in pages:
                results.append(future.result(timeout=4))
                if page == 0:
                    self.assertEqual(prepared, [0, 1])
                    first_finishing.set()
                payload = future = None
        self.assertEqual(results, [['0'], ['1'], ['2'], ['3']])

    def test_early_close_joins_producer_and_closes_native_resources_on_owner_thread(self):
        owners, closed = [], []
        def prepare(page):
            owners.append(threading.get_ident())
            return page
        with PagePrefetch(range(1000), prepare, lambda p, data: data, capacity=2,
                          cancelled=lambda: False,
                          close_preparation=lambda: closed.append(threading.get_ident())) as pages:
            for _page, _prepared, future in pages:
                future.result(timeout=3)
                break
        self.assertLessEqual(len(owners), 2)
        self.assertEqual(set(owners), set(closed))
        self.assertNotEqual(closed[0], threading.get_ident())

    def test_preparation_failure_is_delivered_and_does_not_deadlock_shutdown(self):
        closed = threading.Event()
        def prepare(page):
            raise ValueError('prepare failed')
        with self.assertRaisesRegex(ValueError, 'prepare failed'):
            with PagePrefetch([0], prepare, lambda *_: [], capacity=1,
                              cancelled=lambda: False, close_preparation=closed.set) as pages:
                list(pages)
        self.assertTrue(closed.is_set())

    def test_stop_arriving_during_preparation_does_not_submit_translation(self):
        stopped = threading.Event()
        requested = []
        def prepare(page):
            stopped.set()
            return {'page': page}
        with PagePrefetch([0, 1], prepare, lambda *args: requested.append(args), capacity=2,
                          cancelled=stopped.is_set, close_preparation=lambda: None) as pages:
            self.assertEqual(list(pages), [])
        self.assertEqual(requested, [])


class InferenceGateTests(unittest.TestCase):
    def test_waiting_detector_gets_a_turn_between_repair_tiles(self):
        gate = InferenceGate()
        held, queued = threading.Event(), threading.Event()
        sequence = []
        def repair():
            with gate.slot():
                sequence.append('tile1')
                held.set()
                self.assertTrue(queued.wait(3))
            with gate.slot():
                sequence.append('tile2')
        def detector():
            self.assertTrue(held.wait(3))
            with gate.slot(queued.set):
                sequence.append('detector')
        with ThreadPoolExecutor(2) as pool:
            first, second = pool.submit(repair), pool.submit(detector)
            first.result(timeout=5)
            second.result(timeout=5)
        self.assertEqual(sequence, ['tile1', 'detector', 'tile2'])

    def test_cancelled_waiter_does_not_block_the_next_gpu_job(self):
        gate = InferenceGate()
        queued, cancel = threading.Event(), threading.Event()
        def check():
            queued.set()
            if cancel.is_set():
                raise TaskCancelledError('cancel')
        def waiter():
            with gate.slot(check):
                self.fail('cancelled job must not run')
        with ThreadPoolExecutor(1) as pool:
            with gate.slot():
                future = pool.submit(waiter)
                self.assertTrue(queued.wait(3))
                cancel.set()
                with self.assertRaises(TaskCancelledError):
                    future.result(timeout=3)
        with gate.slot():
            self.assertEqual(len(gate._waiting), 0)

    def test_cpu_inference_can_run_while_gpu_is_occupied(self):
        gate = InferenceGate()
        cpu = SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider'], run=lambda *_: 'done')
        with patch('comic_translate_core.inference_control._gpu_gate', gate), gate.slot():
            self.assertEqual(run_inference(cpu, None, {}), 'done')


class WorkerOverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = []
        for index in range(3):
            path = self.root / f'{index}.png'
            Image.new('RGB', (32, 48), (index, 0, 0)).save(path)
            self.files.append(path)

    def test_next_page_preparation_and_api_overlap_current_repair_without_state_leak(self):
        repairing, next_translated = threading.Event(), threading.Event()
        test = self
        class Pipeline(_CopyPipeline):
            fork_preparation = ComicTranslatorPipeline.fork_preparation
            def prepare_comic_page(self, path):
                number = int(Path(path).stem)
                if number == 1:
                    test.assertTrue(repairing.wait(4))
                self.last_detector_mask = number
                return {'ocr_texts': [str(number)], 'img_cv': path, 'mask': number}
            def translate_page_batch(self, texts, image):
                if texts == ['1']:
                    next_translated.set()
                return texts
            def finish_comic_page(self, output, prepared, translations):
                self.last_detector_mask = prepared['mask']
                if translations == ['0']:
                    repairing.set()
                    test.assertTrue(next_translated.wait(4))
                    test.assertEqual(self.last_detector_mask, 0)
                super().finish_comic_page(output, prepared, translations)
        worker = BatchWorker(self.files, self.root / 'output', {'max_workers': 2}, pipeline=Pipeline())
        summaries = []
        worker.finished.connect(lambda *value: summaries.append(value))
        worker.run()
        self.assertEqual(summaries, [(3, 0)])
        self.assertTrue(next_translated.is_set())

    def test_stop_during_repair_caches_inflight_translation_and_stops_prefetch(self):
        repairing, api_waiting, stop_called = threading.Event(), threading.Event(), threading.Event()
        test = self
        class Pipeline(_CopyPipeline):
            def prepare_comic_page(self, path):
                return {'ocr_texts': [Path(path).stem], 'img_cv': path}
            def translate_page_batch(self, texts, image):
                if texts == ['1']:
                    test.assertTrue(repairing.wait(4))
                    api_waiting.set()
                    test.assertTrue(stop_called.wait(4))
                return ['translated']
            def finish_comic_page(self, output, prepared, translations):
                repairing.set()
                test.assertTrue(api_waiting.wait(4))
                worker.stop()
                stop_called.set()
                raise TaskCancelledError('cancelled repair')
        worker = BatchWorker(self.files, self.root / 'output', {'max_workers': 2}, pipeline=Pipeline())
        worker.run()
        cached = [json.loads(p.read_text(encoding='utf-8'))
                  for p in (self.root / 'output/.comitrans-resume').glob('*.json')]
        self.assertEqual(sum(bool(item['translations']) for item in cached), 2)
        self.assertFalse(any(item['completed'] for item in cached))
        self.assertEqual(list((self.root / 'output').glob('*_translated.png')), [])

    def test_concurrent_checkpoint_updates_preserve_every_response_and_completion(self):
        checkpoint = DocumentCheckpoint(self.files[0], self.root / 'output.png', {})
        def save(number):
            checkpoint.save_translation(number, [str(number)], ['text'])
            checkpoint.mark_completed(number)
        with ThreadPoolExecutor(6) as pool:
            list(pool.map(save, range(20)))
        data = json.loads(checkpoint.path.read_text(encoding='utf-8'))
        self.assertEqual(set(data['completed']), set(range(20)))
        self.assertEqual(set(data['translations']), {str(i) for i in range(20)})

    def test_fatal_api_error_stops_future_pages_and_marks_unfinished_documents_failed(self):
        repairing = threading.Event()
        requested = []
        test = self
        class Pipeline(_CopyPipeline):
            def prepare_comic_page(self, path):
                return {'ocr_texts': [Path(path).stem], 'img_cv': path}
            def translate_page_batch(self, texts, image):
                requested.extend(texts)
                if texts == ['1']:
                    test.assertTrue(repairing.wait(4))
                    raise TranslationError('account rejected', fatal=True)
                return ['translated']
            def finish_comic_page(self, output, prepared, translations):
                repairing.set()
                # Wait on the same cancellation callback used by real inference.
                for _ in range(40):
                    if self.cancel_callback():
                        raise TaskCancelledError('fatal error stopped repair')
                    threading.Event().wait(.05)
                test.fail('fatal error did not stop the current pipeline')
        worker = BatchWorker(self.files, self.root / 'output', {'max_workers': 2}, pipeline=Pipeline())
        summaries = []
        worker.finished.connect(lambda *values: summaries.append(values))
        worker.run()
        self.assertEqual(summaries, [(0, 3)])
        self.assertEqual(set(requested), {'0', '1'})
        self.assertEqual(list((self.root / 'output').glob('*_translated.png')), [])
