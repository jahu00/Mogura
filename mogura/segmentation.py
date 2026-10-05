"""Optional automatic text-block segmentation (comic-text-detector, ONNX).

Segmentation detects the text regions on a manga/comic page so their bounding
boxes can be added as mokuro text blocks automatically, instead of drawing each
one by hand.

It uses the `comic-text-detector <https://github.com/dmMaze/comic-text-detector>`_
model exported to ONNX, run through ``onnxruntime`` (already a dependency of the
RapidOCR backend). The model file is large (~90 MB) and is **not** bundled with
the application; it must be downloaded separately. Settings > Segmentation
offers a one-click download, or it can be fetched manually (see
:data:`MODEL_URL`) into :func:`model_path`.

The feature is fully optional: if ``onnxruntime`` is missing or the model file
has not been downloaded, segmentation simply reports as unavailable and the rest
of the application works unchanged.
"""

from __future__ import annotations

import os
from typing import Callable, List, Optional, Tuple

from PIL import Image

# Where the ONNX model lives (project ``models/`` directory) and where to get
# it. The release asset is published by the manga-image-translator project.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_DIR = os.path.join(_PROJECT_ROOT, "models")
_MODEL_FILENAME = "comictextdetector.pt.onnx"
_MODEL_PATH = os.path.join(_MODEL_DIR, _MODEL_FILENAME)

MODEL_URL = (
    "https://github.com/zyddnys/manga-image-translator/releases/download/"
    "beta-0.3/comictextdetector.pt.onnx"
)
# Expected download size in bytes, used only to sanity-check a finished
# download (the server reports the same via Content-Length).
_MODEL_SIZE = 94669756

# Inference parameters. The model takes a fixed 1024x1024 letterboxed image and
# emits YOLO-style block detections (``blk``) plus a per-pixel text mask
# (``seg``). We use the boxes for detection and, optionally, the mask to clean
# a crop before OCR.
_INPUT_SIZE = 1024
_CONF_THRESHOLD = 0.4
_NMS_IOU = 0.35
# Ignore boxes smaller than this many pixels on a side (in original-image
# coordinates) to drop stray noise detections.
_MIN_SIDE = 3
# Pixels whose text-mask probability is at least this are treated as text when
# cleaning a crop for OCR.
_MASK_THRESHOLD = 0.3

# The engine is relatively expensive to construct, so build it lazily and cache
# the single instance for reuse.
_session = None
_input_name: Optional[str] = None
_import_error: Optional[str] = None


def model_path() -> str:
    """Return the absolute path where the ONNX model is expected."""
    return _MODEL_PATH


def is_model_present() -> bool:
    """Return True if the model file has been downloaded."""
    return os.path.isfile(_MODEL_PATH) and os.path.getsize(_MODEL_PATH) > 0


def _onnxruntime_available() -> bool:
    """Return True if ``onnxruntime`` can be imported."""
    global _import_error
    try:
        import onnxruntime  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on environment
        _import_error = str(exc)
        return False
    return True


def is_runtime_available() -> bool:
    """Return True if the onnxruntime dependency can be imported."""
    return _onnxruntime_available()


def is_available() -> bool:
    """Return True if segmentation can run (runtime installed + model present)."""
    return _onnxruntime_available() and is_model_present()


def unavailable_reason() -> str:
    """Human-readable reason segmentation is unavailable."""
    if not _onnxruntime_available():
        base = (
            "onnxruntime is not installed. Install it in the virtualenv with:\n"
            "    ./venv/bin/pip install onnxruntime"
        )
        if _import_error:
            return f"{base}\n\nImport error: {_import_error}"
        return base
    if not is_model_present():
        return (
            "The segmentation model has not been downloaded yet. Use the "
            "Download button in Settings > Segmentation, or fetch it manually "
            f"from:\n    {MODEL_URL}\nand save it to:\n    {_MODEL_PATH}"
        )
    return ""


