import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from comic_translate_core.image_filters import gaussian_background
from comic_translate_core.onnx_session import create_onnx_session
from comic_translate_desktop.pdf_utils import PdfPageRenderer, plan_pdf_pages, build_pdf_from_images
from comic_translate_desktop.worker import BatchWorker
from tests.test_pdf_translation import _CopyPipeline


class InferenceRuntimeTests(unittest.TestCase):
    def test_installed_runtime_directories_stay_registered_and_preload_once(self):
        handle = object()
        with patch('comic_translate_core.onnx_session._cuda_preloaded', False), \
                patch('comic_translate_core.onnx_session._dll_directory_handles', []) as handles, \
                patch('comic_translate_core.onnx_session.runtime_directories', return_value=[Path('C:/CUDA/bin')]), \
                patch('os.add_dll_directory', return_value=handle, create=True) as register, \
                patch('onnxruntime.preload_dlls') as preload:
            from comic_translate_core.onnx_session import _preload_cuda
            import onnxruntime
            _preload_cuda(onnxruntime)
            _preload_cuda(onnxruntime)
            preload.assert_called_once_with()
            register.assert_called_once_with(str(Path('C:/CUDA/bin')))
            self.assertEqual(handles, [handle])

    def test_cuda_dlls_load_once_before_session_creation(self):
        events = []
        def session(*args, **kwargs):
            events.append('session')
            return SimpleNamespace(get_providers=lambda: ['CUDAExecutionProvider', 'CPUExecutionProvider'])
        with patch('comic_translate_core.onnx_session._cuda_preloaded', False), \
                patch('comic_translate_core.onnx_session.runtime_directories', return_value=[]), \
                patch('onnxruntime.preload_dlls', side_effect=lambda: events.append('preload')), \
                patch('onnxruntime.get_available_providers', return_value=['CUDAExecutionProvider']), \
                patch('onnxruntime.InferenceSession', side_effect=session):
            create_onnx_session('detector.onnx', 'cuda')
            create_onnx_session('lama.onnx', 'cuda')
        self.assertEqual(events, ['preload', 'session', 'session'])

    def test_cpu_does_not_probe_or_load_cuda(self):
        session = SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider'])
        with patch('onnxruntime.preload_dlls') as preload, \
                patch('onnxruntime.get_available_providers') as available, \
                patch('onnxruntime.InferenceSession', return_value=session) as create:
            create_onnx_session('model.onnx', 'cpu')
        available.assert_not_called()
        preload.assert_not_called()
        self.assertEqual(create.call_args.kwargs['providers'], ['CPUExecutionProvider'])

    def test_silent_cpu_fallback_is_reported_even_if_session_creation_succeeds(self):
        session = SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider'])
        log = io.StringIO()
        with patch('onnxruntime.preload_dlls'), \
                patch('onnxruntime.get_available_providers', return_value=['CUDAExecutionProvider']), \
                patch('onnxruntime.InferenceSession', return_value=session), contextlib.redirect_stdout(log):
            create_onnx_session('lama.onnx', 'cuda')
        self.assertIn('GPU 未能启用', log.getvalue())
        self.assertIn('实际使用 CPU', log.getvalue())

    def test_cuda_failure_keeps_session_options_for_cpu_fallback(self):
        options = object()
        session = SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider'])
        with patch('onnxruntime.preload_dlls'), \
                patch('onnxruntime.get_available_providers', return_value=['CUDAExecutionProvider']), \
                patch('onnxruntime.InferenceSession', side_effect=[RuntimeError('CUDA unavailable'), session]) as create:
            self.assertIs(create_onnx_session('model.onnx', 'cuda', sess_options=options), session)
        self.assertEqual(create.call_count, 2)
        self.assertIs(create.call_args.kwargs['sess_options'], options)
        self.assertEqual(create.call_args.kwargs['providers'], ['CPUExecutionProvider'])


