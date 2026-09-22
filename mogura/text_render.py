"""Approximate rendering of mokuro text blocks to a PIL image.

Given the text lines of a block and its orientation, this produces a simple
image that mimics how the text is laid out (horizontal rows, or vertical
columns running right-to-left as in Japanese vertical writing). It is meant as
a rough visual comparison against the original cropped page region, not a
faithful typographic reproduction.
"""

from __future__ import annotations

import os
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

# Candidate Japanese-capable fonts, in order of preference.
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/ipafont-mincho/ipam.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-mincho.ttf",
]

_font_path_cache: Optional[str] = None


def _font_path() -> Optional[str]:
    global _font_path_cache
    if _font_path_cache is not None:
        return _font_path_cache
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            _font_path_cache = path
            return path
    return None


def _load_font(size: int) -> ImageFont.ImageFont:
    size = max(6, int(size))
    path = _font_path()
    if path is not None:
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001
            pass
    return ImageFont.load_default()


def _fit_font(cell: float):
    """Return ``(font, ascent)`` sized so the em-box fits within ``cell`` px.

    Glyphs are placed on their baseline (see the draw helpers), which keeps
    each character's natural vertical position within the cell -- full-height
    kanji fill the cell while low/small glyphs like ``っ`` or ``…`` keep their
    designed margins. To make that fit, the font's ascent+descent (em-box) is
    scaled to the cell height rather than the nominal point size.
    """
    cell = max(6.0, cell)
    # Metrics scale linearly with point size, so probe once and rescale.
    probe = _load_font(100)
    try:
        asc, desc = probe.getmetrics()
    except Exception:  # noqa: BLE001
        asc, desc = 80, 20
    em = asc + desc or 100
    point = max(6, int(cell * 100 / em))
    font = _load_font(point)
    try:
        asc2, _desc2 = font.getmetrics()
    except Exception:  # noqa: BLE001
        asc2 = int(point * asc / em)
    return font, asc2


def render_text(
    lines: List[str],
    vertical: bool,
    width: int,
    height: int,
    bg: str = "#ffffff",
    fg: str = "#000000",
) -> Image.Image:
    """Render ``lines`` into a ``width`` x ``height`` image.

    ``vertical`` lays the lines out as columns running right-to-left; otherwise
    they are stacked as horizontal rows. A font size is chosen so the text
    roughly fills the target box.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    image = Image.new("RGB", (width, height), bg)

    non_empty = [ln for ln in lines if ln != ""]
    if not non_empty:
        return image

    draw = ImageDraw.Draw(image)
    num_lines = len(lines)
    max_len = max((len(ln) for ln in lines), default=1) or 1

    # Choose a cell size (approx square per CJK glyph) that fits the box in
    # both directions given the line/column counts.
    if vertical:
        # columns across width, characters down height
        cell = min(width / num_lines, height / max_len)
    else:
        # rows down height, characters across width
        cell = min(height / num_lines, width / max_len)
    cell = max(6.0, cell)
    font, ascent = _fit_font(cell)

    if vertical:
        _draw_vertical(draw, lines, font, ascent, width, height, cell, fg)
    else:
        _draw_horizontal(draw, lines, font, ascent, width, height, cell, fg)
    return image


def render_text_rgba(
    lines: List[str],
    vertical: bool,
    width: int,
    height: int,
    fg: str = "#ff0000",
) -> Image.Image:
    """Render ``lines`` onto a transparent RGBA image in colour ``fg``.

    Useful for overlaying the render on top of the original image region.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    non_empty = [ln for ln in lines if ln != ""]
    if not non_empty:
        return image

    draw = ImageDraw.Draw(image)
    num_lines = len(lines)
    max_len = max((len(ln) for ln in lines), default=1) or 1
    if vertical:
        cell = min(width / num_lines, height / max_len)
    else:
        cell = min(height / num_lines, width / max_len)
    cell = max(6.0, cell)
    font, ascent = _fit_font(cell)

    if vertical:
        _draw_vertical(draw, lines, font, ascent, width, height, cell, fg)
    else:
        _draw_horizontal(draw, lines, font, ascent, width, height, cell, fg)
    return image


def overlay_render_on_image(
    original: Image.Image,
    lines: List[str],
    vertical: bool,
    fg: str = "#e53935",
) -> Image.Image:
    """Overlay an approximate text render (in ``fg``) on ``original``.

    The render is sized to the original's dimensions and alpha-composited so
    the source art shows through beneath the coloured text.
    """
    base = original.convert("RGBA")
    w, h = base.size
    overlay = render_text_rgba(lines, vertical, w, h, fg=fg)
    return Image.alpha_composite(base, overlay).convert("RGB")


# A small margin inset applied once to the whole render (not per glyph).
_MARGIN = 2


def _line_pitch(available: float, num_lines: int, cell: float) -> float:
    """Spacing between lines so they spread across the ``available`` extent.

    Each line advances by at least ``cell`` (so lines never overlap), but when
    there is spare room the lines are spread out to fill the cross-axis instead
    of huddling against one edge.
    """
    if num_lines <= 1:
        return cell
    return max(cell, available / num_lines)


def _draw_horizontal(draw, lines, font, ascent, width, height, cell, fg) -> None:
    # Rows stack down the height (the cross-axis); spread them to fill it.
    avail = height - 2 * _MARGIN
    pitch = _line_pitch(avail, len(lines), cell)
    for i, line in enumerate(lines):
        # Top of this row's glyph cell, centered within its pitch slot.
        cell_top = _MARGIN + i * pitch + (pitch - cell) / 2
        # Draw on the baseline (anchor "ls") so glyphs keep their natural
        # vertical position within the cell instead of hugging the top.
        baseline = cell_top + ascent
        draw.text((_MARGIN, baseline), line, font=font, fill=fg, anchor="ls")


def _draw_vertical(draw, lines, font, ascent, width, height, cell, fg) -> None:
    # Columns run right-to-left across the width (the cross-axis); spread them
    # to fill it. The first line is the rightmost column.
    avail = width - 2 * _MARGIN
    pitch = _line_pitch(avail, len(lines), cell)
    for col, line in enumerate(lines):
        # Center of this column's slot, measured from the right edge.
        center = width - _MARGIN - (col + 0.5) * pitch
        x = center - cell / 2
        cell_top = float(_MARGIN)
        for ch in line:
            baseline = cell_top + ascent
            draw.text((x, baseline), ch, font=font, fill=fg, anchor="ls")
            cell_top += cell
