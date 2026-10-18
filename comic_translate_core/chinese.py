"""Chinese output variants shared by translation prompts and local normalization."""
from __future__ import annotations

from functools import lru_cache
from threading import Lock

from opencc import OpenCC

TARGET_LANGUAGES = (("zh-Hans", "简体中文"), ("zh-Hant", "繁體中文"))
_TARGET_NAMES = dict(TARGET_LANGUAGES)
_CONVERSION_LOCK = Lock()


class ChineseConversionError(RuntimeError):
    pass


def normalize_target_language(value: str | None) -> str:
    value = str(value or '').strip().lower().replace('_', '-')
    return 'zh-Hant' if value in ('zh-hant', 'zh-tw', 'zh-hk', 'zh-mo', 'traditional') else 'zh-Hans'


def target_language_name(value: str | None) -> str:
    return _TARGET_NAMES[normalize_target_language(value)]


@lru_cache(maxsize=2)
def _converter(profile: str) -> OpenCC:
    return OpenCC(profile)


def convert_chinese(text: str, target: str | None) -> str:
    if not text:
        return text
    profile = 's2t' if normalize_target_language(target) == 'zh-Hant' else 't2s'
    try:
        # Page translation can finish on several worker threads at once. Keep the
        # converters' lazy dictionary initialization and use on the same lock.
        with _CONVERSION_LOCK:
            return _converter(profile).convert(text)
    except Exception as exc:
        raise ChineseConversionError('本地简繁转换失败，请检查程序和 OpenCC 字典资源是否完整。') from exc
