"""Offline font catalog and verified, on-demand downloads from Google Fonts."""
from __future__ import annotations
from .i18n import tr

from functools import lru_cache
from hashlib import sha1
import json
from pathlib import Path, PurePosixPath
import tempfile
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import config
from .font_library import font_alias, font_directory, font_reference, import_font, inspect_font, resolve_font_reference


CATEGORY_LABELS = {'sans-serif': '黑体 / 无衬线', 'serif': '宋体 / 衬线', 'handwriting': '手写',
                   'display': '标题 / 装饰', 'monospace': '等宽', 'other': '其它'}
LANGUAGE_LABELS = {'chinese-simplified': '简体中文', 'chinese-traditional': '繁体中文',
                   'japanese': '日文', 'korean': '韩文', 'latin': '拉丁字母',
                   'cyrillic': '西里尔字母', 'arabic': '阿拉伯文', 'devanagari': '天城文', 'thai': '泰文'}


@lru_cache(maxsize=1)
def load_catalog():
    path = config.AI_ROOT.parent / 'assets/font_catalog.json'
    catalog = json.loads(path.read_text(encoding='utf-8'))
    if catalog.get('schema') != 1 or catalog.get('repository') != 'google/fonts':
        raise ValueError(tr('字体目录格式不正确'))
    return catalog


def search_text(family):
    aliases = font_alias(family['name'])
    languages = [LANGUAGE_LABELS.get(subset, subset) for subset in family['subsets']]
    return ' '.join((family['name'], family['id'], aliases,
                     CATEGORY_LABELS.get(family['category'], ''), *languages)).casefold()


def installed_faces():
    installed = {}
    for metadata in (font_directory() / 'licenses').glob('*/source.json'):
        try:
            data = json.loads(metadata.read_text(encoding='utf-8'))
            inspect_font(resolve_font_reference(data['reference']))
            installed[data['git_sha1']] = data['reference']
        except (OSError, ValueError, KeyError):
            continue
    return installed


def _asset_url(catalog, asset):
    path = PurePosixPath(asset['path'])
    if path.is_absolute() or '..' in path.parts or path.parts[0] not in ('ofl', 'apache', 'ufl'):
        raise ValueError(tr('字体下载路径不正确'))
    revision = catalog['revision']
    if len(revision) != 40 or any(char not in '0123456789abcdef' for char in revision):
        raise ValueError(tr('字体目录版本不正确'))
    return f'https://raw.githubusercontent.com/google/fonts/{revision}/{quote(asset["path"], safe="/")}'


def _download_asset(catalog, asset, target, cancelled, progress):
    request = Request(_asset_url(catalog, asset), headers={'User-Agent': 'ComiTrans-Font-Library'})
    with urlopen(request, timeout=20) as response, target.open('wb') as output:
        total = int(response.headers.get('Content-Length') or asset.get('size') or 0)
        received = 0
        while True:
            if cancelled():
                raise InterruptedError(tr('已取消字体下载'))
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > 256 * 1024 * 1024:
                raise ValueError(tr('单个字体文件超过 256 MB'))
            output.write(chunk)
            progress(received, total)
    content = target.read_bytes()
    digest = sha1(f'blob {len(content)}\0'.encode() + content).hexdigest()
    if digest != asset['sha1']:
        raise ValueError(tr('字体文件校验失败，请重试下载'))


def download_face(family, face, *, cancelled=lambda: False, progress=lambda received, total: None):
    if not family['licenses']:
        raise ValueError(tr('上游目录缺少独立许可证，暂不提供下载'))
    catalog = load_catalog()
    existing = installed_faces().get(face['sha1'])
    if existing:
        return existing
    # Licenses and font bytes are verified before making the font available.
    with tempfile.TemporaryDirectory(prefix='comitrans-font-') as folder:
        folder = Path(folder)
        licenses = []
        for number, asset in enumerate(family['licenses']):
            target = folder / f'license-{number}.txt'
            _download_asset(catalog, asset, target, cancelled, lambda *_: None)
            licenses.append((Path(asset['path']).name, target.read_bytes()))
        target = folder / ('font' + PurePosixPath(face['path']).suffix)
        _download_asset(catalog, face, target, cancelled, progress)
        if cancelled():
            raise InterruptedError(tr('已取消字体下载'))
        info = import_font(target)
        reference = font_reference(info.path)
        license_folder = font_directory() / 'licenses' / info.path.stem
        license_folder.mkdir(parents=True, exist_ok=True)
        for name, content in licenses:
            (license_folder / name).write_bytes(content)
        provenance = dict(repository=catalog['repository'], revision=catalog['revision'],
                          family=family['name'], license=family['license'], path=face['path'],
                          git_sha1=face['sha1'], reference=reference)
        (license_folder / 'source.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
        return reference
