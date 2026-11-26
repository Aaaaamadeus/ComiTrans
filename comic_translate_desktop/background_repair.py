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

    def repair_mask(self, image, mask_array):
        """Return (box, patch_pil) for an arbitrary uint8 selection mask (0..255)."""
        mask_np = np.asarray(mask_array, dtype=np.uint8)
        if mask_np.shape != (image.height, image.width):
            raise ValueError('Repair mask dimensions do not match image')
        ys, xs = np.where(mask_np > 0)
        if xs.size == 0:
            raise ValueError('Invalid repair selection')
        x1, y1, x2, y2 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        if (x1, y1, x2, y2) == (0, 0, image.width, image.height) and np.all(mask_np > 0):
            raise ValueError('Select a smaller area with surrounding background')
        padding = max(64, min(256, max(x2 - x1, y2 - y1)))
        bounds = (
            max(0, x1 - padding),
            max(0, y1 - padding),
            min(image.width, x2 + padding),
            min(image.height, y2 + padding),
        )
        crop = image.crop(bounds).convert('RGB')
        local = (x1 - bounds[0], y1 - bounds[1], x2 - bounds[0], y2 - bounds[1])
        binary_crop = np.where(mask_np[bounds[1]:bounds[3], bounds[0]:bounds[2]] > 0, 255, 0).astype(np.uint8)
        repaired_crop = None
        if crop.width * crop.height <= MAX_RECONSTRUCTION_PIXELS:
            rebuilt = reconstruct_background(np.asarray(crop), binary_crop)
            if rebuilt is not None:
                repaired_crop = Image.fromarray(rebuilt[0])
        if repaired_crop is None:
            if self._inpainter is None:
                from manga_lama import MangaLama
                self._inpainter = MangaLama(self.model_path, device=self.device)
            repaired_crop = self._inpainter(crop, Image.fromarray(binary_crop, mode='L')).convert('RGB')
            if repaired_crop.size != crop.size:
                raise ValueError('Unexpected repair image size')
        repaired_roi = np.asarray(repaired_crop.crop(local), dtype=np.float32)
        orig_roi = np.asarray(image.crop((x1, y1, x2, y2)).convert('RGB'), dtype=np.float32)
        alpha = (mask_np[y1:y2, x1:x2].astype(np.float32) / 255.0)[..., None]
        blended = np.clip(np.rint(orig_roi * (1.0 - alpha) + repaired_roi * alpha), 0, 255).astype(np.uint8)
        return (x1, y1, x2, y2), Image.fromarray(blended)


class RepairWorker(QThread):
    succeeded = Signal(object, object)
    failed = Signal(str)

    def __init__(self, engine, image, box, parent=None, *, mask=None):
        super().__init__(parent)
        self.engine, self.image, self.box = engine, image, box
        self.mask = mask

    def run(self):
        try:
            if self.mask is not None:
                box, patch = self.engine.repair_mask(self.image, self.mask)
                self.succeeded.emit(box, patch)
            else:
                self.succeeded.emit(self.box, self.engine.repair_region(self.image, self.box))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.image = None
            self.mask = None

