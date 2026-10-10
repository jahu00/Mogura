"""Approximate rendering of mokuro text blocks to a PIL image.

Given the text lines of a block and its orientation, this produces a simple
image that mimics how the text is laid out (horizontal rows, or vertical
columns running right-to-left as in Japanese vertical writing). It is meant as
a rough visual comparison against the original cropped page region, not a
faithful typographic reproduction.

Two layouts are offered (selectable via the Editor settings section):

* ``"simplified"`` - every glyph occupies a fixed square cell on a grid, so
  the text reads as an even matrix of characters. Predictable and tidy, but it
  ignores the font's natural proportional spacing.
* ``"default"`` - glyphs flow along each line using the font's own advances
  (proportional horizontal spacing, natural vertical rhythm). Closer to real
  typography. In both layouts the lines/columns are spread to fill the box.

Callers may pass ``layout=`` explicitly; otherwise the module-level default
(set from settings via :func:`set_default_layout`) is used.
"""

from __future__ import annotations

import os
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

from . import fonts as _fonts

# Candidate Japanese-capable system fonts, used only as a fallback when no
# bundled font has been selected (or the selected one is missing).
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/ipafont-mincho/ipam.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-mincho.ttf",
]

_font_path_cache: Optional[str] = None

# Absolute path of the user-selected bundled font (set via set_default_font).
# ``None`` means fall back to a system Japanese font.
_selected_font_path: Optional[str] = None

# Layout identifiers.
LAYOUT_SIMPLIFIED = "simplified"
LAYOUT_DEFAULT = "default"

# Module-level default layout, applied when a caller doesn't pass ``layout``.
# Kept here (rather than threaded through every dialog) so the various preview
# widgets pick up the user's choice without each needing a Settings handle.
_default_layout = LAYOUT_SIMPLIFIED

# Multiplier applied to the fitted glyph size (1.0 == natural box-fitting
# size). Larger values enlarge the glyphs; most visible with the simplified
# fixed-grid layout, where the grid pitch stays put while characters grow.
_SCALE_MIN = 0.5
_SCALE_MAX = 3.0
_font_scale = 1.0


def set_default_layout(layout: str) -> None:
    """Set the layout used when callers don't pass one explicitly."""
    global _default_layout
    _default_layout = LAYOUT_DEFAULT if layout == LAYOUT_DEFAULT else LAYOUT_SIMPLIFIED


def set_default_font(name: str, weight: str = _fonts.DEFAULT_WEIGHT) -> None:
    """Select the bundled font (by name + weight) used for rendering.

    An unknown or empty ``name`` clears the selection, falling back to a system
    Japanese font. Cached fonts are invalidated so the change takes effect.
    """
    global _selected_font_path
    _selected_font_path = _fonts.font_path(name, weight) if name else None
    _font_cache.clear()


def set_default_font_scale(scale: float) -> None:
    """Set the glyph-size multiplier, clamped to a sensible range."""
    global _font_scale
    try:
        value = float(scale)
    except (TypeError, ValueError):
        value = 1.0
    _font_scale = max(_SCALE_MIN, min(_SCALE_MAX, value))


def _resolve_layout(layout: Optional[str]) -> str:
    if layout is None:
        return _default_layout
    return LAYOUT_DEFAULT if layout == LAYOUT_DEFAULT else LAYOUT_SIMPLIFIED


# Cache of loaded truetype fonts, keyed by (path, size).
_font_cache: dict = {}


def _font_path() -> Optional[str]:
    # A user-selected bundled font takes precedence over system candidates.
    if _selected_font_path is not None:
        return _selected_font_path
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
        key = (path, size)
        cached = _font_cache.get(key)
        if cached is not None:
            return cached
        try:
            font = ImageFont.truetype(path, size)
            _font_cache[key] = font
            return font
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
    point = max(6, int(cell * 100 / em * _font_scale))
    font = _load_font(point)
    try:
        asc2, _desc2 = font.getmetrics()
    except Exception:  # noqa: BLE001
        asc2 = int(point * asc / em)
    return font, asc2


