"""Optional OCR support with pluggable backends.

OCR is optional: if the backend for the selected method isn't installed, the
application still works and OCR features simply report as unavailable.

Two backends are available:

* **RapidOCR** (:mod:`mogura.ocr_rapidocr`) - onnxruntime based, uses the
  Japanese model from the ``PaddleOCR-JP-ONNX`` submodule.
* **Tesseract** (:mod:`mogura.ocr_tesseract`) - pytesseract wrapper around the
  Tesseract engine with the ``jpn`` / ``jpn_vert`` language data.

This module is a thin dispatcher: callers use :func:`is_available`,
:func:`unavailable_reason`, and :func:`recognize` exactly as before, and the
active backend is chosen by :func:`set_method` (wired to the user's setting).
"""

from __future__ import annotations

from typing import List

from PIL import Image

from . import ocr_rapidocr, ocr_tesseract

# Registry of method name -> backend module. Each backend exposes
# ``is_available()``, ``unavailable_reason()`` and ``recognize()``.
_BACKENDS = {
    "RapidOCR": ocr_rapidocr,
    "Tesseract": ocr_tesseract,
}

# Order to present methods in the UI.
METHODS = ["RapidOCR", "Tesseract"]

_DEFAULT_METHOD = "RapidOCR"
_current_method = _DEFAULT_METHOD


def available_methods() -> List[str]:
    """Return the OCR method names in display order."""
    return list(METHODS)


def set_method(name: str) -> None:
    """Select the active OCR backend by name (falls back to the default)."""
    global _current_method
    _current_method = name if name in _BACKENDS else _DEFAULT_METHOD


def get_method() -> str:
    """Return the name of the active OCR backend."""
    return _current_method


def _backend(method: str | None = None):
    return _BACKENDS.get(method or _current_method, _BACKENDS[_DEFAULT_METHOD])


def is_available(method: str | None = None) -> bool:
    """Return True if the (selected) backend can be used."""
    return _backend(method).is_available()


def unavailable_reason(method: str | None = None) -> str:
    """Human-readable reason the (selected) backend is unavailable."""
    return _backend(method).unavailable_reason()


def recognize(
    image: Image.Image, vertical: bool = False, method: str | None = None
) -> List[str]:
    """Run OCR on a cropped text block and return the detected lines.

    Dispatches to the active backend (or ``method`` if given). ``vertical``
    should match the block's orientation. Returns an empty list if nothing is
    detected. Raises if OCR is unavailable or the engine fails; callers should
    guard with :func:`is_available`.
    """
    return _backend(method).recognize(image, vertical=vertical)
