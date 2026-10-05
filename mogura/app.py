"""Main application window for the Mogura CBZ viewer / mokuro editor."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .cbz import CbzArchive
from .combine_dialog import CombineDialog
from .edit_dialog import EditBlockDialog
from .find_dialog import FindDialog
from .split_dialog import SplitDialog
from .icons import get_icon
from . import logging_setup, ocr
from .mokuro import MokuroData
from .page_list import PageList
from .page_source import FolderSource, PageSource
from .page_view import PageView
from .settings import Settings
from .settings_dialog import SettingsDialog
from .text_panel import TextPanel
from .tooltip import add_tooltip

# Optional drag-and-drop support via tkinterdnd2. If unavailable, the app runs
# normally without the drop feature.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _TkBase = TkinterDnD.Tk
    _DND_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import/runtime issue disables DnD
    _TkBase = tk.Tk
    _DND_AVAILABLE = False

_log = logging_setup.get_logger("app")


class MoguraApp(_TkBase):
    """Top-level window: menu, toolbar, collapsible side panels, page view."""

    def __init__(self):
        super().__init__()
        self.title("Mogura")
        self.geometry("1200x800")
        self.minsize(700, 500)

        self._settings = Settings()
        # Apply the saved OCR method to the dispatcher before any OCR runs.
        ocr.set_method(self._settings.get("ocr_method"))

        self._archive: Optional[PageSource] = None
        self._mokuro: Optional[MokuroData] = None
        # True when the loaded mokuro came from inside the current CBZ, so
        # saving writes it back into the archive.
        self._mokuro_in_cbz: bool = False
        # Whether the loaded mokuro data has unsaved changes.
        self._dirty: bool = False
        self._current_page: int = -1
        self._current_image = None
        # Filesystem path of the current source (CBZ file or folder), used to
        # locate a sibling mokuro file for auto-loading.
        self._source_path: Optional[str] = None

        self._left_visible = True
        self._right_visible = True

        # Find/replace state: the open dialog (if any) and the current match
        # position, tracked as (page_index, block_index, char_offset).
        self._find_dialog: Optional[FindDialog] = None
        self._find_match: Optional[tuple] = None

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._setup_drag_and_drop()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----------------------------------------------------------- drag & drop
    def _setup_drag_and_drop(self) -> None:
        """Register the central page area as a file drop target (if DnD is
        available). Dropping a CBZ or mokuro file opens it."""
        if not _DND_AVAILABLE:
            return
        try:
            for widget in (self._center, self._center.canvas):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_file_drop)
        except Exception:  # noqa: BLE001 - don't let DnD setup break startup
            pass

    def _on_file_drop(self, event) -> None:
        paths = self._parse_drop_paths(event.data)
        if not paths:
            return
        self._open_dropped_file(paths[0])

    @staticmethod
    def _parse_drop_paths(data: str):
        """Parse the platform drop string into a list of file paths.

        tkdnd joins multiple paths with spaces and wraps paths containing
        spaces in braces, e.g. ``{/a b/x.cbz} /c/y.mokuro``.
        """
        paths = []
        i = 0
        n = len(data)
        while i < n:
            if data[i] == " ":
                i += 1
                continue
            if data[i] == "{":
                j = data.find("}", i + 1)
                if j == -1:
                    paths.append(data[i + 1:])
                    break
                paths.append(data[i + 1:j])
                i = j + 1
            else:
                j = data.find(" ", i)
                if j == -1:
                    paths.append(data[i:])
                    break
                paths.append(data[i:j])
                i = j
        return paths

    def _open_dropped_file(self, path: str) -> None:
        """Open a dropped file by type (CBZ opens images, .mokuro opens text)."""
        lower = path.lower()
        if lower.endswith(".cbz"):
            if not self._maybe_save_changes():
                return
            self._remember_dir(path)
            self._load_source(lambda: CbzArchive(path), path, "Open CBZ")
        elif lower.endswith(".mokuro"):
            if self._archive is None:
                messagebox.showinfo(
                    "Open images first",
                    "Open a CBZ or image folder before dropping a mokuro file.",
                )
                return
            if not self._maybe_save_changes():
                return
            self._remember_dir(path)
            self._load_mokuro(path)
        else:
            self._status.config(
                text=f"Unsupported file dropped: {os.path.basename(path)}"
            )

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
            label="Create Mokuro Data", command=self.create_mokuro
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
        file_menu.add_command(label="Save CBZ...", command=self.save_cbz)
        file_menu.add_command(
            label="Export CBZ with Mokuro...", command=self.export_cbz
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(
            label="Find...", command=self.open_find, accelerator="Ctrl+F"
        )
        edit_menu.add_command(
            label="Find and Replace...",
            command=self.open_find_replace,
            accelerator="Ctrl+H",
        )
        menubar.add_cascade(label="Edit", menu=edit_menu)

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
        self._auto_create_var = tk.BooleanVar(
            value=self._settings.get("auto_create_mokuro")
        )
        settings_menu.add_checkbutton(
            label="Auto-create empty Mokuro data",
            variable=self._auto_create_var,
            command=self._on_auto_create_toggle,
        )
        settings_menu.add_separator()
        settings_menu.add_command(
            label="Options...", command=self.open_settings
        )
        menubar.add_cascade(label="Settings", menu=settings_menu)

        self.config(menu=menubar)
        self.bind_all("<Control-o>", lambda _e: self.open_cbz())
        self.bind_all("<Control-O>", lambda _e: self.open_folder())
        self.bind_all("<Control-m>", lambda _e: self.open_mokuro())
        self.bind_all("<Control-s>", lambda _e: self.save_mokuro())
        self.bind_all("<Control-S>", lambda _e: self.save_mokuro_as())
        self.bind_all("<Control-f>", lambda _e: self.open_find())
        self.bind_all("<Control-h>", lambda _e: self.open_find_replace())
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
        if tooltip:
            add_tooltip(btn, tooltip)
        # Remember the default look so toggle styling can be undone.
        btn._default_relief = btn.cget("relief")
        btn._default_bg = btn.cget("background")
        return btn

    # Background used to highlight a toggle button that is currently "on".
    TOGGLE_ACTIVE_BG = "#aaccee"

    def _set_toggle_active(self, btn, active: bool) -> None:
        """Give a toolbar toggle button a pressed-in look when active."""
        if active:
            btn.config(relief=tk.SUNKEN, background=self.TOGGLE_ACTIVE_BG)
        else:
            btn.config(
                relief=getattr(btn, "_default_relief", tk.RAISED),
                background=getattr(btn, "_default_bg", None),
            )

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
        self._pages_btn = self._toolbar_button(
            toolbar, "pages", "🗐", self.toggle_left_panel, "Toggle Pages"
        )
        self._text_btn = self._toolbar_button(
            toolbar, "text", "💬", self.toggle_right_panel, "Toggle Text"
        )
        self._boxes_btn = self._toolbar_button(
            toolbar, "bounding", "⬚", self.toggle_boxes, "Toggle Bounding Boxes"
        )

        # Reflect the initial on/off state of the toggle buttons.
        self._set_toggle_active(self._pages_btn, self._left_visible)
        self._set_toggle_active(self._text_btn, self._right_visible)
        self._set_toggle_active(self._boxes_btn, self._boxes_var.get())

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
        add_tooltip(self._zoom_label, "Toggle zoom (100% / fit)")

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
        self._page_list = PageList(
            self._left_panel,
            on_select=self.show_page,
            on_delete=self.delete_page,
        )
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
            on_ocr_requested=self._on_ocr_requested,
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

    def _on_auto_create_toggle(self) -> None:
        self._settings.set("auto_create_mokuro", self._auto_create_var.get())

    def open_settings(self) -> None:
        """Open the settings window (sections list + per-section options)."""
        dialog = SettingsDialog(
            self, self._settings, on_change=self._on_settings_changed
        )
        self.wait_window(dialog)

    def _on_settings_changed(self) -> None:
        """Re-apply view-affecting settings (e.g. overlap threshold) live."""
        self._update_text_counts()
        if self._mokuro is not None and self._archive is not None:
            page = self._mokuro.page_for(
                self._archive.page_name(self._current_page)
            )
            self._refresh_overlaps(page)

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
        self._set_toggle_active(self._boxes_btn, self._boxes_var.get())

    # ------------------------------------------------------- box move/resize
    def toggle_box_edit(self) -> None:
        """Toggle move/resize handles on the selected bounding box."""
        if self._center.in_edit_mode:
            self._center.end_edit_mode()
            self._sync_box_edit_button()
            return
        if self._mokuro is None or self._text_panel.selected_index is None:
            self._status.config(text="Select a text item first to move/resize its box.")
            return
        self._center.begin_edit_mode()
        self._sync_box_edit_button()
        self._status.config(
            text="Drag the box to move it, or its handles to resize. "
            "Press the button again to finish."
        )

    def _sync_box_edit_button(self) -> None:
        """Keep the move/resize button's look in step with the canvas state."""
        self._text_panel.set_box_edit_active(self._center.in_edit_mode)

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
        self._set_toggle_active(self._pages_btn, self._left_visible)

    def toggle_right_panel(self) -> None:
        if self._right_visible:
            self._paned.forget(self._right_panel)
        else:
            self._paned.add(self._right_panel, minsize=120, width=200)
        self._right_visible = not self._right_visible
        self._set_toggle_active(self._text_btn, self._right_visible)

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

    def create_mokuro(self) -> None:
        """Create empty mokuro data for the current image source.

        This lets the user annotate a CBZ/folder from scratch (draw boxes,
        OCR, type text) without first loading or having a ``.mokuro`` file.
        A page entry is created for every image, recording its dimensions, so
        the Add/OCR tools work on any page immediately.
        """
        if self._archive is None:
            messagebox.showinfo(
                "Open images first",
                "Open a CBZ or image folder before creating mokuro data.",
            )
            return
        # If existing data has real content, confirm before discarding it.
        # Empty data (e.g. auto-created) is treated as nothing to lose.
        if self._mokuro is not None and not self._mokuro.is_empty():
            if not messagebox.askyesno(
                "Replace mokuro data",
                "Text data is already loaded. Replace it with new, empty "
                "mokuro data? This discards the current text.",
                icon=messagebox.WARNING,
            ):
                return
            if not self._maybe_save_changes():
                return

        self._install_empty_mokuro()
        self._status.config(
            text=f"Created empty mokuro data ({len(self._mokuro.pages)} pages). "
            "Use Add to draw text boxes, then OCR or type the text."
        )

    def _install_empty_mokuro(self) -> None:
        """Build and install empty mokuro data for the current source.

        Creates a page entry for each image (recording its dimensions) and
        wires the data into the app. Empty data counts as "no changes", so the
        dirty flag is left clear until the user actually adds a block.
        """
        if self._archive is None:
            return
        title = ""
        if self._source_path:
            title = os.path.splitext(
                os.path.basename(self._source_path.rstrip("/"))
            )[0]

        mokuro = MokuroData.create_empty(title=title)
        for i in range(self._archive.page_count):
            name = self._archive.page_name(i)
            try:
                width, height = self._archive.image_size(i)
            except Exception:  # noqa: BLE001 - fall back to zero if unreadable
                width, height = 0, 0
            mokuro.ensure_page(name, width, height)

        self._mokuro = mokuro
        # New data is not tied to a file yet, nor embedded in the CBZ.
        self._mokuro_in_cbz = False
        self._set_dirty(False)
        if self._current_page >= 0:
            self._update_text_for_page(self._current_page)
        self._update_text_counts()

    def _load_mokuro(self, path: str, silent_errors: bool = False) -> bool:
        """Load a mokuro file and refresh the text view. Returns success."""
        _log.info("Loading mokuro: %s", path)
        try:
            mokuro = MokuroData.load(path)
        except Exception as exc:  # noqa: BLE001
            _log.error("Failed to load mokuro %s: %s", path, exc)
            if not silent_errors:
                messagebox.showerror("Failed to open Mokuro", str(exc))
            return False
        self._mokuro = mokuro
        # Loaded from a standalone file, not from inside the CBZ.
        self._mokuro_in_cbz = False
        self._set_dirty(False)
        # Refresh the current page so its text appears.
        if self._current_page >= 0:
            self._update_text_for_page(self._current_page)
        self._update_text_counts()
        _log.info(
            "Loaded mokuro '%s' (%d pages)",
            mokuro.volume or os.path.basename(path),
            len(mokuro.pages),
        )
        self._status.config(
            text=f"Loaded mokuro: {mokuro.volume or os.path.basename(path)} "
            f"({len(mokuro.pages)} pages)"
        )
        return True

    # ------------------------------------------------------------------ save
    def save_mokuro(self) -> bool:
        """Save the mokuro data.

        If it was loaded from inside the current CBZ, write it back into the
        archive. Otherwise write to its file path (prompting if none is set).
        """
        if self._mokuro is None:
            return False
        if self._mokuro_in_cbz:
            return self._write_mokuro_to_cbz(self._archive)
        if not self._mokuro.path:
            return self.save_mokuro_as()
        return self._write_mokuro(self._mokuro.path)

    def _write_mokuro_to_cbz(self, archive) -> bool:
        """Write the current mokuro back into ``archive`` (a CbzArchive)."""
        if not isinstance(archive, CbzArchive):
            return False
        self._text_panel.commit_pending()
        try:
            archive.write_mokuro(self._mokuro.to_json())
        except Exception as exc:  # noqa: BLE001
            _log.error("Failed to save mokuro into CBZ %s: %s", archive.path, exc)
            messagebox.showerror("Failed to save into CBZ", str(exc))
            return False
        self._set_dirty(False)
        _log.info("Saved mokuro into CBZ: %s", archive.path)
        self._status.config(text=f"Saved mokuro into {os.path.basename(archive.path)}")
        return True

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
            _log.error("Failed to save mokuro %s: %s", path, exc)
            messagebox.showerror("Failed to save Mokuro", str(exc))
            return False
        self._remember_dir(path)
        self._set_dirty(False)
        _log.info("Saved mokuro: %s", path)
        self._status.config(text=f"Saved: {path}")
        return True

    # ----------------------------------------------------------------- export
    def save_cbz(self) -> bool:
        """Save a new CBZ containing only the current pages (no mokuro file)."""
        if self._archive is None:
            messagebox.showinfo(
                "Nothing to save",
                "Open images before saving a CBZ.",
            )
            return False
        suggested = ""
        if self._source_path:
            root, _ext = os.path.splitext(self._source_path.rstrip("/"))
            suggested = os.path.basename(root) + ".cbz"
        path = filedialog.asksaveasfilename(
            title="Save CBZ",
            defaultextension=".cbz",
            filetypes=[("Comic Book Archive", "*.cbz"), ("All files", "*.*")],
            initialfile=suggested,
            initialdir=self._initial_dir(),
        )
        if not path:
            return False
        try:
            self._export_cbz_to(path, include_mokuro=False)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Failed to save CBZ", str(exc))
            return False
        self._remember_dir(path)
        self._status.config(text=f"Saved: {path}")
        return True

    def export_cbz(self) -> bool:
        """Export a new CBZ containing the current pages and the mokuro file."""
        if self._archive is None or self._mokuro is None:
            messagebox.showinfo(
                "Nothing to export",
                "Open images and mokuro text data before exporting.",
            )
            return False
        suggested = ""
        if self._source_path:
            root, _ext = os.path.splitext(self._source_path.rstrip("/"))
            suggested = os.path.basename(root) + ".cbz"
        path = filedialog.asksaveasfilename(
            title="Export CBZ with Mokuro",
            defaultextension=".cbz",
            filetypes=[("Comic Book Archive", "*.cbz"), ("All files", "*.*")],
            initialfile=suggested,
            initialdir=self._initial_dir(),
        )
        if not path:
            return False
        self._text_panel.commit_pending()
        try:
            self._export_cbz_to(path, include_mokuro=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Failed to export CBZ", str(exc))
            return False
        self._remember_dir(path)
        self._status.config(text=f"Exported: {path}")
        # When no mokuro file was loaded (neither a standalone file nor one
        # embedded in the CBZ), this export is the only place the mokuro data
        # has been persisted, so treat it as saved and clear change tracking.
        if not self._mokuro.path and not self._mokuro_in_cbz:
            self._set_dirty(False)
        return True

    def _export_cbz_to(self, path: str, include_mokuro: bool = True) -> None:
        """Write a CBZ with every current page image, optionally plus mokuro.

        Images are never modified by the app, so their original bytes are
        copied verbatim when they are already PNG or JPEG. Other formats are
        re-encoded to JPEG for broad compatibility. When ``include_mokuro`` is
        True and mokuro data is loaded, the mokuro file is embedded as well.

        The archive is written to a temporary file and then atomically moved
        into place. This keeps the destination intact if writing fails, and
        lets the user safely overwrite the CBZ that is currently open (the
        source is read lazily from disk, so truncating it mid-write would
        otherwise corrupt the output).
        """
        import io
        import os as _os
        import tempfile
        import zipfile

        target_dir = _os.path.dirname(_os.path.abspath(path)) or None
        fd, tmp_path = tempfile.mkstemp(suffix=".cbz", dir=target_dir)
        _os.close(fd)
        try:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as out:
                for i in range(self._archive.page_count):
                    name = self._archive.page_name(i)
                    ext = _os.path.splitext(name)[1].lower()
                    if ext in (".png", ".jpg", ".jpeg"):
                        # Copy original bytes without recompression.
                        out.writestr(name, self._archive.read_raw(i))
                    else:
                        # Re-encode uncommon formats to JPEG for compatibility.
                        image = self._archive.load_image(i).convert("RGB")
                        buf = io.BytesIO()
                        image.save(buf, format="JPEG", quality=95)
                        new_name = _os.path.splitext(name)[0] + ".jpg"
                        out.writestr(new_name, buf.getvalue())
                if include_mokuro and self._mokuro is not None:
                    mokuro_name = self._default_export_mokuro_name()
                    out.writestr(
                        mokuro_name, self._mokuro.to_json().encode("utf-8")
                    )
        except Exception:
            if _os.path.exists(tmp_path):
                _os.remove(tmp_path)
            raise

        # If we are overwriting the currently open CBZ, close its handle first
        # so the replace succeeds (notably on Windows) and reopen it after.
        reopen_source = (
            isinstance(self._archive, CbzArchive)
            and _os.path.abspath(self._archive.path) == _os.path.abspath(path)
        )
        if reopen_source:
            self._archive.close()
        try:
            _os.replace(tmp_path, path)
        except Exception:
            if _os.path.exists(tmp_path):
                _os.remove(tmp_path)
            raise
        finally:
            if reopen_source:
                self._archive.reopen()

    def _default_export_mokuro_name(self) -> str:
        if self._source_path:
            base = os.path.splitext(os.path.basename(self._source_path.rstrip("/")))[0]
        else:
            base = "mokuro"
        return base + ".mokuro"

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
        # Empty data (no text blocks anywhere) is treated as nothing to save.
        if self._mokuro.is_empty():
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
        threshold = self._overlap_threshold()
        counts = []
        warnings = []
        for i in range(self._archive.page_count):
            page = self._mokuro.page_for(self._archive.page_name(i))
            counts.append(len(page.blocks) if page is not None else None)
            warnings.append(
                page.has_overlapping_boxes(threshold)
                if page is not None else False
            )
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
        _log.info("Opening source: %s", path)
        try:
            source = factory()
        except Exception as exc:  # noqa: BLE001 - present any failure to user
            _log.error("Failed to open source %s: %s", path, exc)
            messagebox.showerror(f"Failed to {error_title.lower()}", str(exc))
            return

        if self._archive is not None:
            self._archive.close()
        self._archive = source
        self._source_path = path
        _log.info("Opened source with %d page(s)", source.page_count)
        # A new source invalidates any previously loaded text.
        self._mokuro = None
        self._mokuro_in_cbz = False
        self._set_dirty(False)

        self._status.config(text="Loading thumbnails...")
        self.update_idletasks()
        self._page_list.populate(source)

        self._refresh_title()
        self.show_page(0)

        # A mokuro embedded in the CBZ takes precedence; otherwise try a
        # sibling file if auto-load is enabled. If nothing was loaded and
        # auto-create is enabled, start fresh, empty mokuro data so the user
        # can annotate right away.
        if not self._load_embedded_mokuro():
            self._maybe_auto_load_mokuro(path)
        if self._mokuro is None and self._settings.get("auto_create_mokuro"):
            self._install_empty_mokuro()

    def _load_embedded_mokuro(self) -> bool:
        """Load a mokuro embedded in the current CBZ, if present."""
        archive = self._archive
        if not isinstance(archive, CbzArchive) or not archive.has_mokuro:
            return False
        try:
            text = archive.read_mokuro()
            mokuro = MokuroData.from_json(text, path="")
        except Exception as exc:  # noqa: BLE001
            self._status.config(text=f"Embedded mokuro could not be read: {exc}")
            return False
        self._mokuro = mokuro
        self._mokuro_in_cbz = True
        self._set_dirty(False)
        if self._current_page >= 0:
            self._update_text_for_page(self._current_page)
        self._update_text_counts()
        self._status.config(
            text=f"Loaded embedded mokuro from CBZ "
            f"({len(mokuro.pages)} pages)"
        )
        return True

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

    def delete_page(self, index: int) -> None:
        """Delete the page at ``index`` after confirming with the user.

        Removes the page's mokuro data and drops the page from the source so
        it no longer appears in the app or in an exported CBZ. The underlying
        file/archive on disk is left untouched.
        """
        if self._archive is None:
            return
        if not (0 <= index < self._archive.page_count):
            return

        name = self._archive.page_name(index)
        if not messagebox.askyesno(
            "Delete page",
            f"Delete page {index + 1} ({os.path.basename(name)})?\n\n"
            "This removes the page and its text data from the app. The "
            "original file on disk is not modified, but exported CBZ files "
            "will not include this page.",
            icon=messagebox.WARNING,
        ):
            return

        # Commit any in-progress edit before mutating the model.
        self._text_panel.commit_pending()

        # Remove associated mokuro data, if any.
        if self._mokuro is not None and self._mokuro.remove_page(name):
            self._mark_dirty()

        # Drop the page from the source.
        self._archive.delete_page(index)

        # Rebuild the thumbnail list to reflect the new page set.
        self._page_list.populate(self._archive)

        if self._archive.page_count == 0:
            # Nothing left to show.
            self._current_page = -1
            self._current_image = None
            self._center.show_image(None)
            self._center.set_boxes([])
            self._text_panel.show_page(None)
            self._update_text_counts()
            self._status.config(text="All pages deleted.")
            return

        # Show a sensible neighbouring page.
        new_index = min(index, self._archive.page_count - 1)
        # Force a reload since the index now points at a different page.
        self._current_page = -1
        self.show_page(new_index)
        self._update_text_counts()
        self._status.config(
            text=f"Deleted page {index + 1}. "
            f"{self._archive.page_count} page(s) remaining."
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

    def _overlap_threshold(self) -> float:
        """Current overlap threshold (0..1) from settings, clamped."""
        try:
            value = float(self._settings.get("overlap_threshold"))
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, value))

    def _refresh_overlaps(self, page) -> None:
        """Update the per-item overlap markers in the Text panel."""
        if page is None:
            self._text_panel.set_overlaps(set())
            return
        self._text_panel.set_overlaps(
            page.overlapping_block_indices(self._overlap_threshold())
        )

    # ------------------------------------------------------------- selection
    def _on_box_selected(self, index: int) -> None:
        """A bounding box was clicked in the page view."""
        self._text_panel.set_selected(index)
        self._sync_box_edit_button()

    def _on_block_selected(self, index: int) -> None:
        """A text block was selected in the right panel."""
        self._center.set_selected_box(index)
        self._sync_box_edit_button()

    def _on_add_requested(self) -> None:
        """User pressed Add: arm rectangle drawing on the page.

        Pressing Add again while already armed (i.e. before drawing a
        rectangle) cancels the operation.
        """
        if self._mokuro is None or self._archive is None:
            return
        if self._center.in_draw_mode:
            self._center.cancel_draw_mode()
            self._sync_add_button()
            self._status.config(text="Adding text item cancelled.")
            return
        self._status.config(
            text="Draw a rectangle on the page to place the new text item "
            "(or press Add again to cancel)."
        )
        self._center.begin_draw_mode()
        self._sync_add_button()

    def _sync_add_button(self) -> None:
        """Keep the Add button's look in step with the canvas draw mode."""
        self._text_panel.set_add_active(self._center.in_draw_mode)

    def _on_box_drawn(self, box) -> None:
        """Rectangle drawing finished; ``box`` is None if cancelled/degenerate."""
        self._sync_add_button()
        if box is None:
            self._status.config(text="Adding text item cancelled.")
            return
        self._text_panel.add_block_with_box(box)
        self._status.config(text="Text item added.")
        # Optionally OCR the freshly added item straight away.
        if self._settings.get("auto_ocr_on_add") and ocr.is_available():
            index = self._text_panel.selected_index
            if index is not None:
                self._on_ocr_requested(index)

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

    def _on_ocr_requested(self, index) -> None:
        """Run OCR on the selected block's region and fill in its text."""
        if self._mokuro is None or self._archive is None:
            return
        page = self._mokuro.page_for(self._archive.page_name(self._current_page))
        if page is None or not (0 <= index < len(page.blocks)):
            return
        if not ocr.is_available():
            messagebox.showinfo("OCR unavailable", ocr.unavailable_reason())
            return
        block = page.blocks[index]
        crop = self._crop_block(block)
        if crop is None:
            messagebox.showwarning(
                "OCR", "No image region available to recognize."
            )
            return

        _log.info(
            "Running OCR on item %d (%s) with %s",
            index + 1,
            "vertical" if block.vertical else "horizontal",
            ocr.get_method(),
        )
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            lines = ocr.recognize(crop, vertical=block.vertical)
        except Exception as exc:  # noqa: BLE001 - runtime/engine errors
            _log.error("OCR failed on item %d: %s", index + 1, exc)
            messagebox.showerror("OCR failed", f"OCR failed:\n{exc}")
            return
        finally:
            self.config(cursor="")

        if not lines:
            _log.info("OCR found no text in item %d", index + 1)
            messagebox.showinfo("OCR", "No text was detected in this region.")
            return

        _log.info("OCR result for item %d: %r", index + 1, lines)
        block.lines = lines
        self._mark_dirty()
        self._text_panel.refresh()
        self._text_panel.set_selected(index)
        self._update_text_counts()
        self._status.config(text=f"OCR filled in text for item {index + 1}.")

    def _crop_block(self, block):
        """Return the current page image cropped to ``block``'s box (or None)."""
        if self._current_image is None:
            return None
        x1, y1, x2, y2 = (block.box + [0, 0, 0, 0])[:4]
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        iw, ih = self._current_image.size
        x1 = max(0, min(iw, x1)); x2 = max(0, min(iw, x2))
        y1 = max(0, min(ih, y1)); y2 = max(0, min(ih, y2))
        if x2 - x1 < 1 or y2 - y1 < 1:
            return None
        return self._current_image.crop((x1, y1, x2, y2)).convert("RGB")

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

    # ------------------------------------------------------------ find/replace
    def open_find(self) -> None:
        """Open (or focus) the non-blocking Find dialog."""
        self._open_find_dialog(replace=False)

    def open_find_replace(self) -> None:
        """Open (or focus) the non-blocking Find and Replace dialog."""
        self._open_find_dialog(replace=True)

    def _open_find_dialog(self, replace: bool) -> None:
        if self._find_dialog is not None and self._find_dialog.winfo_exists():
            # Reuse the existing window, switching mode if needed.
            self._find_dialog.set_mode(replace)
            self._find_dialog.deiconify()
            self._find_dialog.lift()
            self._find_dialog.focus_set()
            return
        self._find_dialog = FindDialog(self, self, replace=replace)

    def on_find_closed(self) -> None:
        """Callback from the dialog when it closes."""
        self._find_dialog = None
        self._find_match = None
        self._text_panel.clear_find_highlight()

    def _iter_match_positions(self, query: str):
        """Yield ``(page_index, block_index, char_offset)`` for every match.

        Positions are ordered by page, then block, then offset, so that
        "next"/"previous" follow a natural reading order through the volume.
        """
        if not query or self._mokuro is None or self._archive is None:
            return
        for pi in range(self._archive.page_count):
            page = self._mokuro.page_for(self._archive.page_name(pi))
            if page is None:
                continue
            for bi, block in enumerate(page.blocks):
                text = "\n".join(block.lines)
                start = text.find(query)
                while start != -1:
                    yield (pi, bi, start)
                    start = text.find(query, start + 1)

    def _require_mokuro_for_find(self, query: str) -> Optional[str]:
        """Return an error status string, or None if a search can proceed."""
        if self._mokuro is None or self._archive is None:
            return "Open a mokuro file to search its text."
        if not query:
            return "Enter text to find."
        return None

    def find_next(self, query: str) -> str:
        return self._find_in_direction(query, forward=True)

    def find_prev(self, query: str) -> str:
        return self._find_in_direction(query, forward=False)

    def _find_in_direction(self, query: str, forward: bool) -> str:
        error = self._require_mokuro_for_find(query)
        if error is not None:
            return error
        # Make sure the model reflects any in-progress inline edits.
        self._text_panel.commit_pending()

        matches = list(self._iter_match_positions(query))
        if not matches:
            self._text_panel.clear_find_highlight()
            self._find_match = None
            return f"No matches for '{query}'."

        index = self._pick_match_index(matches, forward)
        target = matches[index]
        self._go_to_match(target, len(query))
        return f"Match {index + 1} of {len(matches)}."

    def _pick_match_index(self, matches, forward: bool) -> int:
        """Choose the next/previous match index relative to the current one."""
        current = self._find_match
        if current is None:
            return 0 if forward else len(matches) - 1
        if forward:
            for i, pos in enumerate(matches):
                if pos > current:
                    return i
            return 0  # wrap to first
        for i in range(len(matches) - 1, -1, -1):
            if matches[i] < current:
                return i
        return len(matches) - 1  # wrap to last

    def _go_to_match(self, match: tuple, length: int) -> None:
        """Navigate to and highlight the given match position."""
        page_index, block_index, offset = match
        if page_index != self._current_page:
            self.show_page(page_index)
        self._find_match = match
        self._text_panel.set_selected(block_index)
        self._on_block_selected(block_index)
        self._text_panel.highlight_match(block_index, offset, offset + length)

    def replace_one(self, query: str, replacement: str) -> str:
        error = self._require_mokuro_for_find(query)
        if error is not None:
            return error
        self._text_panel.commit_pending()

        # Replace the current match if one is selected; otherwise find one.
        if self._find_match is None:
            return self.find_next(query)

        page_index, block_index, offset = self._find_match
        page = self._mokuro.page_for(self._archive.page_name(page_index))
        if page is None or not (0 <= block_index < len(page.blocks)):
            return self.find_next(query)
        block = page.blocks[block_index]
        text = "\n".join(block.lines)
        # Verify the match still sits where we expect it.
        if text[offset:offset + len(query)] != query:
            return self.find_next(query)
        new_text = text[:offset] + replacement + text[offset + len(query):]
        block.lines = new_text.split("\n")
        self._mark_dirty()
        # Advance past the replacement so the next search skips it.
        self._find_match = (page_index, block_index, offset + len(replacement) - 1)
        if page_index == self._current_page:
            self._text_panel.refresh()
            self._text_panel.set_selected(block_index)
        # Find the following match.
        status = self.find_next(query)
        return f"Replaced 1. {status}"

    def replace_all(self, query: str, replacement: str) -> str:
        error = self._require_mokuro_for_find(query)
        if error is not None:
            return error
        self._text_panel.commit_pending()

        count = 0
        for pi in range(self._archive.page_count):
            page = self._mokuro.page_for(self._archive.page_name(pi))
            if page is None:
                continue
            for block in page.blocks:
                text = "\n".join(block.lines)
                if query in text:
                    count += text.count(query)
                    block.lines = text.replace(query, replacement).split("\n")

        if count == 0:
            return f"No matches for '{query}'."
        self._mark_dirty()
        self._find_match = None
        self._text_panel.clear_find_highlight()
        self._update_text_for_page(self._current_page)
        self._update_text_counts()
        return f"Replaced {count} occurrence(s)."

    # ------------------------------------------------------------------ close
    def _on_close(self) -> None:
        if not self._maybe_save_changes():
            return
        if self._archive is not None:
            self._archive.close()
        self.destroy()


def main() -> None:
    logging_setup.configure()
    logging_setup.log_system_checks()
    app = MoguraApp()
    app.mainloop()


if __name__ == "__main__":
    main()
