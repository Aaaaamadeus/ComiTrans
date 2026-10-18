"""Portable font imports shared by the workbench and the typesetter."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile

from fontTools.ttLib import TTFont
from PIL import ImageFont

from . import config
from .i18n import tr, ui_language


FONT_EXTENSIONS = {'.ttf', '.otf', '.ttc', '.otc'}
FONT_NAME_ALIASES = {
    'LXGW WenKai': '霞鹜文楷', 'LXGW WenKai TC': '霞鹜文楷繁体',
    'LXGW WenKai Mono TC': '霞鹜文楷等宽', 'LXGW Marker Gothic': '霞鹜漫黑',
    'Smiley Sans': '得意黑', 'SetoFont': '濑户字体', '851 Tegaki Zatsu': '851手写杂书体',
    'Source Han Sans SC': '思源黑体简体', 'Source Han Serif CN': '思源宋体中文',
    'Source Han Sans TC': '思源黑体（繁体）', 'Source Han Serif TC': '思源宋体（繁体）',
    'GenSenRounded2 TW': '源泉圆体 TW（繁体）', 'jf-openhuninn-2.1': '粉圆（繁体）',
    'Huninn': '粉圆（繁体）', 'Iansui': '芫荽（繁体）', '內海字體': '内海字体（繁体）',
    'JasonHandwriting3': '清松手写体 3（繁体）', '獅尾加糖宋體': '狮尾加糖宋体（繁体）',
    'Pop Gothic CJK TC': '大波浪圆体（繁体）',
    'Swei B2 Sans CJK SC': '狮尾B2黑体（简体）', 'Swei B2 Sans CJK TC': '狮尾B2黑体（繁体）',
    'Swei Toothpaste CJK SC': '狮尾牙膏圆体（简体）', 'Swei Toothpaste CJK TC': '狮尾牙膏圆体（繁体）',
    '獅尾B2黑體SC': '狮尾B2黑体（简体）', '獅尾B2黑體': '狮尾B2黑体（繁体）',
    '獅尾牙膏圓體SC': '狮尾牙膏圆体（简体）', '獅尾牙膏圓體': '狮尾牙膏圆体（繁体）',
    'Noto Sans SC': '思源黑体简体', 'Noto Serif SC': '思源宋体简体',
    'Noto Sans TC': '思源黑体繁体', 'Noto Serif TC': '思源宋体繁体',
    'Ma Shan Zheng': '马善政楷书', 'Zhi Mang Xing': '志莽行', 'Long Cang': '龙藏体',
    'Liu Jian Mao Cao': '刘建毛草',
}
FONT_STYLE_NAMES = {
    'regular': '常规', 'normal': '常规', 'r': '常规', 'medium': '中粗', 'm': '中粗',
    'bold': '粗体', 'b': '粗体', 'heavy': '特粗', 'h': '特粗', 'black': '特黑',
    'light': '细体', 'l': '细体', 'extralight': '特细', 'el': '特细',
    'semibold': '半粗', 'italic': '斜体', 'oblique': '倾斜',
}


def font_alias(name: str) -> str:
    key = ''.join(char for char in name.casefold() if char.isalnum())
    for family, alias in FONT_NAME_ALIASES.items():
        if key == ''.join(char for char in family.casefold() if char.isalnum()):
            return alias
    return ''


def font_display_name(font: FontInfo) -> str:
    family, _, style = font.name.partition(' · ')
    if ui_language() == 'zh-CN':
        family = font_alias(family) or family
    style = tr(FONT_STYLE_NAMES.get(style.casefold().replace(' ', ''), style))
    return f'{family} · {style}' if style else family


def font_description(font: FontInfo) -> str:
    """Keep original family names searchable while showing short localized labels."""
    return f'{font_display_name(font)}\n{font.name}\n{font.path}'


@dataclass(frozen=True)
class FontInfo:
    path: Path
    name: str


@lru_cache(maxsize=128)
def _inspect(path: str, modified: int, size: int) -> FontInfo:
    with open(path, 'rb') as stream, TTFont(stream, fontNumber=0, lazy=True) as font:
        if not font.getBestCmap():
            raise ValueError(tr('字体没有可用的字符映射'))
        names = font['name']
        family = names.getDebugName(16) or names.getDebugName(1) or Path(path).stem
        style = names.getDebugName(17) or names.getDebugName(2) or ''
    # Check the same FreeType loader used for exported translations.
    ImageFont.truetype(path, 24)
    return FontInfo(Path(path), f'{family} · {style}' if style else family)


def inspect_font(path: Path | str) -> FontInfo:
    path = Path(path).resolve()
    if path.suffix.lower() not in FONT_EXTENSIONS:
        raise ValueError(tr('请选择 TTF、OTF、TTC 或 OTC 字体'))
    stat = path.stat()
    return _inspect(str(path), stat.st_mtime_ns, stat.st_size)


def font_directory() -> Path:
    return config.PROJECT_ROOT / 'user_fonts'


def font_reference(path: Path | str) -> str:
    """Keep bundled/imported font choices valid when the app folder moves."""
    path = Path(path).resolve()
    for root, prefix in ((font_directory(), 'user_fonts/'), (config.AI_ROOT, '')):
        try:
            return prefix + path.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return str(path)


def resolve_font_reference(reference: str) -> Path:
    path = Path(reference).expanduser()
    if path.is_absolute():
        return path
    root = config.PROJECT_ROOT if path.parts and path.parts[0] == 'user_fonts' else config.AI_ROOT
    return root / path


def import_font(source: Path | str) -> FontInfo:
    source = Path(source).resolve()
    inspect_font(source)
    digest = _file_digest(source)
    folder = font_directory()
    folder.mkdir(parents=True, exist_ok=True)
    # Content identity also deduplicates the same font imported under another name.
    for existing in folder.glob(f'{digest}.*'):
        try:
            if _file_digest(existing) == digest:
                return inspect_font(existing)
        except Exception:
            continue  # Replace a damaged local copy from the valid source below.
    target = folder / f'{digest}{source.suffix.lower()}'
    with tempfile.NamedTemporaryFile(dir=folder, prefix='.import-', suffix=source.suffix.lower(), delete=False) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copyfile(source, temporary)
        inspect_font(temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return inspect_font(target)


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def available_fonts(settings: dict | None = None) -> list[FontInfo]:
    paths = [config.AI_ROOT / value for value in config.FONT_DEFAULTS.values()]
    for folder_name in ('TC', 'Manga'):
        bundled = config.AI_ROOT / 'font_file' / folder_name
        if bundled.is_dir():
            paths.extend(path for path in bundled.rglob('*') if path.suffix.lower() in FONT_EXTENSIONS)
    if settings:
        paths.extend(Path(value) for value in settings.get('style_font_map', settings.get('font_map', {})).values())
    folder = font_directory()
    if folder.is_dir():
        paths.extend(path for path in folder.iterdir() if not path.name.startswith('.'))
    fonts = {}
    for path in paths:
        try:
            info = inspect_font(path)
        except Exception:
            continue
        fonts[info.path] = info
    return sorted(fonts.values(), key=lambda item: (item.name.casefold(), str(item.path)))
