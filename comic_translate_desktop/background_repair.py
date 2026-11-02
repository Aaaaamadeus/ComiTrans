from __future__ import annotations

import os

import numpy as np
from PIL import Image
from PySide6.QtCore import QThread, Signal

from comic_translate_core.page_store import save_page_files as save_editor_files
from comic_translate_core.background_reconstruction import MAX_RECONSTRUCTION_PIXELS, reconstruct_background


class BackgroundRepair:
    """Reconstruct the selected background from its surroundings at native size."""

    def __init__(self, model_path, device='cpu'):
        self.model_path = model_path
        self.device = device
        self._inpainter = None

    def repair(self, image, box):
        """Return a full repaired copy for callers that need a complete image."""
        patch = self.repair_region(image, box)
        result = image.copy()
        result.paste(patch, tuple(map(int, box)))
        return result

    def repair_region(self, image, box):
        """Return just the replacement pixels, at the selection's native size."""
        x1, y1, x2, y2 = map(int, box)
        if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
            raise ValueError('Invalid repair selection')
        if (x1, y1, x2, y2) == (0, 0, image.width, image.height):
            raise ValueError('Select a smaller area with surrounding background')
        # Give the model surrounding context without processing an entire large page.
        padding = max(64, min(256, max(x2 - x1, y2 - y1)))
        bounds = (max(0, x1 - padding), max(0, y1 - padding),
                  min(image.width, x2 + padding), min(image.height, y2 + padding))
        crop = image.crop(bounds).convert('RGB')
        mask = Image.new('L', crop.size)
        local = (x1 - bounds[0], y1 - bounds[1], x2 - bounds[0], y2 - bounds[1])
        mask.paste(255, local)
        if crop.width * crop.height <= MAX_RECONSTRUCTION_PIXELS:
            rebuilt = reconstruct_background(np.asarray(crop), np.asarray(mask))
            if rebuilt is not None:
                return Image.fromarray(rebuilt[0]).crop(local)
        if self._inpainter is None:
            from manga_lama import MangaLama
            self._inpainter = MangaLama(self.model_path, device=self.device)
        # MangaLama owns the shared tiling/memory policy. Keep source pixels at
        # their native resolution in both automatic translation and the editor.
        repaired = self._inpainter(crop, mask).convert('RGB')
        if repaired.size != crop.size:
            raise ValueError('Unexpected repair image size')
        return repaired.crop(local)


class RepairWorker(QThread):
    succeeded = Signal(object, object)
    failed = Signal(str)

    def __init__(self, engine, image, box, parent=None):
        super().__init__(parent)
        self.engine, self.image, self.box = engine, image, box

    def run(self):
        try:
            self.succeeded.emit(self.box, self.engine.repair_region(self.image, self.box))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.image = None

