"""Dialog for splitting one mokuro text block into two.

A single block is split into two output pieces. For each piece the user:

* clicks on its preview to choose a *cutting point*, which divides the block's
  bounding box into four quarters (top-left, top-right, bottom-left,
  bottom-right), and
* selects which quarter that piece keeps,
* edits the piece's text.

The two panes are laid out according to the writing direction so the reading
order reads naturally: for vertical text the first piece is on the left; for
horizontal text the first piece is on the right.
"""

from __future__ import annotations

import tkinter as tk
from typing import List, Optional

from PIL import Image, ImageTk

from .mokuro import TextBlock
from .text_render import render_text_rgba

# Longest edge (px) of a preview canvas.
_PREVIEW = 220
_CROSSHAIR = "#1e88e5"
_QUARTER = "#e53935"

# Quarter identifiers.
_TL, _TR, _BL, _BR = "TL", "TR", "BL", "BR"
_QUARTERS = (_TL, _TR, _BL, _BR)
_QUARTER_LABELS = {
    _TL: "Top-left",
    _TR: "Top-right",
    _BL: "Bottom-left",
    _BR: "Bottom-right",
}


class _SplitPane:
    """One output piece: preview with cut point/quarter, plus a text editor."""

    def __init__(self, parent, title: str, block: TextBlock, crop: Optional[Image.Image]):
        self._block = block
        self._crop = crop  # PIL image of the block region (RGB) or None
        bx1, by1, bx2, by2 = block.box
        self._bw = max(1, bx2 - bx1)
        self._bh = max(1, by2 - by1)
        self._origin = (bx1, by1)

        # Cut point in local image coords (within the box); default: centre.
        self._cut = [self._bw / 2, self._bh / 2]
        self._quarter_var = tk.StringVar(value=_TL)

        self.frame = tk.Frame(parent, bd=1, relief=tk.GROOVE, padx=6, pady=6)
        tk.Label(self.frame, text=title, font=("TkDefaultFont", 9, "bold")).pack()

        # Compute display scale (fit longest edge to _PREVIEW).
        self._scale = _PREVIEW / max(self._bw, self._bh)
        self._disp_w = max(1, int(self._bw * self._scale))
        self._disp_h = max(1, int(self._bh * self._scale))

        self.canvas = tk.Canvas(
            self.frame, width=self._disp_w, height=self._disp_h,
            highlightthickness=1, highlightbackground="#999999", bg="#dddddd",
            cursor="crosshair",
        )
        self.canvas.pack(pady=4)
        # Click, or press-and-drag, to (continuously) set the cut point.
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_click)

        self._photo = None
        if crop is not None:
            disp = crop.resize((self._disp_w, self._disp_h), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(disp)

        # Quarter selector.
        qframe = tk.Frame(self.frame)
        qframe.pack()
        tk.Label(qframe, text="Keep quarter:").grid(row=0, column=0, columnspan=2)
        positions = {
            _TL: (1, 0), _TR: (1, 1), _BL: (2, 0), _BR: (2, 1),
        }
        for q, (r, c) in positions.items():
            tk.Radiobutton(
                qframe, text=_QUARTER_LABELS[q], variable=self._quarter_var,
                value=q, command=self._render,
            ).grid(row=r, column=c, sticky=tk.W)

        # Text editor.
        tk.Label(self.frame, text="Text:", anchor=tk.W).pack(fill=tk.X, pady=(6, 0))
        self.text = tk.Text(self.frame, height=4, width=24, wrap=tk.NONE)
        self.text.insert("1.0", block.text)
        self.text.pack(fill=tk.BOTH, expand=True)
        # Re-render the overlay as the piece's text changes.
        self.text.bind("<KeyRelease>", lambda _e: self._render())

        self._box_label = tk.Label(self.frame, fg="#666666")
        self._box_label.pack(fill=tk.X)

        self._render()

    def _on_click(self, event) -> None:
        lx = min(max(0, event.x / self._scale), self._bw)
        ly = min(max(0, event.y / self._scale), self._bh)
        self._cut = [lx, ly]
        self._render()

    def _render(self) -> None:
        self.canvas.delete("all")
        cx = self._cut[0] * self._scale
        cy = self._cut[1] * self._scale
        qx1, qy1, qx2, qy2 = self._quarter_display_rect(cx, cy)

        # Compose the crop with the piece's text render overlaid on the chosen
        # quarter (in red, matching the combine dialog's source colour).
        self._photo = self._compose_display(qx1, qy1, qx2, qy2)
        if self._photo is not None:
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)

        # Crosshair at the cut point.
        self.canvas.create_line(cx, 0, cx, self._disp_h, fill=_CROSSHAIR, dash=(3, 2))
        self.canvas.create_line(0, cy, self._disp_w, cy, fill=_CROSSHAIR, dash=(3, 2))
        # Highlight the selected quarter.
        self.canvas.create_rectangle(
            qx1, qy1, qx2, qy2, outline=_QUARTER, width=3
        )
        x1, y1, x2, y2 = self.result_box()
        self._box_label.config(text=f"[{x1}, {y1}, {x2}, {y2}]")

    def _compose_display(self, qx1, qy1, qx2, qy2):
        """Return a PhotoImage of the crop with the render over the quarter."""
        if self._crop is None:
            return None
        base = self._crop.resize((self._disp_w, self._disp_h), Image.LANCZOS)
        base = base.convert("RGBA")
        # Normalize quarter rect to integers within display bounds.
        rx1, rx2 = sorted((int(qx1), int(qx2)))
        ry1, ry2 = sorted((int(qy1), int(qy2)))
        rw, rh = rx2 - rx1, ry2 - ry1
        lines = self.result_lines()
        if rw >= 1 and rh >= 1 and any(ln for ln in lines):
            overlay = render_text_rgba(
                lines, self._block.vertical, rw, rh, fg=_QUARTER
            )
            base.alpha_composite(overlay, dest=(rx1, ry1))
        return ImageTk.PhotoImage(base.convert("RGB"))

    def _quarter_display_rect(self, cx: float, cy: float):
        q = self._quarter_var.get()
        left, right = 0, self._disp_w
        top, bottom = 0, self._disp_h
        if q == _TL:
            return (left, top, cx, cy)
        if q == _TR:
            return (cx, top, right, cy)
        if q == _BL:
            return (left, cy, cx, bottom)
        return (cx, cy, right, bottom)

    def result_box(self) -> list:
        """Selected quarter in absolute image coordinates."""
        ox, oy = self._origin
        lcx, lcy = self._cut
        q = self._quarter_var.get()
        if q == _TL:
            lx1, ly1, lx2, ly2 = 0, 0, lcx, lcy
        elif q == _TR:
            lx1, ly1, lx2, ly2 = lcx, 0, self._bw, lcy
        elif q == _BL:
            lx1, ly1, lx2, ly2 = 0, lcy, lcx, self._bh
        else:  # BR
            lx1, ly1, lx2, ly2 = lcx, lcy, self._bw, self._bh
        return [
            int(round(ox + lx1)), int(round(oy + ly1)),
            int(round(ox + lx2)), int(round(oy + ly2)),
        ]

    def result_lines(self) -> List[str]:
        return self.text.get("1.0", "end-1c").split("\n")


