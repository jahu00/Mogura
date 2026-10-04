"""Reusable 'insert special character' drop-down button.

Both the text-item edit dialog and the find/replace dialog need a quick way to
insert manga-oriented special characters (long vowel marks, ellipses, etc.)
into a text input. This module centralises that control so the character set
and behaviour stay consistent across the app.

The button inserts the chosen character at the insertion cursor of a target
widget (any ``tk.Entry`` or ``tk.Text``). The target can be fixed at creation
time or resolved on demand via a callable, which is handy when several inputs
share one button and the destination depends on which one last had focus.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional, Sequence, Union

# Default manga-oriented characters offered by the drop-down.
DEFAULT_SPECIAL_CHARS = ("ー", "…", "‼", "⁉", "⁇", "！", "？", "〜", "♥")

# A target is either a widget or a callable returning the widget to use.
TargetProvider = Union[tk.Widget, Callable[[], Optional[tk.Widget]]]


class SpecialCharButton(tk.Menubutton):
    """A menu button that inserts a special character into a text input."""

    def __init__(
        self,
        master,
        target: TargetProvider,
        chars: Sequence[str] = DEFAULT_SPECIAL_CHARS,
        text: str = "Insert ▾",
        relief=tk.RAISED,
        on_insert: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(master, text=text, relief=relief, **kwargs)
        self._target = target
        # Optional callback fired after a character is inserted (e.g. to
        # refresh a live preview).
        self._on_insert = on_insert
        menu = tk.Menu(self, tearoff=0)
        for ch in chars:
            menu.add_command(label=ch, command=lambda c=ch: self._insert(c))
        self.config(menu=menu)

    def _resolve_target(self) -> Optional[tk.Widget]:
        if callable(self._target):
            return self._target()
        return self._target

    def _insert(self, char: str) -> None:
        widget = self._resolve_target()
        if widget is None:
            return
        widget.insert(tk.INSERT, char)
        widget.focus_set()
        if self._on_insert is not None:
            self._on_insert()
