"""Crisp magazine screentone, generated as cached inline SVG."""
from __future__ import annotations

from functools import lru_cache
from math import ceil, hypot, sqrt

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import theme

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
def halftone_svg(width, height, compact=False, mask='linear', profile='section', direction='left',
                 dot_color=DOT_COLOR):
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
        f'<g fill="{dot_color}">',
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
def _renderer(width, height, compact, mask, profile, direction, dot_color):
    # 由 GUI 线程调用，按尺寸缓存；日志追加不会重新构建 SVG。
    return QSvgRenderer(QByteArray(halftone_svg(width, height, compact, mask, profile, direction, dot_color)))


@lru_cache(maxsize=96)
def _tone_pixmap(width, height, dpr_tenth, compact, mask, profile, direction, dot_color):
    dpr = max(1.0, dpr_tenth / 10.0)
    pix = QPixmap(max(1, round(width * dpr)), max(1, round(height * dpr)))
    pix.fill(Qt.transparent)
    pix.setDevicePixelRatio(dpr)
    p = QPainter(pix)
    _renderer(width, height, compact, mask, profile, direction, dot_color).render(
        p, QRectF(0, 0, width, height)
    )
    p.end()
    return pix


def draw_tone(painter, bounds, *, compact=False, mask='linear', profile='section', direction='left'):
    if bounds.width() <= 0 or bounds.height() <= 0:
        return
    palette = theme()
    w = max(1, round(bounds.width()))
    h = max(1, round(bounds.height()))
    dev = painter.device()
    dpr = dev.devicePixelRatioF() if dev is not None and hasattr(dev, 'devicePixelRatioF') else 1.0
    dpr_tenth = max(10, round(dpr * 10))
    pix = _tone_pixmap(w, h, dpr_tenth, compact, mask, profile, direction, palette['tone'])
    painter.save()
    if palette['toneBlend'] == 'multiply':
        # QWidget 中用 Qt 的对应混合模式实现 SVG 的 mix-blend-mode: multiply。
        painter.setCompositionMode(QPainter.CompositionMode_Multiply)
    else:
        painter.setOpacity(palette['toneAlpha'])
    painter.drawPixmap(bounds, pix, QRectF(0, 0, pix.width(), pix.height()))
    painter.restore()


def draw_corner_tones(painter, bounds, *, compact=False):
    """Small page-edge accents; keep the central reading area open."""
    if bounds.width() < 320 or bounds.height() < 150:
        return
    width = max(16, round(min(192, bounds.width() * .24) / 8) * 8)
    height = max(16, round(min(112, bounds.height() * .28) / 8) * 8)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setOpacity(.3 if theme()['toneBlend'] == 'multiply' else 1.0)
    corners = (
        (QRectF(bounds.left() + 8, bounds.top() + 8, width, height), 'left'),
        (QRectF(bounds.right() - width - 8, bounds.bottom() - height - 8, width, height), 'right'),
    )
    for corner, direction in corners:
        wedge = QPainterPath()
        wedge.moveTo(corner.topLeft() if direction == 'left' else corner.bottomRight())
        wedge.lineTo(corner.topRight())
        wedge.lineTo(corner.bottomLeft())
        wedge.closeSubpath()
        painter.save()
        painter.setClipPath(wedge, Qt.IntersectClip)
        draw_tone(painter, corner, compact=compact, profile='section', direction=direction)
        painter.restore()
    painter.restore()
