"""Bundled fonts available for the text overlay / previews.

The project ships Noto Sans JP and Noto Serif JP under ``<project>/fonts``.
This module maps human-readable names to concrete ``.ttf`` files so the
settings UI can offer a choice and the renderer can resolve the selection to a
path.

Each family ships several static weight files (Thin ... Black). The settings
UI lets the user pick both the family and the weight; the renderer resolves the
(name, weight) pair to a concrete file.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

# Directory holding the bundled fonts (``<project>/fonts``).
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"
)

# Ordered list of weight names, lightest to heaviest. Used to present weights
# in a sensible order and to pick a sane default.
_WEIGHT_ORDER = [
    "Thin",
    "ExtraLight",
    "Light",
    "Regular",
    "Medium",
    "SemiBold",
    "Bold",
    "ExtraBold",
    "Black",
]

# Default weight when none is selected (or the selection is unavailable).
DEFAULT_WEIGHT = "Regular"

# Human-readable family name -> (sub-directory, file prefix). The concrete file
# for a weight is ``<dir>/static/<prefix>-<Weight>.ttf``, relative to
# ``_FONT_DIR``.
_FAMILIES: Dict[str, tuple[str, str]] = {
    "Noto Sans JP": ("Noto_Sans_JP", "NotoSansJP"),
    "Noto Serif JP": ("Noto_Serif_JP", "NotoSerifJP"),
}


def _weight_rel_path(family: str, weight: str) -> Optional[str]:
    """Return the path (relative to ``_FONT_DIR``) for a family + weight."""
    spec = _FAMILIES.get(family)
    if spec is None:
        return None
    sub, prefix = spec
    return os.path.join(sub, "static", f"{prefix}-{weight}.ttf")


def available_fonts() -> List[str]:
    """Return the names of bundled families that have at least one weight."""
    names = []
    for name in _FAMILIES:
        if available_weights(name):
            names.append(name)
    return names


def available_weights(name: str) -> List[str]:
    """Return the weight names present on disk for a family, light to heavy."""
    weights = []
    for weight in _WEIGHT_ORDER:
        rel = _weight_rel_path(name, weight)
        if rel is not None and os.path.isfile(os.path.join(_FONT_DIR, rel)):
            weights.append(weight)
    return weights


def resolve_weight(name: str, weight: str) -> str:
    """Return a usable weight for ``name``, falling back sensibly.

    Prefers the requested ``weight``; otherwise the default weight if present;
    otherwise the first available weight; otherwise the requested value as-is.
    """
    available = available_weights(name)
    if weight in available:
        return weight
    if DEFAULT_WEIGHT in available:
        return DEFAULT_WEIGHT
    if available:
        return available[0]
    return weight


def font_path(name: str, weight: str = DEFAULT_WEIGHT) -> Optional[str]:
    """Return the absolute path for a bundled font name + weight, or ``None``."""
    rel = _weight_rel_path(name, resolve_weight(name, weight))
    if rel is None:
        return None
    path = os.path.join(_FONT_DIR, rel)
    return path if os.path.isfile(path) else None
