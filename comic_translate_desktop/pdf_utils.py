from __future__ import annotations

import os
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from PIL import Image

from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF
from PySide6.QtGui import QImage, QImageReader, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument


class PdfProcessingError(RuntimeError):
    """Raised when a PDF cannot be rendered or assembled safely."""


@dataclass(frozen=True)
class RenderedPdfPage:
    page_index: int
    image_path: Path
    width_points: float
    height_points: float


def _open_pdf(path: Path) -> QPdfDocument:
    document = QPdfDocument()
    error = document.load(str(path))
    if error == QPdfDocument.Error.None_ and document.pageCount() > 0:
        return document

    messages = {
        QPdfDocument.Error.FileNotFound: "PDF 文件不存在",
        QPdfDocument.Error.InvalidFileFormat: "PDF 格式无效或文件已损坏",
        QPdfDocument.Error.IncorrectPassword: "PDF 已加密，需要密码",
        QPdfDocument.Error.UnsupportedSecurityScheme: "PDF 使用了不支持的加密方式",
    }
    document.close()
    detail = messages.get(error, "无法读取 PDF")
    raise PdfProcessingError(f"{detail}: {path.name}")


def _scaled_pixel_size(width_points: float, height_points: float, dpi: int) -> QSize:
    width = max(1, round(width_points * dpi / 72.0))
    height = max(1, round(height_points * dpi / 72.0))
    # Reject oversized allocations instead of silently reducing the requested resolution.
    longest = max(width, height)
    if longest > 12000:
        raise PdfProcessingError("页面渲染尺寸超过 12000 像素安全上限，已停止；不会自动降低 DPI 或缩小页面。")
    return QSize(width, height)


class PdfPageRenderer:
    """One open document; native-resolution pages are materialized on demand."""

    def __init__(self, pdf_path, dpi=200):
        self.document = _open_pdf(Path(pdf_path))
        self.dpi = dpi

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        if self.document is not None:
            self.document.close()
            self.document = None

    def pages(self, output_dir, cancel_callback=None):
        pages = []
        for page_index in range(self.document.pageCount()):
            if cancel_callback:
                cancel_callback()
            size = self.document.pagePointSize(page_index)
            if any(not math.isfinite(v) or v <= 0 for v in (size.width(), size.height())):
                raise PdfProcessingError(f"PDF 第 {page_index + 1} 页尺寸无效")
            pages.append(RenderedPdfPage(page_index,
                Path(output_dir) / f'page_{page_index + 1:04d}.png',
                float(size.width()), float(size.height())))
        return pages

    def render(self, page, *, reuse_cached=False, cancel_callback=None):
        if cancel_callback:
            cancel_callback()
        target = _scaled_pixel_size(page.width_points, page.height_points, self.dpi)
        if reuse_cached:
            try:
                with Image.open(page.image_path) as cached:
                    valid = cached.format == 'PNG' and cached.size == (target.width(), target.height())
                    cached.verify()
                if valid:
                    return page
            except (OSError, ValueError, SyntaxError):
                pass
        page.image_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='.render-', suffix='.png', dir=page.image_path.parent)
        os.close(descriptor)
        staged = Path(name)
        try:
            image = self.document.render(page.page_index, target)
            if image.isNull():
                raise PdfProcessingError(f"PDF 第 {page.page_index + 1} 页渲染失败")
            if cancel_callback:
                cancel_callback()
            if not image.save(str(staged), 'PNG'):
                raise PdfProcessingError(f"PDF 第 {page.page_index + 1} 页临时图片保存失败")
            if cancel_callback:
                cancel_callback()
            os.replace(staged, page.image_path)
        finally:
            staged.unlink(missing_ok=True)
        return page


def plan_pdf_pages(pdf_path, output_dir, dpi=200, cancel_callback=None):
    """Read page sizes without rendering or decoding any page images."""
    with PdfPageRenderer(pdf_path, dpi) as renderer:
        return renderer.pages(output_dir, cancel_callback)


def render_pdf_pages(pdf_path: str | Path, output_dir: str | Path, dpi: int = 200) -> list[RenderedPdfPage]:
    """Compatibility helper for callers that explicitly need all page images."""
    with PdfPageRenderer(pdf_path, dpi) as renderer:
        pages = renderer.pages(output_dir)
        for page in pages:
            renderer.render(page)
        return pages