class NativeFilterTests(unittest.TestCase):
    def test_large_filter_matches_original_pixels_and_borders(self):
        random = np.random.default_rng(71)
        for shape in ((47, 81, 3), (1, 81, 3), (47, 1, 3), (47, 81)):
            source = random.integers(0, 256, shape, dtype=np.uint8)
            original = source.copy()
            source.flags.writeable = False
            for sigma in (1., 11.99, 12., 31.5, 55.25, 265.):
                with self.subTest(shape=shape, sigma=sigma):
                    expected = cv2.GaussianBlur(source, (0, 0), sigma)
                    actual = gaussian_background(source, sigma)
                    np.testing.assert_array_equal(actual, expected)
                    np.testing.assert_array_equal(source, original)


class LazyPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'source.png'
        Image.new('RGB', (160, 240), '#7c3a92').save(source)
        self.pdf = build_pdf_from_images([source] * 7, [(120, 180)] * 7, self.root / 'book.pdf')

    def test_plan_has_all_sizes_and_creates_no_page_images(self):
        target = self.root / 'pages'
        pages = plan_pdf_pages(self.pdf, target, dpi=200)
        self.assertEqual(len(pages), 7)
        self.assertEqual((pages[0].width_points, pages[0].height_points), (120, 180))
        self.assertFalse(target.exists())

    def test_cached_native_page_is_reused_and_corrupt_or_wrong_size_pages_are_rebuilt(self):
        with PdfPageRenderer(self.pdf, dpi=200) as renderer:
            page = renderer.pages(self.root / 'pages')[0]
            renderer.render(page)
            original = page.image_path.read_bytes()
            class CountedDocument:
                def __init__(self, document):
                    self.document = document
                    self.calls = 0
                def render(self, *args):
                    self.calls += 1
                    return self.document.render(*args)
                def close(self):
                    self.document.close()
            renderer.document = CountedDocument(renderer.document)
            renderer.render(page, reuse_cached=True)
            self.assertEqual(renderer.document.calls, 0)
            for bad in ('size', 'corrupt'):
                if bad == 'size':
                    Image.new('RGB', (10, 10)).save(page.image_path)
                else:
                    page.image_path.write_bytes(original[:60])
                renderer.render(page, reuse_cached=True)
                with Image.open(page.image_path) as result:
                    self.assertEqual(result.size, (333, 500))
                self.assertEqual(page.image_path.read_bytes(), original)
            self.assertEqual(renderer.document.calls, 2)

    def test_cancel_during_render_or_save_preserves_previous_page(self):
        with PdfPageRenderer(self.pdf) as renderer:
            page = renderer.pages(self.root / 'pages')[0]
            renderer.render(page)
            original = page.image_path.read_bytes()
            for cancel_at in (2, 3):
                calls = []
                def cancel():
                    calls.append(None)
                    if len(calls) == cancel_at:
                        raise InterruptedError('cancel')
                with self.assertRaises(InterruptedError):
                    renderer.render(page, cancel_callback=cancel)
                self.assertEqual(page.image_path.read_bytes(), original)
                self.assertEqual(list(page.image_path.parent.glob('.render-*')), [])

    def test_first_batch_finishes_before_later_pdf_pages_are_rendered(self):
        pipeline = _CopyPipeline()
        worker = BatchWorker([self.pdf], self.root / 'output',
                             dict(pdf_dpi=200, max_workers=2), pipeline=pipeline)
        real_prepare, real_finish = pipeline.prepare_comic_page, pipeline.finish_comic_page
        def prepare(path):
            page = Path(path)
            self.assertEqual(len(list(page.parent.glob('page_*.png'))), int(page.stem[-4:]))
            return real_prepare(path)
        def finish(path, prepared, translations):
            self.assertLessEqual(len(list(Path(prepared['img_cv']).parent.glob('page_*.png'))), 2)
            real_finish(path, prepared, translations)
            worker.stop()
        pipeline.prepare_comic_page = prepare
        pipeline.finish_comic_page = finish
        failures = []
        worker.image_failed.connect(lambda *args: failures.append(args))
        worker.run()
        project = next((self.root / 'output').glob('*_edit_*'))
        self.assertEqual(failures, [])
        self.assertIn(len(list((project / 'source').glob('*.png'))), (1, 2))
        self.assertEqual(len(list((project / 'translated').glob('*.png'))), 1)
        self.assertIsNone(worker._pdf_renderer)
