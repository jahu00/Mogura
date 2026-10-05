"""A tiny hover-tooltip helper for Tkinter widgets.

Tkinter has no built-in tooltip support, so this module provides a small
``Tooltip`` class and a ``add_tooltip`` convenience function that shows a
borderless label near a widget while the pointer hovers over it.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional


class Tooltip:
    """Show a short help text when the pointer rests over a widget."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay  # milliseconds before the tip appears
        self._after_id: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _event=None) -> None:
        self._schedule()

    def _on_leave(self, _event=None) -> None:
        self._cancel()
        self._hide()

    def _schedule(self) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self) -> None:
        if self._tip is not None or not self.text:
            return
        # Position the tip just below the widget.
        x = self.widget.winfo_rootx() + 8
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4

        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._tip,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            foreground="#000000",
            relief=tk.SOLID,
            borderwidth=1,
            padx=4,
            pady=2,
        )
        label.pack()

    def _hide(self) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def add_tooltip(widget: tk.Widget, text: str, delay: int = 500) -> Tooltip:
    """Attach a hover tooltip with ``text`` to ``widget``."""
    return Tooltip(widget, text, delay=delay)
