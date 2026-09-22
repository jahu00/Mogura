"""Icon loading and caching.

Icons live as PNG files under the project's ``icons/`` directory. They are
high-resolution (512px) source images; this module loads them, resizes to the
requested pixel size with Pillow, and caches the resulting ``PhotoImage``
objects (which must be kept referenced to stay visible in Tk).
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

from PIL import Image, ImageTk

# Directory holding the PNG icons (``<project>/icons``).
_ICON_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons"
)

# Cache keyed by (name, size) so repeated requests reuse the same PhotoImage.
_cache: Dict[Tuple[str, int], ImageTk.PhotoImage] = {}


def icon_path(name: str) -> str:
    return os.path.join(_ICON_DIR, f"{name}.png")


def has_icon(name: str) -> bool:
    return os.path.isfile(icon_path(name))


def get_icon(name: str, size: int = 20) -> Optional[ImageTk.PhotoImage]:
    """Return a cached ``PhotoImage`` for ``name`` at the given pixel size.

    Returns ``None`` if the icon file does not exist, so callers can fall back
    to text labels.
    """
    key = (name, size)
    if key in _cache:
        return _cache[key]
    path = icon_path(name)
    if not os.path.isfile(path):
        return None
    image = Image.open(path).convert("RGBA")
    image = image.resize((size, size), Image.LANCZOS)
    photo = ImageTk.PhotoImage(image)
    _cache[key] = photo
    return photo
