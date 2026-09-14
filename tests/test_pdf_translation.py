from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QSize

from comic_translate_desktop.pdf_utils import (
    build_pdf_from_images,
    render_pdf_pages,
    render_pdf_preview,
)
from comic_translate_desktop.worker import BatchWorker


class _CopyPipeline:
    def prepare_comic_page(self, path):
        return {"ocr_texts": [], "img_cv": path}

    def translate_page_batch(self, texts, _image):
        return [""] * len(texts)

    def finish_comic_page(self, output_path, prepared, translations):
        if translations is None:
            raise AssertionError("blank PDF pages must not be treated as API failures")
        shutil.copyfile(prepared["img_cv"], output_path)


def _make_page(path: Path, size: tuple[int, int], color: str, label: str) -> None:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, size[0] - 9, size[1] - 9), outline="black", width=3)
    draw.text((18, 18), label, fill="black")
    image.save(path)


class PdfTranslationTests(unittest.TestCase):
    def test_round_trip_preserves_page_count_sizes_and_preview(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            first = root / "first.png"
            second = root / "second.png"
            _make_page(first, (400, 600), "#fff2cc", "PAGE 1")
            _make_page(second, (700, 400), "#d9ead3", "PAGE 2")
            page_sizes = [(288.0, 432.0), (504.0, 288.0)]
            source_pdf = root / "source.pdf"
            build_pdf_from_images([first, second], page_sizes, source_pdf)

            rendered = render_pdf_pages(source_pdf, root / "rendered", dpi=96)
            self.assertEqual(len(rendered), 2)
            for page, expected in zip(rendered, page_sizes):
                self.assertAlmostEqual(page.width_points, expected[0], delta=1.5)
                self.assertAlmostEqual(page.height_points, expected[1], delta=1.5)
                self.assertTrue(page.image_path.exists())

            preview = render_pdf_preview(source_pdf, QSize(160, 160))
            self.assertFalse(preview.isNull())
            self.assertLessEqual(preview.width(), 160)
            self.assertLessEqual(preview.height(), 160)

    def test_worker_translates_pdf_as_one_output_document(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            first = root / "first.png"
            second = root / "second.png"
            _make_page(first, (300, 500), "white", "ONE")
            _make_page(second, (500, 300), "white", "TWO")
            source_pdf = root / "comic.pdf"
            build_pdf_from_images(
                [first, second],
                [(216.0, 360.0), (360.0, 216.0)],
                source_pdf,
            )

            output_dir = root / "output"
            worker = BatchWorker(
                [source_pdf],
                output_dir,
                {
                    "api_key": "unused-for-blank-pages",
                    "api_base_url": "https://example.invalid/v1",
                    "translation_model": "demo-model",
                    "max_workers": 2,
                    "pdf_dpi": 96,
                },
                pipeline=_CopyPipeline(),
            )
            done = []
            failed = []
            summary = []
            worker.image_done.connect(lambda source, output: done.append((source, output)))
            worker.image_failed.connect(lambda name, message: failed.append((name, message)))
            worker.finished.connect(lambda success, failures: summary.append((success, failures)))

            worker.run()

            output_pdf = output_dir / "comic_translated.pdf"
            self.assertEqual(summary, [(1, 0)])
            self.assertEqual(len(done), 1)
            self.assertEqual(failed, [])
            self.assertTrue(output_pdf.exists())
            rendered = render_pdf_pages(output_pdf, root / "output_rendered", dpi=96)
            self.assertEqual(len(rendered), 2)
            self.assertAlmostEqual(rendered[0].width_points, 216.0, delta=1.5)
            self.assertAlmostEqual(rendered[1].height_points, 216.0, delta=1.5)


if __name__ == "__main__":
    unittest.main()
