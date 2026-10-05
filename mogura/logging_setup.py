"""Console logging setup and startup diagnostics.

A single :func:`configure` call wires up a console logger for the whole app.
:func:`log_system_checks` prints a short diagnostic report at startup covering
Python, the GUI toolkit, optional dependencies, and the OCR backends so issues
(like a missing Tesseract binary) are obvious from the console.

Modules obtain a logger with :func:`get_logger` and log through it; everything
flows to stderr via the root ``mogura`` logger configured here.
"""

from __future__ import annotations

import logging
import os
import platform
import sys

# Root logger name; module loggers are children (``mogura.app`` etc.).
_ROOT_NAME = "mogura"

_configured = False


def configure(level: int | str = logging.INFO) -> logging.Logger:
    """Configure and return the root ``mogura`` logger (idempotent).

    The level can be overridden via the ``MOGURA_LOG_LEVEL`` environment
    variable (e.g. ``DEBUG``), which takes precedence over ``level``.
    """
    global _configured
    root = logging.getLogger(_ROOT_NAME)

    env_level = os.environ.get("MOGURA_LOG_LEVEL")
    if env_level:
        level = env_level.upper()
    root.setLevel(level)

    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)
        # Don't propagate to the (unconfigured) Python root logger.
        root.propagate = False
        _configured = True

    return root


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``mogura`` root (e.g. ``mogura.app``)."""
    if name == _ROOT_NAME or name.startswith(_ROOT_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")


def _module_version(module_name: str) -> str | None:
    """Return a module's version string if it can be imported, else None."""
    try:
        module = __import__(module_name)
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        return None
    return getattr(module, "__version__", "unknown")


def log_system_checks(logger: logging.Logger | None = None) -> None:
    """Print a startup diagnostic report to the log.

    Covers the Python runtime, the Tk toolkit, optional dependencies and the
    availability of each OCR backend, so environment problems are visible at a
    glance.
    """
    log = logger or get_logger("startup")

    from . import __version__

    log.info("=== Mogura %s system checks ===", __version__)
    log.info(
        "Python %s on %s (%s)",
        platform.python_version(),
        platform.system(),
        platform.machine(),
    )

    # GUI toolkit.
    try:
        import tkinter

        log.info("Tk version: %s", tkinter.TkVersion)
    except Exception as exc:  # noqa: BLE001
        log.warning("tkinter unavailable: %s", exc)

    # Optional dependencies.
    for label, mod in (
        ("Pillow", "PIL"),
        ("numpy", "numpy"),
        ("tkinterdnd2", "tkinterdnd2"),
    ):
        version = _module_version(mod)
        if version is not None:
            log.info("%s: %s", label, version)
        else:
            log.info("%s: not installed", label)

    # OCR backends: report availability and the active method.
    from . import ocr

    for method in ocr.available_methods():
        if ocr.is_available(method):
            log.info("OCR backend '%s': available", method)
        else:
            # The reason is multi-line (install hints); keep it to one line.
            reason = ocr.unavailable_reason(method).splitlines()[0]
            log.info("OCR backend '%s': unavailable (%s)", method, reason)
    log.info("Active OCR method: %s", ocr.get_method())

    log.info("=== system checks complete ===")
