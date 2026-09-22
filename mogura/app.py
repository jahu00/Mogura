"""Main application window for the Mogura CBZ viewer / mokuro editor."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .cbz import CbzArchive
from .combine_dialog import CombineDialog
from .edit_dialog import EditBlockDialog
from .split_dialog import SplitDialog
from .icons import get_icon
from .mokuro import MokuroData
from .page_list import PageList
from .page_source import FolderSource, PageSource
from .page_view import PageView
from .settings import Settings
from .text_panel import TextPanel


class MoguraApp(tk.Tk):
    """Top-level window: menu, toolbar, collapsible side panels, page view."""

    def __init__(self):
        super().__init__()
        self.title("Mogura")
        self.geometry("1200x800")
        self.minsize(700, 500)

        self._settings = Settings()

        self._archive: Optional[PageSource] = None
        self._mokuro: Optional[MokuroData] = None
        # Whether the loaded mokuro data has unsaved changes.
        self._dirty: bool = False
        self._current_page: int = -1
        self._current_image = None
        # Filesystem path of the current source (CBZ file or folder), used to
        # locate a sibling mokuro file for auto-loading.
        self._source_path: Optional[str] = None

        self._left_visible = True
        self._right_visible = True

        self._build_menu()
        self._build_toolbar()
        self._build_body()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ menu
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="Open CBZ...", command=self.open_cbz, accelerator="Ctrl+O"
        )
        file_menu.add_command(
            label="Open Folder...", command=self.open_folder, accelerator="Ctrl+Shift+O"
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Open Mokuro...", command=self.open_mokuro, accelerator="Ctrl+M"
        )
        file_menu.add_command(
            label="Save Mokuro", command=self.save_mokuro, accelerator="Ctrl+S"
        )
        file_menu.add_command(
            label="Save Mokuro As...",
            command=self.save_mokuro_as,
            accelerator="Ctrl+Shift+S",
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(
            label="Toggle Pages Panel", command=self.toggle_left_panel
        )
        view_menu.add_command(
            label="Toggle Text Panel", command=self.toggle_right_panel
        )
        view_menu.add_separator()
        self._boxes_var = tk.BooleanVar(value=True)
        view_menu.add_checkbutton(
            label="Show Bounding Boxes",
            variable=self._boxes_var,
            command=self._on_boxes_menu_toggle,
        )
        menubar.add_cascade(label="View", menu=view_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        self._auto_load_var = tk.BooleanVar(
            value=self._settings.get("auto_load_mokuro")
        )
        settings_menu.add_checkbutton(
            label="Auto-load matching Mokuro file",
            variable=self._auto_load_var,
            command=self._on_auto_load_toggle,
        )
        menubar.add_cascade(label="Settings", menu=settings_menu)

        self.config(menu=menubar)
        self.bind_all("<Control-o>", lambda _e: self.open_cbz())
        self.bind_all("<Control-O>", lambda _e: self.open_folder())
        self.bind_all("<Control-m>", lambda _e: self.open_mokuro())
        self.bind_all("<Control-s>", lambda _e: self.save_mokuro())
        self.bind_all("<Control-S>", lambda _e: self.save_mokuro_as())
        self.bind_all("<Prior>", lambda _e: self.prev_page())  # Page Up
        self.bind_all("<Next>", lambda _e: self.next_page())   # Page Down

    # --------------------------------------------------------------- toolbar
    def _toolbar_button(
        self, toolbar, icon_name: str, fallback: str, command, tooltip: str
    ) -> tk.Button:
        """Create a toolbar button using a PNG icon, falling back to text."""
        photo = get_icon(icon_name, size=22)
        if photo is not None:
            btn = tk.Button(toolbar, image=photo, command=command)
            btn._icon = photo  # keep a reference alive
        else:
            btn = tk.Button(
                toolbar, text=fallback, command=command,
                font=("TkDefaultFont", 14),
            )
        btn.pack(side=tk.LEFT, padx=2, pady=2)
        return btn

    def _build_toolbar(self) -> None:
        toolbar = tk.Frame(self, bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self._toolbar_button(
            toolbar, "open", "📂", self.open_cbz, "Open CBZ"
        )
        self._toolbar_button(
            toolbar, "save", "💾", self.save_mokuro, "Save Mokuro"
        )
        tk.Frame(toolbar, width=1, bg="#c0c0c0").pack(
            side=tk.LEFT, fill=tk.Y, padx=4, pady=2
        )
        self._toolbar_button(
            toolbar, "left", "◀", self.prev_page, "Previous page"
        )
        self._toolbar_button(
            toolbar, "right", "▶", self.next_page, "Next page"
        )
        tk.Frame(toolbar, width=1, bg="#c0c0c0").pack(
            side=tk.LEFT, fill=tk.Y, padx=4, pady=2
        )
        self._toolbar_button(
            toolbar, "pages", "🗐", self.toggle_left_panel, "Toggle Pages"
        )
        self._toolbar_button(
            toolbar, "text", "💬", self.toggle_right_panel, "Toggle Text"
        )
        self._toolbar_button(
            toolbar, "bounding", "⬚", self.toggle_boxes, "Toggle Bounding Boxes"
        )

        # Zoom level indicator, docked to the far right. Clicking it toggles
        # between 100% and fit-to-window.
        self._zoom_label = tk.Label(
            toolbar,
            text="--",
            width=6,
            relief=tk.GROOVE,
            cursor="hand2",
            padx=4,
            pady=2,
        )
        self._zoom_label.pack(side=tk.RIGHT, padx=4, pady=2)
        self._zoom_label.bind("<Button-1>", lambda _e: self.toggle_zoom())

        self._toolbar = toolbar

    # ------------------------------------------------------------------ body
    def _build_body(self) -> None:
        # PanedWindow lets the user resize the panels by dragging the sashes.
        self._paned = tk.PanedWindow(
            self, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED
        )
        self._paned.pack(fill=tk.BOTH, expand=True)

        # Left panel ("Pages"): titled container wrapping the thumbnail list.
        self._left_panel = tk.Frame(self._paned, width=200)
        self._make_panel_title(self._left_panel, "Pages")
        self._page_list = PageList(self._left_panel, on_select=self.show_page)
        self._page_list.pack(fill=tk.BOTH, expand=True)

        self._center = PageView(
            self._paned,
            on_box_selected=self._on_box_selected,
            on_zoom_changed=self._on_zoom_changed,
            on_box_drawn=self._on_box_drawn,
            on_box_edited=self._on_box_edited_on_canvas,
        )

        # Right panel ("Text"): displays/manages mokuro text blocks.
        self._right_panel = tk.Frame(self._paned, width=200, bg="#f0f0f0")
        self._make_panel_title(self._right_panel, "Text")
        self._text_panel = TextPanel(
            self._right_panel,
            on_block_edited=self._on_block_edited,
            on_block_selected=self._on_block_selected,
            on_blocks_changed=self._on_blocks_changed,
            on_add_requested=self._on_add_requested,
            on_edit_requested=self._on_edit_requested,
            on_combine_requested=self._on_combine_requested,
            on_split_requested=self._on_split_requested,
            on_box_edit_requested=self.toggle_box_edit,
        )
        self._text_panel.pack(fill=tk.BOTH, expand=True)

        self._paned.add(self._left_panel, minsize=120, width=200)
        self._paned.add(self._center, minsize=300, stretch="always")
        self._paned.add(self._right_panel, minsize=120, width=200)

        self._status = tk.Label(self, text="No file loaded.", anchor=tk.W, bd=1,
                                relief=tk.SUNKEN)
        self._status.pack(side=tk.BOTTOM, fill=tk.X)

    def _make_panel_title(self, parent: tk.Frame, text: str) -> None:
        """Add a title header bar to the top of a panel."""
        header = tk.Label(
            parent,
            text=text,
            anchor=tk.W,
            bg="#dcdcdc",
            fg="#333333",
            font=("TkDefaultFont", 9, "bold"),
            padx=8,
            pady=4,
        )
        header.pack(side=tk.TOP, fill=tk.X)

    # ---------------------------------------------------------------- settings
    def _on_auto_load_toggle(self) -> None:
        self._settings.set("auto_load_mokuro", self._auto_load_var.get())

    # ----------------------------------------------------------- bounding box
    def toggle_boxes(self) -> None:
        """Toggle bounding box visibility (from the toolbar button)."""
        self._boxes_var.set(not self._boxes_var.get())
        self._apply_boxes_visibility()

    def _on_boxes_menu_toggle(self) -> None:
        """Handle the View menu checkbutton (already flipped the var)."""
        self._apply_boxes_visibility()

    def _apply_boxes_visibility(self) -> None:
        self._center.set_boxes_visible(self._boxes_var.get())

    # ------------------------------------------------------- box move/resize
    def toggle_box_edit(self) -> None:
        """Toggle move/resize handles on the selected bounding box."""
        if self._center.in_edit_mode:
            self._center.end_edit_mode()
            return
        if self._mokuro is None or self._text_panel.selected_index is None:
            self._status.config(text="Select a text item first to move/resize its box.")
            return
        self._center.begin_edit_mode()
        self._status.config(
            text="Drag the box to move it, or its handles to resize. "
            "Press the button again to finish."
        )

    def _on_box_edited_on_canvas(self, index: int, box) -> None:
        """The selected box was moved/resized on the canvas."""
        if self._mokuro is None or self._archive is None:
            return
        page = self._mokuro.page_for(self._archive.page_name(self._current_page))
        if page is None or not (0 <= index < len(page.blocks)):
            return
        page.blocks[index].box = [int(round(v)) for v in box]
        self._mark_dirty()
        self._update_text_counts()
        self._refresh_overlaps(page)

    # ---------------------------------------------------------------- zoom
    def _on_zoom_changed(self, scale: float) -> None:
        self._zoom_label.config(text=f"{round(scale * 100)}%")

    def toggle_zoom(self) -> None:
        """Toggle between 100% and fit-to-window."""
        if self._archive is None:
            return
        # If already at (approximately) 100%, fit; otherwise go to 100%.
        if abs(self._center.scale - 1.0) < 0.005:
            self._center.fit_to_window()
        else:
            self._center.zoom_to_actual()

    # ------------------------------------------------------------- panel show
    def toggle_left_panel(self) -> None:
        if self._left_visible:
            self._paned.forget(self._left_panel)
        else:
            self._paned.add(self._left_panel, minsize=120, width=200, before=self._center)
        self._left_visible = not self._left_visible

    def toggle_right_panel(self) -> None:
        if self._right_visible:
            self._paned.forget(self._right_panel)
        else:
            self._paned.add(self._right_panel, minsize=120, width=200)
        self._right_visible = not self._right_visible

    # ------------------------------------------------------------------ file
    def _initial_dir(self) -> Optional[str]:
        """Directory to seed file dialogs with (the last used one)."""
        last = self._settings.get("last_dir")
        return last if last and os.path.isdir(last) else None

    def _remember_dir(self, path: str) -> None:
        """Persist the directory of ``path`` for next time."""
        directory = path if os.path.isdir(path) else os.path.dirname(path)
        if directory:
            self._settings.set("last_dir", directory)

    def open_cbz(self) -> None:
        if not self._maybe_save_changes():
            return
        path = filedialog.askopenfilename(
            title="Open CBZ file",
            filetypes=[("Comic Book Archive", "*.cbz"), ("All files", "*.*")],
            initialdir=self._initial_dir(),
        )
        if not path:
            return
        self._remember_dir(path)
        self._load_source(lambda: CbzArchive(path), path, "Open CBZ")

    def open_folder(self) -> None:
        if not self._maybe_save_changes():
            return
        path = filedialog.askdirectory(
            title="Open folder of images", initialdir=self._initial_dir()
        )
        if not path:
            return
        self._remember_dir(path)
        self._load_source(lambda: FolderSource(path), path, "Open Folder")

    def open_mokuro(self) -> None:
        if not self._maybe_save_changes():
            return
        path = filedialog.askopenfilename(
            title="Open Mokuro file",
            filetypes=[("Mokuro file", "*.mokuro"), ("All files", "*.*")],
            initialdir=self._initial_dir(),
        )
        if not path:
            return
        self._remember_dir(path)
        if not self._load_mokuro(path):
            return
        if self._archive is None:
            messagebox.showinfo(
                "Mokuro loaded",
                "Text data loaded. Open the matching CBZ or image folder to "
                "view pages alongside the text.",
            )

    def _load_mokuro(self, path: str, silent_errors: bool = False) -> bool:
        """Load a mokuro file and refresh the text view. Returns success."""
        try:
            mokuro = MokuroData.load(path)
        except Exception as exc:  # noqa: BLE001
            if not silent_errors:
                messagebox.showerror("Failed to open Mokuro", str(exc))
            return False
        self._mokuro = mokuro
        self._set_dirty(False)
        # Refresh the current page so its text appears.
        if self._current_page >= 0:
            self._update_text_for_page(self._current_page)
        self._update_text_counts()
        self._status.config(
            text=f"Loaded mokuro: {mokuro.volume or os.path.basename(path)} "
            f"({len(mokuro.pages)} pages)"
        )
        return True

    # ------------------------------------------------------------------ save
    def save_mokuro(self) -> bool:
        """Save to the current mokuro path, prompting if none is set."""
        if self._mokuro is None:
            return False
        if not self._mokuro.path:
            return self.save_mokuro_as()
        return self._write_mokuro(self._mokuro.path)

    def save_mokuro_as(self) -> bool:
        """Prompt for a path and save the mokuro data there."""
        if self._mokuro is None:
            return False
        initial = self._mokuro.path or self._suggested_mokuro_path()
        initial_dir = os.path.dirname(initial) if initial else None
        if not initial_dir or not os.path.isdir(initial_dir):
            initial_dir = self._initial_dir()
        path = filedialog.asksaveasfilename(
            title="Save Mokuro As",
            defaultextension=".mokuro",
            filetypes=[("Mokuro file", "*.mokuro"), ("All files", "*.*")],
            initialfile=os.path.basename(initial) if initial else "",
            initialdir=initial_dir,
        )
        if not path:
            return False
        return self._write_mokuro(path)

    def _suggested_mokuro_path(self) -> str:
        """Suggest a mokuro path based on the current image source."""
        if self._source_path:
            root, _ext = os.path.splitext(self._source_path.rstrip("/"))
            return root + ".mokuro"
        return ""

    def _write_mokuro(self, path: str) -> bool:
        # Commit any in-progress text edit before serializing.
        self._text_panel.commit_pending()
        try:
            self._mokuro.save(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Failed to save Mokuro", str(exc))
            return False
        self._remember_dir(path)
        self._set_dirty(False)
        self._status.config(text=f"Saved: {path}")
        return True

    # ----------------------------------------------------------- dirty state
    def _mark_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._refresh_title()

    def _refresh_title(self) -> None:
        base = "Mogura"
        if self._source_path:
            name = os.path.basename(self._source_path.rstrip("/")) or self._source_path
            base = f"Mogura - {name}"
        self.title(("*" + base) if self._dirty else base)

    def _on_block_edited(self, _index: int, _content: str) -> None:
        self._mark_dirty()

    def _maybe_save_changes(self) -> bool:
        """If there are unsaved changes, ask to save/discard/cancel.

        Returns True if it is safe to proceed (saved or discarded), False if
        the user cancelled.
        """
        if not self._dirty or self._mokuro is None:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            "The mokuro text data has unsaved changes. Save before continuing?",
        )
        if answer is None:  # Cancel
            return False
        if answer:  # Yes -> save; block proceeding if the save fails
            return self.save_mokuro()
        return True  # No -> discard

    def _update_text_counts(self) -> None:
        """Refresh per-page text-item counts and overlap warnings."""
        if self._mokuro is None or self._archive is None:
            self._page_list.set_text_counts(None)
            self._page_list.set_warnings(None)
            return
        counts = []
        warnings = []
        for i in range(self._archive.page_count):
            page = self._mokuro.page_for(self._archive.page_name(i))
            counts.append(len(page.blocks) if page is not None else None)
            warnings.append(page.has_overlapping_boxes() if page is not None else False)
        self._page_list.set_text_counts(counts)
        self._page_list.set_warnings(warnings)

    def _sibling_mokuro_path(self, source_path: str) -> Optional[str]:
        """Return the path of a mokuro file matching the given source.

        A CBZ ``/x/manga.cbz`` matches ``/x/manga.mokuro``; a folder
        ``/x/manga`` matches ``/x/manga.mokuro``.
        """
        cleaned = source_path.rstrip("/")
        root, _ext = os.path.splitext(cleaned)
        candidate = root + ".mokuro"
        return candidate if os.path.isfile(candidate) else None

    def _load_source(self, factory, path: str, error_title: str) -> None:
        try:
            source = factory()
        except Exception as exc:  # noqa: BLE001 - present any failure to user
            messagebox.showerror(f"Failed to {error_title.lower()}", str(exc))
            return

        if self._archive is not None:
            self._archive.close()
        self._archive = source
        self._source_path = path
        # A new source invalidates any previously loaded text.
        self._mokuro = None
        self._set_dirty(False)

        self._status.config(text="Loading thumbnails...")
        self.update_idletasks()
        self._page_list.populate(source)

        self._refresh_title()
        self.show_page(0)

        self._maybe_auto_load_mokuro(path)

    def _maybe_auto_load_mokuro(self, source_path: str) -> None:
        """Auto-load a sibling mokuro file if the setting is enabled."""
        if not self._settings.get("auto_load_mokuro"):
            return
        sibling = self._sibling_mokuro_path(source_path)
        if sibling is not None:
            self._load_mokuro(sibling, silent_errors=True)

    def show_page(self, index: int) -> None:
        if self._archive is None:
            return
        if not (0 <= index < self._archive.page_count):
            return
        try:
            image = self._archive.load_image(index)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Failed to load page", str(exc))
            return
        # Commit any in-progress text edits for the current page before its
        # widgets are rebuilt for the new page, otherwise unfocused edits are
        # lost.
        self._text_panel.commit_pending()
        self._current_page = index
        self._current_image = image
        self._center.show_image(image)
        self._page_list.set_selected(index)
        self._update_text_for_page(index)
        self._status.config(
            text=f"Page {index + 1} / {self._archive.page_count}  -  "
            f"{self._archive.page_name(index)}"
        )

    def prev_page(self) -> None:
        if self._archive is not None and self._current_page > 0:
            self.show_page(self._current_page - 1)

    def next_page(self) -> None:
        if (
            self._archive is not None
            and self._current_page < self._archive.page_count - 1
        ):
            self.show_page(self._current_page + 1)

    def _update_text_for_page(self, index: int) -> None:
        """Show the mokuro text blocks associated with the given page."""
        if self._mokuro is None or self._archive is None:
            self._text_panel.show_page(None)
            self._center.set_boxes([])
            return
        img_name = self._archive.page_name(index)
        page = self._mokuro.page_for(img_name)
        self._text_panel.show_page(page)
        self._center.set_boxes([b.box for b in page.blocks] if page else [])
        self._refresh_overlaps(page)

    def _refresh_overlaps(self, page) -> None:
        """Update the per-item overlap markers in the Text panel."""
        if page is None:
            self._text_panel.set_overlaps(set())
            return
        self._text_panel.set_overlaps(page.overlapping_block_indices())

    # ------------------------------------------------------------- selection
    def _on_box_selected(self, index: int) -> None:
        """A bounding box was clicked in the page view."""
        self._text_panel.set_selected(index)

    def _on_block_selected(self, index: int) -> None:
        """A text block was selected in the right panel."""
        self._center.set_selected_box(index)

    def _on_add_requested(self) -> None:
        """User pressed Add: arm rectangle drawing on the page.

        Pressing Add again while already armed (i.e. before drawing a
        rectangle) cancels the operation.
        """
        if self._mokuro is None or self._archive is None:
            return
        if self._center.in_draw_mode:
            self._center.cancel_draw_mode()
            self._status.config(text="Adding text item cancelled.")
            return
        self._status.config(
            text="Draw a rectangle on the page to place the new text item "
            "(or press Add again to cancel)."
        )
        self._center.begin_draw_mode()

    def _on_box_drawn(self, box) -> None:
        """Rectangle drawing finished; ``box`` is None if cancelled/degenerate."""
        if box is None:
            self._status.config(text="Adding text item cancelled.")
            return
        self._text_panel.add_block_with_box(box)
        self._status.config(text="Text item added.")

    def _on_edit_requested(self, index: int) -> None:
        """Open the detailed edit dialog for the block at ``index``."""
        if self._mokuro is None or self._archive is None:
            return
        page = self._mokuro.page_for(self._archive.page_name(self._current_page))
        if page is None or not (0 <= index < len(page.blocks)):
            return
        block = page.blocks[index]
        dialog = EditBlockDialog(self, block, self._current_image)
        self.wait_window(dialog)
        if dialog.result:
            # The block was modified in place; refresh UI and mark dirty.
            self._mark_dirty()
            self._text_panel.refresh()
            self._center.set_boxes([b.box for b in page.blocks])
            self._center.set_selected_box(index)
            self._update_text_counts()
            self._refresh_overlaps(page)

    def _on_combine_requested(self, indices) -> None:
        """Open the combine dialog for the checked blocks and apply the merge."""
        if self._mokuro is None or self._archive is None or len(indices) < 2:
            return
        page = self._mokuro.page_for(self._archive.page_name(self._current_page))
        if page is None:
            return
        blocks = [page.blocks[i] for i in sorted(indices) if 0 <= i < len(page.blocks)]
        if len(blocks) < 2:
            return
        dialog = CombineDialog(self, blocks, self._current_image)
        self.wait_window(dialog)
        if not dialog.result:
            return
        self._text_panel.apply_combine(
            sorted(indices), dialog.combined_lines, dialog.combined_box, dialog.vertical
        )

    def _on_split_requested(self, index) -> None:
        """Open the split dialog for the selected block and apply the split."""
        if self._mokuro is None or self._archive is None:
            return
        page = self._mokuro.page_for(self._archive.page_name(self._current_page))
        if page is None or not (0 <= index < len(page.blocks)):
            return
        block = page.blocks[index]
        dialog = SplitDialog(self, block, self._current_image)
        self.wait_window(dialog)
        if not dialog.result:
            return
        self._text_panel.apply_split(index, dialog.pieces)

    def _on_blocks_changed(self) -> None:
        """Text blocks were added/removed/reordered in the right panel."""
        if self._mokuro is None or self._archive is None:
            return
        self._mark_dirty()
        page = self._mokuro.page_for(self._archive.page_name(self._current_page))
        self._center.set_boxes([b.box for b in page.blocks] if page else [])
        # Keep the box highlight in sync with the panel's selection.
        self._center.set_selected_box(self._text_panel.selected_index)
        self._update_text_counts()
        self._refresh_overlaps(page)

    # ------------------------------------------------------------------ close
    def _on_close(self) -> None:
        if not self._maybe_save_changes():
            return
        if self._archive is not None:
            self._archive.close()
        self.destroy()


def main() -> None:
    app = MoguraApp()
    app.mainloop()


if __name__ == "__main__":
    main()
