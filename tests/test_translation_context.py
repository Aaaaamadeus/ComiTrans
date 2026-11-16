import json
import tempfile
import threading
import unittest
import numpy as np
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from comic_translate_core.pipeline_settings import TranslationSettings
from comic_translate_core.translation_context import (
    TranslationContext, MAX_CONTEXT_CHARS, MAX_CONTEXT_PAGES,
)
from comic_translate_core.errors import TranslationError
from comic_translate_desktop import config as app_config
from comic_translate_desktop.worker import BatchWorker
from tests.test_translation_contract import _pipeline, response, pipeline_module
from tests.test_resume_translation import RecordingPipeline
from comic_translate_core.text_mask import MaskResult


class ContextTests(unittest.TestCase):
    def test_every_translation_uses_validated_previous_pages_without_an_enable_switch(self):
        pipeline = _pipeline()
        client = Mock()
        client.chat.completions.create.side_effect = [
            response('{"translations":["小春走了"]}'), response('{"translations":["她回来了"]}')]
        with patch.object(pipeline_module, 'OpenAI', return_value=client):
            pipeline.translate_page_batch(['小春は出かけた'], None)
            pipeline.translate_page_batch(['戻ってきた'], None)
        first, second = client.chat.completions.create.call_args_list
        self.assertNotIn('【前文参考】', str(first.kwargs['messages']))
        self.assertIn('小春は出かけた', str(second.kwargs['messages']))
        self.assertIn('小春走了', str(second.kwargs['messages']))
        self.assertEqual(len(pipeline.translation_context.entries), 2)
        before = json.dumps(pipeline.translation_context.entries)
        with patch.object(pipeline_module, 'OpenAI', return_value=client):
            client.chat.completions.create.side_effect = [response('invalid')] * 3
            with self.assertRaises(TranslationError):
                pipeline.translate_page_batch(['failed page'], None)
        self.assertEqual(json.dumps(pipeline.translation_context.entries), before)

    def test_partial_response_supplies_current_page_prefix_without_committing_invalid_context(self):
        pipeline = _pipeline()
        client = Mock()
        client.chat.completions.create.side_effect = [
            response('{"translations":["小春",', 'length'), response('{"translations":["她"]}')]
        with patch.object(pipeline_module, 'OpenAI', return_value=client):
            self.assertEqual(pipeline.translate_page_batch(['小春', '彼女'], None), ['小春', '她'])
        self.assertIn('本页已完成的前缀', str(client.chat.completions.create.call_args.kwargs['messages']))
        self.assertEqual(len(pipeline.translation_context.entries), 1)

    def test_bounded_persistent_context_filters_languages_and_deduplicates_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'context.json'
            settings = TranslationSettings()
            context = TranslationContext.start(path, retain=False)
            for index in range(30):
                context.record(str(index), ['原文' * 1000], ['译文' * 1000], settings)
            self.assertLessEqual(len(context.entries), MAX_CONTEXT_PAGES)
            self.assertLessEqual(len(json.dumps(context.entries, ensure_ascii=False)), MAX_CONTEXT_CHARS)
            loaded = TranslationContext.start(path, retain=True)
            self.assertEqual(loaded.entries, context.entries)
            loaded.record('29', ['原文'], ['译文'], settings)
            self.assertEqual(loaded.entries, context.entries)
            self.assertEqual(loaded.prompt(replace(settings, target_language='zh-Hant')), '')
            before = path.read_bytes()
            with patch('comic_translate_core.translation_context.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    loaded.record('failed write', ['text'], ['译文'], settings)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(loaded.entries, context.entries)
            self.assertEqual(list(path.parent.glob('*.writing')), [])
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(TranslationContext.start(path, retain=True).entries, [])

    def test_parallel_repair_matches_original_pixels_masks_and_layout_including_empty_translations(self):
        from comic_translator_pipeline import ComicTranslatorPipeline
        class Mask:
            def generate(self, request):
                mask = np.full(request.image.shape[:2], 255, np.uint8)
                return MaskResult(mask, mask.copy(), (255, 255, 255))
        class Typesetter:
            def draw_text(self, canvas, *args, **kwargs):
                return canvas
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = np.full((96, 128, 3), 190, np.uint8)
            source[20:40, 20:40] = 0
            source[20:40, 65:80] = 0
            boxes = [(10, 10, 50, 60, 0, 'dialogue', 16, 0),
                     (55, 10, 90, 60, 0, 'dialogue', 16, 0)]
            for translations in (['甲', '乙'], ['甲', ''], ['', '']):
                layouts, pixels = [], []
                for parallel in (False, True):
                    pipeline = ComicTranslatorPipeline.__new__(ComicTranslatorPipeline)
                    pipeline.multimodal = pipeline.watermark_enabled = False
                    pipeline.progress_callback = pipeline.cancel_callback = None
                    pipeline.text_mask_generator = Mask()
                    pipeline.typesetter = Typesetter()
                    prepared = dict(img_cv=source, bubbles_data=boxes, ocr_texts=['a', 'b'],
                        bubble_metadata=[dict(raw=raw, box=box[:4], style='dialogue', direction=0,
                                              target_font_size=16, non_bubble=False)
                                         for raw, box in zip(['a', 'b'], boxes)])
                    if parallel:
                        prepared['repaired'] = pipeline.repair_comic_page(prepared)
                        self.assertFalse(hasattr(pipeline, 'current_mask_image'))
                    output = root / f'mode-{parallel}' / 'page.png'
                    output.parent.mkdir(exist_ok=True)
                    pipeline.finish_comic_page(output, prepared, translations)
                    with Image.open(output) as image:
                        pixels.append(image.tobytes())
                    layouts.append(json.loads((root / f'mode-{parallel}_layout/page_layout.json')
                                               .read_text(encoding='utf-8')))
                self.assertEqual(pixels[0], pixels[1])
                self.assertEqual(layouts[0], layouts[1])


class ContextWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.patch = patch.object(app_config, 'PROJECT_ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.files = []
        for index in range(3):
            path = self.root / f'{index}.png'
            Image.new('RGB', (32, 48), 'white').save(path)
            self.files.append(path)
        self.cache = self.root / '.cache/translation-context.json'

    def run_batch(self, pipeline, *, files=None, **config):
        worker = BatchWorker(files or self.files, self.root / 'output',
                             dict(max_workers=3, **config), pipeline=pipeline)
        worker.run()
        return worker

    def test_reading_order_is_preserved_with_prefetch_and_completed_pages_rebuild_context(self):
        seen = []
        class Pipeline(RecordingPipeline):
            def translate_page_batch(branch, texts, image):
                seen.append(branch.translation_context.prompt(TranslationSettings()))
                return super().translate_page_batch(texts, image)
        self.run_batch(Pipeline(fail_translate='1.png'))
        self.assertIn('0.png', seen[1])
        second = Pipeline()
        seen.clear()
        self.run_batch(second)
        self.assertEqual(second.requests, ['1.png'])
        self.assertIn('0.png', seen[0])
        self.assertNotIn('2.png', seen[0])
        self.assertEqual(len(json.loads(self.cache.read_text(encoding='utf-8'))['entries']), 3)

    def test_switch_is_only_read_at_task_start_and_retention_forces_resume(self):
        initial = TranslationContext.start(self.cache, retain=False)
        initial.record('previous task', ['旧剧情'], ['旧译文'], TranslationSettings())
        pipeline = RecordingPipeline()
        worker = BatchWorker(self.files[:1], self.root / 'output',
                             {'retain_translation_context': True, 'resume_enabled': False}, pipeline=pipeline)
        self.assertTrue(worker._config['resume_enabled'])
        def change_preference():
            worker._config['retain_translation_context'] = False
        pipeline.on_translate = change_preference
        worker.run()
        self.assertIn('旧剧情', self.cache.read_text(encoding='utf-8'))
        second = RecordingPipeline()
        self.run_batch(second, files=self.files[:1], retain_translation_context=True, resume_enabled=False)
        self.assertEqual(second.requests, [])
        self.run_batch(RecordingPipeline(), files=self.files[1:2], retain_translation_context=False)
        data = self.cache.read_text(encoding='utf-8')
        self.assertNotIn('旧剧情', data)
        self.assertIn('1.png', data)

    def test_cancelled_paid_response_is_saved_to_both_caches_and_reused(self):
        pipeline = RecordingPipeline()
        worker = BatchWorker(self.files, self.root / 'output', {}, pipeline=pipeline)
        pipeline.on_translate = worker.stop
        worker.run()
        self.assertIn('0.png', self.cache.read_text(encoding='utf-8'))
        second = RecordingPipeline()
        self.run_batch(second, retain_translation_context=True)
        self.assertNotIn('0.png', second.requests)

    def test_translation_and_repair_fork_on_same_page_even_with_one_page_in_flight(self):
        translating, repairing = threading.Event(), threading.Event()
        test = self
        class Pipeline(RecordingPipeline):
            def repair_comic_page(branch, prepared):
                repairing.set()
                test.assertTrue(translating.wait(3))
                return {'independent repair': True}
            def translate_page_batch(branch, texts, image):
                translating.set()
                test.assertTrue(repairing.wait(3))
                return super().translate_page_batch(texts, image)
            def finish_comic_page(branch, output, prepared, translations):
                test.assertEqual(prepared.pop('repaired'), {'independent repair': True})
                return super().finish_comic_page(output, prepared, translations)
        pipeline = Pipeline()
        worker = BatchWorker(self.files[:1], self.root / 'output', {'max_workers': 1}, pipeline=pipeline)
        worker.run()
        self.assertEqual(pipeline.finished, ['0.png'])

    def test_repair_failure_preserves_successful_translation_for_retry(self):
        class Pipeline(RecordingPipeline):
            def repair_comic_page(branch, prepared):
                raise RuntimeError('repair failed')
        pipeline = Pipeline()
        self.run_batch(pipeline, files=self.files[:1])
        self.assertEqual(pipeline.requests, ['0.png'])
        self.assertEqual(pipeline.finished, [])
        second = RecordingPipeline()
        self.run_batch(second, files=self.files[:1])
        self.assertEqual(second.requests, [])
        self.assertEqual(second.finished, ['0.png'])

    def test_retained_resume_does_not_replay_older_chapters_over_the_latest_context(self):
        self.run_batch(RecordingPipeline(), files=self.files[:1], retain_translation_context=True)
        context = TranslationContext.start(self.cache, retain=True)
        for index in range(MAX_CONTEXT_PAGES + 1):
            context.record(f'later-{index}', [f'后文{index}'], ['译文'], TranslationSettings())
        before = self.cache.read_bytes()
        self.run_batch(RecordingPipeline(), files=self.files[:1], retain_translation_context=True)
        self.assertEqual(self.cache.read_bytes(), before)
