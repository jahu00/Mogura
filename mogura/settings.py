"""Persistent application settings.

Settings are stored as JSON in the user's config directory so they survive
between runs. The location follows platform conventions where practical and
falls back to ``~/.config/mogura`` otherwise.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

_APP_DIR_NAME = "mogura"
_SETTINGS_FILE = "settings.json"

# Default values for every known setting.
_DEFAULTS: Dict[str, Any] = {
    "auto_load_mokuro": True,
    # Automatically create empty mokuro data when opening images that have no
    # mokuro file, so the user can annotate right away.
    "auto_create_mokuro": True,
    # Directory of the most recently opened file, used to seed file dialogs.
    "last_dir": "",
    # Which OCR backend to use. Only "RapidOCR" exists for now.
    "ocr_method": "RapidOCR",
    # Minimum fraction (0..1) of the smaller box's area that must be covered
    # for two text items to count as overlapping. Overlap below this is
    # ignored (no warning marker).
    "overlap_threshold": 0.0,
    # Automatically run OCR on a newly added text item.
    "auto_ocr_on_add": False,
    # How the segmentation model feeds OCR when the Segmentation Mask view is
    # enabled. Either:
    #   "apply" - apply the mask to the image (whiten non-text, keep original
    #             text pixels). Best for the usual black-on-white text, but can
    #             hurt white-on-black text (the white text blends into the
    #             whitened background).
    #   "mask"  - OCR the raw segmentation mask (white text on black). Polarity
    #             independent, so it copes with white-on-black text.
    "ocr_segmentation_mode": "apply",
    # Reading-order layout for detected segmentation blocks. True orders blocks
    # right-to-left (manga); False orders them left-to-right (Western comics).
    "segmentation_rtl": True,
    # How the rendered-text overlay/preview lays out glyphs. Either:
    #   "simplified" - each glyph sits in a fixed square cell on a grid, and
    #                  lines are spread to fill the box. Predictable, but
    #                  ignores the font's natural proportional spacing.
    #   "default"    - the font's natural glyph advances flow each line, while
    #                  lines are still spread to fill the box. Closer to real
    #                  typography, but less uniform.
    "text_overlay_layout": "simplified",
    # Which bundled font the overlay/previews render with. Matches a key in
    # mogura.fonts.available_fonts(); "" (or an unknown value) falls back to a
    # system Japanese font.
    "text_overlay_font": "Noto Sans JP",
}


def _config_dir() -> str:
    """Return the directory where settings are stored, creating it if needed."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, _APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


class Settings:
    """In-memory settings backed by a JSON file on disk."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(_config_dir(), _SETTINGS_FILE)
        self._values: Dict[str, Any] = dict(_DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict):
                # Only keep known keys, falling back to defaults otherwise.
                for key in _DEFAULTS:
                    if key in stored:
                        self._values[key] = stored[key]
        except (OSError, ValueError):
            # Missing or corrupt file: keep defaults.
            pass

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2)
        except OSError:
            pass

    def get(self, key: str) -> Any:
        return self._values.get(key, _DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value
        self.save()
