"""Handwritten kanji input via OCR.

An alternative to :mod:`mogura.kanji_draw`: instead of stroke-order matching
with the optional ``kanjidraw`` package, the user draws a character freehand
on a canvas and the active OCR backend (see :mod:`mogura.ocr`) is asked to read
it. Recognised candidates are offered as clickable buttons; picking one inserts
it into the target text widget via the supplied callback.

This works whenever an OCR backend is installed, so it needs no extra
dependency beyond what OCR already requires.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font
from typing import Callable, List, Optional

from PIL import Image, ImageDraw

from . import logging_setup, ocr

_log = logging_setup.get_logger("kanji_ocr")

# Canvas geometry (pixels). The drawing is rendered to an off-screen image of
# the same size for OCR.
_SIZE = 320
_LINEWIDTH = 10
_RESULT_COLS = 6
_RESULT_FONTSIZE = 22
# Pad the recognized crop so the OCR engine sees some margin around the glyph.
_OCR_MARGIN = 24


def is_available() -> bool:
    """Return True if OCR-based handwriting recognition can be used."""
    return ocr.is_available()


def unavailable_reason() -> str:
    """Human-readable explanation for why the feature is unavailable."""
    return (
        "OCR-based kanji input needs an OCR backend.\n\n"
        + ocr.unavailable_reason()
    )


class KanjiOcrDialog(tk.Toplevel):
    """Modal dialog to draw a character and recognize it with OCR."""

    def __init__(self, master, on_pick: Callable[[str], None]):
        super().__init__(master)
        self.title("Draw Kanji (OCR)")
        self.transient(master)
        self.resizable(False, False)

        self._on_pick = on_pick
        # Off-screen image mirroring the canvas, used as the OCR input. White
        # background, black ink, matching the usual dark-on-light expectation.
        self._image = Image.new("L", (_SIZE, _SIZE), 255)
        self._draw = ImageDraw.Draw(self._image)
        # Canvas line item ids per stroke, for undo.
        self._lines: List[List[int]] = []
        # Pixel points per stroke, mirrored onto the off-screen image on undo.
        self._points: List[List[tuple]] = []
        self._drawing = False
        self._x = 0.0
        self._y = 0.0

        self._kanji_font = self._make_kanji_font()

        self._build_ui()

        self.bind("<Escape>", lambda _e: self._on_close())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.grab_set()
        self._canvas.focus_set()

    # ------------------------------------------------------------------ setup
    def _make_kanji_font(self) -> tkinter.font.Font:
        font = tkinter.font.Font(size=_RESULT_FONTSIZE)
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

        self._recognize_btn = tk.Button(
            toolbar, text="Recognize", command=self._recognize
        )
        self._recognize_btn.pack(side=tk.RIGHT)

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

        tk.Label(
            self,
            text="Draw a character, then press Recognize.",
            anchor=tk.W,
            fg="#666666",
        ).pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6, 0))

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
    def _on_mousedown(self, event) -> None:
        self._drawing = True
        self._x, self._y = event.x, event.y
        self._lines.append([])
        self._points.append([(event.x, event.y)])

    def _on_mousemove(self, event) -> None:
        if self._drawing:
            self._draw_segment(event.x, event.y)

    def _on_mouseup(self, event) -> None:
        if not self._drawing:
            return
        self._draw_segment(event.x, event.y)
        self._drawing = False
        self._update_buttons()

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
        self._draw.line(
            (self._x, self._y, x2, y2), fill=0, width=_LINEWIDTH
        )
        self._points[-1].append((x2, y2))
        self._x, self._y = x2, y2

    def _on_undo(self) -> None:
        if not self._lines:
            return
        for item in self._lines.pop():
            self._canvas.delete(item)
        self._points.pop()
        self._redraw_image()
        self._update_buttons()

    def _on_clear(self) -> None:
        self._lines.clear()
        self._points.clear()
        self._canvas.delete("all")
        self._image.paste(255, (0, 0, _SIZE, _SIZE))
        self._update_buttons()
        self._clear_results()

    def _redraw_image(self) -> None:
        """Rebuild the off-screen OCR image from the remaining strokes."""
        self._image.paste(255, (0, 0, _SIZE, _SIZE))
        for stroke in self._points:
            if len(stroke) == 1:
                x, y = stroke[0]
                self._draw.line((x, y, x, y), fill=0, width=_LINEWIDTH)
            else:
                self._draw.line(stroke, fill=0, width=_LINEWIDTH)

    def _update_buttons(self) -> None:
        state = tk.NORMAL if self._lines else tk.DISABLED
        self._undo_btn.config(state=state)
        self._clear_btn.config(state=state)
        self._recognize_btn.config(state=state)

    # -------------------------------------------------------------- recognise
    def _clear_results(self) -> None:
        for child in self._results.winfo_children():
            child.destroy()

    def _ocr_image(self) -> Optional[Image.Image]:
        """Return the drawn ink as a tightly-cropped, padded RGB image."""
        # getbbox finds the extent of non-zero pixels; the ink is black (0) on
        # a white (255) background, so invert first to locate the strokes.
        from PIL import ImageOps

        ink = ImageOps.invert(self._image)
        bbox = ink.getbbox()
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox
        x1 = max(0, x1 - _OCR_MARGIN)
        y1 = max(0, y1 - _OCR_MARGIN)
        x2 = min(_SIZE, x2 + _OCR_MARGIN)
        y2 = min(_SIZE, y2 + _OCR_MARGIN)
        return self._image.crop((x1, y1, x2, y2)).convert("RGB")

    def _recognize(self) -> None:
        self._clear_results()
        if not ocr.is_available():
            tk.Label(
                self._results,
                text="OCR is not available.",
                fg="#c62828",
            ).grid(row=0, column=0, sticky="w")
            return
        crop = self._ocr_image()
        if crop is None:
            return

        self.config(cursor="watch")
        self._recognize_btn.config(state=tk.DISABLED)
        self.update_idletasks()
        try:
            lines = ocr.recognize(crop, vertical=False)
        except Exception as exc:  # pragma: no cover - runtime/engine errors
            _log.error("OCR kanji recognition failed: %s", exc)
            lines = []
        finally:
            self.config(cursor="")
            self._recognize_btn.config(state=tk.NORMAL)

        # Flatten the recognized lines into individual characters so each one
        # can be inserted on its own.
        chars: List[str] = []
        for line in lines:
            for ch in line:
                if not ch.isspace() and ch not in chars:
                    chars.append(ch)

        if not chars:
            tk.Label(
                self._results,
                text="No character recognized. Try drawing more clearly.",
                fg="#666666",
                wraplength=_SIZE,
                justify=tk.LEFT,
            ).grid(row=0, column=0, columnspan=_RESULT_COLS, sticky="w")
            return

        for i, ch in enumerate(chars):
            col, row = i % _RESULT_COLS, i // _RESULT_COLS
            btn = tk.Button(
                self._results,
                text=ch,
                font=self._kanji_font,
                width=2,
                command=lambda c=ch: self._choose(c),
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