def _fit_font_default(lines: List[str], vertical: bool, width: float, height: float):
    """Size a font for the *default* layout, honouring natural glyph advances.

    Returns ``(font, ascent, line_height)`` where ``line_height`` is the full
    em (ascent+descent) of the chosen font -- used both as the per-row height
    (horizontal) and the per-character advance (vertical).

    The font is chosen so the text roughly fills the box in both axes: lines
    are capped to fit the cross-axis, and the longest line (its natural pixel
    width, horizontal) or column (its character count, vertical) is capped to
    fit the main axis.
    """
    width = max(6.0, width)
    height = max(6.0, height)
    num_lines = max(1, len(lines))

    probe = _load_font(100)
    try:
        asc, desc = probe.getmetrics()
    except Exception:  # noqa: BLE001
        asc, desc = 80, 20
    em = asc + desc or 100

    if vertical:
        # Columns span the width; characters stack down the height.
        max_len = max((len(ln) for ln in lines), default=1) or 1
        point_w = (width / num_lines) * 100 / em
        point_h = (height / max_len) * 100 / em
        point = min(point_w, point_h)
    else:
        # Rows stack down the height; glyphs run along the width naturally.
        max_width = 1.0
        for ln in lines:
            if not ln:
                continue
            try:
                w = probe.getlength(ln)
            except Exception:  # noqa: BLE001
                w = len(ln) * em
            if w > max_width:
                max_width = w
        point_h = (height / num_lines) * 100 / em
        point_w = width * 100 / max_width if max_width > 0 else point_h
        point = min(point_h, point_w)

    point = max(6, int(point * _font_scale))
    font = _load_font(point)
    try:
        asc2, desc2 = font.getmetrics()
    except Exception:  # noqa: BLE001
        asc2 = int(point * asc / em)
        desc2 = int(point * desc / em)
    line_height = max(6.0, float(asc2 + desc2))
    return font, asc2, line_height


