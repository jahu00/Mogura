"""Handwritten kanji input dialog.

Provides a small drawing canvas where the user sketches a kanji stroke by
stroke; candidate characters are recognised with the optional ``kanjidraw``
module and offered as clickable buttons. Picking one inserts it into a target
text widget at the insertion cursor.

The feature is optional: if ``kanjidraw`` is not installed the dialog simply
reports as unavailable and the triggering button can be disabled.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font
from typing import Callable, List, Optional, Tuple

from . import logging_setup

_log = logging_setup.get_logger("kanji_draw")

# Canvas geometry; strokes are stored in a 0..255 coordinate space to match the
# kanjidraw data set.
_SIZE = 320
_LINEWIDTH = 5
_RESULT_COLS = 6
_RESULT_FONTSIZE = 22

try:  # pragma: no cover - import guard
    from kanjidraw import matches, kanji_data

    _KANJIDRAW_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - optional dependency
    matches = None  # type: ignore
    kanji_data = None  # type: ignore
    _KANJIDRAW_ERROR = str(exc)


def is_available() -> bool:
    """Return True if handwriting recognition can be used."""
    return matches is not None


def unavailable_reason() -> str:
    """Human-readable explanation for why the feature is unavailable."""
    detail = f" ({_KANJIDRAW_ERROR})" if _KANJIDRAW_ERROR else ""
    return (
        "Handwritten kanji input needs the 'kanjidraw' package.\n"
        "Install it with: pip install kanjidraw" + detail
    )


class KanjiDrawDialog(tk.Toplevel):
    """Modal dialog to draw a kanji and insert the chosen character."""

    def __init__(self, master, on_pick: Callable[[str], None]):
        super().__init__(master)
        self.title("Draw Kanji")
        self.transient(master)
        self.resizable(False, False)

        self._on_pick = on_pick
        # Each stroke is [x1, y1, x2, y2] in 0..255 space (start/end points).
        self._strokes: List[List[float]] = []
        # Canvas line item ids per stroke, for undo.
        self._lines: List[List[int]] = []
        self._drawing = False
        self._x = 0.0
        self._y = 0.0

        self._max_strokes = max(kanji_data().keys()) if kanji_data else 30

        # A font that can display CJK on the candidate buttons.
        self._kanji_font = self._make_kanji_font()

        self._build_ui()

        self.bind("<Escape>", lambda _e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()
        self._canvas.focus_set()

    # ------------------------------------------------------------------ setup
    def _make_kanji_font(self) -> tkinter.font.Font:
        font = tkinter.font.Font(size=_RESULT_FONTSIZE)
        # Resolve a reasonable installed CJK family so candidate glyphs show.
        installed = set(tkinter.font.families(self))
        for candidate in (
            "Noto Sans CJK JP",
            "Noto Sans JP",
            "Noto Serif CJK JP",
            "IPAexGothic",
            "IPAGothic",
            "TakaoGothic",
            "VL Gothic",
        ):
            if candidate in installed:
                font.config(family=candidate)
                break
        return font

    def _build_ui(self) -> None:
        toolbar = tk.Frame(self, padx=8, pady=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self._undo_btn = tk.Button(toolbar, text="Undo", command=self._on_undo)
        self._undo_btn.pack(side=tk.LEFT)
        self._clear_btn = tk.Button(
            toolbar, text="Clear", command=self._on_clear
        )
        self._clear_btn.pack(side=tk.LEFT, padx=4)
        self._strokes_lbl = tk.Label(toolbar, text="Strokes: 0", fg="#666666")
        self._strokes_lbl.pack(side=tk.LEFT, padx=8)

        self._fuzzy_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            toolbar,
            text="Ignore stroke order",
            variable=self._fuzzy_var,
            command=self._recognize,
        ).pack(side=tk.RIGHT)

        self._canvas = tk.Canvas(
            self,
            width=_SIZE,
            height=_SIZE,
            background="#ffffff",
            highlightthickness=1,
            highlightbackground="#000000",
            cursor="pencil",
        )
        self._canvas.pack(side=tk.TOP, padx=8)
        self._canvas.bind("<ButtonPress-1>", self._on_mousedown)
        self._canvas.bind("<B1-Motion>", self._on_mousemove)
        self._canvas.bind("<ButtonRelease-1>", self._on_mouseup)
        self._draw_grid()

        tk.Label(self, text="Candidates:", anchor=tk.W, fg="#666666").pack(
            side=tk.TOP, fill=tk.X, padx=8, pady=(6, 0)
        )
        self._results = tk.Frame(self, padx=8, pady=4)
        self._results.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        btns = tk.Frame(self, padx=8, pady=8)
        btns.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Button(btns, text="Close", command=self._on_close).pack(
            side=tk.RIGHT
        )

        self._update_buttons()

    # ------------------------------------------------------------- canvas i/o
    def _draw_grid(self) -> None:
        for x in (_SIZE // 3, 2 * _SIZE // 3):
            self._canvas.create_line(x, 0, x, _SIZE, fill="#cccccc", dash=(2, 4))
        for y in (_SIZE // 3, 2 * _SIZE // 3):
            self._canvas.create_line(0, y, _SIZE, y, fill="#cccccc", dash=(2, 4))

    def _to_data(self, px: float) -> float:
        return px * 255.0 / _SIZE

    def _on_mousedown(self, event) -> None:
        if len(self._strokes) >= self._max_strokes:
            return
        self._drawing = True
        self._x, self._y = event.x, event.y
        self._strokes.append([self._to_data(event.x), self._to_data(event.y)])
        self._lines.append([])

    def _on_mousemove(self, event) -> None:
        if self._drawing:
            self._draw_segment(event.x, event.y)

    def _on_mouseup(self, event) -> None:
        if not self._drawing:
            return
        self._draw_segment(event.x, event.y)
        self._drawing = False
        self._strokes[-1] += [self._to_data(event.x), self._to_data(event.y)]
        self._update_buttons()
        self._recognize()

    def _draw_segment(self, x2: float, y2: float) -> None:
        line = self._canvas.create_line(
            self._x,
            self._y,
            x2,
            y2,
            width=_LINEWIDTH,
            capstyle=tk.ROUND,
            fill="#000000",
        )
        self._lines[-1].append(line)
        self._x, self._y = x2, y2

    def _on_undo(self) -> None:
        if not self._strokes:
            return
        self._strokes.pop()
        for item in self._lines.pop():
            self._canvas.delete(item)
        self._update_buttons()
        self._recognize()

    def _on_clear(self) -> None:
        self._strokes.clear()
        self._lines.clear()
        self._canvas.delete("all")
        self._draw_grid()
        self._update_buttons()
        self._clear_results()

    def _update_buttons(self) -> None:
        n = len(self._strokes)
        self._strokes_lbl.config(text=f"Strokes: {n}")
        state = tk.NORMAL if n else tk.DISABLED
        self._undo_btn.config(state=state)
        self._clear_btn.config(state=state)

    # -------------------------------------------------------------- recognise
    def _clear_results(self) -> None:
        for child in self._results.winfo_children():
            child.destroy()

    def _recognize(self) -> None:
        self._clear_results()
        # Only complete strokes (4 coordinates) count.
        strokes = [s for s in self._strokes if len(s) == 4]
        if not strokes or matches is None:
            return
        try:
            results: List[Tuple[float, str]] = list(
                matches(strokes, fuzzy=self._fuzzy_var.get())
            )
        except Exception as exc:  # pragma: no cover - runtime errors
            _log.error("Kanji recognition failed: %s", exc)
            return

        for i, (_score, kanji) in enumerate(results):
            col, row = i % _RESULT_COLS, i // _RESULT_COLS
            btn = tk.Button(
                self._results,
                text=kanji,
                font=self._kanji_font,
                width=2,
                command=lambda k=kanji: self._choose(k),
            )
            btn.grid(row=row, column=col, padx=2, pady=2, sticky="nsew")

    def _choose(self, kanji: str) -> None:
        try:
            self._on_pick(kanji)
        except Exception as exc:  # pragma: no cover - callback errors
            _log.error("Kanji insert callback failed: %s", exc)
        # Reset so the user can draw the next character right away.
        self._on_clear()

    # ------------------------------------------------------------------ close
    def _on_close(self) -> None:
        self.grab_release()
        self.destroy()
