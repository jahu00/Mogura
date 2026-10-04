"""Optional OCR support via RapidOCR (onnxruntime backend).

The dependency is optional: if ``rapidocr_onnxruntime`` is not installed, the
application still works and OCR features simply report as unavailable.

The pip package is ``rapidocr_onnxruntime``. Install it inside the project's
virtualenv, e.g.::

    ./venv/bin/pip install rapidocr_onnxruntime
"""

from __future__ import annotations

import os
from typing import List, Optional

from PIL import Image

# Japanese recognition model + character dictionary, produced by the
# PaddleOCR-JP-ONNX submodule. The default RapidOCR models only recognize
# Chinese/English, so we point the recognizer at these instead.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JP_MODEL_DIR = os.path.join(
    _PROJECT_ROOT, "PaddleOCR-JP-ONNX", "models", "onnx"
)
_JP_REC_MODEL = os.path.join(_JP_MODEL_DIR, "japan_PP-OCRv3_rec_infer.onnx")
_JP_REC_KEYS = os.path.join(_JP_MODEL_DIR, "japan_dict.txt")

# The engine is relatively expensive to construct, so build it lazily and
# cache the single instance for reuse.
_engine = None
_import_error: Optional[str] = None


def is_available() -> bool:
    """Return True if the RapidOCR dependency can be imported."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on environment
        global _import_error
        _import_error = str(exc)
        return False
    return True


def unavailable_reason() -> str:
    """Human-readable reason OCR is unavailable (install hint)."""
    base = (
        "RapidOCR is not installed. Install it in the virtualenv with:\n"
        "    ./venv/bin/pip install rapidocr_onnxruntime"
    )
    if _import_error:
        return f"{base}\n\nImport error: {_import_error}"
    return base


def _get_engine():
    """Return a cached RapidOCR engine, importing on first use.

    When the Japanese model from the PaddleOCR-JP-ONNX submodule is present,
    the recognizer is pointed at it (the stock RapidOCR models only handle
    Chinese/English). Otherwise RapidOCR falls back to its bundled defaults.
    """
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        if os.path.exists(_JP_REC_MODEL) and os.path.exists(_JP_REC_KEYS):
            _engine = RapidOCR(
                rec_model_path=_JP_REC_MODEL,
                rec_keys_path=_JP_REC_KEYS,
            )
        else:
            _engine = RapidOCR()
    return _engine


def recognize(image: Image.Image) -> List[str]:
    """Run OCR on a PIL image and return the detected text lines.

    Returns an empty list if nothing is detected. Raises if OCR is
    unavailable or the engine fails; callers should guard with
    :func:`is_available`.
    """
    import numpy as np

    engine = _get_engine()
    rgb = image.convert("RGB")
    array = np.asarray(rgb)
    result, _elapsed = engine(array)
    if not result:
        return []
    # Each entry is [box, text, score]; keep the recognized text in order.
    return [str(entry[1]) for entry in result if len(entry) >= 2 and entry[1]]