def render_text(
    lines: List[str],
    vertical: bool,
    width: int,
    height: int,
    bg: str = "#ffffff",
    fg: str = "#000000",
    layout: Optional[str] = None,
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
    _render_onto(image, draw, lines, vertical, width, height, fg, _resolve_layout(layout))
    return image


def render_text_rgba(
    lines: List[str],
    vertical: bool,
    width: int,
    height: int,
    fg: str = "#ff0000",
    layout: Optional[str] = None,
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
    _render_onto(image, draw, lines, vertical, width, height, fg, _resolve_layout(layout))
    return image


def overlay_render_on_image(
    original: Image.Image,
    lines: List[str],
    vertical: bool,
    fg: str = "#e53935",
    layout: Optional[str] = None,
) -> Image.Image:
    """Overlay an approximate text render (in ``fg``) on ``original``.

    The render is sized to the original's dimensions and alpha-composited so
    the source art shows through beneath the coloured text.
    """
    base = original.convert("RGBA")
    w, h = base.size
    overlay = render_text_rgba(lines, vertical, w, h, fg=fg, layout=layout)
    return Image.alpha_composite(base, overlay).convert("RGB")


# A small margin inset applied once to the whole render (not per glyph).
_MARGIN = 2

# Characters that are rotated 90° clockwise when set in vertical writing.
# In real vertical typography these are substituted with dedicated vertical
# presentation forms (via the font's ``vert`` OpenType feature); since PIL has
# no access to that, rotating the horizontal glyph is a close approximation.
#
#   * long vowel marks / dashes / hyphens / wave dashes -> become vertical bars
#   * horizontal ellipses -> become a vertical stack of dots
#   * paired brackets and corner quotation marks -> rotate to their vert forms
_VERTICAL_ROTATE = set(
    "ー"                       # KATAKANA-HIRAGANA prolonged sound mark
    "ｰ"                       # halfwidth prolonged sound mark
    "－‐‑‒–—―"                 # fullwidth hyphen-minus, hyphens, dashes
    "～〜"                     # wave dashes
    "…‥"                      # horizontal / two-dot ellipses
    "（）｛｝〔〕［］【】〈〉《》「」『』〖〗〘〙〚〛｟｠"  # brackets / corner quotes
)


def _draw_rotated_glyph(image, ch, font, cx, cy, fg) -> None:
    """Draw ``ch`` rotated 90° clockwise, centred at ``(cx, cy)`` on ``image``.

    The glyph is rendered to a transparent tile, rotated, then pasted using its
    own alpha as the mask so it composites cleanly over whatever is beneath.
    """
    try:
        bbox = font.getbbox(ch)
    except Exception:  # noqa: BLE001
        size = getattr(font, "size", 16)
        bbox = (0, 0, size, size)
    gw = max(1, bbox[2] - bbox[0])
    gh = max(1, bbox[3] - bbox[1])
    pad = 2
    tile = Image.new("RGBA", (gw + 2 * pad, gh + 2 * pad), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    td.text((pad - bbox[0], pad - bbox[1]), ch, font=font, fill=fg)
    # PIL rotates counter-clockwise for positive angles; -90 == clockwise.
    tile = tile.rotate(-90, expand=True)
    tw, th = tile.size
    image.paste(tile, (int(cx - tw / 2), int(cy - th / 2)), tile)


def _render_onto(image, draw, lines, vertical, width, height, fg, layout) -> None:
    """Dispatch to the chosen layout's drawing routine."""
    if layout == LAYOUT_DEFAULT:
        font, ascent, line_h = _fit_font_default(lines, vertical, width, height)
        if vertical:
            _draw_vertical_default(image, draw, lines, font, ascent, width, height, line_h, fg)
        else:
            _draw_horizontal_default(draw, lines, font, ascent, width, height, line_h, fg)
        return

    # Simplified: fixed square cells on a grid.
    num_lines = len(lines)
    max_len = max((len(ln) for ln in lines), default=1) or 1
    if vertical:
        cell = min(width / num_lines, height / max_len)
    else:
        cell = min(height / num_lines, width / max_len)
    cell = max(6.0, cell)
    font, ascent = _fit_font(cell)
    if vertical:
        _draw_vertical(image, draw, lines, font, ascent, width, height, cell, fg)
    else:
        _draw_horizontal(draw, lines, font, ascent, width, height, cell, fg)


def _line_pitch(available: float, num_lines: int, cell: float) -> float:
    """Spacing between lines so they spread across the ``available`` extent.

    Each line advances by at least ``cell`` (so lines never overlap), but when
    there is spare room the lines are spread out to fill the cross-axis instead
    of huddling against one edge.
    """
    if num_lines <= 1:
        return cell
    return max(cell, available / num_lines)


# --------------------------------------------------------------- simplified
def _draw_horizontal(draw, lines, font, ascent, width, height, cell, fg) -> None:
    # Rows stack down the height (the cross-axis); spread them to fill it.
    # Glyphs step along the width by a fixed ``cell`` so the row forms a true
    # square grid (mirroring _draw_vertical) rather than flowing with the
    # font's natural proportional advances -- that keeps the drawn width equal
    # to ``max_len * cell``, matching the sizing assumption in _render_onto.
    avail = height - 2 * _MARGIN
    pitch = _line_pitch(avail, len(lines), cell)
    for i, line in enumerate(lines):
        # Top of this row's glyph cell, centered within its pitch slot.
        cell_top = _MARGIN + i * pitch + (pitch - cell) / 2
        # Draw on the baseline (anchor "ls" -> middle/baseline below) so glyphs
        # keep their natural vertical position within the cell instead of
        # hugging the top.
        baseline = cell_top + ascent
        # Center of the first glyph's cell, measured from the left edge.
        center = _MARGIN + cell / 2
        for ch in line:
            draw.text((center, baseline), ch, font=font, fill=fg, anchor="ms")
            center += cell


def _draw_vertical(image, draw, lines, font, ascent, width, height, cell, fg) -> None:
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
            if ch in _VERTICAL_ROTATE:
                _draw_rotated_glyph(image, ch, font, center, cell_top + cell / 2, fg)
            else:
                baseline = cell_top + ascent
                draw.text((x, baseline), ch, font=font, fill=fg, anchor="ls")
            cell_top += cell


# ------------------------------------------------------------------ default
def _draw_horizontal_default(draw, lines, font, ascent, width, height, line_h, fg) -> None:
    # Rows stack down the height (spread to fill it); each line flows along the
    # width using the font's natural proportional advances.
    avail = height - 2 * _MARGIN
    pitch = _line_pitch(avail, len(lines), line_h)
    for i, line in enumerate(lines):
        cell_top = _MARGIN + i * pitch + (pitch - line_h) / 2
        baseline = cell_top + ascent
        draw.text((_MARGIN, baseline), line, font=font, fill=fg, anchor="ls")


def _draw_vertical_default(image, draw, lines, font, ascent, width, height, line_h, fg) -> None:
    # Columns run right-to-left (spread across the width); characters stack down
    # each column advancing by the font's natural line height.
    avail = width - 2 * _MARGIN
    pitch = _line_pitch(avail, len(lines), line_h)
    for col, line in enumerate(lines):
        center = width - _MARGIN - (col + 0.5) * pitch
        cell_top = float(_MARGIN)
        for ch in line:
            if ch in _VERTICAL_ROTATE:
                _draw_rotated_glyph(image, ch, font, center, cell_top + line_h / 2, fg)
            else:
                baseline = cell_top + ascent
                # Center each glyph horizontally within its column slot.
                draw.text((center, baseline), ch, font=font, fill=fg, anchor="ms")
            cell_top += line_h
