"""Batch-processing wizard: segment (and optionally OCR) every page.

This window drives the whole document through automatic segmentation, adding a
mokuro text block for each detected region on every page, and optionally running
OCR on each one. It is independent of the per-run global settings: the OCR
engine and whether to OCR from segmentation-cleaned imagery are chosen here.

Options
-------
* **Skip pages that already have text items** - leave annotated pages untouched.
* **When a page already has text** (only when not skipping) - either *Overwrite*
  (clear the page and add all detected blocks anew) or *Skip overlapping* (add
  only detected blocks that do not overlap an existing item, reusing the app's
  overlap threshold).
* **Run OCR** - fill each new block's text using the chosen engine.
* **OCR source** - recognize from the original image or from a
  segmentation-cleaned image (non-text whitened out).

The heavy work runs on a background thread so the progress bar stays live and
the operation can be cancelled; the dialog is modal so the document is not
edited elsewhere while it runs.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from . import ocr, segmentation
from .mokuro import MokuroPage, TextBlock

# Values for the "existing text" behaviour dropdown.
_MODE_OVERWRITE = "Overwrite (replace all text on the page)"
_MODE_SKIP_OVERLAP = "Add only non-overlapping blocks"
_EXISTING_MODES = [_MODE_OVERWRITE, _MODE_SKIP_OVERLAP]

# OCR source choices.
_SRC_ORIGINAL = "Original image"
_SRC_SEGMENTED = "Segmentation-cleaned image"
_OCR_SOURCES = [_SRC_ORIGINAL, _SRC_SEGMENTED]


class WizardDialog(tk.Toplevel):
    """Modal wizard for automatic whole-document processing."""

    def __init__(self, master, app):
        super().__init__(master)
        self.title("Auto-process document")
        self.transient(master)
        self.minsize(480, 420)

        self._app = app
        self._settings = app._settings

        # Background-processing state shared with the UI thread.
        self._thread: Optional[threading.Thread] = None
        self._cancel = False
        self._running = False
        self._progress_state = {"done": 0, "total": 0, "page": 0}
        self._result = None  # (pages_processed, blocks_added, ocr_count)
        self._error: Optional[str] = None

        self._build_body()
        self._build_buttons()

        self.bind("<Escape>", lambda _e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()

        self._sync_enabled_state()

    # ------------------------------------------------------------------ body
    def _build_body(self) -> None:
        body = tk.Frame(self, padx=12, pady=12)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text="Automatically segment every page and add a text block for "
            "each detected region.",
            anchor=tk.W,
            wraplength=440,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 10))

        # Skip pages that already have text.
        self._skip_existing_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            body,
            text="Skip pages that already have text items",
            variable=self._skip_existing_var,
            anchor=tk.W,
            command=self._sync_enabled_state,
        ).pack(fill=tk.X)

        # What to do with pages that already have text (when not skipping).
        existing = tk.Frame(body)
        existing.pack(fill=tk.X, pady=(6, 0))
        self._existing_label = tk.Label(
            existing, text="When a page already has text:", anchor=tk.W
        )
        self._existing_label.pack(side=tk.LEFT)
        self._existing_mode_var = tk.StringVar(value=_MODE_SKIP_OVERLAP)
        self._existing_combo = ttk.Combobox(
            existing,
            textvariable=self._existing_mode_var,
            values=_EXISTING_MODES,
            state="readonly",
            width=36,
        )
        self._existing_combo.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(body, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=12)

        # Run OCR toggle.
        self._run_ocr_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            body,
            text="Run OCR on each new text block",
            variable=self._run_ocr_var,
            anchor=tk.W,
            command=self._sync_enabled_state,
        ).pack(fill=tk.X)

        # OCR engine selection (independent of the global setting).
        engine = tk.Frame(body)
        engine.pack(fill=tk.X, pady=(6, 0))
        self._engine_label = tk.Label(
            engine, text="OCR engine:", anchor=tk.W, width=16
        )
        self._engine_label.pack(side=tk.LEFT)
        methods = ocr.available_methods()
        self._engine_var = tk.StringVar(value=ocr.get_method())
        if self._engine_var.get() not in methods and methods:
            self._engine_var.set(methods[0])
        self._engine_combo = ttk.Combobox(
            engine,
            textvariable=self._engine_var,
            values=methods,
            state="readonly",
            width=20,
        )
        self._engine_combo.pack(side=tk.LEFT, padx=(6, 0))

        # OCR source (original vs segmentation-cleaned).
        src = tk.Frame(body)
        src.pack(fill=tk.X, pady=(6, 0))
        self._src_label = tk.Label(
            src, text="OCR source:", anchor=tk.W, width=16
        )
        self._src_label.pack(side=tk.LEFT)
        default_src = (
            _SRC_SEGMENTED
            if getattr(self._app, "_mask_mode", False)
            else _SRC_ORIGINAL
        )
        self._src_var = tk.StringVar(value=default_src)
        self._src_combo = ttk.Combobox(
            src,
            textvariable=self._src_var,
            values=_OCR_SOURCES,
            state="readonly",
            width=28,
        )
        self._src_combo.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Separator(body, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=12)

        # Progress.
        self._progress = ttk.Progressbar(
            body, orient=tk.HORIZONTAL, mode="determinate"
        )
        self._progress.pack(fill=tk.X)
        self._progress_label = tk.Label(body, text="", anchor=tk.W, fg="#666666")
        self._progress_label.pack(fill=tk.X, pady=(4, 0))

    def _build_buttons(self) -> None:
        btns = tk.Frame(self, padx=12, pady=12)
        btns.pack(side=tk.BOTTOM, fill=tk.X)
        self._cancel_btn = tk.Button(
            btns, text="Cancel", command=self._on_close
        )
        self._cancel_btn.pack(side=tk.RIGHT)
        self._start_btn = tk.Button(
            btns, text="Start", command=self._on_start, default=tk.ACTIVE
        )
        self._start_btn.pack(side=tk.RIGHT, padx=(0, 8))

    # --------------------------------------------------------------- state
    def _sync_enabled_state(self) -> None:
        """Enable/disable dependent controls based on the current choices."""
        if self._running:
            return
        # Existing-text mode only matters when not skipping annotated pages.
        skipping = self._skip_existing_var.get()
        state = tk.DISABLED if skipping else "readonly"
        self._existing_combo.config(state=state)
        self._existing_label.config(fg="#999999" if skipping else "#000000")

        # OCR engine/source only matter when OCR is enabled.
        ocr_on = self._run_ocr_var.get()
        combo_state = "readonly" if ocr_on else tk.DISABLED
        fg = "#000000" if ocr_on else "#999999"
        self._engine_combo.config(state=combo_state)
        self._src_combo.config(state=combo_state)
        self._engine_label.config(fg=fg)
        self._src_label.config(fg=fg)

    # --------------------------------------------------------------- start
    def _on_start(self) -> None:
        app = self._app
        if app._archive is None:
            messagebox.showinfo(
                "Nothing to process", "Open a document first.", parent=self
            )
            return
        if not segmentation.is_available():
            messagebox.showinfo(
                "Segmentation unavailable",
                segmentation.unavailable_reason(),
                parent=self,
            )
            return

        run_ocr = self._run_ocr_var.get()
        engine = self._engine_var.get()
        use_seg = self._src_var.get() == _SRC_SEGMENTED
        if run_ocr and not ocr.is_available(engine):
            messagebox.showinfo(
                "OCR unavailable",
                ocr.unavailable_reason(engine),
                parent=self,
            )
            return

        page_count = app._archive.page_count
        if not messagebox.askyesno(
            "Start processing",
            f"Process {page_count} page(s) now?\n\n"
            "This adds detected text blocks across the whole document and "
            "can take a while. You can cancel while it runs.",
            parent=self,
        ):
            return

        # Ensure there is mokuro data to write into.
        if app._mokuro is None:
            app._install_empty_mokuro()

        options = {
            "skip_existing": self._skip_existing_var.get(),
            "existing_mode": self._existing_mode_var.get(),
            "run_ocr": run_ocr,
            "engine": engine,
            "use_segmentation": use_seg,
            "threshold": app._overlap_threshold(),
        }

        self._running = True
        self._cancel = False
        self._error = None
        self._result = None
        self._progress_state = {"done": 0, "total": page_count, "page": 0}
        self._progress.config(value=0, maximum=max(1, page_count))
        self._start_btn.config(state=tk.DISABLED)
        self._cancel_btn.config(text="Cancel")
        self._set_options_enabled(False)

        self._thread = threading.Thread(
            target=self._worker, args=(options,), daemon=True
        )
        self._thread.start()
        self._poll()

    def _set_options_enabled(self, enabled: bool) -> None:
        """Enable/disable all option widgets (while running)."""
        if enabled:
            self._sync_enabled_state()
            return
        for widget in (
            self._existing_combo, self._engine_combo, self._src_combo,
        ):
            widget.config(state=tk.DISABLED)

    # --------------------------------------------------------------- worker
    def _worker(self, options) -> None:
        """Background processing of every page. Mutates mokuro data in place.

        Runs off the UI thread; the dialog is modal so the document is not
        edited concurrently. Progress is published via ``_progress_state`` and
        cancellation polled via ``_cancel``.
        """
        app = self._app
        archive = app._archive
        mokuro = app._mokuro
        pages_processed = 0
        blocks_added = 0
        ocr_count = 0

        try:
            for i in range(archive.page_count):
                if self._cancel:
                    break
                self._progress_state = {
                    "done": i, "total": archive.page_count, "page": i + 1
                }

                name = archive.page_name(i)
                page = mokuro.page_for(name)
                has_text = page is not None and len(page.blocks) > 0

                if options["skip_existing"] and has_text:
                    continue

                try:
                    image = archive.load_image(i).convert("RGB")
                except Exception:  # noqa: BLE001 - skip unreadable pages
                    continue

                if page is None:
                    width, height = image.size
                    page = mokuro.ensure_page(name, width, height)

                # Detect (optionally also getting a cleaned page for OCR).
                cleaned = None
                if options["run_ocr"] and options["use_segmentation"]:
                    boxes, cleaned = segmentation.detect_and_clean(image)
                else:
                    boxes = segmentation.detect(image)

                # Decide how to merge with any existing blocks.
                existing_boxes = []
                if has_text:
                    if options["existing_mode"] == _MODE_OVERWRITE:
                        page.blocks.clear()
                    else:
                        existing_boxes = [
                            b.box for b in page.blocks if len(b.box) == 4
                        ]

                threshold = options["threshold"]
                new_blocks = []
                for box in boxes:
                    if self._cancel:
                        break
                    if existing_boxes and any(
                        MokuroPage._boxes_overlap(box, eb, threshold)
                        for eb in existing_boxes
                    ):
                        continue
                    x1, y1, x2, y2 = box
                    vertical = (y2 - y1) > (x2 - x1)
                    block = TextBlock(
                        box=list(box), vertical=vertical, font_size=0,
                        lines=[""],
                    )
                    page.blocks.append(block)
                    new_blocks.append(block)
                    blocks_added += 1

                # OCR the new blocks.
                if options["run_ocr"] and new_blocks:
                    src_image = cleaned if cleaned is not None else image
                    for block in new_blocks:
                        if self._cancel:
                            break
                        crop = app._crop_block(block, source=src_image)
                        if crop is None:
                            continue
                        try:
                            lines = ocr.recognize(
                                crop,
                                vertical=block.vertical,
                                method=options["engine"],
                            )
                        except Exception:  # noqa: BLE001 - skip failed block
                            continue
                        if lines:
                            block.lines = lines
                            ocr_count += 1

                pages_processed += 1

            self._progress_state = {
                "done": archive.page_count,
                "total": archive.page_count,
                "page": archive.page_count,
            }
        except Exception as exc:  # noqa: BLE001 - report to UI thread
            self._error = str(exc)

        self._result = (pages_processed, blocks_added, ocr_count)

    def _poll(self) -> None:
        """Poll the worker, updating the progress bar until it finishes."""
        state = self._progress_state
        done, total, page = state["done"], state["total"], state["page"]
        self._progress.config(value=done)
        if self._cancel:
            self._progress_label.config(text="Cancelling...")
        elif total:
            self._progress_label.config(
                text=f"Processing page {page} / {total}..."
            )

        if self._thread is not None and self._thread.is_alive():
            self.after(150, self._poll)
            return

        # Finished.
        self._running = False
        if self._error:
            messagebox.showerror(
                "Processing failed", self._error, parent=self
            )
        self._finish()

    def _finish(self) -> None:
        """Apply results to the app and close the wizard."""
        processed, added, ocr_count = self._result or (0, 0, 0)
        self._app._on_wizard_finished(processed, added, ocr_count, self._cancel)
        self.grab_release()
        self.destroy()

    # --------------------------------------------------------------- close
    def _on_close(self) -> None:
        if self._running:
            # Request cancellation; the worker stops at the next checkpoint and
            # _poll() will finish and close the window.
            self._cancel = True
            self._progress_label.config(text="Cancelling...")
            self._cancel_btn.config(state=tk.DISABLED)
            return
        self.grab_release()
        self.destroy()
