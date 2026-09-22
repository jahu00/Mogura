"""Dialog for combining several mokuro text blocks into one.

Shows each source block's original image region with an approximate text
render overlaid in colour, lets the user correct the combined text, and
previews the resulting (naively unioned) bounding box. The user confirms or
cancels the merge.
"""

from __future__ import annotations

import tkinter as tk
from typing import List, Optional

from PIL import Image, ImageTk

from .mokuro import TextBlock
from .text_render import overlay_render_on_image

_THUMB = 160

# Overlay colours: sources use red, the combined result uses blue to tell them
# apart at a glance.
_SOURCE_COLOR = "#e53935"
_RESULT_COLOR = "#1e88e5"
_PREVIEW = 200


def union_box(boxes: List[list]) -> list:
    """Return the naive union of boxes: min of top-left, max of bottom-right."""
    xs1 = [b[0] for b in boxes]
    ys1 = [b[1] for b in boxes]
    xs2 = [b[2] for b in boxes]
    ys2 = [b[3] for b in boxes]
    return [min(xs1), min(ys1), max(xs2), max(ys2)]


class CombineDialog(tk.Toplevel):
    """Modal dialog to review and confirm combining several text blocks."""

    def __init__(
        self,
        master,
        blocks: List[TextBlock],
        page_image: Optional[Image.Image],
    ):
        super().__init__(master)
        self.title("Combine Text Items")
        self.transient(master)
        self.resizable(False, True)

        self._blocks = blocks
        self._page_image = page_image
        self.result = False
        self.combined_lines: List[str] = []
        self._union_box: list = union_box([b.box for b in blocks])
        self.combined_box: list = list(self._union_box)
        # Box source: -1 means the union of all sources; 0..n-1 selects the box
        # of that source block. Defaults to the union ("combine").
        self._box_source_var = tk.IntVar(value=-1)
        # Orientation: follow the majority; ties default to the first block.
        vote = sum(1 if b.vertical else -1 for b in blocks)
        self._vertical_var = tk.BooleanVar(
            value=(vote > 0) or (vote == 0 and blocks[0].vertical)
        )

        self._photos: list = []
        self._preview_photo = None

        self._build_sources()
        self._build_editor()
        self._build_preview()
        self._build_buttons()

        self._refresh_preview()

        self.bind("<Escape>", lambda _e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.grab_set()

    # --------------------------------------------------------------- sources
    def _build_sources(self) -> None:
        tk.Label(
            self,
            text="Sources (original with render overlaid in red):",
            anchor=tk.W,
        ).pack(fill=tk.X, padx=10, pady=(10, 2))

        strip = tk.Frame(self, padx=10)
        strip.pack(side=tk.TOP, fill=tk.X)

        for block in self._blocks:
            pane = tk.Frame(strip, padx=4)
            pane.pack(side=tk.LEFT)
            img = self._source_preview(block)
            if img is not None:
                photo = ImageTk.PhotoImage(img)
                self._photos.append(photo)
                tk.Label(pane, image=photo, bd=1, relief=tk.SOLID).pack()
            else:
                tk.Label(
                    pane, text="(no image)", width=12, height=6,
                    bd=1, relief=tk.SOLID, bg="#dddddd",
                ).pack()
            tk.Label(pane, text=block.text.replace("\n", " ") or "(empty)",
                     fg="#666666", wraplength=_THUMB).pack()

    def _source_preview(self, block: TextBlock) -> Optional[Image.Image]:
        if self._page_image is None:
            return None
        x1, y1, x2, y2 = block.box
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        iw, ih = self._page_image.size
        x1 = max(0, min(iw, x1)); x2 = max(0, min(iw, x2))
        y1 = max(0, min(ih, y1)); y2 = max(0, min(ih, y2))
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        crop = self._page_image.crop((x1, y1, x2, y2))
        composed = overlay_render_on_image(
            crop, block.lines, block.vertical, fg=_SOURCE_COLOR
        )
        composed.thumbnail((_THUMB, _THUMB), Image.LANCZOS)
        return composed

    # --------------------------------------------------------------- editor
    def _build_editor(self) -> None:
        editor = tk.Frame(self, padx=10, pady=6)
        editor.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        tk.Label(
            editor, text="Combined text (edit as needed):", anchor=tk.W
        ).pack(fill=tk.X)
        self._text = tk.Text(editor, height=6, width=44, wrap=tk.NONE)
        # Seed with each source's text stacked in order.
        seed = "\n".join(b.text for b in self._blocks)
        self._text.insert("1.0", seed)
        self._text.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self._text.bind("<KeyRelease>", lambda _e: self._refresh_preview())

        orient = tk.Frame(editor)
        orient.pack(fill=tk.X)
        tk.Label(orient, text="Orientation:").pack(side=tk.LEFT)
        tk.Radiobutton(
            orient, text="Horizontal", variable=self._vertical_var, value=False,
            command=self._refresh_preview,
        ).pack(side=tk.LEFT)
        tk.Radiobutton(
            orient, text="Vertical", variable=self._vertical_var, value=True,
            command=self._refresh_preview,
        ).pack(side=tk.LEFT)

        # Bounding box source selection.
        boxf = tk.Frame(editor)
        boxf.pack(fill=tk.X, pady=(6, 0))
        tk.Label(boxf, text="Bounding box:", anchor=tk.W).pack(fill=tk.X)
        ux1, uy1, ux2, uy2 = self._union_box
        tk.Radiobutton(
            boxf,
            text=f"Combine (union)  [{ux1}, {uy1}, {ux2}, {uy2}]",
            variable=self._box_source_var,
            value=-1,
            command=self._update_box_label,
        ).pack(anchor=tk.W)
        for i, block in enumerate(self._blocks):
            bx1, by1, bx2, by2 = block.box
            tk.Radiobutton(
                boxf,
                text=f"Item {i + 1}  [{bx1}, {by1}, {bx2}, {by2}]",
                variable=self._box_source_var,
                value=i,
                command=self._update_box_label,
            ).pack(anchor=tk.W)

        self._box_label = tk.Label(editor, fg="#666666", anchor=tk.W)
        self._box_label.pack(fill=tk.X, pady=(4, 0))
        self._update_box_label()

    def _selected_box(self) -> list:
        src = self._box_source_var.get()
        if src == -1 or not (0 <= src < len(self._blocks)):
            return list(self._union_box)
        return list(self._blocks[src].box)

    def _update_box_label(self) -> None:
        x1, y1, x2, y2 = self._selected_box()
        self._box_label.config(text=f"Resulting box: [{x1}, {y1}, {x2}, {y2}]")
        self._refresh_preview()

    # --------------------------------------------------------------- preview
    def _build_preview(self) -> None:
        frame = tk.Frame(self, padx=10, pady=4)
        frame.pack(side=tk.TOP, fill=tk.X)
        tk.Label(
            frame,
            text="Result preview (render overlaid in blue):",
            anchor=tk.W,
        ).pack(fill=tk.X)
        self._preview_label = tk.Label(frame, bd=1, relief=tk.SOLID, bg="#dddddd")
        self._preview_label.pack(anchor=tk.W, pady=2)

    def _current_lines(self) -> List[str]:
        return self._text.get("1.0", "end-1c").split("\n")

    def _result_preview(self) -> Optional[Image.Image]:
        if self._page_image is None:
            return None
        x1, y1, x2, y2 = self._selected_box()
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        iw, ih = self._page_image.size
        x1 = max(0, min(iw, x1)); x2 = max(0, min(iw, x2))
        y1 = max(0, min(ih, y1)); y2 = max(0, min(ih, y2))
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        crop = self._page_image.crop((x1, y1, x2, y2))
        composed = overlay_render_on_image(
            crop, self._current_lines(), self._vertical_var.get(), fg=_RESULT_COLOR
        )
        composed.thumbnail((_PREVIEW, _PREVIEW), Image.LANCZOS)
        return composed

    def _refresh_preview(self) -> None:
        # May be called from _update_box_label during editor construction,
        # before the preview widget exists.
        if not hasattr(self, "_preview_label"):
            return
        img = self._result_preview()
        if img is None:
            self._preview_photo = None
            self._preview_label.config(image="", text="(no image)")
            return
        self._preview_photo = ImageTk.PhotoImage(img)
        self._preview_label.config(image=self._preview_photo, text="")

    # --------------------------------------------------------------- buttons
    def _build_buttons(self) -> None:
        btns = tk.Frame(self, padx=10, pady=8)
        btns.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Button(btns, text="Cancel", command=self._on_cancel).pack(
            side=tk.RIGHT
        )
        tk.Button(
            btns, text="Combine", command=self._on_confirm, default=tk.ACTIVE
        ).pack(side=tk.RIGHT, padx=6)

    def _on_confirm(self) -> None:
        self.combined_lines = self._text.get("1.0", "end-1c").split("\n")
        self.combined_box = self._selected_box()
        self._vertical = self._vertical_var.get()
        self.result = True
        self.grab_release()
        self.destroy()

    @property
    def vertical(self) -> bool:
        return self._vertical_var.get()

    def _on_cancel(self) -> None:
        self.result = False
        self.grab_release()
        self.destroy()
