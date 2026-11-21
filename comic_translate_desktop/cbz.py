"""Read comic archives in page order and package translated pages losslessly."""
from pathlib import Path, PurePosixPath
import os
import re
import tempfile
from zipfile import ZipFile, ZIP_STORED

from PIL import Image, ImageOps

from .i18n import tr


IMAGE_EXTS = frozenset(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))
PROJECT_EXTS = frozenset(('.pdf', '.cbz'))


def _sort_member(member):
    name = member.filename.replace('\\', '/')
    parts = re.split(r'([0-9]+)', name.casefold())
    return tuple(int(part) if index % 2 else part for index, part in enumerate(parts)), name


class CbzReader:
    def __init__(self, path):
        self.path = Path(path)
        self.archive = ZipFile(path)
        try:
            self.members = sorted(
                (member for member in self.archive.infolist() if self._is_page(member)),
                key=_sort_member)
            if not self.members:
                raise ValueError(tr('CBZ 中没有可读取的漫画图片'))
        except Exception:
            self.archive.close()
            raise

    @staticmethod
    def _is_page(member):
        path = PurePosixPath(member.filename.replace('\\', '/'))
        return (not member.is_dir() and path.suffix.lower() in IMAGE_EXTS
                and not any(part.startswith('.') or part == '__MACOSX' for part in path.parts))

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        self.archive.close()

    def page_sizes(self, cancel_callback):
        sizes = []
        for member in self.members:
            cancel_callback()
            with self.archive.open(member) as stream, Image.open(stream) as image:
                width, height = image.size
                if image.getexif().get(274) in (5, 6, 7, 8):
                    width, height = height, width
                sizes.append((width * 72 / 200, height * 72 / 200))
        return sizes

    def render(self, index, destination, cancel_callback):
        cancel_callback()
        if destination.is_file():
            try:
                with Image.open(destination) as cached:
                    cached.verify()
                return
            except (OSError, ValueError, SyntaxError):
                pass
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.cbz-page-', dir=destination.parent) as directory:
            staged = Path(directory) / destination.name
            with self.archive.open(self.members[index]) as stream, Image.open(stream) as image:
                ImageOps.exif_transpose(image).convert('RGB').save(staged)
            cancel_callback()
            os.replace(staged, destination)

    def preview(self, size):
        from PIL.ImageQt import ImageQt
        with self.archive.open(self.members[0]) as stream, Image.open(stream) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((size.width(), size.height()))
            return ImageQt(image).copy()


def render_cbz_preview(path, size):
    with CbzReader(path) as archive:
        return archive.preview(size)


def build_cbz_from_images(images, output, *, progress_callback=lambda *_: None, cancel_callback=lambda: None):
    output = Path(output)
    if not images:
        raise ValueError(tr('没有可导出的漫画页'))
    output.parent.mkdir(parents=True, exist_ok=True)
    digits = max(4, len(str(len(images))))
    with tempfile.TemporaryDirectory(prefix='.cbz-export-', dir=output.parent) as directory:
        staged = Path(directory) / output.name
        with ZipFile(staged, 'w', compression=ZIP_STORED) as archive:
            for number, image in enumerate(images, 1):
                cancel_callback()
                archive.write(image, f'page_{number:0{digits}d}{Path(image).suffix.lower()}')
                progress_callback(number, len(images))
        cancel_callback()
        os.replace(staged, output)
    return output
