import json
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.test_translation_errors import _pipeline as bare_pipeline, pipeline_module
from comic_translate_core.errors import TaskCancelledError, TranslationError
from comic_translate_core.pipeline_settings import TranslationSettings
from comic_translate_core.translation_format import (
    TranslationFormatError, parse_translation_response, ResponseFormatCapabilities,
)


def _pipeline():
    return bare_pipeline('test-key', 'https://example.invalid/v1', 'test-model')


def response(content, reason='stop', refusal=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=reason, message=SimpleNamespace(content=content, refusal=refusal))])


class TranslationContractTests(unittest.TestCase):
    def request(self, results, texts=None, pipeline=None):
        pipeline = pipeline or _pipeline()
        client = Mock()
        client.chat.completions.create.side_effect = results
        with patch.object(pipeline_module, 'OpenAI', return_value=client):
            output = pipeline.translate_page_batch(texts or ['原文一', '原文二'], None)
        return output, client.chat.completions.create.call_args_list

    def test_wrong_shapes_types_duplicate_fields_and_invalid_unicode_are_rejected(self):
        invalid = ['[]', '{"translations":null}', '{"translations":[null]}',
                   '{"translations":[1]}', '{"translations":[false]}', '{"translations":[{}]}',
                   '{"translations":["甲"],"other":1}',
                   '{"translations":["甲"],"translations":["乙"]}',
                   '说明 {"translations":["甲"]}', '{"translations":["甲"]} extra',
                   '{"translations":["\\ud800"]}']
        for content in invalid:
            with self.subTest(content=content), self.assertRaises(TranslationFormatError):
                parse_translation_response(content)

    def test_fences_only_removed_at_outer_boundary_and_escapes_preserved(self):
        texts = ['他说："你好"\n下一行\\', 'literal ```json and ```', '']
        content = '```json\n' + json.dumps({'translations': texts}, ensure_ascii=False) + '\n```'
        self.assertEqual(parse_translation_response(content), (texts, True))

    def test_malformed_truncation_never_skips_commas_or_coerces_types(self):
        for content in ('{"translations":["甲",,"乙",', '{"translations":[null,',
                        '{"translations":["甲" "乙",', '{"translations":["甲"],"extra":',
                        '{"translations":["甲","bad\\q'):
            with self.subTest(content=content), self.assertRaises(TranslationFormatError):
                parse_translation_response(content)

    def test_strict_schema_and_corrective_retry_preserve_positions(self):
        output, calls = self.request([
            response('{"translations":["错误的少量结果"]}'),
            response('{"translations":["甲","乙"]}'),
        ])
        self.assertEqual(output, ['甲', '乙'])
        schema = calls[0].kwargs['response_format']['json_schema']
        self.assertTrue(schema['strict'])
        self.assertFalse(schema['schema']['additionalProperties'])
        self.assertEqual(schema['schema']['properties']['translations']['minItems'], 2)
        self.assertEqual(schema['schema']['properties']['translations']['maxItems'], 2)
        prompt = calls[1].kwargs['messages'][1]['content'][0]['text']
        self.assertIn('[0] 原文一', prompt)
        self.assertIn('[1] 原文二', prompt)
        self.assertIn('数量不匹配', prompt)

    def test_excess_items_and_nonstrings_are_never_silently_accepted(self):
        for content in ('{"translations":["甲","乙","丙"]}', '{"translations":["甲",null]}'):
            client = Mock()
            client.chat.completions.create.return_value = response(content)
            with self.subTest(content=content), patch.object(pipeline_module, 'OpenAI', return_value=client):
                with self.assertRaises(TranslationError):
                    _pipeline().translate_page_batch(['一', '二'], None)
            self.assertEqual(client.chat.completions.create.call_count, 3)

    def test_only_length_truncation_can_advance_suffix_and_it_updates_schema_count(self):
        output, calls = self.request([
            response('{"translations":["甲",', 'length'),
            response('{"translations":["乙"]}'),
        ])
        self.assertEqual(output, ['甲', '乙'])
        self.assertNotIn('[0] 原文一', calls[1].kwargs['messages'][1]['content'][0]['text'])
        self.assertEqual(calls[1].kwargs['response_format']['json_schema']['schema']
                         ['properties']['translations']['maxItems'], 1)
        for content, reason in (('{"translations":["甲",', 'stop'),
                                ('{"translations":["甲","乙"', 'length')):
            _, calls = self.request([response(content, reason), response('{"translations":["丙","丁"]}')])
            self.assertIn('[0] 原文一', calls[1].kwargs['messages'][1]['content'][0]['text'])

    def test_format_negotiation_remembers_endpoint_model_and_keeps_validation(self):
        pipeline = _pipeline()
        rejection = RuntimeError('unsupported response_format')
        output, calls = self.request([rejection, rejection,
                                     response('{"translations":[null,"乙"]}'),
                                     response('{"translations":["甲","乙"]}')], pipeline=pipeline)
        self.assertEqual(output, ['甲', '乙'])
        self.assertEqual(calls[0].kwargs['response_format']['type'], 'json_schema')
        self.assertEqual(calls[1].kwargs['response_format']['type'], 'json_object')
        self.assertNotIn('response_format', calls[2].kwargs)
        _, calls = self.request([response('{"translations":["甲","乙"]}')], pipeline=pipeline)
        self.assertNotIn('response_format', calls[0].kwargs)
        pipeline.translation_model = 'another-model'
        _, calls = self.request([response('{"translations":["甲","乙"]}')], pipeline=pipeline)
        self.assertEqual(calls[0].kwargs['response_format']['type'], 'json_schema')

    def test_auth_and_server_errors_do_not_weaken_format(self):
        for code in (401, 429, 500):
            pipeline = _pipeline()
            error = RuntimeError('unsupported response_format')
            error.status_code = code
            client = Mock()
            client.chat.completions.create.side_effect = error
            with self.subTest(code=code), patch.object(pipeline_module, 'OpenAI', return_value=client):
                with self.assertRaises(TranslationError):
                    pipeline.translate_page_batch(['原文'], None)
            self.assertEqual(client.chat.completions.create.call_count, 1)
            self.assertEqual(pipeline._translation_capabilities.mode(
                pipeline.api_base_url, pipeline.translation_model), 'json_schema')

    def test_refusal_and_filter_are_reported_without_automatic_retries(self):
        for reply in (response(None, refusal='refused'), response(None, reason='content_filter')):
            client = Mock()
            client.chat.completions.create.return_value = reply
            with patch.object(pipeline_module, 'OpenAI', return_value=client), self.assertRaises(TranslationError):
                _pipeline().translate_page_batch(['原文'], None)
            self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_cancel_after_response_prevents_retries(self):
        pipeline = _pipeline()
        cancelled = False
        pipeline.cancel_callback = lambda: cancelled
        def reply(**kwargs):
            nonlocal cancelled
            cancelled = True
            return response('invalid')
        with patch.object(pipeline_module, 'OpenAI') as constructor:
            constructor.return_value.chat.completions.create.side_effect = reply
            with self.assertRaises(TaskCancelledError):
                pipeline.translate_page_batch(['原文'], None)
            self.assertEqual(constructor.return_value.chat.completions.create.call_count, 1)

    def test_configuration_is_immutable_snapshot(self):
        pipeline = _pipeline()
        snapshot = TranslationSettings.from_pipeline(pipeline)
        pipeline.translation_model = 'next model'
        self.assertNotEqual(snapshot.translation_model, pipeline.translation_model)
        with self.assertRaises(FrozenInstanceError):
            snapshot.translation_model = 'change'

    def test_cancel_after_valid_response_preserves_paid_translation(self):
        pipeline = _pipeline()
        def reply(**kwargs):
            pipeline.cancel_callback = lambda: True
            return response('{"translations":["可缓存的译文"]}')
        with patch.object(pipeline_module, 'OpenAI') as constructor:
            constructor.return_value.chat.completions.create.side_effect = reply
            self.assertEqual(pipeline.translate_page_batch(['原文'], None), ['可缓存的译文'])
            self.assertEqual(constructor.return_value.chat.completions.create.call_count, 1)

    def test_all_unsupported_options_can_negotiate_within_one_bounded_attempt(self):
        import numpy as np
        pipeline = _pipeline()
        pipeline.multimodal = True
        failures = [RuntimeError('unsupported response_format'), RuntimeError('unsupported response_format'),
                    RuntimeError('unknown parameter thinking'), RuntimeError('unsupported max_tokens'),
                    RuntimeError('unsupported image_url'), response('{"translations":["结果"]}')]
        with patch.object(pipeline_module, 'OpenAI') as constructor:
            create = constructor.return_value.chat.completions.create
            create.side_effect = failures
            self.assertEqual(pipeline.translate_page_batch(['原文'], np.zeros((2, 2, 3), np.uint8)), ['结果'])
        self.assertEqual(create.call_count, 6)
        final = create.call_args.kwargs
        self.assertNotIn('response_format', final)
        self.assertNotIn('extra_body', final)
        self.assertNotIn('max_tokens', final)
        self.assertEqual(len(final['messages'][1]['content']), 1)