# --------------------------------------------------------------------------
# Model download
# --------------------------------------------------------------------------
def download_model(
    progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> None:
    """Download the ONNX model to :func:`model_path`.

    ``progress`` (if given) is called as ``progress(downloaded, total)`` as the
    download proceeds (``total`` may be ``0`` if the server omits the length).
    ``cancel`` (if given) is polled periodically; returning True aborts the
    download and removes the partial file. Raises on failure.
    """
    import urllib.request

    os.makedirs(_MODEL_DIR, exist_ok=True)
    tmp_path = _MODEL_PATH + ".part"

    try:
        request = urllib.request.Request(
            MODEL_URL, headers={"User-Agent": "Mogura"}
        )
        with urllib.request.urlopen(request) as response:  # noqa: S310
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            with open(tmp_path, "wb") as handle:
                while True:
                    if cancel is not None and cancel():
                        raise RuntimeError("Download cancelled.")
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(downloaded, total)
    except Exception:
        # Clean up a partial file so a later retry starts fresh.
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    os.replace(tmp_path, _MODEL_PATH)
    # Reset any cached session so the freshly downloaded model is picked up.
    reset()


def reset() -> None:
    """Drop the cached inference session (e.g. after (re)downloading)."""
    global _session, _input_name
    _session = None
    _input_name = None


def _get_session():
    """Return a cached onnxruntime session, building it on first use."""
    global _session, _input_name
    if _session is None:
        import onnxruntime as ort

        _session = ort.InferenceSession(
            _MODEL_PATH, providers=["CPUExecutionProvider"]
        )
        _input_name = _session.get_inputs()[0].name
    return _session


# --------------------------------------------------------------------------
# Inference helpers
# --------------------------------------------------------------------------
def _letterbox(image: Image.Image, size: int) -> Tuple["object", float]:
    """Resize ``image`` to fit a ``size`` x ``size`` canvas, padding bottom/right.

    Returns the padded RGB array and the scale ratio applied (so detections can
    be mapped back to original-image coordinates).
    """
    import numpy as np

    width, height = image.size
    ratio = min(size / width, size / height)
    new_w = int(round(width * ratio))
    new_h = int(round(height * ratio))
    resized = image.convert("RGB").resize((new_w, new_h), Image.BILINEAR)
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    canvas[:new_h, :new_w] = np.asarray(resized)
    return canvas, ratio


def _nms(boxes, scores, iou_threshold: float) -> List[int]:
    """Plain NumPy non-maximum suppression; returns kept indices."""
    import numpy as np

    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_threshold]
    return keep


def _infer(image: Image.Image):
    """Run the model once, returning ``(blk, mask, ratio)``.

    ``blk`` is the raw ``(N, 7)`` detection array, ``mask`` is the per-pixel
    text probability map resized back to the original image size (a float32
    HxW array in ``0..1``), and ``ratio`` is the letterbox scale factor.
    """
    import numpy as np

    session = _get_session()
    width, height = image.size
    ratio = min(_INPUT_SIZE / width, _INPUT_SIZE / height)
    new_w = int(round(width * ratio))
    new_h = int(round(height * ratio))
    canvas, _ = _letterbox(image, _INPUT_SIZE)
    blob = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0

    blk, seg, _det = session.run(None, {_input_name: blob})

    # Crop the mask to the non-padded region and resize to the original image.
    mask = seg[0, 0][:new_h, :new_w]
    mask_img = Image.fromarray((mask * 255).astype(np.uint8)).resize(
        (width, height), Image.BILINEAR
    )
    mask = np.asarray(mask_img).astype(np.float32) / 255.0
    return blk, mask, ratio


