"""Crisp magazine screentone, generated as cached inline SVG."""
from __future__ import annotations

from functools import lru_cache
from math import ceil, hypot, sqrt

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer

DOT_COLOR = '#111111'
COMPACT_SPACING = 4.0
COMPACT_BREAKPOINT = 960
PROFILES = {
    'hero': ((4.8, 0.6), (7.0, 11.0)),
    'section': ((3.2, 0.6), (6.0, 10.0)),
    'quiet': ((2.0, 0.6), (8.0, 14.0)),
}


def _mix(start, end, amount):
    return start + (end - start) * amount


@lru_cache(maxsize=96)
def halftone_svg(width, height, compact=False, mask='linear', profile='section', direction='left'):
    """45° grid, black ink and a taper toward the title's white space.

    The latest visual reference supersedes the earlier 8–15% opacity rule.
    right mirrors the composition so the dense edge meets the page boundary.
    """
    if width <= 0 or height <= 0:
        raise ValueError('网点区域必须具有正宽度和高度')
    if mask not in ('linear', 'radial') or direction not in ('left', 'right'):
        raise ValueError('无效的网点方向或遮罩')
    diameter, spacing = PROFILES[profile]
    diagonal = sqrt(2.0)
    extent = (width + height) / diagonal
    extra = COMPACT_SPACING if compact else 0.0
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" aria-hidden="true" '
        'style="mix-blend-mode: multiply; pointer-events: none;">',
        f'<g fill="{DOT_COLOR}">',
    ]
    # u、v 为旋转 45° 后的网格坐标；沿 u 轴逐行增加间距。
    u = spacing[0] / 2
    while u < extent:
        progress = u / extent
        pitch = _mix(*spacing, progress) + extra
        # 仅遍历当前斜行与 SVG 视口相交的部分。
        first_v = max(u - diagonal * width, -u)
        last_v = min(u, diagonal * height - u)
        v = ceil(first_v / pitch) * pitch
        while v <= last_v:
            x, y = (u - v) / diagonal, (u + v) / diagonal
            # Dense full-height edge, tapering through dot size rather than gray ink.
            fade = (min(1.0, hypot(2 * x / width - 1, 2 * y / height - 1))
                    if mask == 'radial' else min(1.0, .85 * x / width + .15 * y / height))
            radius = _mix(*diameter, fade) / 2
            inside = radius <= x <= width - radius and radius <= y <= height - radius
            if inside:
                if direction == 'right':
                    x = width - x
                elements.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{radius:.3f}"/>')
            v += pitch
        u += pitch
    elements.extend(('</g>', '</svg>'))
    return '\n'.join(elements).encode('utf-8')


@lru_cache(maxsize=96)
def _renderer(width, height, compact, mask, profile, direction):
    # 由 GUI 线程调用，按尺寸缓存；日志追加不会重新构建 SVG。
    return QSvgRenderer(QByteArray(halftone_svg(width, height, compact, mask, profile, direction)))


def draw_tone(painter, bounds, *, compact=False, mask='linear', profile='section', direction='left'):
    if bounds.width() <= 0 or bounds.height() <= 0:
        return
    renderer = _renderer(max(1, round(bounds.width())), max(1, round(bounds.height())),
                         compact, mask, profile, direction)
    painter.save()
    # QWidget 中用 Qt 的对应混合模式实现 SVG 的 mix-blend-mode: multiply。
    painter.setCompositionMode(QPainter.CompositionMode_Multiply)
    renderer.render(painter, bounds)
    painter.restore()
