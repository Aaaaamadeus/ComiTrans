"""Desktop instrumentation around the existing translation client, without model changes."""
from types import SimpleNamespace

from comic_translate_core.pipeline_settings import TranslationSettings
from comic_translate_core.translation import TranslationClient
from comic_translate_core.translation_context import TranslationContext
from comic_translate_core.translation_format import ResponseFormatCapabilities


def metered_client_factory(factory, meter):
    def create_client(**kwargs):
        client = factory(**kwargs)
        class ClientProxy:
            def __init__(self):
                def create(**options):
                    response = client.chat.completions.create(**options)
                    if meter is not None:
                        meter.record(response)
                    return response
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

            def __getattr__(self, name):
                return getattr(client, name)
        return ClientProxy()
    return create_client


class DesktopTranslationMixin:
    def translate_page_batch(self, ocr_texts, image_input):
        from openai import OpenAI
        from comic_translate_core.chinese import convert_chinese
        if not hasattr(self, '_translation_capabilities'):
            self._translation_capabilities = ResponseFormatCapabilities()
        if not hasattr(self, 'translation_context'):
            self.translation_context = TranslationContext()
        settings = TranslationSettings.from_pipeline(self)
        client = TranslationClient(
            settings, self._translation_capabilities,
            client_factory=metered_client_factory(OpenAI, getattr(self, 'usage_meter', None)),
            convert_text=convert_chinese, report_progress=self._report_progress,
            check_cancelled=self._check_cancelled,
            context_prompt=self.translation_context.prompt(settings))
        result = client.translate(ocr_texts, image_input)
        if not getattr(self, 'translation_context_managed', False):
            self.translation_context.record(None, ocr_texts, result, settings)
        return result
