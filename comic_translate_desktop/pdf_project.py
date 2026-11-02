"""Persistent PDF pages shared by the batch translator and the image editor."""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .pdf_utils import PdfProcessingError, build_pdf_from_images


@dataclass(frozen=True)
class PdfProject:
    directory: Path
    images: list[Path]
    page_sizes: list[tuple[float, float]]


def project_link_path(pdf_path: str | Path) -> Path:
    return Path(pdf_path).with_suffix('.comitrans.json')


def create_pdf_project(pdf_path: Path) -> Path:
    # Separate generations keep earlier edits and partially completed jobs intact.
    return Path(tempfile.mkdtemp(prefix=f'{pdf_path.stem}_edit_', dir=pdf_path.parent)).resolve()


def write_project_metadata(directory: Path, source_name: str, page_sizes) -> None:
    (directory / 'project.json').write_text(json.dumps({
        'version': 1,
        'source_file': source_name,
        'page_sizes_points': list(page_sizes),
    }, ensure_ascii=False, indent=2), encoding='utf-8')


def read_project(directory: Path) -> PdfProject:
    """Only complete, editable generations can be published as a PDF."""
    try:
        data = json.loads((directory / 'project.json').read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('不支持的 PDF 精修数据版本')
        raw_sizes = data.get('page_sizes_points')
        if not isinstance(raw_sizes, list) or not raw_sizes:
            raise ValueError('PDF 精修数据没有页面')
        sizes = []
        images = []
        for number, pair in enumerate(raw_sizes, 1):
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           or value <= 0 for value in pair)):
                raise ValueError(f'PDF 第 {number} 页尺寸无效')
            stem = f'page_{number:04d}'
            image = directory / 'translated' / f'{stem}.png'
            required = (image, directory / 'translated_cleaned' / f'{stem}_cleaned.png',
                        directory / 'translated_layout' / f'{stem}_layout.json')
            for path in required:
                if not path.is_file():
                    raise ValueError(f'PDF 第 {number} 页缺少精修文件：{path.name}')
            sizes.append(tuple(pair))
            images.append(image)
        return PdfProject(directory, images, sizes)
    except (OSError, ValueError, TypeError) as exc:
        raise PdfProcessingError(f'无法读取 PDF 精修数据：{exc}') from exc


def load_pdf_project(pdf_path: str | Path) -> PdfProject:
    pdf_path = Path(pdf_path).resolve()
    link = project_link_path(pdf_path)
    try:
        data = json.loads(link.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('不支持的 PDF 精修索引版本')
        relative = Path(data['project_dir'])
        directory = (pdf_path.parent / relative).resolve()
        if relative.is_absolute() or directory == pdf_path.parent or not directory.is_relative_to(pdf_path.parent):
            raise ValueError('PDF 精修目录必须位于 PDF 所在文件夹内')
        return read_project(directory)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise PdfProcessingError(f'无法打开 PDF 精修资料（请保留同名 .comitrans.json 和配套目录）：{exc}') from exc


def publish_pdf_project(pdf_path: Path, directory: Path) -> None:
    """Commit the PDF and its index together, rolling back on a write failure."""
    pdf_path = pdf_path.resolve()
    project = read_project(directory)
    with tempfile.TemporaryDirectory(prefix='.pdf-publish-', dir=pdf_path.parent) as temporary:
        staging = Path(temporary)
        staged_pdf = staging / pdf_path.name
        build_pdf_from_images(project.images, project.page_sizes, staged_pdf)
        staged_link = staging / 'index.json'
        staged_link.write_text(json.dumps({
            'version': 1, 'project_dir': directory.relative_to(pdf_path.parent).as_posix(),
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        targets = [pdf_path, project_link_path(pdf_path)]
        backups = []
        for index, target in enumerate(targets):
            backup = staging / f'backup-{index}'
            if target.exists():
                shutil.copy2(target, backup)
                backups.append(backup)
            else:
                backups.append(None)
        committed = []
        try:
            for index, (source, target) in enumerate(zip((staged_pdf, staged_link), targets)):
                os.replace(source, target)
                committed.append(index)
        except Exception:
            for index in reversed(committed):
                if backups[index] is None:
                    targets[index].unlink()
                else:
                    shutil.copy2(backups[index], targets[index])
            raise
