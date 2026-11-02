"""Atomic, per-document progress; contains text and paths, never API credentials."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from functools import wraps
from threading import RLock

from PIL import Image


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode('utf-8')).hexdigest()


def _identity(source, config):
    with source.open('rb') as stream:
        source_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    ignored = {'raw', 'api_key', 'max_workers', 'resume_enabled', 'use_gpu',
               'ui_language', 'ui_language_selected', 'issue_url',
               'page_input_dir', 'page_output_dir', 'page_test_output_dir'}
    settings = {key: value for key, value in config.items()
                if key not in ignored and not key.endswith(('_key', '_token', '_password'))}
    # Replacing a model/font at the same path must invalidate previous results.
    resources = []
    for key, value in settings.items():
        values = value.values() if key in ('font_map', 'style_font_map') else (
            value if key == 'font_fallbacks' else [value] if key.endswith('_model') else [])
        for item in values:
            if isinstance(item, str) and Path(item).exists():
                path = Path(item)
                stat = path.stat()
                resources.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    return _digest([str(source.resolve()), source_hash, settings, resources])


def editable_files_exist(output: Path) -> bool:
    cleaned = output.parent.parent / f'{output.parent.name}_cleaned' / f'{output.stem}_cleaned.png'
    layout = output.parent.parent / f'{output.parent.name}_layout' / f'{output.stem}_layout.json'
    try:
        for path in (output, cleaned):
            with Image.open(path) as image:
                image.verify()
        data = json.loads(layout.read_text(encoding='utf-8'))
        return isinstance(data, list) and all(isinstance(item, dict) and
            isinstance(item.get('box'), list) and len(item['box']) >= 4 for item in data)
    except (OSError, ValueError, TypeError, SyntaxError):
        return False


def _synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class DocumentCheckpoint:
    def __init__(self, source: Path, output: Path, config):
        self._lock = RLock()
        self.output = output.resolve()
        directory = self.output.parent / '.comitrans-resume'
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f'{_digest(str(self.output))}.json'
        identity = _identity(source, config)
        self.data = {'version': 1, 'identity': identity, 'completed': [], 'translations': {}}
        if config.get('resume_enabled', True):
            try:
                old = json.loads(self.path.read_text(encoding='utf-8'))
                if (isinstance(old, dict) and old.get('version') == 1 and old.get('identity') == identity
                        and isinstance(old.get('completed'), list)
                        and isinstance(old.get('translations'), dict)):
                    self.data = old
            except (OSError, ValueError, TypeError):
                pass
        self.save()

    @_synchronized
    def save(self):
        temporary = self.path.with_suffix('.writing')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    @_synchronized
    def project_directory(self):
        value = self.data.get('project_dir')
        if not isinstance(value, str):
            return None
        path = (self.output.parent / value).resolve()
        return path if path.parent == self.output.parent and path.is_dir() else None

    @_synchronized
    def set_project_directory(self, path):
        self.data['project_dir'] = str(path.relative_to(self.output.parent))
        self.save()

    @_synchronized
    def completed(self, number, output):
        if number not in self.data['completed']:
            return False
        if editable_files_exist(output):
            return True
        self.data['completed'].remove(number)
        self.save()
        return False

    @_synchronized
    def mark_completed(self, number):
        if number not in self.data['completed']:
            self.data['completed'].append(number)
        self.save()

    @_synchronized
    def translation(self, number, ocr):
        entry = self.data['translations'].get(str(number))
        if isinstance(entry, dict) and entry.get('ocr') == ocr:
            texts = entry.get('texts')
            if isinstance(texts, list) and len(texts) == len(ocr) and all(isinstance(text, str) for text in texts):
                return texts
        return None

    @_synchronized
    def save_translation(self, number, ocr, texts):
        from comic_translate_core.translation_format import validate_translations
        validate_translations(texts, len(ocr))
        self.data['translations'][str(number)] = {'ocr': list(ocr), 'texts': list(texts)}
        self.save()
