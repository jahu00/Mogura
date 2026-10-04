"""Non-modal Find / Find-and-Replace dialog.

Unlike the other dialogs in the app, this window is intentionally *not* modal:
it does not call ``grab_set`` or ``wait_window``, so the main window stays
fully usable while it is open (navigating pages, editing text, etc.).

The dialog is a thin UI shell. All of the actual searching and replacing is
delegated to a *controller* (the main app), which owns the mokuro data and
knows how to navigate to and highlight matches. The controller must provide::

    find_next(query) -> str
    find_prev(query) -> str
    replace_one(query, replacement) -> str
    replace_all(query, replacement) -> str
    on_find_closed() -> None

Each search/replace method returns a short status message that the dialog
shows to the user.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from .special_chars import SpecialCharButton


class FindDialog(tk.Toplevel):
    """A reusable, non-blocking find / find-and-replace window."""

    def __init__(self, master, controller, replace: bool = False):
        super().__init__(master)
        self._controller = controller
        self._replace = replace
        # The entry (search or replace) that most recently had focus; used as
        # the target for inserted special characters.
        self._last_entry: Optional[tk.Entry] = None

        self.transient(master)
        self.resizable(False, False)

        # Persist entry contents across mode switches / rebuilds.
        self._query_var = tk.StringVar()
        self._replace_var = tk.StringVar()

        self._body = tk.Frame(self, padx=10, pady=10)
        self._body.pack(fill=tk.BOTH, expand=True)

        self._build_body()

        self.bind("<Escape>", lambda _e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ mode
    def set_mode(self, replace: bool) -> None:
        """Switch between find-only and find-and-replace layouts."""
        if replace == self._replace:
            return
        self._replace = replace
        for child in self._body.winfo_children():
            child.destroy()
        self._build_body()

    # ------------------------------------------------------------------ build
    def _build_body(self) -> None:
        self.title("Find and Replace" if self._replace else "Find")

        # --- Search row ---------------------------------------------------
        search_row = tk.Frame(self._body)
        search_row.pack(fill=tk.X)
        tk.Label(search_row, text="Find:", width=8, anchor=tk.W).pack(
            side=tk.LEFT
        )
        self._search_entry = tk.Entry(
            search_row, textvariable=self._query_var, width=30
        )
        self._search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._search_entry.bind("<FocusIn>", self._on_entry_focus)
        self._search_entry.bind("<Return>", lambda _e: self._do_find_next())
        self._search_entry.bind("<Shift-Return>", lambda _e: self._do_find_prev())

        self._build_special_menu(search_row)

        # --- Replace row (replace mode only) ------------------------------
        if self._replace:
            replace_row = tk.Frame(self._body)
            replace_row.pack(fill=tk.X, pady=(6, 0))
            tk.Label(replace_row, text="Replace:", width=8, anchor=tk.W).pack(
                side=tk.LEFT
            )
            self._replace_entry = tk.Entry(
                replace_row, textvariable=self._replace_var, width=30
            )
            self._replace_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._replace_entry.bind("<FocusIn>", self._on_entry_focus)
        else:
            self._replace_entry = None

        # --- Buttons ------------------------------------------------------
        btns = tk.Frame(self._body)
        btns.pack(fill=tk.X, pady=(10, 0))

        tk.Button(btns, text="Previous", command=self._do_find_prev).pack(
            side=tk.LEFT
        )
        tk.Button(btns, text="Next", command=self._do_find_next).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        if self._replace:
            tk.Button(btns, text="Replace", command=self._do_replace).pack(
                side=tk.LEFT, padx=(6, 0)
            )
            tk.Button(
                btns, text="Replace All", command=self._do_replace_all
            ).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(btns, text="Close", command=self._on_close).pack(
            side=tk.RIGHT
        )

        # --- Status line --------------------------------------------------
        self._status = tk.Label(
            self._body, text="", anchor=tk.W, fg="#666666"
        )
        self._status.pack(fill=tk.X, pady=(8, 0))

        self._last_entry = self._search_entry
        self._search_entry.focus_set()

    def _build_special_menu(self, parent) -> None:
        """Create the 'Insert special character' drop-down button.

        The target is resolved on demand so the character lands in whichever
        input (search or replace) last had focus.
        """
        self._insert_btn = SpecialCharButton(parent, target=self._insert_target)
        self._insert_btn.pack(side=tk.LEFT, padx=(4, 0))

    # --------------------------------------------------------------- helpers
    def _on_entry_focus(self, event) -> None:
        self._last_entry = event.widget

    def _insert_target(self) -> tk.Entry:
        """Return the input that should receive an inserted character."""
        return self._last_entry or self._search_entry

    def _set_status(self, message: str) -> None:
        self._status.config(text=message)

    # --------------------------------------------------------------- actions
    def _do_find_next(self) -> None:
        self._set_status(self._controller.find_next(self._query_var.get()))

    def _do_find_prev(self) -> None:
        self._set_status(self._controller.find_prev(self._query_var.get()))

    def _do_replace(self) -> None:
        self._set_status(
            self._controller.replace_one(
                self._query_var.get(), self._replace_var.get()
            )
        )

    def _do_replace_all(self) -> None:
        self._set_status(
            self._controller.replace_all(
                self._query_var.get(), self._replace_var.get()
            )
        )

    def _on_close(self) -> None:
        self._controller.on_find_closed()
        self.destroy()
