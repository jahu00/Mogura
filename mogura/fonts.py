"""Bundled fonts available for the text overlay / previews.

The project ships Noto Sans JP and Noto Serif JP under ``<project>/fonts``.
This module maps human-readable names to concrete ``.ttf`` files so the
settings UI can offer a choice and the renderer can resolve the selection to a
path.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

# Directory holding the bundled fonts (``<project>/fonts``).
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"
)

# Human-readable name -> path, relative to ``_FONT_DIR``. Static (single
# weight) files are used because Pillow handles plain TrueType most reliably.
_FONTS: Dict[str, str] = {
    "Noto Sans JP": os.path.join(
        "Noto_Sans_JP", "static", "NotoSansJP-Regular.ttf"
    ),
    "Noto Serif JP": os.path.join(
        "Noto_Serif_JP", "static", "NotoSerifJP-Regular.ttf"
    ),
}


def available_fonts() -> List[str]:
    """Return the names of bundled fonts whose files are present on disk."""
    names = []
    for name, rel in _FONTS.items():
        if os.path.isfile(os.path.join(_FONT_DIR, rel)):
            names.append(name)
    return names


def font_path(name: str) -> Optional[str]:
    """Return the absolute path for a bundled font name, or ``None``."""
    rel = _FONTS.get(name)
    if rel is None:
        return None
    path = os.path.join(_FONT_DIR, rel)
    return path if os.path.isfile(path) else None
