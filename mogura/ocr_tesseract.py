"""Tesseract backend (pytesseract).

Optional dependency: if ``pytesseract`` isn't installed, or the Tesseract
binary / Japanese language data isn't present, this backend reports as
unavailable and the application still works.

Install the Python wrapper in the virtualenv and the Tesseract engine plus the
Japanese language packs via the system package manager, e.g.::

    ./venv/bin/pip install pytesseract
    sudo apt install tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert

Japanese recognition
---------------------
Tesseract ships dedicated Japanese models: ``jpn`` for horizontal text and
``jpn_vert`` for vertical text. We pick the language to match the block's
orientation and let Tesseract handle layout within the crop, so no custom
segmentation is needed.
"""

from __future__ import annotations

from typing import List, Optional

from PIL import Image

# Language codes for the two writing directions.
_LANG_HORIZONTAL = "jpn"
_LANG_VERTICAL = "jpn_vert"

_import_error: Optional[str] = None


def is_available() -> bool:
    """Return True if pytesseract, the binary, and jpn data are all present."""
    global _import_error
    try:
        import pytesseract
    except Exception as exc:  # pragma: no cover - depends on environment
        _import_error = str(exc)
        return False
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # pragma: no cover - binary missing/misconfigured
        _import_error = str(exc)
        return False
    if _LANG_HORIZONTAL not in langs:
        _import_error = (
            "Tesseract is installed but the Japanese language data "
            "('jpn') was not found."
        )
        return False
    return True


def unavailable_reason() -> str:
    """Human-readable reason this backend is unavailable (install hint)."""
    base = (
        "Tesseract OCR is not available. Install the Python wrapper and the "
        "Tesseract engine with Japanese data:\n"
        "    ./venv/bin/pip install pytesseract\n"
        "    sudo apt install tesseract-ocr tesseract-ocr-jpn "
        "tesseract-ocr-jpn-vert"
    )
    if _import_error:
        return f"{base}\n\nDetails: {_import_error}"
    return base


def recognize(image: Image.Image, vertical: bool = False) -> List[str]:
    """Run Tesseract on a cropped text block and return the detected lines.

    ``vertical`` selects the Japanese language model (``jpn_vert`` vs ``jpn``)
    so Tesseract reads the crop in the right direction. Returns an empty list
    if nothing is detected. Raises if the engine fails; callers should guard
    with :func:`is_available`.
    """
    import pytesseract

    lang = _LANG_HORIZONTAL
    if vertical:
        # Fall back to horizontal data if the vertical pack isn't installed.
        try:
            if _LANG_VERTICAL in set(pytesseract.get_languages(config="")):
                lang = _LANG_VERTICAL
        except Exception:  # noqa: BLE001 - keep horizontal on any failure
            pass

    rgb = image.convert("RGB")
    # PSM 5 = assume a single uniform block of vertically aligned text;
    # PSM 6 = assume a single uniform block of (horizontal) text.
    psm = 5 if vertical else 6
    config = f"--psm {psm}"
    text = pytesseract.image_to_string(rgb, lang=lang, config=config)

    lines: List[str] = []
    for raw in text.splitlines():
        # Tesseract tends to pad Japanese output with spaces between glyphs.
        stripped = raw.replace(" ", "").replace("\u3000", "").strip()
        if stripped:
            lines.append(stripped)
    return lines
