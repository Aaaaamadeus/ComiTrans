from __future__ import annotations

import shutil
import json
import re
import tempfile
import unittest
import zlib
from unittest.mock import patch
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QSize

from comic_translate_desktop.pdf_utils import (
    build_pdf_from_images,
    render_pdf_pages,
    render_pdf_preview,
    _scaled_pixel_size,
    PdfProcessingError,
)
from comic_translate_desktop.worker import BatchWorker
from comic_translate_desktop.pdf_project import load_pdf_project, project_link_path


class _CopyPipeline:
    def prepare_comic_page(self, path):
        return {"ocr_texts": [], "img_cv": path}

    def translate_page_batch(self, texts, _image):
        return [""] * len(texts)

    def finish_comic_page(self, output_path, prepared, translations):
        if translations is None:
            raise AssertionError("blank PDF pages must not be treated as API failures")
        shutil.copyfile(prepared["img_cv"], output_path)
        output = Path(output_path)
        cleaned = output.parent.parent / f'{output.parent.name}_cleaned' / f'{output.stem}_cleaned.png'
        layout = output.parent.parent / f'{output.parent.name}_layout' / f'{output.stem}_layout.json'
        cleaned.parent.mkdir(exist_ok=True)
        layout.parent.mkdir(exist_ok=True)
        shutil.copyfile(prepared['img_cv'], cleaned)
        layout.write_text(json.dumps([]), encoding='utf-8')


def _make_page(path: Path, size: tuple[int, int], color: str, label: str) -> None:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, size[0] - 9, size[1] - 9), outline="black", width=3)
    draw.text((18, 18), label, fill="black")
    image.save(path)


class PdfTranslationTests(unittest.TestCase):
    def test_large_page_is_not_silently_downsampled(self):
        self.assertEqual(_scaled_pixel_size(720, 1440, 300), QSize(3000, 6000))
        with self.assertRaises(PdfProcessingError):
            _scaled_pixel_size(7200, 14400, 300)

    def test_cancelled_export_preserves_existing_pdf_and_removes_staging(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = root / 'page.png'
            Image.new('RGB', (100, 100), '#123456').save(source)
            output = build_pdf_from_images([source], [(72, 72)], root / 'out.pdf')
            before = output.read_bytes()
            progress = []
            def cancel():
                if progress:
                    raise InterruptedError('cancel requested')
            with self.assertRaises(InterruptedError):
                build_pdf_from_images([source] * 2, [(72, 72)] * 2, output,
                    progress_callback=lambda *value: progress.append(value), cancel_callback=cancel)
            self.assertEqual(progress, [(1, 2)])
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(list(root.glob('*.writing.pdf')), [])

    def test_export_embeds_full_resolution_pixels_losslessly(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            page = Image.new("RGB", (320, 256))
            # Fine colour detail exposes JPEG loss and any downsampling.
            page.putdata([
                ((x * 71 + y * 31) % 256,
                 (x * 17 + y * 113) % 256,
                 (x * 157 + y * 43) % 256)
                for y in range(page.height) for x in range(page.width)
            ])
            source = root / "page.png"
            page.save(source)
            output = build_pdf_from_images([source], [(80, 64)], root / "out.pdf")
            pdf = output.read_bytes()
            embedded = re.search(rb"/Subtype\s*/Image\b(.*?)\bstream\r?\n", pdf, re.S)
            self.assertIsNotNone(embedded)
            dictionary = embedded.group(1)
            self.assertRegex(dictionary, rb"/Width\s+320\b")
            self.assertRegex(dictionary, rb"/Height\s+256\b")
            self.assertIn(b"/FlateDecode", dictionary)
            self.assertNotIn(b"/DCTDecode", dictionary)
            # zlib stops at the end of this stream, ignoring subsequent PDF objects.
            self.assertEqual(zlib.decompress(pdf[embedded.end():]), page.tobytes())

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
                    "resume_enabled": False,
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
            project = load_pdf_project(output_pdf)
            self.assertEqual(len(project.images), 2)
            self.assertTrue((project.directory / 'source' / 'page_0001.png').is_file())
            self.assertEqual(project.page_sizes, [(216.0, 360.0), (360.0, 216.0)])
            # A second translation keeps the first generation's editable files.
            worker.run()
            self.assertEqual(summary, [(1, 0), (1, 0)])
            self.assertNotEqual(load_pdf_project(output_pdf).directory, project.directory)
            self.assertTrue(project.images[0].is_file())
            rendered = render_pdf_pages(output_pdf, root / "output_rendered", dpi=96)
            self.assertEqual(len(rendered), 2)
            self.assertAlmostEqual(rendered[0].width_points, 216.0, delta=1.5)
            self.assertAlmostEqual(rendered[1].height_points, 216.0, delta=1.5)

            # Failed and cancelled retranslations retain completed page data and
            # never replace a previously published PDF/index.
            previous_pdf = output_pdf.read_bytes()
            previous_link = project_link_path(output_pdf).read_bytes()
            finish = worker._pipeline.finish_comic_page
            for cancel in (False, True):
                existing = set(output_dir.glob('*_edit_*'))
                def interrupted(output_path, prepared, translations):
                    if Path(output_path).stem == 'page_0002':
                        raise RuntimeError('second page failed')
                    finish(output_path, prepared, translations)
                    if cancel:
                        worker.stop()
                with patch.object(worker._pipeline, 'finish_comic_page', side_effect=interrupted):
                    worker.run()
                new_directories = set(output_dir.glob('*_edit_*')) - existing
                self.assertEqual(len(new_directories), 1)
                saved = new_directories.pop()
                self.assertTrue((saved / 'translated/page_0001.png').is_file())
                self.assertTrue((saved / 'translated_layout/page_0001_layout.json').is_file())
                self.assertEqual(output_pdf.read_bytes(), previous_pdf)
                self.assertEqual(project_link_path(output_pdf).read_bytes(), previous_link)


if __name__ == "__main__":
    unittest.main()
