from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
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
    # 防止异常页面尺寸一次性占用过多内存，同时保持纵横比。
    longest = max(width, height)
    if longest > 12000:
        scale = 12000 / longest
        width = max(1, round(width * scale))
        height = max(1, round(height * scale))
    return QSize(width, height)


def render_pdf_pages(pdf_path: str | Path, output_dir: str | Path, dpi: int = 200) -> list[RenderedPdfPage]:
    """Render every PDF page to a PNG and retain its original point size."""

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    document = _open_pdf(pdf_path)
    pages: list[RenderedPdfPage] = []
    try:
        for page_index in range(document.pageCount()):
            point_size = document.pagePointSize(page_index)
            if point_size.width() <= 0 or point_size.height() <= 0:
                raise PdfProcessingError(f"PDF 第 {page_index + 1} 页尺寸无效")
            image = document.render(
                page_index,
                _scaled_pixel_size(point_size.width(), point_size.height(), dpi),
            )
            if image.isNull():
                raise PdfProcessingError(f"PDF 第 {page_index + 1} 页渲染失败")
            image_path = output_dir / f"page_{page_index + 1:04d}.png"
            if not image.save(str(image_path), "PNG"):
                raise PdfProcessingError(f"PDF 第 {page_index + 1} 页临时图片保存失败")
            pages.append(
                RenderedPdfPage(
                    page_index=page_index,
                    image_path=image_path,
                    width_points=float(point_size.width()),
                    height_points=float(point_size.height()),
                )
            )
    finally:
        document.close()
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
) -> Path:
    """Assemble translated page images into a validated, atomically-written PDF."""

    paths = [Path(path) for path in image_paths]
    sizes = list(page_sizes_points)
    if not paths or len(paths) != len(sizes):
        raise PdfProcessingError("PDF 页面图片与页面尺寸数量不一致")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.stem}.writing.pdf")

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

        for index, (image_path, (width, height)) in enumerate(zip(paths, sizes)):
            if index:
                if not writer.setPageSize(_page_size(width, height)) or not writer.newPage():
                    raise PdfProcessingError(f"无法创建 PDF 第 {index + 1} 页")
            image = QImage(str(image_path))
            if image.isNull():
                raise PdfProcessingError(f"无法读取译图: {image_path.name}")
            target = QRectF(writer.pageLayout().paintRectPixels(writer.resolution()))
            painter.drawImage(target, image)
    finally:
        if painter.isActive():
            painter.end()

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

    # Windows keeps the source handle open until the QPdfDocument wrapper is
    # destroyed, even after close(). Drop the final reference before replace().
    del document
    os.replace(temporary_path, output_path)
    return output_path
