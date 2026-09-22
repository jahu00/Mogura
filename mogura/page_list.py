"""Left panel: scrollable list of page thumbnails used for navigation."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional

from PIL import ImageTk

from .icons import get_icon
from .page_source import PageSource


class PageList(tk.Frame):
    """Scrollable vertical list of page thumbnails.

    Clicking a thumbnail invokes the ``on_select`` callback with the page
    index. The currently selected page is highlighted.
    """

    THUMB_SIZE = 140
    SELECTED_BG = "#3d6fb4"
    NORMAL_BG = "#f0f0f0"

    def __init__(self, master, on_select: Callable[[int], None], **kwargs):
        super().__init__(master, **kwargs)
        self._on_select = on_select

        self.canvas = tk.Canvas(self, highlightthickness=0, width=self.THUMB_SIZE + 40)
        self.scrollbar = tk.Scrollbar(
            self, orient=tk.VERTICAL, command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = tk.Frame(self.canvas)
        self._inner_id = self.canvas.create_window(
            (0, 0), window=self._inner, anchor=tk.NW
        )

        self._inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_scroll(self.canvas)

        # Keep references to PhotoImages so they are not garbage collected.
        self._thumbs: List[ImageTk.PhotoImage] = []
        self._items: List[tk.Frame] = []
        self._count_labels: List[tk.Label] = []
        self._warn_labels: List[tk.Label] = []
        self._selected: Optional[int] = None

    # ------------------------------------------------------------- scrolling
    def _bind_scroll(self, widget) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        widget.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _on_inner_configure(self, _event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._inner_id, width=event.width)

    # ---------------------------------------------------------------- content
    def clear(self) -> None:
        for child in self._inner.winfo_children():
            child.destroy()
        self._thumbs.clear()
        self._items.clear()
        self._count_labels.clear()
        self._warn_labels.clear()
        self._selected = None

    def populate(self, archive: PageSource) -> None:
        """Build thumbnail rows for every page in the archive."""
        self.clear()
        for index in range(archive.page_count):
            thumb, (width, height) = archive.load_thumbnail_with_size(
                index, self.THUMB_SIZE
            )
            photo = ImageTk.PhotoImage(thumb)
            self._thumbs.append(photo)

            row = tk.Frame(self._inner, bg=self.NORMAL_BG, padx=4, pady=4)
            row.pack(fill=tk.X, padx=4, pady=2)

            # Container holding the thumbnail, so the resolution label can be
            # placed on top of it in the upper-right corner.
            holder = tk.Frame(row, bg=self.NORMAL_BG)
            holder.pack()

            label = tk.Label(holder, image=photo, bg=self.NORMAL_BG, bd=0)
            label.pack()

            resolution = tk.Label(
                holder,
                text=f"{width}x{height}",
                bg="#000000",
                fg="#ffffff",
                font=("TkDefaultFont", 7),
                padx=3,
                pady=1,
            )
            # Overlay in the top-right corner of the thumbnail.
            resolution.place(relx=1.0, rely=0.0, anchor=tk.NE)
            # Marker so selection highlighting leaves this overlay untouched.
            resolution._is_overlay = True  # type: ignore[attr-defined]

            # Text-item count overlay in the lower-right corner. Hidden until a
            # count is provided via ``set_text_counts``.
            count = tk.Label(
                holder,
                text="",
                bg="#1b5e20",
                fg="#ffffff",
                font=("TkDefaultFont", 7),
                padx=3,
                pady=1,
            )
            count._is_overlay = True  # type: ignore[attr-defined]
            self._count_labels.append(count)

            # Warning overlay (overlapping boxes) in the top-left corner.
            warn_icon = get_icon("warning", size=18)
            if warn_icon is not None:
                warn = tk.Label(holder, image=warn_icon, bg=self.NORMAL_BG, bd=0)
                warn._icon = warn_icon  # keep a reference alive
            else:
                warn = tk.Label(
                    holder,
                    text="\u26a0",
                    bg="#000000",
                    fg="#ffcc00",
                    font=("TkDefaultFont", 9),
                    padx=2,
                )
            warn._is_overlay = True  # type: ignore[attr-defined]
            self._warn_labels.append(warn)

            caption = tk.Label(
                row, text=f"{index + 1}", bg=self.NORMAL_BG, fg="#333333"
            )
            caption.pack()

            for widget in (row, holder, label, caption, resolution, count, warn):
                widget.bind(
                    "<Button-1>", lambda _e, i=index: self._on_select(i)
                )
                self._bind_scroll(widget)

            self._items.append(row)

        self.canvas.yview_moveto(0)

    def set_text_counts(self, counts: Optional[List[Optional[int]]]) -> None:
        """Show a text-item count on each thumbnail's lower-right corner.

        ``counts`` is a list parallel to the pages; an entry of ``None`` (or a
        list shorter than the page count) hides the overlay for that page.
        Passing ``None`` clears all counts.
        """
        for i, label in enumerate(self._count_labels):
            value = None
            if counts is not None and i < len(counts):
                value = counts[i]
            if value is None:
                label.place_forget()
            else:
                label.config(text=str(value))
                label.place(relx=1.0, rely=1.0, anchor=tk.SE)

    def set_warnings(self, warnings: Optional[List[bool]]) -> None:
        """Show a warning marker on pages flagged True (e.g. overlapping boxes).

        ``warnings`` is parallel to the pages. Passing ``None`` clears all.
        """
        for i, label in enumerate(self._warn_labels):
            flag = bool(warnings[i]) if warnings is not None and i < len(warnings) else False
            if flag:
                label.place(relx=0.0, rely=0.0, anchor=tk.NW)
            else:
                label.place_forget()

    def set_selected(self, index: int) -> None:
        """Highlight the given page and scroll it into view."""
        if self._selected is not None and 0 <= self._selected < len(self._items):
            self._set_row_bg(self._items[self._selected], self.NORMAL_BG)
        if 0 <= index < len(self._items):
            self._set_row_bg(self._items[index], self.SELECTED_BG)
            self._scroll_into_view(index)
        self._selected = index

    def _set_row_bg(self, row: tk.Frame, color: str) -> None:
        """Recolor a row and its children, skipping overlay labels."""
        def recolor(widget) -> None:
            if getattr(widget, "_is_overlay", False):
                return
            widget.configure(bg=color)
            for child in widget.winfo_children():
                recolor(child)

        recolor(row)

    def _scroll_into_view(self, index: int) -> None:
        self.update_idletasks()
        total = len(self._items)
        if total <= 1:
            return
        row = self._items[index]
        row_top = row.winfo_y()
        inner_height = self._inner.winfo_height() or 1
        self.canvas.yview_moveto(max(0.0, row_top / inner_height))
