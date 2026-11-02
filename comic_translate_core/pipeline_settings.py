"""Runtime options that do not require rebuilding inference models."""
from dataclasses import dataclass, fields

from .chinese import normalize_target_language
from .layout_options import normalize_text_color, normalize_vertical_alignment


@dataclass(frozen=True)
class TranslationSettings:
    api_key: str = ''
    api_base_url: str = ''
    translation_model: str = ''
    translation_prompt: str = ''
    chinese_names: str = ''
    source_language_name: str = '日语'
    target_language: str = 'zh-Hans'
    multimodal: bool = False
    disable_thinking: bool = True

    @classmethod
    def from_pipeline(cls, pipeline):
        return cls(**{field.name: getattr(pipeline, field.name, field.default) for field in fields(cls)})


def apply_runtime_settings(pipeline, config):
    for field in fields(TranslationSettings):
        if field.name != 'source_language_name':
            setattr(pipeline, field.name, config.get(field.name, field.default))
    pipeline.target_language = normalize_target_language(config.get('target_language'))
    pipeline.text_color = normalize_text_color(config.get('text_color'))
    pipeline.vertical_alignment = normalize_vertical_alignment(config.get('vertical_alignment'))
    pipeline.multimodal_font_probe = bool(config.get('multimodal_font_probe', False)
                                          and not config.get('translation_font_active', False))
    pipeline.font_probe_samples = int(config.get('font_probe_samples') or 3)
