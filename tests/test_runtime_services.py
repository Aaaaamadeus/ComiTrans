import gc
import tempfile
import unittest
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from tests.test_translation_errors import pipeline_module
from comic_translate_core.errors import TaskCancelledError, TranslationError, TypesettingError
from comic_translate_core.restoration import original_snapshot_path
from comic_translate_desktop.background_repair import BackgroundRepair
from comic_translate_desktop.ui.editor_page import EditorPage
from manga_lama import MangaLama
from vertical_typesetter import VerticalTypesetter


class RuntimeServicesTests(unittest.TestCase):
    def fake_session(self):
        return Mock(get_providers=lambda: ['CPUExecutionProvider'], get_inputs=lambda: [SimpleNamespace(name='image'), SimpleNamespace(name='mask')],
                    get_outputs=lambda: [SimpleNamespace(name='out')])

    def test_model_sessions_shared_by_device_and_file_version_and_released(self):
        with tempfile.TemporaryDirectory() as folder, patch('onnxruntime.InferenceSession', side_effect=lambda *a, **k: self.fake_session()) as create:
            path = Path(folder) / 'test.onnx'
            path.write_bytes(b'model')
            first, second = MangaLama(path, 'cuda'), MangaLama(path, 'cuda')
            self.assertIs(first.onnx_session, second.onnx_session)
            self.assertEqual(create.call_count, 1)
            first.cancel_callback = Mock()
            first._tile_size = 256
            self.assertEqual(second._tile_size, 768)
            self.assertIsNone(second.cancel_callback)
            cpu = MangaLama(path, 'cpu')
            self.assertIsNot(cpu.onnx_session, first.onnx_session)
            self.assertEqual(create.call_args.kwargs['providers'], ['CPUExecutionProvider'])
            resource = weakref.ref(first._session_resource)
            del first, second
            gc.collect()
            self.assertIsNone(resource())
            replacement = MangaLama(path, 'cuda')
            path.write_bytes(b'new model bytes')
            refreshed = MangaLama(path, 'cuda')
            self.assertIsNot(refreshed.onnx_session, replacement.onnx_session)
            self.assertEqual(create.call_count, 4)

    def test_shared_inference_serializes_and_waiting_caller_can_cancel(self):
        with tempfile.TemporaryDirectory() as folder, patch('onnxruntime.InferenceSession', return_value=self.fake_session()):
            path = Path(folder) / 'test.onnx'
            path.write_bytes(b'model')
            first, second = MangaLama(path), MangaLama(path)
            entered, release = Event(), Event()
            def run(*args):
                entered.set()
                if not release.wait(3):
                    raise AssertionError('test did not release first inference')
                return [np.zeros((1, 3, 16, 16), np.float32)]
            first.onnx_session.run.side_effect = run
            image, mask = Image.new('RGB', (16, 16)), Image.new('L', (16, 16), 255)
            with ThreadPoolExecutor(2) as pool:
                active = pool.submit(first._infer, image, mask)
                try:
                    self.assertTrue(entered.wait(2))
                    second.cancel_callback = Mock(side_effect=TaskCancelledError('cancelled'))
                    queued = pool.submit(second._infer, image, mask)
                    with self.assertRaises(TaskCancelledError):
                        queued.result(timeout=2)
                    self.assertEqual(first.onnx_session.run.call_count, 1)
                finally:
                    release.set()
                self.assertEqual(active.result(timeout=2).size, image.size)
            # Exception handling releases the same lock for the next caller.
            second.cancel_callback = None
            self.assertEqual(second._infer(image, mask).size, image.size)

    def test_editor_repair_uses_configured_device_and_reconfiguration_preserves_active_engine(self):
        engine = BackgroundRepair('test.onnx', device='cuda')
        fake_model = Mock(side_effect=lambda image, mask: image)
        with patch('comic_translate_desktop.background_repair.reconstruct_background', return_value=None), \
             patch('manga_lama.MangaLama', return_value=fake_model) as create:
            engine.repair_region(Image.new('RGB', (100, 100)), (20, 20, 40, 40))
        create.assert_called_once_with('test.onnx', device='cuda')
        editor = SimpleNamespace(_repair_engine=engine, config={})
        EditorPage.set_repair_config(editor, {'lama_model': 'new.onnx', 'use_gpu': False})
        self.assertIsNot(editor._repair_engine, engine)
        self.assertEqual(engine.device, 'cuda')
        self.assertIs(engine._inpainter, fake_model)
        self.assertEqual(editor._repair_engine.device, 'cpu')
        current = editor._repair_engine
        EditorPage.set_repair_config(editor, {'lama_model': 'new.onnx', 'use_gpu': False})
        self.assertIs(editor._repair_engine, current)

    def pipeline(self):
        pipeline = pipeline_module.ComicTranslatorPipeline.__new__(pipeline_module.ComicTranslatorPipeline)
        pipeline.source_language = 'ja'
        pipeline.multimodal = pipeline.watermark_enabled = False
        pipeline.progress_callback = pipeline.cancel_callback = None
        pipeline.current_mask_image = Image.new('L', (128, 128), 0)
        pipeline.inpaint_bubbles = Mock(return_value=Image.new('RGB', (128, 128), 'white'))
        pipeline.typesetter = Mock()
        prepared = dict(img_cv=np.zeros((128, 128, 3), np.uint8), ocr_texts=['日本語'],
                        bubbles_data=[(10, 10, 90, 90, 1, 'dialogue', 16, 0)],
                        bubble_metadata=[dict(raw='日本語', box=[10, 10, 90, 90], style='dialogue',
                                              direction=1, target_font_size=16, non_bubble=False)])
        return pipeline, prepared

    def test_typesetter_does_not_hide_automatic_render_failure(self):
        typesetter = VerticalTypesetter.__new__(VerticalTypesetter)
        for manual in (False, True):
            with self.subTest(manual=manual), self.assertRaises(ValueError):
                typesetter.draw_text(Image.new('RGB', (32, 32)), ['invalid'] * 4,
                                     '测试', 'dialogue', manual_layout=manual)

    def test_invalid_translation_fails_before_erasing_pixels(self):
        pipeline, prepared = self.pipeline()
        for translated in ([], ['一', '二'], [None]):
            with self.subTest(translated=translated), self.assertRaises(TranslationError):
                pipeline.finish_comic_page('unused.png', prepared, translated)
        pipeline.inpaint_bubbles.assert_not_called()

    def test_render_failure_preserves_previous_output_cleaned_layout_and_original(self):
        pipeline, prepared = self.pipeline()
        pipeline.typesetter.draw_text.side_effect = RuntimeError('font failed')
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'translated' / 'page.png'
            targets = [output, Path(folder)/'translated_cleaned/page_cleaned.png',
                       Path(folder)/'translated_layout/page_layout.json', original_snapshot_path(output)]
            for index, target in enumerate(targets):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f'previous-{index}'.encode())
            before = [target.read_bytes() for target in targets]
            with self.assertRaisesRegex(TypesettingError, '第 1 个气泡嵌字失败'):
                pipeline.finish_comic_page(output, prepared, ['测试'])
            self.assertEqual([target.read_bytes() for target in targets], before)
            self.assertEqual(list(output.parent.glob('.page-save-*')), [])
