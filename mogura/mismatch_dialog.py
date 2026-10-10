"""Dialog shown when a mokuro file does not match the current page source.

When mokuro data is loaded for a CBZ (or folder) that is missing some of the
pages the mokuro references, the text data for those pages can never be shown
or edited. This dialog informs the user about the mismatch and lets them
either:

* drop the orphaned pages from the mokuro data (so the data matches the pages
  actually available), or
* keep the data unchanged and continue as-is.
"""

from __future__ import annotations

import tkinter as tk
from typing import List

from .mokuro import MokuroPage

# Cap how many page names we list verbatim before summarising the rest.
_MAX_LISTED = 50


class MismatchDialog(tk.Toplevel):
    """Modal dialog reporting mokuro pages absent from the image source."""

    def __init__(self, master, missing: List[MokuroPage], total_pages: int):
        super().__init__(master)
        self.title("Mokuro / pages mismatch")
        self.transient(master)
        self.resizable(False, True)

        # True if the user chose to delete the missing pages from the data.
        self.remove_missing = False

        count = len(missing)
        body = tk.Frame(self, padx=14, pady=12)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        header = (
            f"The mokuro data references {count} page"
            f"{'s' if count != 1 else ''} that are not present in the "
            f"current images ({total_pages} page"
            f"{'s' if total_pages != 1 else ''} available)."
        )
        tk.Label(
            body, text=header, justify=tk.LEFT, wraplength=420, anchor=tk.W
        ).pack(fill=tk.X)

        tk.Label(
            body,
            text="Text for these pages cannot be shown or edited:",
            justify=tk.LEFT,
            anchor=tk.W,
            pady=6,
        ).pack(fill=tk.X)

        self._build_list(body, missing)

        tk.Label(
            body,
            text=(
                "You can remove these pages from the mokuro data, or keep "
                "the data unchanged and continue."
            ),
            justify=tk.LEFT,
            wraplength=420,
            anchor=tk.W,
            pady=8,
        ).pack(fill=tk.X)

        self._build_buttons()
        self.bind("<Escape>", lambda _e: self._on_continue())
        self.protocol("WM_DELETE_WINDOW", self._on_continue)
        self.grab_set()

    def _build_list(self, parent, missing: List[MokuroPage]) -> None:
        frame = tk.Frame(parent, bd=1, relief=tk.SUNKEN)
        frame.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(frame, orient=tk.VERTICAL)
        listbox = tk.Listbox(
            frame,
            height=min(10, max(3, len(missing))),
            width=52,
            yscrollcommand=scroll.set,
            activestyle=tk.NONE,
        )
        scroll.config(command=listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        shown = missing[:_MAX_LISTED]
        for page in shown:
            listbox.insert(tk.END, page.img_path or "(unnamed page)")
        remaining = len(missing) - len(shown)
        if remaining > 0:
            listbox.insert(tk.END, f"... and {remaining} more")

    def _build_buttons(self) -> None:
        btns = tk.Frame(self, padx=14, pady=10)
        btns.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Button(
            btns, text="Continue", command=self._on_continue, default=tk.ACTIVE
        ).pack(side=tk.RIGHT)
        tk.Button(
            btns,
            text="Remove missing pages",
            command=self._on_remove,
        ).pack(side=tk.RIGHT, padx=6)

    def _on_remove(self) -> None:
        self.remove_missing = True
        self.grab_release()
        self.destroy()

    def _on_continue(self) -> None:
        self.remove_missing = False
        self.grab_release()
        self.destroy()
