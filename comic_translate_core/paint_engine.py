"""Headless painting, selection, fill, and filter engine for manga retouching.

Operates strictly on NumPy RGB arrays (H x W x 3, uint8) and Pillow images
with zero Qt dependencies so it can be tested headlessly and embedded in
ComiTrans's desktop editor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import math
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image


Box = tuple[int, int, int, int]  # (left, top, right, bottom) with exclusive ends


class BrushTool:
    PENCIL = "pencil"
    PEN = "pen"
    AIRBRUSH = "airbrush"
    WATERCOLOR = "watercolor"
    BRUSH = "brush"
    MARKER = "marker"
    BINARY = "binary"
    BLUR = "blur"
    SMUDGE = "smudge"
    ERASER = "eraser"
    CLONE = "clone"
    EYEDROPPER = "eyedropper"
    BUCKET = "bucket"
    GRADIENT = "gradient"
    RECT_SELECT = "rect_select"
    LASSO_SELECT = "lasso_select"
    POLY_LASSO = "poly_lasso"
    MAGIC_WAND = "magic_wand"
    SELECT_PEN = "select_pen"
    DESELECT_PEN = "deselect_pen"
    MOVE_SELECTION = "move_selection"
    LINE = "line"
    CURVE = "curve"
    RECT_SHAPE = "rect_shape"
    ELLIPSE_SHAPE = "ellipse_shape"

    STROKE_TOOLS = frozenset({
        PENCIL, PEN, AIRBRUSH, WATERCOLOR, BRUSH, MARKER,
        BINARY, BLUR, SMUDGE, ERASER, CLONE,
    })
    SELECTION_STROKE_TOOLS = frozenset({SELECT_PEN, DESELECT_PEN})
    SHAPE_TOOLS = frozenset({LINE, CURVE, RECT_SHAPE, ELLIPSE_SHAPE})
    SELECT_TOOLS = frozenset({
        RECT_SELECT, LASSO_SELECT, POLY_LASSO, MAGIC_WAND,
        SELECT_PEN, DESELECT_PEN, MOVE_SELECTION,
    })
    ALL = (
        PENCIL, PEN, AIRBRUSH, WATERCOLOR, BRUSH, MARKER,
        BINARY, BLUR, SMUDGE, ERASER, CLONE, EYEDROPPER,
        RECT_SELECT, LASSO_SELECT, POLY_LASSO, MAGIC_WAND,
        SELECT_PEN, DESELECT_PEN, MOVE_SELECTION, BUCKET, GRADIENT,
        LINE, CURVE, RECT_SHAPE, ELLIPSE_SHAPE,
    )


@dataclass
class BrushSettings:
    tool: str = BrushTool.PEN
    color: tuple[int, int, int] = (0, 0, 0)
    bg_color: tuple[int, int, int] = (255, 255, 255)
    size: int = 12
    min_size_ratio: float = 0.25
    opacity: float = 1.0
    hardness: float = 0.85
    stabilizer: int = 4  # 0..15 standard, 16..22 -> S-1..S-7
    blending: float = 0.5
    dilution: float = 0.35
    persistence: float = 0.65
    spacing: float = 0.15
    pressure_size: bool = True
    pressure_opacity: bool = False
    antialias: bool = True
    shape_name: str = "round"
    texture_name: str = "none"
    texture_strength: float = 0.35
    eraser_mode: Literal["color", "original"] = "color"
    symmetry: Literal["none", "horizontal", "vertical"] = "none"
    tolerance: int = 24
    contiguous: bool = True
    gap_close: int = 0
    fill_expand: int = 1
    gradient_mode: Literal["fg_bg", "fg_transparent"] = "fg_bg"
    gradient_shape: Literal["linear", "radial"] = "linear"
    shape_filled: bool = False
    select_mode: Literal["replace", "add", "subtract", "intersect"] = "replace"


# User-imported custom shapes & textures (runtime only, never bundled).
_CUSTOM_SHAPES: dict[str, np.ndarray] = {}
_CUSTOM_TEXTURES: dict[str, np.ndarray] = {}

BUILTIN_SHAPES = ("round", "flat", "bristle", "scatter")
BUILTIN_TEXTURES = ("none", "paper_fine", "paper_rough", "tone_dot", "tone_line")


def available_brush_shapes() -> tuple[str, ...]:
    return BUILTIN_SHAPES + tuple(sorted(_CUSTOM_SHAPES))


def available_paper_textures() -> tuple[str, ...]:
    return BUILTIN_TEXTURES + tuple(sorted(_CUSTOM_TEXTURES))


def clear_custom_textures() -> None:
    _CUSTOM_SHAPES.clear()
    _CUSTOM_TEXTURES.clear()


def load_custom_textures(directory: str | Path) -> dict[str, list[str]]:
    """Load grayscale .bmp/.png brush shapes and paper textures from a user directory."""
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"Directory not found: {root}")
    loaded_shapes: list[str] = []
    loaded_textures: list[str] = []
    shape_dirs = {"brshape", "bristle", "scatter", "blotmap"}
    tex_dirs = {"brushtex", "papertex"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".bmp", ".png"):
            continue
        try:
            with Image.open(path) as img:
                gray = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
        except Exception:
            continue
        if gray.size == 0:
            continue
        # Normalize so white/bright values represent ink/grain cleanly.
        if gray.mean() > 0.75:
            # Grayscale brush tip bitmaps often store dark strokes on white paper.
            shape_arr = np.clip(1.0 - gray, 0.0, 1.0)
        else:
            shape_arr = gray
        key = f"custom:{path.stem}"
        parent_name = path.parent.name.lower()
        if parent_name in shape_dirs:
            _CUSTOM_SHAPES[key] = shape_arr
            loaded_shapes.append(key)
        elif parent_name in tex_dirs:
            _CUSTOM_TEXTURES[key] = np.clip(gray, 0.0, 1.0)
            loaded_textures.append(key)
        else:
            _CUSTOM_TEXTURES[key] = np.clip(gray, 0.0, 1.0)
            loaded_textures.append(key)
    return {"shapes": loaded_shapes, "textures": loaded_textures}


@lru_cache(maxsize=16)
def _builtin_shape_template(name: str, resolution: int = 128) -> np.ndarray:
    """Procedural base masks in [0, 1] for non-round brush tip shapes."""
    yy, xx = np.mgrid[:resolution, :resolution]
    cx = (resolution - 1) / 2.0
    cy = (resolution - 1) / 2.0
    nx = (xx - cx) / (resolution / 2.0)
    ny = (yy - cy) / (resolution / 2.0)
    if name == "flat":
        angle = math.radians(-28.0)
        rx = nx * math.cos(angle) - ny * math.sin(angle)
        ry = nx * math.sin(angle) + ny * math.cos(angle)
        dist = np.sqrt((rx / 0.92) ** 2 + (ry / 0.36) ** 2)
        return np.clip(1.0 - np.clip((dist - 0.72) / 0.28, 0.0, 1.0), 0.0, 1.0).astype(np.float32)
    if name == "bristle":
        rng = np.random.default_rng(2021)
        canvas = np.zeros((resolution, resolution), dtype=np.float32)
        for _ in range(36):
            angle = rng.uniform(0, 2 * math.pi)
            rad = rng.uniform(0.0, 0.72)
            bx = cx + math.cos(angle) * rad * (resolution / 2.0)
            by = cy + math.sin(angle) * rad * (resolution / 2.0)
            br = rng.uniform(0.08, 0.20) * (resolution / 2.0)
            d = np.sqrt((xx - bx) ** 2 + (yy - by) ** 2) / max(1.0, br)
            canvas = np.maximum(canvas, np.clip(1.0 - d, 0.0, 1.0))
        radial = np.sqrt(nx ** 2 + ny ** 2)
        canvas *= np.clip(1.0 - np.clip((radial - 0.78) / 0.22, 0.0, 1.0), 0.0, 1.0)
        return canvas.astype(np.float32)
    if name == "scatter":
        rng = np.random.default_rng(703)
        canvas = np.zeros((resolution, resolution), dtype=np.float32)
        for _ in range(48):
            angle = rng.uniform(0, 2 * math.pi)
            rad = math.sqrt(rng.uniform(0.0, 1.0)) * 0.85
            bx = cx + math.cos(angle) * rad * (resolution / 2.0)
            by = cy + math.sin(angle) * rad * (resolution / 2.0)
            br = rng.uniform(0.04, 0.11) * (resolution / 2.0)
            d = np.sqrt((xx - bx) ** 2 + (yy - by) ** 2) / max(1.0, br)
            canvas = np.maximum(canvas, np.clip(1.0 - np.maximum(0.0, d - 0.4) / 0.6, 0.0, 1.0))
        return canvas.astype(np.float32)
    # Default round fallback
    r = np.sqrt(nx ** 2 + ny ** 2)
    return np.clip(1.0 - r, 0.0, 1.0).astype(np.float32)


@lru_cache(maxsize=16)
def _builtin_paper_texture(name: str, size: int = 256) -> np.ndarray | None:
    if name == "none":
        return None
    if name in _CUSTOM_TEXTURES:
        return _CUSTOM_TEXTURES[name]
    yy, xx = np.mgrid[:size, :size].astype(np.float32)
    if name == "paper_fine":
        rng = np.random.default_rng(101)
        noise = rng.uniform(0.65, 1.0, (size, size)).astype(np.float32)
        noise = cv2.GaussianBlur(noise, (3, 3), 0.7)
        grain = 0.85 + 0.15 * np.sin(2 * math.pi * xx / 16.0) * np.cos(2 * math.pi * yy / 16.0)
        return np.clip(noise * grain, 0.0, 1.0).astype(np.float32)
    if name == "paper_rough":
        rng = np.random.default_rng(303)
        coarse = rng.uniform(0.25, 1.0, (size // 4, size // 4)).astype(np.float32)
        coarse = cv2.resize(coarse, (size, size), interpolation=cv2.INTER_CUBIC)
        weave = 0.75 + 0.25 * (
            0.5 * np.sin(2 * math.pi * xx / 12.0) + 0.5 * np.sin(2 * math.pi * yy / 12.0)
        )
        return np.clip(coarse * weave, 0.0, 1.0).astype(np.float32)
    if name == "tone_dot":
        period = 12.0
        gx = (xx % period) - period * 0.5
        gy = (yy % period) - period * 0.5
        dist = np.sqrt(gx ** 2 + gy ** 2)
        return np.where(dist <= 3.1, 1.0, 0.15).astype(np.float32)
    if name == "tone_line":
        diag = ((xx + yy) % 8.0) / 8.0
        return np.where(diag < 0.45, 1.0, 0.2).astype(np.float32)
    return None


def _get_paper_texture(name: str) -> np.ndarray | None:
    if not name or name == "none":
        return None
    if name in _CUSTOM_TEXTURES:
        return _CUSTOM_TEXTURES[name]
    return _builtin_paper_texture(name)


@lru_cache(maxsize=256)
def build_brush_stamp(
    diameter_key: int,
    hardness_q: int,
    shape_name: str,
    antialias: bool,
    binary: bool,
) -> np.ndarray:
    """Create a normalized 2D float32 brush stamp mask in [0, 1].

    `diameter_key` is round(diameter * 2) (half-pixel quantized) and `hardness_q`
    is round(hardness * 100) for fast cache hits across stroke dabs.
    """
    diameter = max(1.0, diameter_key / 2.0)
    hardness = max(0.0, min(1.0, hardness_q / 100.0))
    px = max(1, int(math.ceil(diameter)))
    if px <= 2:
        if binary or not antialias:
            return np.ones((px, px), dtype=np.float32)
        if diameter <= 1.0:
            return np.full((1, 1), max(0.25, diameter), dtype=np.float32)
    # Odd side length keeps stamp symmetric around the dab center.
    side = px if px % 2 == 1 else px + 1
    if diameter <= 1.5:
        side = 1 if binary else 3
    center = (side - 1) / 2.0
    radius = max(0.5, diameter / 2.0)
    yy, xx = np.mgrid[:side, :side].astype(np.float32)
    dist = np.sqrt((xx - center) ** 2 + (yy - center) ** 2)

    if shape_name in _CUSTOM_SHAPES:
        base = cv2.resize(_CUSTOM_SHAPES[shape_name], (side, side), interpolation=cv2.INTER_AREA)
    elif shape_name != "round" and shape_name in BUILTIN_SHAPES:
        base = cv2.resize(_builtin_shape_template(shape_name), (side, side), interpolation=cv2.INTER_AREA)
    else:
        base = None

    if binary or not antialias:
        if base is not None:
            return (base >= 0.5).astype(np.float32)
        return (dist <= radius).astype(np.float32)

    if base is not None:
        # Apply hardness contrast on shaped tip
        if hardness < 0.99:
            gamma = 1.8 - hardness * 1.4
            mask = np.power(np.clip(base, 0.0, 1.0), gamma)
        else:
            mask = base.astype(np.float32)
        return np.clip(mask, 0.0, 1.0).astype(np.float32)

    # Round stamp with anti-aliased edge + hardness falloff
    inner = radius * min(0.98, hardness)
    edge_outer = radius + 0.5
    if hardness >= 0.98:
        mask = np.clip((edge_outer - dist), 0.0, 1.0)
    else:
        span = max(0.75, edge_outer - inner)
        t = np.clip((dist - inner) / span, 0.0, 1.0)
        # Smooth cosine radial falloff produces soft airbrush and pencil edges.
        mask = 0.5 * (1.0 + np.cos(math.pi * t))
        mask = np.where(dist <= inner, 1.0, mask)
        mask = np.where(dist >= edge_outer, 0.0, mask)
    return mask.astype(np.float32)


class StrokeStabilizer:
    """Stroke stabilizer supporting levels 0..15 and heavy lag levels S-1..S-7 (16..22)."""

    def __init__(self, level: int = 4, spacing_px: float = 2.0):
        self.level = max(0, min(22, int(level)))
        self.spacing_px = max(1.0, float(spacing_px))
        self._raw: list[tuple[float, float, float]] = []
        self._smooth_x = 0.0
        self._smooth_y = 0.0
        self._smooth_p = 1.0
        self._last_emitted: tuple[float, float, float] | None = None
        self._initialized = False

    def begin(self, x: float, y: float, pressure: float) -> list[tuple[float, float, float]]:
        p = max(0.0, min(1.0, float(pressure)))
        self._raw = [(float(x), float(y), p)]
        self._smooth_x = float(x)
        self._smooth_y = float(y)
        self._smooth_p = p
        self._last_emitted = (float(x), float(y), p)
        self._initialized = True
        return [self._last_emitted]

    def push(self, x: float, y: float, pressure: float) -> list[tuple[float, float, float]]:
        if not self._initialized:
            return self.begin(x, y, pressure)
        p = max(0.0, min(1.0, float(pressure)))
        rx, ry = float(x), float(y)
        self._raw.append((rx, ry, p))
        sx, sy, sp = self._compute_smoothed(rx, ry, p)
        return self._resample_to(sx, sy, sp)

    def finish(self) -> list[tuple[float, float, float]]:
        if not self._initialized or not self._raw:
            return []
        rx, ry, rp = self._raw[-1]
        if self.level <= 0 or self._last_emitted is None:
            return []
        # Catch up to the final raw pen position so strokes terminate where released.
        lx, ly, lp = self._last_emitted
        dist = math.hypot(rx - lx, ry - ly)
        if dist < 0.5:
            return []
        return self._resample_to(rx, ry, rp)

    def _compute_smoothed(self, rx: float, ry: float, rp: float) -> tuple[float, float, float]:
        if self.level == 0:
            self._smooth_x, self._smooth_y, self._smooth_p = rx, ry, rp
            return rx, ry, rp
        if self.level <= 15:
            win = min(len(self._raw), 2 + self.level)
            recent = self._raw[-win:]
            weights = [i + 1 for i in range(win)]
            total = sum(weights)
            sx = sum(pt[0] * w for pt, w in zip(recent, weights)) / total
            sy = sum(pt[1] * w for pt, w in zip(recent, weights)) / total
            sp = sum(pt[2] * w for pt, w in zip(recent, weights)) / total
            self._smooth_x, self._smooth_y, self._smooth_p = sx, sy, sp
            return sx, sy, sp
        # S-1..S-7 (16..22): heavy exponential lag string + moving window blend
        s_rank = self.level - 15  # 1..7
        alpha = max(0.06, 0.28 - 0.03 * s_rank)
        self._smooth_x = self._smooth_x * (1.0 - alpha) + rx * alpha
        self._smooth_y = self._smooth_y * (1.0 - alpha) + ry * alpha
        self._smooth_p = self._smooth_p * (1.0 - alpha * 1.4) + rp * (alpha * 1.4)
        return self._smooth_x, self._smooth_y, self._smooth_p

    def _resample_to(self, tx: float, ty: float, tp: float) -> list[tuple[float, float, float]]:
        assert self._last_emitted is not None
        lx, ly, lp = self._last_emitted
        dx = tx - lx
        dy = ty - ly
        dist = math.hypot(dx, dy)
        if dist < self.spacing_px * 0.35:
            return []
        steps = max(1, int(math.floor(dist / self.spacing_px)))
        points: list[tuple[float, float, float]] = []
        for idx in range(1, steps + 1):
            t = idx / steps
            px = lx + dx * t
            py = ly + dy * t
            pp = lp + (tp - lp) * t
            points.append((px, py, pp))
        self._last_emitted = points[-1]
        return points


def _clamp_box(box: Box, width: int, height: int) -> Box | None:
    x1, y1, x2, y2 = box
    x1 = max(0, min(width, int(x1)))
    y1 = max(0, min(height, int(y1)))
    x2 = max(0, min(width, int(x2)))
    y2 = max(0, min(height, int(y2)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _union_box(a: Box | None, b: Box | None) -> Box | None:
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _effective_mask_crop(
    box: Box,
    selection_mask: np.ndarray | None,
    protected_mask: np.ndarray | None,
) -> np.ndarray | None:
    x1, y1, x2, y2 = box
    result: np.ndarray | None = None
    if selection_mask is not None:
        result = selection_mask[y1:y2, x1:x2].astype(np.float32) / 255.0
    if protected_mask is not None:
        allow = (protected_mask[y1:y2, x1:x2] == 0).astype(np.float32)
        result = allow if result is None else result * allow
    return result


class _TileSnapshot:
    """Lazy 128x128 RGB tile store for low-memory undo snapshots & marker base."""

    TILE = 128

    def __init__(self, canvas: np.ndarray):
        self._canvas = canvas
        self._tiles: dict[tuple[int, int], np.ndarray] = {}

    def capture_roi(self, box: Box) -> None:
        h, w = self._canvas.shape[:2]
        x1, y1, x2, y2 = box
        tx1, ty1 = x1 // self.TILE, y1 // self.TILE
        tx2, ty2 = (x2 - 1) // self.TILE, (y2 - 1) // self.TILE
        for ty in range(ty1, ty2 + 1):
            for tx in range(tx1, tx2 + 1):
                key = (tx, ty)
                if key not in self._tiles:
                    rx1, ry1 = tx * self.TILE, ty * self.TILE
                    rx2, ry2 = min(w, rx1 + self.TILE), min(h, ry1 + self.TILE)
                    self._tiles[key] = self._canvas[ry1:ry2, rx1:rx2].copy()

    def read_before_roi(self, box: Box) -> np.ndarray:
        x1, y1, x2, y2 = box
        out = np.empty((y2 - y1, x2 - x1, 3), dtype=np.uint8)
        tx1, ty1 = x1 // self.TILE, y1 // self.TILE
        tx2, ty2 = (x2 - 1) // self.TILE, (y2 - 1) // self.TILE
        for ty in range(ty1, ty2 + 1):
            for tx in range(tx1, tx2 + 1):
                tile = self._tiles.get((tx, ty))
                rx1, ry1 = tx * self.TILE, ty * self.TILE
                ix1, iy1 = max(x1, rx1), max(y1, ry1)
                if tile is not None:
                    ix2 = min(x2, rx1 + tile.shape[1])
                    iy2 = min(y2, ry1 + tile.shape[0])
                    out[iy1 - y1:iy2 - y1, ix1 - x1:ix2 - x1] = tile[iy1 - ry1:iy2 - ry1, ix1 - rx1:ix2 - rx1]
                else:
                    ix2 = min(x2, rx1 + self.TILE)
                    iy2 = min(y2, ry1 + self.TILE)
                    out[iy1 - y1:iy2 - y1, ix1 - x1:ix2 - x1] = self._canvas[iy1:iy2, ix1:ix2]
        return out


@dataclass
class _BranchState:
    stabilizer: StrokeStabilizer
    carry_color: np.ndarray | None = None
    smudge_patch: np.ndarray | None = None
    marker_tiles: dict[tuple[int, int], np.ndarray] = field(default_factory=dict)


class StrokeSession:
    """Incremental single-stroke session on a mutable H x W x 3 uint8 canvas."""

    def __init__(
        self,
        canvas: np.ndarray,
        settings: BrushSettings,
        *,
        selection_mask: np.ndarray | None = None,
        original_canvas: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
        clone_source: tuple[float, float] | None = None,
    ):
        self.canvas = canvas
        self.settings = settings
        self.selection_mask = selection_mask
        self.original_canvas = original_canvas
        self.protected_mask = protected_mask
        self.clone_source = clone_source
        self._clone_offset: tuple[float, float] | None = None
        self._snapshot = _TileSnapshot(canvas)
        self._full_bbox: Box | None = None
        self._branches: list[_BranchState] = []
        self._active = False

    def begin(self, x: float, y: float, pressure: float = 1.0) -> Box | None:
        h, w = self.canvas.shape[:2]
        self._active = True
        if self.settings.tool == BrushTool.CLONE and self.clone_source is not None:
            self._clone_offset = (self.clone_source[0] - x, self.clone_source[1] - y)
        spacing_px = max(1.0, self.settings.size * self.settings.spacing)
        coords = [(float(x), float(y))]
        if self.settings.symmetry == "horizontal":
            coords.append(((w - 1) - float(x), float(y)))
        elif self.settings.symmetry == "vertical":
            coords.append((float(x), (h - 1) - float(y)))
        self._branches = []
        dirty: Box | None = None
        for bx, by in coords:
            stab = StrokeStabilizer(self.settings.stabilizer, spacing_px=spacing_px)
            branch = _BranchState(stabilizer=stab)
            self._branches.append(branch)
            pts = stab.begin(bx, by, pressure)
            for px, py, pp in pts:
                dirty = _union_box(dirty, self._stamp_dab(branch, px, py, pp))
        self._full_bbox = _union_box(self._full_bbox, dirty)
        return dirty

    def add_point(self, x: float, y: float, pressure: float = 1.0) -> Box | None:
        if not self._active:
            return self.begin(x, y, pressure)
        h, w = self.canvas.shape[:2]
        coords = [(float(x), float(y))]
        if self.settings.symmetry == "horizontal":
            coords.append(((w - 1) - float(x), float(y)))
        elif self.settings.symmetry == "vertical":
            coords.append((float(x), (h - 1) - float(y)))
        dirty: Box | None = None
        for branch, (bx, by) in zip(self._branches, coords):
            for px, py, pp in branch.stabilizer.push(bx, by, pressure):
                dirty = _union_box(dirty, self._stamp_dab(branch, px, py, pp))
        self._full_bbox = _union_box(self._full_bbox, dirty)
        return dirty

    def end(self) -> tuple[Box, Image.Image, Image.Image] | None:
        if not self._active:
            return None
        for branch in self._branches:
            for px, py, pp in branch.stabilizer.finish():
                self._full_bbox = _union_box(self._full_bbox, self._stamp_dab(branch, px, py, pp))
        self._active = False
        if self._full_bbox is None:
            return None
        box = self._full_bbox
        before_arr = self._snapshot.read_before_roi(box)
        after_arr = self.canvas[box[1]:box[3], box[0]:box[2]].copy()
        if np.array_equal(before_arr, after_arr):
            return None
        return box, Image.fromarray(before_arr), Image.fromarray(after_arr)

    def _marker_max_alpha(self, branch: _BranchState, box: Box, dab_alpha: np.ndarray) -> np.ndarray:
        tile_sz = _TileSnapshot.TILE
        x1, y1, x2, y2 = box
        prev_max = np.zeros_like(dab_alpha, dtype=np.float32)
        tx1, ty1 = x1 // tile_sz, y1 // tile_sz
        tx2, ty2 = (x2 - 1) // tile_sz, (y2 - 1) // tile_sz
        h, w = self.canvas.shape[:2]
        for ty in range(ty1, ty2 + 1):
            for tx in range(tx1, tx2 + 1):
                key = (tx, ty)
                rx1, ry1 = tx * tile_sz, ty * tile_sz
                rx2, ry2 = min(w, rx1 + tile_sz), min(h, ry1 + tile_sz)
                tile = branch.marker_tiles.get(key)
                if tile is None:
                    tile = np.zeros((ry2 - ry1, rx2 - rx1), dtype=np.float32)
                    branch.marker_tiles[key] = tile
                ix1, iy1 = max(x1, rx1), max(y1, ry1)
                ix2, iy2 = min(x2, rx2), min(y2, ry2)
                sub_new = dab_alpha[iy1 - y1:iy2 - y1, ix1 - x1:ix2 - x1]
                sub_old = tile[iy1 - ry1:iy2 - ry1, ix1 - rx1:ix2 - rx1]
                merged = np.maximum(sub_old, sub_new)
                prev_max[iy1 - y1:iy2 - y1, ix1 - x1:ix2 - x1] = merged
                tile[iy1 - ry1:iy2 - ry1, ix1 - rx1:ix2 - rx1] = merged
        return prev_max

    def _stamp_dab(self, branch: _BranchState, x: float, y: float, pressure: float) -> Box | None:
        s = self.settings
        tool = s.tool
        h, w = self.canvas.shape[:2]

        # Compute effective diameter & opacity from pressure
        p = max(0.0, min(1.0, pressure))
        if s.pressure_size and tool not in (BrushTool.BINARY,):
            diam = s.size * (s.min_size_ratio + (1.0 - s.min_size_ratio) * p)
        else:
            diam = float(s.size)
        diam = max(1.0, min(500.0, diam))

        eff_opacity = float(s.opacity)
        if s.pressure_opacity and tool != BrushTool.BINARY:
            eff_opacity *= max(0.05, p)

        hardness = float(s.hardness)
        if tool == BrushTool.PEN:
            hardness = max(0.78, hardness)
        elif tool == BrushTool.AIRBRUSH:
            hardness = min(0.32, hardness * 0.4)
            eff_opacity *= 0.35
        elif tool == BrushTool.WATERCOLOR:
            hardness = min(0.65, hardness)
            eff_opacity *= max(0.12, 1.0 - 0.65 * s.dilution)
        elif tool == BrushTool.MARKER:
            hardness = max(0.82, hardness)

        is_binary = (tool == BrushTool.BINARY)
        stamp = build_brush_stamp(
            max(1, round(diam * 2)),
            round(hardness * 100),
            s.shape_name,
            s.antialias and not is_binary,
            is_binary,
        )
        sh, sw = stamp.shape
        cx, cy = round(x), round(y)
        sx0 = cx - sw // 2
        sy0 = cy - sh // 2
        raw_box = (sx0, sy0, sx0 + sw, sy0 + sh)
        box = _clamp_box(raw_box, w, h)
        if box is None:
            return None
        x1, y1, x2, y2 = box
        alpha = stamp[y1 - sy0:y2 - sy0, x1 - sx0:x2 - sx0].copy()

        # Apply paper texture modulation
        tex = _get_paper_texture(s.texture_name)
        if tex is not None and s.texture_strength > 0 and tool not in (BrushTool.BINARY, BrushTool.BLUR, BrushTool.SMUDGE):
            th, tw = tex.shape
            ty_idx = np.arange(y1, y2) % th
            tx_idx = np.arange(x1, x2) % tw
            tile_vals = tex[np.ix_(ty_idx, tx_idx)]
            alpha *= (1.0 - s.texture_strength * (1.0 - tile_vals))

        # Clip to active selection & protected restored bubbles
        gate = _effective_mask_crop(box, self.selection_mask, self.protected_mask)
        if gate is not None:
            alpha *= gate
        if not np.any(alpha > 1e-4):
            return None

        self._snapshot.capture_roi(box)
        roi = self.canvas[y1:y2, x1:x2]
        roi_f = roi.astype(np.float32)

        if tool == BrushTool.MARKER:
            dab_a = np.clip(alpha * eff_opacity, 0.0, 1.0)
            total_a = self._marker_max_alpha(branch, box, dab_a)
            base_f = self._snapshot.read_before_roi(box).astype(np.float32)
            fg = np.array(s.color, dtype=np.float32)
            blended = base_f * (1.0 - total_a[..., None]) + fg * total_a[..., None]
            roi[:] = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
            return box

        if tool == BrushTool.BLUR:
            k = max(3, min(31, (int(round(diam * 0.4)) | 1)))
            blurred = cv2.GaussianBlur(roi, (k, k), 0).astype(np.float32)
            a = np.clip(alpha * eff_opacity * max(0.25, s.blending), 0.0, 1.0)[..., None]
            roi[:] = np.clip(np.rint(roi_f * (1.0 - a) + blurred * a), 0, 255).astype(np.uint8)
            return box

        if tool == BrushTool.SMUDGE:
            if branch.smudge_patch is None:
                branch.smudge_patch = roi_f.copy()
                return box
            patch = branch.smudge_patch
            if patch.shape[:2] != roi_f.shape[:2]:
                patch = cv2.resize(patch, (roi_f.shape[1], roi_f.shape[0]), interpolation=cv2.INTER_LINEAR)
            a = np.clip(alpha * eff_opacity, 0.0, 1.0)[..., None]
            blended = roi_f * (1.0 - a) + patch * a
            roi[:] = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
            keep = max(0.1, min(0.95, s.persistence))
            pick = max(0.05, 1.0 - s.blending * 0.7)
            branch.smudge_patch = patch * keep + roi_f * (1.0 - keep) * pick + patch * (1.0 - keep) * (1.0 - pick)
            return box

        if tool == BrushTool.ERASER:
            if s.eraser_mode == "original" and self.original_canvas is not None:
                target = self.original_canvas[y1:y2, x1:x2].astype(np.float32)
            else:
                target = np.array(s.bg_color, dtype=np.float32)
            a = np.clip(alpha * eff_opacity, 0.0, 1.0)[..., None]
            roi[:] = np.clip(np.rint(roi_f * (1.0 - a) + target * a), 0, 255).astype(np.uint8)
            return box

        if tool == BrushTool.CLONE:
            if self._clone_offset is None:
                return None
            ox, oy = round(self._clone_offset[0]), round(self._clone_offset[1])
            sy_idx = np.clip(np.arange(y1, y2) + oy, 0, h - 1)
            sx_idx = np.clip(np.arange(x1, x2) + ox, 0, w - 1)
            sx_min, sx_max = int(sx_idx.min()), int(sx_idx.max())
            sy_min, sy_max = int(sy_idx.min()), int(sy_idx.max())
            src_block = self._snapshot.read_before_roi((sx_min, sy_min, sx_max + 1, sy_max + 1))
            src = src_block[np.ix_(sy_idx - sy_min, sx_idx - sx_min)]
            a = np.clip(alpha * eff_opacity, 0.0, 1.0)[..., None]
            roi[:] = np.clip(np.rint(roi_f * (1.0 - a) + src.astype(np.float32) * a), 0, 255).astype(np.uint8)
            return box

        if tool in (BrushTool.WATERCOLOR, BrushTool.BRUSH):
            weights = alpha + 1e-6
            sample_rgb = (roi_f * weights[..., None]).sum(axis=(0, 1)) / weights.sum()
            fg = np.array(s.color, dtype=np.float32)
            mix_rate = float(s.blending) if tool == BrushTool.WATERCOLOR else float(s.blending) * 0.6
            target = fg * (1.0 - mix_rate) + sample_rgb * mix_rate
            if branch.carry_color is None:
                branch.carry_color = target.copy()
            else:
                pers = float(s.persistence)
                branch.carry_color = branch.carry_color * pers + target * (1.0 - pers)
            paint_rgb = branch.carry_color
            a = np.clip(alpha * eff_opacity, 0.0, 1.0)[..., None]
            roi[:] = np.clip(np.rint(roi_f * (1.0 - a) + paint_rgb * a), 0, 255).astype(np.uint8)
            return box

        # Pencil, Pen, Airbrush, Binary
        fg = np.array(s.color, dtype=np.float32)
        if is_binary:
            a = (alpha > 0.5).astype(np.float32)[..., None] * eff_opacity
        else:
            a = np.clip(alpha * eff_opacity, 0.0, 1.0)[..., None]
        roi[:] = np.clip(np.rint(roi_f * (1.0 - a) + fg * a), 0, 255).astype(np.uint8)
        return box


def sample_color(canvas: np.ndarray, x: int, y: int) -> tuple[int, int, int] | None:
    """Return the RGB tuple at (x, y) if inside the canvas, else None."""
    h, w = canvas.shape[:2]
    ix, iy = int(x), int(y)
    if not (0 <= ix < w and 0 <= iy < h):
        return None
    r, g, b = canvas[iy, ix]
    return int(r), int(g), int(b)


class BrushEngine:
    """Factory and stateless drawing helpers for brush strokes, shapes, and gradients."""

    def start_stroke(
        self,
        canvas: np.ndarray,
        settings: BrushSettings,
        *,
        selection_mask: np.ndarray | None = None,
        original_canvas: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
        clone_source: tuple[float, float] | None = None,
    ) -> StrokeSession:
        return StrokeSession(
            canvas,
            settings,
            selection_mask=selection_mask,
            original_canvas=original_canvas,
            protected_mask=protected_mask,
            clone_source=clone_source,
        )

    @staticmethod
    def draw_shape(
        canvas: np.ndarray,
        tool: str,
        points: list[tuple[float, float]],
        settings: BrushSettings,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        if len(points) < 2:
            return None
        h, w = canvas.shape[:2]
        thickness = max(1, int(settings.size))
        pad = thickness + 4
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]

        def _render_branch(pts: list[tuple[float, float]]) -> tuple[Box, np.ndarray] | None:
            bxs = [p[0] for p in pts]
            bys = [p[1] for p in pts]
            raw = (
                math.floor(min(bxs)) - pad,
                math.floor(min(bys)) - pad,
                math.ceil(max(bxs)) + pad,
                math.ceil(max(bys)) + pad,
            )
            box = _clamp_box(raw, w, h)
            if box is None:
                return None
            x1, y1, x2, y2 = box
            mask = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
            line_type = cv2.LINE_AA if settings.antialias else cv2.LINE_8
            local = [(int(round(px - x1)), int(round(py - y1))) for px, py in pts]
            if tool == BrushTool.LINE or (tool == BrushTool.CURVE and len(pts) == 2):
                cv2.line(mask, local[0], local[1], 255, thickness, lineType=line_type)
            elif tool == BrushTool.CURVE and len(pts) >= 3:
                p0, ctrl, p1 = pts[0], pts[1], pts[2]
                steps = max(24, int(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 2))
                poly = []
                for i in range(steps + 1):
                    t = i / steps
                    mt = 1.0 - t
                    qx = mt * mt * p0[0] + 2 * mt * t * ctrl[0] + t * t * p1[0] - x1
                    qy = mt * mt * p0[1] + 2 * mt * t * ctrl[1] + t * t * p1[1] - y1
                    poly.append([round(qx), round(qy)])
                cv2.polylines(mask, [np.array(poly, dtype=np.int32)], False, 255, thickness, lineType=line_type)
            elif tool == BrushTool.RECT_SHAPE:
                rx1, ry1 = min(local[0][0], local[1][0]), min(local[0][1], local[1][1])
                rx2, ry2 = max(local[0][0], local[1][0]), max(local[0][1], local[1][1])
                cv2.rectangle(mask, (rx1, ry1), (rx2, ry2), 255, -1 if settings.shape_filled else thickness, lineType=line_type)
            elif tool == BrushTool.ELLIPSE_SHAPE:
                rx1, ry1 = min(local[0][0], local[1][0]), min(local[0][1], local[1][1])
                rx2, ry2 = max(local[0][0], local[1][0]), max(local[0][1], local[1][1])
                cx, cy = (rx1 + rx2) // 2, (ry1 + ry2) // 2
                ax, ay = max(1, (rx2 - rx1) // 2), max(1, (ry2 - ry1) // 2)
                cv2.ellipse(mask, (cx, cy), (ax, ay), 0, 0, 360, 255, -1 if settings.shape_filled else thickness, lineType=line_type)
            return box, mask

        branches = [points]
        if settings.symmetry == "horizontal":
            branches.append([((w - 1) - px, py) for px, py in points])
        elif settings.symmetry == "vertical":
            branches.append([(px, (h - 1) - py) for px, py in points])

        # Compute union box and snapshot once before mutating
        rendered = []
        full_box: Box | None = None
        for br in branches:
            res = _render_branch(br)
            if res is not None:
                box, mask = res
                rendered.append((box, mask))
                full_box = _union_box(full_box, box)
        if full_box is None:
            return None
        before_pil = Image.fromarray(canvas[full_box[1]:full_box[3], full_box[0]:full_box[2]].copy())
        fg = np.array(settings.color, dtype=np.float32)
        for box, mask in rendered:
            x1, y1, x2, y2 = box
            alpha = (mask.astype(np.float32) / 255.0) * settings.opacity
            gate = _effective_mask_crop(box, selection_mask, protected_mask)
            if gate is not None:
                alpha *= gate
            roi_f = canvas[y1:y2, x1:x2].astype(np.float32)
            a = alpha[..., None]
            canvas[y1:y2, x1:x2] = np.clip(np.rint(roi_f * (1.0 - a) + fg * a), 0, 255).astype(np.uint8)
        after_pil = Image.fromarray(canvas[full_box[1]:full_box[3], full_box[0]:full_box[2]].copy())
        return full_box, before_pil, after_pil

    @staticmethod
    def draw_gradient(
        canvas: np.ndarray,
        start: tuple[float, float],
        end: tuple[float, float],
        settings: BrushSettings,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        h, w = canvas.shape[:2]
        if selection_mask is not None and np.any(selection_mask > 0):
            ys, xs = np.where(selection_mask > 0)
            box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        else:
            box = (0, 0, w, h)
        x1, y1, x2, y2 = box
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1e-3:
            return None
        yy, xx = np.mgrid[y1:y2, x1:x2].astype(np.float32)
        if settings.gradient_shape == "radial":
            t = np.sqrt((xx - start[0]) ** 2 + (yy - start[1]) ** 2) / length
        else:
            t = ((xx - start[0]) * dx + (yy - start[1]) * dy) / (length * length)
        t = np.clip(t, 0.0, 1.0)

        before_pil = Image.fromarray(canvas[y1:y2, x1:x2].copy())
        roi_f = canvas[y1:y2, x1:x2].astype(np.float32)
        fg = np.array(settings.color, dtype=np.float32)
        bg = np.array(settings.bg_color, dtype=np.float32)
        gate = _effective_mask_crop(box, selection_mask, protected_mask)

        if settings.gradient_mode == "fg_transparent":
            alpha = (1.0 - t) * settings.opacity
            if gate is not None:
                alpha *= gate
            out = roi_f * (1.0 - alpha[..., None]) + fg * alpha[..., None]
        else:
            grad_rgb = fg * (1.0 - t[..., None]) + bg * t[..., None]
            alpha = np.full((y2 - y1, x2 - x1), settings.opacity, dtype=np.float32)
            if gate is not None:
                alpha *= gate
            out = roi_f * (1.0 - alpha[..., None]) + grad_rgb * alpha[..., None]

        canvas[y1:y2, x1:x2] = np.clip(np.rint(out), 0, 255).astype(np.uint8)
        after_pil = Image.fromarray(canvas[y1:y2, x1:x2].copy())
        return box, before_pil, after_pil


class SelectionEngine:
    """Manages an optional uint8 selection mask and mask-aware fill/move operations."""

    def __init__(self, width: int = 0, height: int = 0):
        self.width = int(width)
        self.height = int(height)
        self.mask: np.ndarray | None = None

    def resize(self, width: int, height: int) -> None:
        w, h = int(width), int(height)
        if w <= 0 or h <= 0 or self.mask is None or self.mask.shape != (h, w):
            self.mask = None
        self.width = w
        self.height = h

    def is_empty(self) -> bool:
        return self.mask is None or not np.any(self.mask > 0)

    def bbox(self) -> Box | None:
        if self.mask is None:
            return None
        ys, xs = np.where(self.mask > 0)
        if xs.size == 0:
            return None
        return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    def clear(self) -> None:
        self.mask = None

    def select_all(self) -> None:
        if self.width > 0 and self.height > 0:
            self.mask = np.full((self.height, self.width), 255, dtype=np.uint8)

    def invert(self) -> None:
        if self.width <= 0 or self.height <= 0:
            return
        if self.mask is None:
            self.select_all()
        else:
            self.mask = (255 - self.mask).astype(np.uint8)
            if not np.any(self.mask > 0):
                self.mask = None

    def _combine(self, new_mask: np.ndarray, mode: str) -> None:
        if mode == "replace" or self.mask is None:
            if mode == "subtract":
                self.mask = None
                return
            if mode == "intersect" and self.mask is None:
                self.mask = new_mask
            else:
                self.mask = new_mask
        elif mode == "add":
            self.mask = np.maximum(self.mask, new_mask)
        elif mode == "subtract":
            self.mask = np.clip(self.mask.astype(np.int16) - new_mask, 0, 255).astype(np.uint8)
        elif mode == "intersect":
            self.mask = np.minimum(self.mask, new_mask)
        if self.mask is not None and not np.any(self.mask > 0):
            self.mask = None

    def apply_rect(self, box: Box, mode: str = "replace") -> None:
        clamped = _clamp_box(box, self.width, self.height)
        if clamped is None:
            if mode == "replace":
                self.mask = None
            return
        new_mask = np.zeros((self.height, self.width), dtype=np.uint8)
        x1, y1, x2, y2 = clamped
        new_mask[y1:y2, x1:x2] = 255
        self._combine(new_mask, mode)

    def apply_lasso(
        self,
        points: list[tuple[float, float]],
        mode: str = "replace",
        antialias: bool = True,
    ) -> None:
        if len(points) < 3 or self.width <= 0 or self.height <= 0:
            return
        new_mask = np.zeros((self.height, self.width), dtype=np.uint8)
        pts = np.array([[round(px), round(py)] for px, py in points], dtype=np.int32)
        cv2.fillPoly(new_mask, [pts], 255, lineType=cv2.LINE_AA if antialias else cv2.LINE_8)
        self._combine(new_mask, mode)

    def apply_poly_lasso(
        self,
        points: list[tuple[float, float]],
        mode: str = "replace",
        antialias: bool = True,
    ) -> None:
        self.apply_lasso(points, mode=mode, antialias=antialias)

    def apply_magic_wand(
        self,
        canvas: np.ndarray,
        x: int,
        y: int,
        tolerance: int = 24,
        contiguous: bool = True,
        antialias: bool = True,
        mode: str = "replace",
    ) -> None:
        h, w = canvas.shape[:2]
        self.width, self.height = w, h
        if not (0 <= x < w and 0 <= y < h):
            return
        tol = max(0, min(255, int(tolerance)))
        if contiguous:
            flood_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
            flags = 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
            work = canvas.copy()
            cv2.floodFill(work, flood_mask, (int(x), int(y)), (0, 0, 0), (tol, tol, tol), (tol, tol, tol), flags)
            new_mask = flood_mask[1:-1, 1:-1]
        else:
            seed = canvas[int(y), int(x)].astype(np.int16)
            diff = np.max(np.abs(canvas.astype(np.int16) - seed), axis=2)
            new_mask = np.where(diff <= tol, 255, 0).astype(np.uint8)
        if antialias and np.any(new_mask > 0):
            new_mask = cv2.GaussianBlur(new_mask, (3, 3), 0.5)
        self._combine(new_mask, mode)

    def paint_mask_stroke(
        self,
        points: list[tuple[float, float]],
        radius: float,
        *,
        erase: bool = False,
        antialias: bool = True,
    ) -> None:
        if self.width <= 0 or self.height <= 0 or not points:
            return
        if self.mask is None:
            if erase:
                return
            self.mask = np.zeros((self.height, self.width), dtype=np.uint8)
        r = max(1, int(round(radius)))
        value = 0 if erase else 255
        line_type = cv2.LINE_AA if antialias else cv2.LINE_8
        if len(points) == 1:
            px, py = round(points[0][0]), round(points[0][1])
            cv2.circle(self.mask, (px, py), r, value, -1, lineType=line_type)
        else:
            for p1, p2 in zip(points, points[1:]):
                cv2.line(
                    self.mask,
                    (round(p1[0]), round(p1[1])),
                    (round(p2[0]), round(p2[1])),
                    value,
                    max(1, r * 2),
                    lineType=line_type,
                )
        if erase and not np.any(self.mask > 0):
            self.mask = None

    def expand(self, px: int) -> None:
        if self.mask is None or px <= 0:
            return
        k = 2 * int(px) + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        self.mask = cv2.dilate(self.mask, kernel)

    def contract(self, px: int) -> None:
        if self.mask is None or px <= 0:
            return
        k = 2 * int(px) + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        self.mask = cv2.erode(self.mask, kernel)
        if not np.any(self.mask > 0):
            self.mask = None

    def feather(self, radius: int) -> None:
        if self.mask is None or radius <= 0:
            return
        k = 2 * int(radius) + 1
        self.mask = cv2.GaussianBlur(self.mask, (k, k), 0)
        if not np.any(self.mask > 0):
            self.mask = None

    def contours(self) -> list[np.ndarray]:
        if self.mask is None:
            return []
        binary = (self.mask >= 128).astype(np.uint8)
        found, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        return found

    @staticmethod
    def bucket_fill(
        canvas: np.ndarray,
        x: int,
        y: int,
        color: tuple[int, int, int],
        *,
        tolerance: int = 24,
        contiguous: bool = True,
        gap_close: int = 0,
        expand_px: int = 1,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        h, w = canvas.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return None
        if selection_mask is not None and selection_mask[y, x] == 0:
            return None
        tol = max(0, min(255, int(tolerance)))
        seed = canvas[int(y), int(x)].astype(np.int16)

        if contiguous:
            if gap_close > 0:
                barrier = (np.max(np.abs(canvas.astype(np.int16) - seed), axis=2) > tol).astype(np.uint8)
                k = max(3, int(gap_close) * 2 + 1)
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
                closed = cv2.morphologyEx(barrier, cv2.MORPH_CLOSE, kernel)
                closed[y, x] = 0
                flood_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
                # Flood fill the unobstructed region (where closed == 0)
                work = (1 - closed) * 255
                flags = 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
                cv2.floodFill(work.astype(np.uint8), flood_mask, (int(x), int(y)), 255, 0, 0, flags)
                fill_mask = flood_mask[1:-1, 1:-1]
            else:
                flood_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
                flags = 4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE
                work = canvas.copy()
                cv2.floodFill(work, flood_mask, (int(x), int(y)), (0, 0, 0), (tol, tol, tol), (tol, tol, tol), flags)
                fill_mask = flood_mask[1:-1, 1:-1]
        else:
            diff = np.max(np.abs(canvas.astype(np.int16) - seed), axis=2)
            fill_mask = np.where(diff <= tol, 255, 0).astype(np.uint8)

        if expand_px > 0 and np.any(fill_mask > 0):
            k = 2 * int(expand_px) + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            fill_mask = cv2.dilate(fill_mask, kernel)

        if selection_mask is not None:
            fill_mask = np.minimum(fill_mask, selection_mask)
        if protected_mask is not None:
            fill_mask[protected_mask > 0] = 0

        ys, xs = np.where(fill_mask > 0)
        if xs.size == 0:
            return None
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        x1, y1, x2, y2 = box
        before_pil = Image.fromarray(canvas[y1:y2, x1:x2].copy())
        alpha = (fill_mask[y1:y2, x1:x2].astype(np.float32) / 255.0)[..., None]
        roi_f = canvas[y1:y2, x1:x2].astype(np.float32)
        fg = np.array(color, dtype=np.float32)
        canvas[y1:y2, x1:x2] = np.clip(np.rint(roi_f * (1.0 - alpha) + fg * alpha), 0, 255).astype(np.uint8)
        after_pil = Image.fromarray(canvas[y1:y2, x1:x2].copy())
        return box, before_pil, after_pil

    @staticmethod
    def fill_selection(
        canvas: np.ndarray,
        color: tuple[int, int, int],
        selection_mask: np.ndarray,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        if selection_mask is None:
            return None
        ys, xs = np.where(selection_mask > 0)
        if xs.size == 0:
            return None
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        x1, y1, x2, y2 = box
        alpha = selection_mask[y1:y2, x1:x2].astype(np.float32) / 255.0
        if protected_mask is not None:
            alpha *= (protected_mask[y1:y2, x1:x2] == 0).astype(np.float32)
        if not np.any(alpha > 0):
            return None
        before_pil = Image.fromarray(canvas[y1:y2, x1:x2].copy())
        roi_f = canvas[y1:y2, x1:x2].astype(np.float32)
        fg = np.array(color, dtype=np.float32)
        canvas[y1:y2, x1:x2] = np.clip(np.rint(roi_f * (1.0 - alpha[..., None]) + fg * alpha[..., None]), 0, 255).astype(np.uint8)
        after_pil = Image.fromarray(canvas[y1:y2, x1:x2].copy())
        return box, before_pil, after_pil

    @staticmethod
    def move_selection(
        canvas: np.ndarray,
        selection_mask: np.ndarray,
        dx: int,
        dy: int,
        bg_color: tuple[int, int, int] = (255, 255, 255),
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image, np.ndarray | None] | None:
        if selection_mask is None or (dx == 0 and dy == 0):
            return None
        h, w = canvas.shape[:2]
        ys, xs = np.where(selection_mask > 0)
        if xs.size == 0:
            return None
        sx1, sy1, sx2, sy2 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        dx, dy = int(dx), int(dy)
        src_alpha = selection_mask[sy1:sy2, sx1:sx2].astype(np.float32) / 255.0
        if protected_mask is not None:
            src_alpha *= (protected_mask[sy1:sy2, sx1:sx2] == 0).astype(np.float32)
        lifted = canvas[sy1:sy2, sx1:sx2].copy()

        dst_box = _clamp_box((sx1 + dx, sy1 + dy, sx2 + dx, sy2 + dy), w, h)
        full_box = _union_box((sx1, sy1, sx2, sy2), dst_box)
        assert full_box is not None
        before_pil = Image.fromarray(canvas[full_box[1]:full_box[3], full_box[0]:full_box[2]].copy())

        # Clear source pixels with bg_color
        bg = np.array(bg_color, dtype=np.float32)
        src_f = canvas[sy1:sy2, sx1:sx2].astype(np.float32)
        canvas[sy1:sy2, sx1:sx2] = np.clip(np.rint(src_f * (1.0 - src_alpha[..., None]) + bg * src_alpha[..., None]), 0, 255).astype(np.uint8)

        # Paste lifted pixels at shifted target
        new_mask = np.zeros((h, w), dtype=np.uint8)
        if dst_box is not None:
            tx1, ty1, tx2, ty2 = dst_box
            ox1, oy1 = tx1 - (sx1 + dx), ty1 - (sy1 + dy)
            ox2, oy2 = ox1 + (tx2 - tx1), oy1 + (ty2 - ty1)
            paste_alpha = src_alpha[oy1:oy2, ox1:ox2].copy()
            if protected_mask is not None:
                paste_alpha *= (protected_mask[ty1:ty2, tx1:tx2] == 0).astype(np.float32)
            dst_f = canvas[ty1:ty2, tx1:tx2].astype(np.float32)
            lifted_f = lifted[oy1:oy2, ox1:ox2].astype(np.float32)
            canvas[ty1:ty2, tx1:tx2] = np.clip(np.rint(dst_f * (1.0 - paste_alpha[..., None]) + lifted_f * paste_alpha[..., None]), 0, 255).astype(np.uint8)
            new_mask[ty1:ty2, tx1:tx2] = np.clip(np.rint(paste_alpha * 255.0), 0, 255).astype(np.uint8)

        after_pil = Image.fromarray(canvas[full_box[1]:full_box[3], full_box[0]:full_box[2]].copy())
        return full_box, before_pil, after_pil, (new_mask if np.any(new_mask > 0) else None)


class ImageFilters:
    """Selection-aware and protected-region-safe image adjustments and filters.

    All filter methods are non-mutating and return ``(box, before_pil, after_pil)``
    so callers can support interactive live preview before committing.
    """

    @staticmethod
    def _apply_roi_fn(
        canvas: np.ndarray,
        fn,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        h, w = canvas.shape[:2]
        if selection_mask is not None and np.any(selection_mask > 0):
            ys, xs = np.where(selection_mask > 0)
            box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        else:
            box = (0, 0, w, h)
        x1, y1, x2, y2 = box
        src_roi = canvas[y1:y2, x1:x2]
        before_pil = Image.fromarray(src_roi.copy())
        out_roi = fn(src_roi)
        gate = _effective_mask_crop(box, selection_mask, protected_mask)
        if gate is not None:
            blended = src_roi.astype(np.float32) * (1.0 - gate[..., None]) + out_roi.astype(np.float32) * gate[..., None]
            final_roi = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
        else:
            final_roi = np.clip(out_roi, 0, 255).astype(np.uint8)
        if np.array_equal(src_roi, final_roi):
            return None
        after_pil = Image.fromarray(final_roi)
        return box, before_pil, after_pil

    @classmethod
    def adjust_hsl(
        cls,
        canvas: np.ndarray,
        hue_deg: float = 0.0,
        sat_pct: float = 0.0,
        lum_pct: float = 0.0,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        def _fn(roi: np.ndarray) -> np.ndarray:
            hls = cv2.cvtColor(roi, cv2.COLOR_RGB2HLS).astype(np.float32)
            # OpenCV H is in [0, 180)
            hls[..., 0] = (hls[..., 0] + (hue_deg / 2.0)) % 180.0
            if lum_pct >= 0:
                hls[..., 1] = hls[..., 1] + (255.0 - hls[..., 1]) * (lum_pct / 100.0)
            else:
                hls[..., 1] = hls[..., 1] * (1.0 + lum_pct / 100.0)
            if sat_pct >= 0:
                hls[..., 2] = hls[..., 2] + (255.0 - hls[..., 2]) * (sat_pct / 100.0)
            else:
                hls[..., 2] = hls[..., 2] * (1.0 + sat_pct / 100.0)
            hls = np.clip(np.rint(hls), 0, 255).astype(np.uint8)
            return cv2.cvtColor(hls, cv2.COLOR_HLS2RGB)

        return cls._apply_roi_fn(canvas, _fn, selection_mask=selection_mask, protected_mask=protected_mask)

    @classmethod
    def adjust_brightness_contrast(
        cls,
        canvas: np.ndarray,
        brightness: float = 0.0,
        contrast: float = 0.0,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        def _fn(roi: np.ndarray) -> np.ndarray:
            f = roi.astype(np.float32)
            # Map contrast in [-100, 100] to standard slope
            c = max(-100.0, min(100.0, float(contrast)))
            factor = (259.0 * (c + 255.0)) / (255.0 * (259.0 - c)) if c < 259.0 else 1.0
            out = factor * (f - 128.0) + 128.0 + float(brightness) * 2.55
            return np.clip(np.rint(out), 0, 255).astype(np.uint8)

        return cls._apply_roi_fn(canvas, _fn, selection_mask=selection_mask, protected_mask=protected_mask)

    @classmethod
    def adjust_levels(
        cls,
        canvas: np.ndarray,
        in_black: int = 0,
        gamma: float = 1.0,
        in_white: int = 255,
        out_black: int = 0,
        out_white: int = 255,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        in_b = max(0, min(254, int(in_black)))
        in_w = max(in_b + 1, min(255, int(in_white)))
        g = max(0.1, min(9.99, float(gamma)))
        x = np.arange(256, dtype=np.float32)
        norm = np.clip((x - in_b) / (in_w - in_b), 0.0, 1.0)
        mapped = np.power(norm, 1.0 / g) * (out_white - out_black) + out_black
        lut = np.clip(np.rint(mapped), 0, 255).astype(np.uint8)

        def _fn(roi: np.ndarray) -> np.ndarray:
            return lut[roi]

        return cls._apply_roi_fn(canvas, _fn, selection_mask=selection_mask, protected_mask=protected_mask)

    @classmethod
    def gaussian_blur(
        cls,
        canvas: np.ndarray,
        radius: float = 3.0,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        r = max(0.5, float(radius))
        k = max(3, int(round(r * 2)) | 1)

        def _fn(roi: np.ndarray) -> np.ndarray:
            return cv2.GaussianBlur(roi, (k, k), r)

        return cls._apply_roi_fn(canvas, _fn, selection_mask=selection_mask, protected_mask=protected_mask)

    @classmethod
    def sharpen(
        cls,
        canvas: np.ndarray,
        amount: float = 100.0,
        radius: float = 1.5,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        r = max(0.5, float(radius))
        k = max(3, int(round(r * 2)) | 1)
        strength = float(amount) / 100.0

        def _fn(roi: np.ndarray) -> np.ndarray:
            blurred = cv2.GaussianBlur(roi, (k, k), r).astype(np.float32)
            out = roi.astype(np.float32) + strength * (roi.astype(np.float32) - blurred)
            return np.clip(np.rint(out), 0, 255).astype(np.uint8)

        return cls._apply_roi_fn(canvas, _fn, selection_mask=selection_mask, protected_mask=protected_mask)

    @classmethod
    def invert_colors(
        cls,
        canvas: np.ndarray,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        return cls._apply_roi_fn(canvas, lambda roi: (255 - roi).astype(np.uint8),
                                 selection_mask=selection_mask, protected_mask=protected_mask)

    @classmethod
    def desaturate(
        cls,
        canvas: np.ndarray,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        def _fn(roi: np.ndarray) -> np.ndarray:
            gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
            return np.repeat(gray[..., None], 3, axis=2)

        return cls._apply_roi_fn(canvas, _fn, selection_mask=selection_mask, protected_mask=protected_mask)

    @classmethod
    def luminance_to_white(
        cls,
        canvas: np.ndarray,
        threshold: int = 215,
        softness: int = 24,
        *,
        selection_mask: np.ndarray | None = None,
        protected_mask: np.ndarray | None = None,
    ) -> tuple[Box, Image.Image, Image.Image] | None:
        thr = max(1, min(255, int(threshold)))
        soft = max(1, int(softness))

        def _fn(roi: np.ndarray) -> np.ndarray:
            luma = (0.299 * roi[..., 0] + 0.587 * roi[..., 1] + 0.114 * roi[..., 2]).astype(np.float32)
            t = np.clip((luma - (thr - soft)) / soft, 0.0, 1.0)[..., None]
            out = roi.astype(np.float32) * (1.0 - t) + 255.0 * t
            return np.clip(np.rint(out), 0, 255).astype(np.uint8)

        return cls._apply_roi_fn(canvas, _fn, selection_mask=selection_mask, protected_mask=protected_mask)
