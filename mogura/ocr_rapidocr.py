"""RapidOCR backend (onnxruntime).

The dependency is optional: if ``rapidocr_onnxruntime`` is not installed, this
backend reports as unavailable and the application still works.

The pip package is ``rapidocr_onnxruntime``. Install it inside the project's
virtualenv, e.g.::

    ./venv/bin/pip install rapidocr_onnxruntime

Japanese recognition
---------------------
The stock RapidOCR models only recognize Chinese/English, so we point the
recognizer at the Japanese model produced by the ``PaddleOCR-JP-ONNX``
submodule (``japan_PP-OCRv3_rec_infer.onnx`` + ``japan_dict.txt``).

Multi-line blocks
-----------------
RapidOCR's text *detection* stage is tuned for horizontal Latin/Chinese layout
and does a poor job on the vertical, right-to-left columns typical of manga.
Since every block already comes with a known orientation and a tight bounding
box, we skip detection and instead segment the crop ourselves with simple
projection-profile analysis ("algorithmic line segmentation"):

* horizontal text -> split into rows, recognize each row as one line;
* vertical text   -> split into right-to-left columns; for each column, split
  into square character cells by pitch and lay them out left-to-right into a
  single horizontal strip the recognizer can read in one pass.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from PIL import Image

# Japanese recognition model + character dictionary, produced by the
# PaddleOCR-JP-ONNX submodule.
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
    the recognizer is pointed at it. Otherwise RapidOCR falls back to its
    bundled (Chinese/English) defaults.
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


# --------------------------------------------------------------------------
# Projection-profile segmentation helpers
# --------------------------------------------------------------------------
def _ink_profile(gray, axis):
    """Sum of ink (darkness) collapsed along ``axis``.

    ``gray`` is a HxW uint8 array of dark text on a light background.
    """
    return (255 - gray.astype("int32")).sum(axis=axis)


def _find_runs(profile, thr_ratio: float, min_run: int):
    """Return ``[start, end)`` spans where ``profile`` exceeds a threshold."""
    peak = float(profile.max()) if len(profile) else 0.0
    thr = peak * thr_ratio
    runs: List[List[int]] = []
    start: Optional[int] = None
    for i, value in enumerate(profile):
        if value > thr and start is None:
            start = i
        elif value <= thr and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(profile)])
    return [r for r in runs if r[1] - r[0] >= min_run]


def _merge_close(runs, max_gap: int):
    """Merge adjacent spans separated by a gap of at most ``max_gap``."""
    if not runs:
        return runs
    merged = [list(runs[0])]
    for start, end in runs[1:]:
        if start - merged[-1][1] <= max_gap:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def _tight_bounds(gray, axis) -> Optional[Tuple[int, int]]:
    """Return the ``[start, end)`` extent of ink along ``axis`` (or None)."""
    import numpy as np

    profile = _ink_profile(gray, axis)
    thr = float(profile.max()) * 0.04 if len(profile) else 0.0
    idx = np.where(profile > thr)[0]
    if len(idx) == 0:
        return None
    return int(idx[0]), int(idx[-1]) + 1


def _rec_line(image: Image.Image) -> str:
    """Recognize a single horizontal line image (detection disabled)."""
    import numpy as np

    engine = _get_engine()
    array = np.asarray(image.convert("RGB"))
    result, _elapsed = engine(array, use_det=False, use_cls=False)
    if not result:
        return ""
    return str(result[0][0])


def _recognize_vertical_column(column: Image.Image) -> str:
    """Recognize one vertical column by reassembling it into a line.

    The column is trimmed to its ink, split into roughly square character
    cells using the column width as the pitch (vertical Japanese advances
    about one em per glyph), and the cells are laid out left-to-right into a
    single horizontal strip which the recognizer reads in one pass. This gives
    the CRNN recognizer the character sequence context it expects, which is far
    more reliable than recognizing each glyph in isolation.
    """
    import numpy as np

    gray = np.asarray(column.convert("L"))
    bounds = _tight_bounds(gray, 1)
    if bounds is None:
        return ""
    column = column.crop((0, bounds[0], column.width, bounds[1]))

    width, height = column.size
    cell = max(1, width)
    count = max(1, int(round(height / cell)))

    strip = Image.new("RGB", (cell * count, cell), "white")
    for i in range(count):
        top = int(round(i * height / count))
        bottom = int(round((i + 1) * height / count))
        glyph = column.crop((0, top, width, bottom)).convert("RGB")
        glyph.thumbnail((cell, cell), Image.LANCZOS)
        square = Image.new("RGB", (cell, cell), "white")
        square.paste(
            glyph,
            ((cell - glyph.width) // 2, (cell - glyph.height) // 2),
        )
        strip.paste(square, (i * cell, 0))
    return _rec_line(strip)


def recognize(image: Image.Image, vertical: bool = False) -> List[str]:
    """Run OCR on a cropped text block and return the detected lines.

    ``vertical`` selects the segmentation strategy and should match the
    block's orientation. Returns an empty list if nothing is detected. Raises
    if OCR is unavailable or the engine fails; callers should guard with
    :func:`is_available`.
    """
    import numpy as np

    rgb = image.convert("RGB")
    gray = np.asarray(rgb.convert("L"))
    height, width = gray.shape

    lines: List[str] = []
    if vertical:
        # Split into columns, then recognize them right-to-left.
        col_runs = _find_runs(
            _ink_profile(gray, 0), thr_ratio=0.05, min_run=max(4, width // 20)
        )
        col_runs = _merge_close(col_runs, max_gap=max(3, width // 40))
        for x1, x2 in reversed(col_runs):
            column = rgb.crop((x1, 0, x2, height))
            text = _recognize_vertical_column(column)
            if text:
                lines.append(text)
    else:
        # Split into rows, recognize each as one horizontal line.
        row_runs = _find_runs(
            _ink_profile(gray, 1), thr_ratio=0.05, min_run=max(4, height // 20)
        )
        row_runs = _merge_close(row_runs, max_gap=max(3, height // 40))
        for y1, y2 in row_runs:
            row = rgb.crop((0, y1, width, y2))
            text = _rec_line(row)
            if text:
                lines.append(text)

    # Fallback: if segmentation found nothing, try the whole crop as one line.
    if not lines:
        text = _rec_line(rgb)
        if text:
            lines.append(text)
    return lines
