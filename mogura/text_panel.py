"""Right panel: displays and manages the mokuro text blocks of a page."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional

from .icons import get_icon
from .mokuro import MokuroPage, TextBlock


class TextPanel(tk.Frame):
    """Scrollable list of editable text blocks for the current page."""

    NORMAL_BG = "#f0f0f0"
    SELECTED_BG = "#d6e4f5"

    def __init__(
        self,
        master,
        on_block_edited: Optional[Callable[[int, str], None]] = None,
        on_block_selected: Optional[Callable[[int], None]] = None,
        on_blocks_changed: Optional[Callable[[], None]] = None,
        on_add_requested: Optional[Callable[[], None]] = None,
        on_edit_requested: Optional[Callable[[int], None]] = None,
        on_combine_requested: Optional[Callable[[List[int]], None]] = None,
        on_split_requested: Optional[Callable[[int], None]] = None,
        on_box_edit_requested: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        super().__init__(master, bg=self.NORMAL_BG, **kwargs)
        self._on_block_edited = on_block_edited
        self._on_block_selected = on_block_selected
        # Called whenever the set/order of blocks changes (add/remove/reorder),
        # so the rest of the app can refresh boxes, counts, etc.
        self._on_blocks_changed = on_blocks_changed
        # Called when the user presses "Add"; the app drives the draw-a-box
        # flow and calls back into ``add_block_with_box`` once complete.
        self._on_add_requested = on_add_requested
        # Called when the user presses a row's edit button; the app opens the
        # detailed edit dialog (it has the page image needed for the preview).
        self._on_edit_requested = on_edit_requested
        # Called when the user presses the combine button with >=2 items
        # checked; the app opens the combine dialog.
        self._on_combine_requested = on_combine_requested
        # Called when the user presses split with one item selected.
        self._on_split_requested = on_split_requested
        # Called when the user presses the move/resize box button.
        self._on_box_edit_requested = on_box_edit_requested

        # State used by the toolbar; initialized before it is built.
        self._page: Optional[MokuroPage] = None
        self._selected: Optional[int] = None
        self._check_vars: List[tk.BooleanVar] = []

        self._build_toolbar()

        self.canvas = tk.Canvas(
            self, highlightthickness=0, bg=self.NORMAL_BG
        )
        self.scrollbar = tk.Scrollbar(
            self, orient=tk.VERTICAL, command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = tk.Frame(self.canvas, bg=self.NORMAL_BG)
        self._inner_id = self.canvas.create_window(
            (0, 0), window=self._inner, anchor=tk.NW
        )
        self._inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_scroll(self.canvas)

        self._block_widgets: List[tk.Text] = []
        self._rows: List[tk.Frame] = []
        self._warn_markers: List[tk.Label] = []
        self._empty_label: Optional[tk.Label] = None

        self.show_page(None)

    # --------------------------------------------------------------- toolbar
    def _build_toolbar(self) -> None:
        bar = tk.Frame(self, bd=1, relief=tk.RAISED, bg=self.NORMAL_BG)
        bar.pack(side=tk.TOP, fill=tk.X)

        self._tool_buttons: List[tk.Button] = []
        specs = [
            ("add", "＋", self.add_block, "Add text item"),
            ("delete", "🗑", self.remove_selected_block, "Remove selected item"),
            ("up", "▲", self.move_selected_up, "Move item up"),
            ("down", "▼", self.move_selected_down, "Move item down"),
            ("join", "⧉", self._request_combine, "Combine checked items"),
            ("split", "⇔", self._request_split, "Split selected item"),
            ("select", "❖", self._request_box_edit, "Move/resize selected box"),
        ]
        for icon_name, fallback, command, _tip in specs:
            photo = get_icon(icon_name, size=18)
            if photo is not None:
                btn = tk.Button(bar, image=photo, command=command)
                btn._icon = photo  # keep a reference alive
            else:
                btn = tk.Button(
                    bar, text=fallback, command=command,
                    font=("TkDefaultFont", 11),
                )
            btn.pack(side=tk.LEFT, padx=2, pady=2)
            self._tool_buttons.append(btn)

        self._update_toolbar_state()

    def _update_toolbar_state(self) -> None:
        """Enable/disable toolbar buttons based on current selection/page."""
        has_page = self._page is not None
        has_sel = self._selected is not None
        count = len(self._page.blocks) if self._page is not None else 0
        # Buttons: [add, delete, up, down, combine, split, box-edit]
        (add_btn, del_btn, up_btn, down_btn, combine_btn, split_btn,
         box_edit_btn) = self._tool_buttons
        add_btn.config(state=tk.NORMAL if has_page else tk.DISABLED)
        del_btn.config(state=tk.NORMAL if has_sel else tk.DISABLED)
        up_btn.config(
            state=tk.NORMAL if has_sel and self._selected > 0 else tk.DISABLED
        )
        down_btn.config(
            state=tk.NORMAL
            if has_sel and self._selected is not None and self._selected < count - 1
            else tk.DISABLED
        )
        # Combine needs at least two checked items.
        combine_btn.config(
            state=tk.NORMAL if len(self.checked_indices()) >= 2 else tk.DISABLED
        )
        # Split and box-edit act on the single selected item.
        split_btn.config(state=tk.NORMAL if has_sel else tk.DISABLED)
        box_edit_btn.config(state=tk.NORMAL if has_sel else tk.DISABLED)

    def checked_indices(self) -> List[int]:
        """Indices of blocks whose multi-select checkbox is ticked."""
        return [i for i, v in enumerate(self._check_vars) if v.get()]

    def _on_check_toggled(self) -> None:
        self._update_toolbar_state()

    def _request_combine(self) -> None:
        """Ask the app to combine the checked items."""
        if self._on_combine_requested is not None:
            self._on_combine_requested(self.checked_indices())

    def _request_split(self) -> None:
        """Ask the app to split the currently selected item."""
        if self._selected is None:
            return
        self._commit_block(self._selected)
        if self._on_split_requested is not None:
            self._on_split_requested(self._selected)

    def _request_box_edit(self) -> None:
        """Ask the app to toggle move/resize for the selected box."""
        if self._on_box_edit_requested is not None:
            self._on_box_edit_requested()

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
        self._block_widgets.clear()
        self._rows.clear()
        self._check_vars.clear()
        self._warn_markers.clear()
        self._empty_label = None

    def show_page(self, page: Optional[MokuroPage]) -> None:
        """Render the text blocks of ``page`` (or an empty-state message)."""
        self.clear()
        self._page = page
        self._selected = None

        if page is None or not page.blocks:
            msg = (
                "No text data."
                if page is None
                else "No text blocks on this page."
            )
            self._empty_label = tk.Label(
                self._inner, text=msg, bg=self.NORMAL_BG, fg="#999999"
            )
            self._empty_label.pack(pady=10)
            self.canvas.yview_moveto(0)
            self._update_toolbar_state()
            return

        for i, block in enumerate(page.blocks):
            self._build_block_row(i, block)
        self.canvas.yview_moveto(0)
        self._update_toolbar_state()

    def _build_block_row(self, index: int, block: TextBlock) -> None:
        row = tk.Frame(
            self._inner, bg=self.NORMAL_BG, bd=1, relief=tk.SOLID, padx=4, pady=4
        )
        row.pack(fill=tk.X, padx=6, pady=4)

        orientation = "vertical" if block.vertical else "horizontal"
        header_row = tk.Frame(row, bg=self.NORMAL_BG)
        header_row.pack(fill=tk.X)

        # Multi-select checkbox (independent of single-click selection).
        check_var = tk.BooleanVar(value=False)
        check = tk.Checkbutton(
            header_row,
            variable=check_var,
            bg=self.NORMAL_BG,
            activebackground=self.NORMAL_BG,
            command=self._on_check_toggled,
        )
        check._is_overlay = True  # type: ignore[attr-defined]
        check.pack(side=tk.LEFT)
        self._check_vars.append(check_var)

        header = tk.Label(
            header_row,
            text=f"Block {index + 1}  ({orientation})",
            bg=self.NORMAL_BG,
            fg="#666666",
            font=("TkDefaultFont", 8),
            anchor=tk.W,
        )
        header.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Overlap warning marker, shown only when this block overlaps another.
        warn_icon = get_icon("warning2", size=14)
        if warn_icon is not None:
            warn = tk.Label(header_row, image=warn_icon, bg=self.NORMAL_BG, bd=0)
            warn._icon = warn_icon  # keep reference
        else:
            warn = tk.Label(
                header_row, text="\u26a0", bg=self.NORMAL_BG, fg="#c9a000"
            )
        # Not packed yet; shown via set_overlaps().
        self._warn_markers.append(warn)

        edit_icon = get_icon("edit", size=14)
        if edit_icon is not None:
            edit_btn = tk.Button(
                header_row, image=edit_icon,
                command=lambda i=index: self._request_edit(i),
            )
            edit_btn._icon = edit_icon  # keep reference
        else:
            edit_btn = tk.Button(
                header_row, text="Edit",
                command=lambda i=index: self._request_edit(i),
            )
        edit_btn.pack(side=tk.RIGHT)

        text = tk.Text(row, height=max(1, len(block.lines)), wrap=tk.WORD)
        text.insert("1.0", block.text)
        text.pack(fill=tk.X)
        text.bind("<FocusOut>", lambda _e, i=index: self._commit_block(i))
        # Focusing the text box (clicking into it) also selects the block.
        text.bind("<FocusIn>", lambda _e, i=index: self._select_from_ui(i))

        # Clicking the row or its header selects the block.
        for widget in (row, header_row, header):
            widget.bind("<Button-1>", lambda _e, i=index: self._select_from_ui(i))

        self._bind_scroll(header)
        self._rows.append(row)
        self._block_widgets.append(text)

    def _select_from_ui(self, index: int) -> None:
        """Handle a selection originating from a click inside the panel."""
        self.set_selected(index)
        if self._on_block_selected is not None:
            self._on_block_selected(index)

    def _request_edit(self, index: int) -> None:
        """Open the detailed edit dialog for a block (via the app)."""
        self.set_selected(index)
        if self._on_block_selected is not None:
            self._on_block_selected(index)
        # Commit the inline edit so the dialog sees the latest text.
        self._commit_block(index)
        if self._on_edit_requested is not None:
            self._on_edit_requested(index)

    def refresh(self) -> None:
        """Rebuild rows for the current page, preserving the selection."""
        sel = self._selected
        self.show_page(self._page)
        if sel is not None:
            self.set_selected(sel)

    def commit_pending(self) -> None:
        """Commit any in-progress text edits back into the model.

        Called before saving so unfocused edits in the text widgets are not
        lost.
        """
        for i in range(len(self._block_widgets)):
            self._commit_block(i)

    def _commit_block(self, index: int) -> None:
        """Push edited text back into the model."""
        if self._page is None or index >= len(self._block_widgets):
            return
        widget = self._block_widgets[index]
        content = widget.get("1.0", "end-1c")
        block = self._page.blocks[index]
        new_lines = content.split("\n")
        if new_lines != block.lines:
            block.lines = new_lines
            if self._on_block_edited is not None:
                self._on_block_edited(index, content)

    def set_overlaps(self, indices) -> None:
        """Show the overlap marker on the given block indices (a set/list)."""
        flagged = set(indices or [])
        for i, marker in enumerate(self._warn_markers):
            if i in flagged:
                marker.pack(side=tk.RIGHT, padx=(0, 4))
            else:
                marker.pack_forget()

    @property
    def selected_index(self) -> Optional[int]:
        return self._selected

    def set_selected(self, index: Optional[int]) -> None:
        """Highlight the given block row and scroll it into view."""
        self._selected = index
        for i, row in enumerate(self._rows):
            color = self.SELECTED_BG if i == index else self.NORMAL_BG
            row.configure(bg=color)
            for child in row.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(bg=color)
        if index is not None and 0 <= index < len(self._rows):
            self._scroll_into_view(index)
        self._update_toolbar_state()

    def _scroll_into_view(self, index: int) -> None:
        self.update_idletasks()
        row = self._rows[index]
        inner_height = self._inner.winfo_height() or 1
        self.canvas.yview_moveto(max(0.0, row.winfo_y() / inner_height))

    # ------------------------------------------------------------ block edits
    def _rerender(self, select: Optional[int]) -> None:
        """Rebuild the rows for the current page and restore a selection."""
        page = self._page
        self.show_page(page)
        if select is not None and page is not None and page.blocks:
            select = max(0, min(select, len(page.blocks) - 1))
            self.set_selected(select)
        if self._on_blocks_changed is not None:
            self._on_blocks_changed()

    def add_block(self) -> None:
        """Begin adding a new text block.

        The actual insertion happens in :meth:`add_block_with_box` once the
        user has drawn a rectangle on the page. If no callback is wired, this
        is a no-op.
        """
        if self._page is None:
            return
        if self._on_add_requested is not None:
            self._on_add_requested()

    def apply_combine(
        self, indices: List[int], lines: List[str], box: list, vertical: bool
    ) -> None:
        """Replace the blocks at ``indices`` with one combined block.

        The combined block takes the corrected ``lines``, ``box``, and
        ``vertical`` orientation. It is inserted at the position of the first
        (topmost) removed block; the others are deleted.
        """
        if self._page is None or len(indices) < 2:
            return
        self.commit_pending()
        ordered = sorted(indices)
        insert_at = ordered[0]
        combined = TextBlock(
            box=list(box), vertical=vertical, font_size=0, lines=list(lines)
        )
        # Remove from the end so earlier indices stay valid.
        for i in reversed(ordered):
            if 0 <= i < len(self._page.blocks):
                del self._page.blocks[i]
        self._page.blocks.insert(insert_at, combined)
        self._rerender(select=insert_at)

    def apply_split(self, index: int, pieces: List[tuple]) -> None:
        """Replace the block at ``index`` with the given ``pieces``.

        Each piece is a ``(lines, box, vertical)`` tuple. The original block is
        removed and the pieces are inserted in order at its position.
        """
        if self._page is None or not (0 <= index < len(self._page.blocks)):
            return
        if not pieces:
            return
        self.commit_pending()
        del self._page.blocks[index]
        for offset, (lines, box, vertical) in enumerate(pieces):
            block = TextBlock(
                box=list(box), vertical=vertical, font_size=0, lines=list(lines)
            )
            self._page.blocks.insert(index + offset, block)
        self._rerender(select=index)

    def add_block_with_box(self, box: list) -> None:
        """Insert a new text block with the given ``[x1, y1, x2, y2]`` box."""
        if self._page is None:
            return
        # Commit any pending edit first so it isn't lost on rebuild.
        if self._selected is not None:
            self._commit_block(self._selected)
        insert_at = (
            self._selected + 1 if self._selected is not None
            else len(self._page.blocks)
        )
        # Guess orientation from the box shape: taller than wide => vertical.
        x1, y1, x2, y2 = box
        vertical = (y2 - y1) > (x2 - x1)
        new_block = TextBlock(
            box=list(box), vertical=vertical, font_size=0, lines=[""]
        )
        self._page.blocks.insert(insert_at, new_block)
        self._rerender(select=insert_at)

    def remove_selected_block(self) -> None:
        """Remove the currently selected text block."""
        if self._page is None or self._selected is None:
            return
        index = self._selected
        if not (0 <= index < len(self._page.blocks)):
            return
        del self._page.blocks[index]
        # Select the item that shifts into this slot, or the new last item.
        new_sel = None
        if self._page.blocks:
            new_sel = min(index, len(self._page.blocks) - 1)
        self._rerender(select=new_sel)

    def move_selected_up(self) -> None:
        self._move_selected(-1)

    def move_selected_down(self) -> None:
        self._move_selected(1)

    def _move_selected(self, delta: int) -> None:
        if self._page is None or self._selected is None:
            return
        i = self._selected
        j = i + delta
        blocks = self._page.blocks
        if not (0 <= j < len(blocks)):
            return
        if self._selected is not None:
            self._commit_block(self._selected)
        blocks[i], blocks[j] = blocks[j], blocks[i]
        self._rerender(select=j)