def render_pdf_preview(pdf_path: str | Path, max_size: QSize) -> QImage:
    """Render the first PDF page for thumbnails and the in-app preview."""

    document = _open_pdf(Path(pdf_path))
    try:
        point_size = document.pagePointSize(0)
        scale = min(
            max_size.width() / max(1.0, point_size.width()),
            max_size.height() / max(1.0, point_size.height()),
        )
        target = QSize(
            max(1, round(point_size.width() * scale)),
            max(1, round(point_size.height() * scale)),
        )
        return document.render(0, target)
    finally:
        document.close()


def _page_size(width_points: float, height_points: float) -> QPageSize:
    return QPageSize(
        QSizeF(width_points, height_points),
        QPageSize.Unit.Point,
        "ComiTrans source page",
        QPageSize.SizeMatchPolicy.ExactMatch,
    )


def build_pdf_from_images(
    image_paths: Iterable[str | Path],
    page_sizes_points: Iterable[tuple[float, float]],
    output_path: str | Path,
    *, progress_callback=None, cancel_callback=None,
) -> Path:
    """Assemble translated page images into a validated, atomically-written PDF."""

    paths = [Path(path) for path in image_paths]
    sizes = list(page_sizes_points)
    if not paths or len(paths) != len(sizes):
        raise PdfProcessingError("PDF 页面图片与页面尺寸数量不一致")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output_path.stem}.", suffix=".writing.pdf", dir=output_path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        return _write_pdf(paths, sizes, output_path, temporary_path, progress_callback, cancel_callback)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_pdf(paths, sizes, output_path, temporary_path, progress_callback, cancel_callback):

    writer = QPdfWriter(str(temporary_path))
    writer.setResolution(72)
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    writer.setTitle(output_path.stem)
    painter = QPainter()
    try:
        first_width, first_height = sizes[0]
        if not writer.setPageSize(_page_size(first_width, first_height)):
            raise PdfProcessingError("无法设置 PDF 页面尺寸")
        if not painter.begin(writer):
            raise PdfProcessingError("无法创建输出 PDF")
        # Embed every page at its full pixel dimensions without JPEG loss.
        # The writer's 72 DPI sets page coordinates, not image resolution.
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering, True)

        for index, (image_path, (width, height)) in enumerate(zip(paths, sizes)):
            if cancel_callback:
                cancel_callback()
            if index:
                if not writer.setPageSize(_page_size(width, height)) or not writer.newPage():
                    raise PdfProcessingError(f"无法创建 PDF 第 {index + 1} 页")
            reader = QImageReader(str(image_path))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                raise PdfProcessingError(f"无法读取译图: {image_path.name}")
            # QPdfWriter paints in page points. Using the integer pixel paint
            # rectangle leaves a thin unpainted strip when the physical page
            # size contains fractional points, which renders as a black gap.
            target = QRectF(writer.pageLayout().paintRect(QPageLayout.Unit.Point))
            painter.drawImage(target, image)
            if progress_callback:
                progress_callback(index + 1, len(paths))
    finally:
        if painter.isActive():
            painter.end()
        del writer

    # 重新打开并核对页数/页面尺寸，验证通过后才替换最终文件。
    document = _open_pdf(temporary_path)
    try:
        if document.pageCount() != len(paths):
            raise PdfProcessingError(
                f"输出 PDF 页数不正确：期望 {len(paths)}，实际 {document.pageCount()}"
            )
        for index, (expected_width, expected_height) in enumerate(sizes):
            actual = document.pagePointSize(index)
            if (
                abs(actual.width() - expected_width) > 1.5
                or abs(actual.height() - expected_height) > 1.5
            ):
                raise PdfProcessingError(f"输出 PDF 第 {index + 1} 页尺寸不正确")
    finally:
        document.close()
        del document

    # Windows keeps the source handle open until the QPdfDocument wrapper is
    # destroyed, even after close(). Drop the final reference before replace().
    if cancel_callback:
        cancel_callback()
    os.replace(temporary_path, output_path)
    return output_path
