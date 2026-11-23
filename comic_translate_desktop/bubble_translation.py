"""Translate one selected bubble through the configured translation service."""
from dataclasses import replace
from types import SimpleNamespace

from comic_translate_core.chinese import convert_chinese
from comic_translate_core.errors import TaskCancelledError, TranslationError
from comic_translate_core.languages import source_language_name
from comic_translate_core.pipeline_settings import TranslationSettings
from comic_translate_core.translation import TranslationClient
from comic_translate_core.translation_format import ResponseFormatCapabilities

from .i18n import tr


_CAPABILITIES = ResponseFormatCapabilities()


def retranslate_bubble(config, source_language, source, instruction, context,
                       original_path, box, cancelled):
    from openai import OpenAI

    def check_cancelled():
        if cancelled():
            raise TaskCancelledError()

    check_cancelled()
    settings = TranslationSettings.from_pipeline(SimpleNamespace(**config))
    guidance = settings.translation_prompt or ''
    if instruction.strip():
        guidance = f'{guidance}\n\n【本次单气泡翻译要求】\n{instruction.strip()}'.strip()
    image = None
    if settings.multimodal and original_path is not None:
        import numpy as np
        from PIL import Image

        with Image.open(original_path) as original:
            image = np.asarray(original.crop(tuple(box)).convert('RGB'))[:, :, ::-1]
    settings = replace(settings, translation_prompt=guidance, multimodal=image is not None,
                       source_language_name=source_language_name(
                           {**config, 'source_language': source_language}))
    client = TranslationClient(settings, _CAPABILITIES, client_factory=OpenAI,
                               convert_text=convert_chinese, report_progress=lambda *_: None,
                               check_cancelled=check_cancelled, context_prompt=context)
    candidate, = client.translate([source], image)
    if not candidate.strip():
        raise TranslationError(tr('翻译服务未返回可用译文'))
    return candidate