class SplitDialog(tk.Toplevel):
    """Modal dialog to split one text block into two pieces."""

    def __init__(self, master, block: TextBlock, page_image: Optional[Image.Image]):
        super().__init__(master)
        self.title("Split Text Item")
        self.transient(master)
        self.resizable(False, True)

        self._block = block
        self.result = False
        # Populated on confirm: list of (lines, box, vertical) in list order.
        self.pieces: List[tuple] = []

        crop = self._crop_block(block, page_image)

        body = tk.Frame(self, padx=10, pady=10)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # "First" piece per reading order; "second" is the other.
        self._first = _SplitPane(body, "First piece", block, crop)
        self._second = _SplitPane(body, "Second piece", block, crop)
        # Default the two panes to complementary quarters for convenience.
        self._first._quarter_var.set(_TL)
        self._first._render()
        self._second._quarter_var.set(_BR)
        self._second._render()

        # Layout by orientation: vertical -> first on left; horizontal ->
        # first on the right.
        if block.vertical:
            self._first.frame.pack(side=tk.LEFT, padx=6, fill=tk.Y)
            self._second.frame.pack(side=tk.LEFT, padx=6, fill=tk.Y)
        else:
            self._second.frame.pack(side=tk.LEFT, padx=6, fill=tk.Y)
            self._first.frame.pack(side=tk.LEFT, padx=6, fill=tk.Y)

        self._build_buttons()
        self.bind("<Escape>", lambda _e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

    def _crop_block(self, block, page_image) -> Optional[Image.Image]:
        if page_image is None:
            return None
        x1, y1, x2, y2 = block.box
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        iw, ih = page_image.size
        x1 = max(0, min(iw, x1)); x2 = max(0, min(iw, x2))
        y1 = max(0, min(ih, y1)); y2 = max(0, min(ih, y2))
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        return page_image.crop((x1, y1, x2, y2)).convert("RGB")

    def _build_buttons(self) -> None:
        btns = tk.Frame(self, padx=10, pady=8)
        btns.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Button(btns, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)
        tk.Button(
            btns, text="Split", command=self._on_confirm, default=tk.ACTIVE
        ).pack(side=tk.RIGHT, padx=6)

    def _on_confirm(self) -> None:
        v = self._block.vertical
        # Pieces are stored in list order: first then second.
        self.pieces = [
            (self._first.result_lines(), self._first.result_box(), v),
            (self._second.result_lines(), self._second.result_box(), v),
        ]
        self.result = True
        self.grab_release()
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = False
        self.grab_release()
        self.destroy()