def _decode_boxes(blk, ratio, size) -> List[List[int]]:
    """Decode the raw ``blk`` detections into sorted integer boxes."""
    import numpy as np

    pred = blk[0]  # (N, 7): cx, cy, w, h, obj_conf, cls0, cls1
    obj = pred[:, 4]
    pred = pred[obj > _CONF_THRESHOLD]
    if len(pred) == 0:
        return []

    cx, cy, bw, bh = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    boxes = np.stack(
        [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1
    )
    scores = pred[:, 4] * pred[:, 5:].max(axis=1)

    keep = _nms(boxes, scores, _NMS_IOU)
    boxes = boxes[keep]

    # Map letterboxed coordinates back onto the original image and clamp.
    boxes = boxes / ratio
    width, height = size
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, width)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, height)

    result: List[List[int]] = []
    for x1, y1, x2, y2 in boxes:
        if (x2 - x1) < _MIN_SIDE or (y2 - y1) < _MIN_SIDE:
            continue
        result.append([int(round(x1)), int(round(y1)),
                       int(round(x2)), int(round(y2))])

    # Reading order: top-to-bottom, then left-to-right.
    result.sort(key=lambda b: (b[1], b[0]))
    return result


def detect(image: Image.Image) -> List[List[int]]:
    """Detect text-block bounding boxes on ``image``.

    Returns a list of ``[x1, y1, x2, y2]`` integer boxes in the coordinate
    space of the input image, sorted top-to-bottom then left-to-right. Returns
    an empty list if nothing is detected. Raises if segmentation is unavailable
    or the engine fails; callers should guard with :func:`is_available`.
    """
    blk, _mask, ratio = _infer(image)
    return _decode_boxes(blk, ratio, image.size)


def _clean_with_mask(image: Image.Image, mask) -> Image.Image:
    """Return ``image`` with everything but detected text whitened out.

    ``mask`` is a float32 text-probability map the same size as ``image``.
    Pixels below :data:`_MASK_THRESHOLD` are forced to white, leaving the dark
    text strokes on a clean background so the recognizer isn't distracted by
    artwork or screentones. If the mask is essentially empty (no text found)
    the original image is returned unchanged.
    """
    import numpy as np

    text = mask >= _MASK_THRESHOLD
    if not text.any():
        return image.convert("RGB")
    rgb = np.asarray(image.convert("RGB")).copy()
    rgb[~text] = 255
    return Image.fromarray(rgb)


def clean_crop(image: Image.Image, box=None) -> Optional[Image.Image]:
    """Return a cleaned-up version of ``image`` (or a sub-region of it).

    Runs the model over ``image``, uses the text mask to whiten everything
    that isn't text, and returns the result. If ``box`` (``[x1, y1, x2, y2]``
    in ``image`` coordinates) is given, only that region is returned. Returns
    ``None`` if the region is empty. Raises if segmentation is unavailable or
    the engine fails; callers should guard with :func:`is_available`.
    """
    _blk, mask, _ratio = _infer(image)
    cleaned = _clean_with_mask(image, mask)
    if box is None:
        return cleaned
    width, height = cleaned.size
    x1, y1, x2, y2 = (list(box) + [0, 0, 0, 0])[:4]
    x1 = max(0, min(width, int(x1))); x2 = max(0, min(width, int(x2)))
    y1 = max(0, min(height, int(y1))); y2 = max(0, min(height, int(y2)))
    if x2 - x1 < 1 or y2 - y1 < 1:
        return None
    return cleaned.crop((x1, y1, x2, y2))


def detect_and_clean(image: Image.Image):
    """Return ``(boxes, cleaned_image)`` from a single inference pass.

    Convenience for whole-page segmentation that also wants the mask-cleaned
    page (so each detected block can be OCR'd from the clean image without
    re-running the model per block). ``boxes`` is as from :func:`detect`;
    ``cleaned_image`` is the full page with non-text whitened out.
    """
    blk, mask, ratio = _infer(image)
    boxes = _decode_boxes(blk, ratio, image.size)
    cleaned = _clean_with_mask(image, mask)
    return boxes, cleaned
