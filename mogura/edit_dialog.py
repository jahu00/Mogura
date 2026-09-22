"""Detailed edit dialog for a single mokuro text block.

Shows, at the top, the original image region covered by the block's bounding
box beside an approximate render of the stored text. The relative placement
follows the writing direction:

* vertical text  -> original on the left, render on the right
* horizontal text -> original on the top, render on the bottom

Below that, the user can edit the text, toggle orientation, and edit the
bounding box coordinates. Changes are applied to the block on OK.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Optional

from PIL import Image, ImageTk

from .mokuro import TextBlock
from .text_render import render_text

# Size of the comparison preview panes (px).
_PREVIEW = 220


class EditBlockDialog(tk.Toplevel):
    """Modal dialog to edit a single text block's text, orientation, and box."""

    def __init__(self, master, block: TextBlock, page_image: Optional[Image.Image]):
        super().__init__(master)
        self.title(f"Edit Text Item")
        self.transient(master)
        self.resizable(False, False)

        self._block = block
        self._page_image = page_image
        self.result = False  # set True if applied

        # Tk variables for the editable fields.
        self._vertical_var = tk.BooleanVar(value=block.vertical)
        x1, y1, x2, y2 = (block.box + [0, 0, 0, 0])[:4]
        self._box_vars = [tk.IntVar(value=int(v)) for v in (x1, y1, x2, y2)]

        # Keep references to PhotoImages so they survive.
        self._photos: list = []

        self._build_preview()
        self._build_editors()
        self._build_buttons()

        self._refresh_preview()

        self.bind("<Escape>", lambda _e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

    # --------------------------------------------------------------- preview
    def _build_preview(self) -> None:
        self._preview_frame = tk.Frame(self, padx=10, pady=10)
        self._preview_frame.pack(side=tk.TOP, fill=tk.X)

        # Two labeled panes; their arrangement is set in _refresh_preview.
        self._orig_pane = tk.Frame(self._preview_frame)
        self._render_pane = tk.Frame(self._preview_frame)

        tk.Label(self._orig_pane, text="Original", fg="#666666").pack()
        self._orig_image_label = tk.Label(
            self._orig_pane, bd=1, relief=tk.SOLID, bg="#dddddd"
        )
        self._orig_image_label.pack()

        tk.Label(self._render_pane, text="Render", fg="#666666").pack()
        self._render_image_label = tk.Label(
            self._render_pane, bd=1, relief=tk.SOLID, bg="#ffffff"
        )
        self._render_image_label.pack()

    def _reflow_preview(self) -> None:
        """Place the two panes according to the current orientation."""
        self._orig_pane.pack_forget()
        self._render_pane.pack_forget()
        if self._vertical_var.get():
            # Vertical: original on the left, render on the right.
            self._orig_pane.pack(side=tk.LEFT, padx=8)
            self._render_pane.pack(side=tk.LEFT, padx=8)
        else:
            # Horizontal: original on top, render on the bottom.
            self._orig_pane.pack(side=tk.TOP, pady=4)
            self._render_pane.pack(side=tk.TOP, pady=4)

    def _current_box(self):
        return [v.get() for v in self._box_vars]

    def _current_lines(self):
        return self._text.get("1.0", "end-1c").split("\n")

    def _refresh_preview(self) -> None:
        self._reflow_preview()
        self._photos.clear()
        vertical = self._vertical_var.get()
        box = self._current_box()

        # Original cropped region.
        orig = self._crop_original(box)
        if orig is not None:
            orig_fit = self._fit(orig, _PREVIEW)
            photo = ImageTk.PhotoImage(orig_fit)
            self._photos.append(photo)
            self._orig_image_label.config(image=photo, text="")
        else:
            self._orig_image_label.config(image="", text="(no image)")

        # Rendered text, sized to match the box aspect where sensible.
        x1, y1, x2, y2 = box
        bw, bh = max(1, x2 - x1), max(1, y2 - y1)
        rw, rh = self._fit_dims(bw, bh, _PREVIEW)
        render = render_text(self._current_lines(), vertical, rw, rh)
        rphoto = ImageTk.PhotoImage(render)
        self._photos.append(rphoto)
        self._render_image_label.config(image=rphoto, text="")

    def _crop_original(self, box) -> Optional[Image.Image]:
        if self._page_image is None:
            return None
        x1, y1, x2, y2 = box
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        iw, ih = self._page_image.size
        x1 = max(0, min(iw, x1)); x2 = max(0, min(iw, x2))
        y1 = max(0, min(ih, y1)); y2 = max(0, min(ih, y2))
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        return self._page_image.crop((x1, y1, x2, y2)).convert("RGB")

    @staticmethod
    def _fit_dims(w: int, h: int, box: int):
        scale = min(box / w, box / h, 1.0) if w and h else 1.0
        # Ensure a reasonable minimum so tall/thin boxes remain visible.
        return (max(20, int(w * scale)), max(20, int(h * scale)))

    def _fit(self, image: Image.Image, box: int) -> Image.Image:
        image = image.copy()
        image.thumbnail((box, box), Image.LANCZOS)
        return image

    # --------------------------------------------------------------- editors
    def _build_editors(self) -> None:
        editors = tk.Frame(self, padx=10, pady=6)
        editors.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Text editor.
        tk.Label(editors, text="Text (one line per row):", anchor=tk.W).pack(
            fill=tk.X
        )
        self._text = tk.Text(editors, height=5, width=40, wrap=tk.NONE)
        self._text.insert("1.0", "\n".join(self._block.lines))
        self._text.pack(fill=tk.X, pady=(0, 6))
        self._text.bind("<KeyRelease>", lambda _e: self._refresh_preview())

        # Orientation.
        orient = tk.Frame(editors)
        orient.pack(fill=tk.X, pady=2)
        tk.Label(orient, text="Orientation:").pack(side=tk.LEFT)
        tk.Radiobutton(
            orient, text="Horizontal", variable=self._vertical_var,
            value=False, command=self._refresh_preview,
        ).pack(side=tk.LEFT)
        tk.Radiobutton(
            orient, text="Vertical", variable=self._vertical_var,
            value=True, command=self._refresh_preview,
        ).pack(side=tk.LEFT)

        # Bounding box.
        boxf = tk.Frame(editors)
        boxf.pack(fill=tk.X, pady=4)
        tk.Label(boxf, text="Box:").pack(side=tk.LEFT)
        for label, var in zip(("x1", "y1", "x2", "y2"), self._box_vars):
            tk.Label(boxf, text=label).pack(side=tk.LEFT, padx=(6, 1))
            entry = tk.Spinbox(boxf, from_=0, to=100000, width=6, textvariable=var)
            entry.pack(side=tk.LEFT)
            var.trace_add("write", lambda *_a: self._refresh_preview())

    # --------------------------------------------------------------- buttons
    def _build_buttons(self) -> None:
        btns = tk.Frame(self, padx=10, pady=8)
        btns.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Button(btns, text="Cancel", command=self._on_cancel).pack(
            side=tk.RIGHT
        )
        tk.Button(btns, text="OK", command=self._on_ok, default=tk.ACTIVE).pack(
            side=tk.RIGHT, padx=6
        )

    def _on_ok(self) -> None:
        box = self._current_box()
        x1, y1, x2, y2 = box
        if x2 <= x1 or y2 <= y1:
            messagebox.showerror(
                "Invalid box",
                "Bounding box must have x2 > x1 and y2 > y1.",
                parent=self,
            )
            return
        # Apply changes to the block.
        self._block.lines = self._current_lines()
        self._block.vertical = self._vertical_var.get()
        self._block.box = box
        self.result = True
        self.grab_release()
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = False
        self.grab_release()
        self.destroy()
