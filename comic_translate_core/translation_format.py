"""Strict translation payloads, independent of models, Qt and image processing."""
import json
import re
from threading import Lock


class TranslationFormatError(ValueError):
    pass


def validate_translations(items, expected_count=None):
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        raise TranslationFormatError('translations 必须是字符串数组，不能包含 null、数字或对象')
    if expected_count is not None and len(items) != expected_count:
        raise TranslationFormatError(f'译文数量不匹配，需要 {expected_count} 条，实际 {len(items)} 条')
    try:
        for item in items:
            item.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise TranslationFormatError('译文包含无效的 Unicode 字符') from exc
    return items


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TranslationFormatError(f'JSON 包含重复字段 {key}')
        result[key] = value
    return result


def parse_translation_response(content, *, allow_partial=True):
    """Return strings and completeness; salvage only a valid truncated prefix."""
    if not isinstance(content, str) or not content.strip():
        raise TranslationFormatError('翻译响应为空')
    cleaned = content.strip().removeprefix('\ufeff').strip()
    fenced = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.I | re.S)
    if fenced:
        cleaned = fenced[1].strip()
    try:
        data = json.loads(cleaned, object_pairs_hook=_unique_fields)
    except json.JSONDecodeError as exc:
        if not allow_partial:
            raise TranslationFormatError('翻译响应不是合法 JSON') from exc
    else:
        if not isinstance(data, dict) or set(data) != {'translations'}:
            raise TranslationFormatError('JSON 顶层只能包含 translations 字段')
        return validate_translations(data['translations']), True

    match = re.match(r'^\{\s*"translations"\s*:\s*\[', cleaned)
    if not match:
        raise TranslationFormatError('翻译响应不是合法 JSON')
    cursor, recovered = match.end(), []
    decoder = json.JSONDecoder()
    while True:
        cursor = len(cleaned) - len(cleaned[cursor:].lstrip())
        if cursor == len(cleaned):
            return validate_translations(recovered), False
        if cleaned[cursor] != '"':
            raise TranslationFormatError('截断 JSON 的数组元素或分隔符无效')
        try:
            item, cursor = decoder.raw_decode(cleaned, cursor)
        except json.JSONDecodeError as exc:
            if exc.msg.startswith('Unterminated string'):
                return validate_translations(recovered), False
            raise TranslationFormatError('截断 JSON 含有无效转义或控制字符') from exc
        recovered.append(item)
        cursor = len(cleaned) - len(cleaned[cursor:].lstrip())
        if cursor == len(cleaned):
            return validate_translations(recovered), False
        separator = cleaned[cursor]
        if separator == ']' and not cleaned[cursor+1:].strip():
            return validate_translations(recovered), False
        if separator != ',':
            raise TranslationFormatError('截断 JSON 的数组元素或分隔符无效')
        cursor += 1


def response_format(mode, count):
    if mode == 'prompt':
        return {}
    if mode == 'json_object':
        return {'response_format': {'type': 'json_object'}}
    return {'response_format': {'type': 'json_schema', 'json_schema': {
        'name': 'comic_translations', 'strict': True,
        'schema': {'type': 'object', 'properties': {'translations': {
            'type': 'array', 'items': {'type': 'string'},
            'minItems': count, 'maxItems': count,
        }}, 'required': ['translations'], 'additionalProperties': False},
    }}}


def unsupported_option(error, *names):
    status = getattr(error, 'status_code', None)
    if isinstance(status, int) and status not in (400, 422):
        return False
    message = str(error).lower()
    return (any(name in message for name in names)
            and any(word in message for word in ('unsupported', 'not support', 'unknown',
                                                 'unrecognized', 'invalid', 'not allowed',
                                                 '不支持', '不允许')))


class ResponseFormatCapabilities:
    """Remember explicit parameter rejections for this pipeline's endpoints."""
    modes = ('json_schema', 'json_object', 'prompt')

    def __init__(self):
        self._levels = {}
        self._lock = Lock()

    def mode(self, endpoint, model):
        with self._lock:
            return self.modes[self._levels.get((endpoint, model), 0)]

    def downgrade(self, endpoint, model, rejected):
        with self._lock:
            level = max(self._levels.get((endpoint, model), 0), self.modes.index(rejected) + 1)
            self._levels[(endpoint, model)] = min(level, len(self.modes)-1)
            return self.modes[self._levels[(endpoint, model)]]
