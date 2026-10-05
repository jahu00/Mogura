"""Application settings window.

A single window with a list of sections on the left and the settings for the
selected section on the right. Sections are kept small and self-contained so
new ones can be added without disturbing the others.

Sections:

* **OCR** - shows which OCR backends are installed and lets the user pick the
  active method.
* **Mokuro** - overlap-detection threshold and whether to auto-OCR newly added
  text items.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import ocr
from .settings import Settings


class SettingsDialog(tk.Toplevel):
    """Modal settings window with a section list and per-section panels."""

    def __init__(self, master, settings: Settings, on_change=None):
        super().__init__(master)
        self.title("Settings")
        self.transient(master)
        self.minsize(560, 360)

        self._settings = settings
        # Optional callback invoked when a setting that affects the live view
        # (e.g. the overlap threshold) changes.
        self._on_change = on_change

        # Map a section label to the frame that holds its widgets.
        self._sections: dict[str, tk.Frame] = {}
        self._current: tk.Frame | None = None

        self._build_body()
        self._build_buttons()

        # Select the first section by default.
        self._section_list.selection_set(0)
        self._on_section_select()

        self.bind("<Escape>", lambda _e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()

    # ------------------------------------------------------------------ body
    def _build_body(self) -> None:
        body = tk.Frame(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Left: list of sections.
        left = tk.Frame(body, bd=1, relief=tk.SUNKEN)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 4), pady=8)
        self._section_list = tk.Listbox(
            left, width=18, activestyle="none", exportselection=False,
            highlightthickness=0, bd=0,
        )
        self._section_list.pack(fill=tk.BOTH, expand=True)
        self._section_list.bind(
            "<<ListboxSelect>>", lambda _e: self._on_section_select()
        )

        # Right: container that swaps between section panels.
        self._panel_host = tk.Frame(body)
        self._panel_host.pack(
            side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 8), pady=8
        )

        self._add_section("OCR", self._build_ocr_section)
        self._add_section("Mokuro", self._build_mokuro_section)

    def _add_section(self, label: str, builder) -> None:
        """Register a section: add it to the list and build its panel."""
        frame = tk.Frame(self._panel_host)
        builder(frame)
        self._sections[label] = frame
        self._section_list.insert(tk.END, label)

    def _on_section_select(self) -> None:
        selection = self._section_list.curselection()
        if not selection:
            return
        label = self._section_list.get(selection[0])
        frame = self._sections.get(label)
        if frame is None or frame is self._current:
            return
        if self._current is not None:
            self._current.pack_forget()
        frame.pack(fill=tk.BOTH, expand=True)
        self._current = frame

    # ------------------------------------------------------------- OCR panel
    def _build_ocr_section(self, parent: tk.Frame) -> None:
        tk.Label(
            parent, text="OCR", anchor=tk.W,
            font=("TkDefaultFont", 11, "bold"),
        ).pack(fill=tk.X, pady=(0, 10))

        # Per-method install status (read-only), one row per backend.
        status = tk.Frame(parent)
        status.pack(fill=tk.X, pady=2)
        for method_name in ocr.available_methods():
            row = tk.Frame(status)
            row.pack(fill=tk.X, pady=1)
            tk.Label(
                row, text=f"{method_name} installed:", anchor=tk.W, width=20
            ).pack(side=tk.LEFT)
            installed = ocr.is_available(method_name)
            tk.Label(
                row,
                text="Yes" if installed else "No",
                fg="#2e7d32" if installed else "#c62828",
                font=("TkDefaultFont", 9, "bold"),
            ).pack(side=tk.LEFT, padx=(6, 0))

        # OCR method selection.
        method = tk.Frame(parent)
        method.pack(fill=tk.X, pady=(12, 2))
        tk.Label(method, text="OCR method:", anchor=tk.W).pack(side=tk.LEFT)
        methods = ocr.available_methods()
        self._ocr_method_var = tk.StringVar(
            value=self._settings.get("ocr_method")
        )
        combo = ttk.Combobox(
            method,
            textvariable=self._ocr_method_var,
            values=methods,
            state="readonly",
            width=20,
        )
        # Guard against a stored value no longer in the list.
        if self._ocr_method_var.get() not in methods:
            self._ocr_method_var.set(methods[0])
        combo.pack(side=tk.LEFT, padx=(6, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_ocr_method())

    def _on_ocr_method(self) -> None:
        method = self._ocr_method_var.get()
        self._settings.set("ocr_method", method)
        ocr.set_method(method)

    # ---------------------------------------------------------- Mokuro panel
    def _build_mokuro_section(self, parent: tk.Frame) -> None:
        tk.Label(
            parent, text="Mokuro", anchor=tk.W,
            font=("TkDefaultFont", 11, "bold"),
        ).pack(fill=tk.X, pady=(0, 10))

        # Overlap threshold (percentage of the smaller box's area).
        thr = tk.Frame(parent)
        thr.pack(fill=tk.X, pady=2)
        tk.Label(thr, text="Overlap threshold (%):", anchor=tk.W).pack(
            side=tk.LEFT
        )
        stored = self._settings.get("overlap_threshold")
        try:
            initial_pct = int(round(float(stored) * 100))
        except (TypeError, ValueError):
            initial_pct = 0
        self._overlap_var = tk.IntVar(value=max(0, min(100, initial_pct)))
        spin = tk.Spinbox(
            thr,
            from_=0,
            to=100,
            increment=1,
            width=6,
            textvariable=self._overlap_var,
            command=self._on_overlap_threshold,
        )
        spin.pack(side=tk.LEFT, padx=(6, 0))
        # Also catch typed values (the command only fires on arrow clicks).
        spin.bind("<FocusOut>", lambda _e: self._on_overlap_threshold())
        spin.bind("<Return>", lambda _e: self._on_overlap_threshold())

        tk.Label(
            parent,
            text="Overlap below this fraction of the smaller item's area is "
            "ignored.",
            anchor=tk.W,
            fg="#666666",
            wraplength=320,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 10))

        # Auto-OCR on add.
        self._auto_ocr_var = tk.BooleanVar(
            value=bool(self._settings.get("auto_ocr_on_add"))
        )
        tk.Checkbutton(
            parent,
            text="Automatically run OCR when adding a new text item",
            variable=self._auto_ocr_var,
            anchor=tk.W,
            command=self._on_auto_ocr,
        ).pack(fill=tk.X)

    def _on_overlap_threshold(self) -> None:
        try:
            pct = int(self._overlap_var.get())
        except (tk.TclError, ValueError):
            return
        pct = max(0, min(100, pct))
        self._overlap_var.set(pct)
        self._settings.set("overlap_threshold", pct / 100.0)
        if self._on_change is not None:
            self._on_change()

    def _on_auto_ocr(self) -> None:
        self._settings.set("auto_ocr_on_add", self._auto_ocr_var.get())

    # --------------------------------------------------------------- buttons
    def _build_buttons(self) -> None:
        btns = tk.Frame(self, padx=8, pady=8)
        btns.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Button(btns, text="Close", command=self._on_close).pack(
            side=tk.RIGHT
        )

    def _on_close(self) -> None:
        self.grab_release()
        self.destroy()
