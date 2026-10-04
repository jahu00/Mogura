"""Application settings window.

A single window with a list of sections on the left and the settings for the
selected section on the right. Sections are kept small and self-contained so
new ones can be added without disturbing the others.

Currently the only section is **OCR**, which shows whether the optional
RapidOCR dependency is installed and lets the user pick which OCR method to
use (only RapidOCR exists for now).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import ocr
from .settings import Settings


class SettingsDialog(tk.Toplevel):
    """Modal settings window with a section list and per-section panels."""

    def __init__(self, master, settings: Settings):
        super().__init__(master)
        self.title("Settings")
        self.transient(master)
        self.minsize(560, 360)

        self._settings = settings

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
