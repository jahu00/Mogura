# Mogura

A desktop editor for [mokuro](https://github.com/kha-white/mokuro) files built with Python + tkinter.

## Features (current)

- Top menu: open a CBZ file, open a folder of images, open/save a mokuro file,
  toggle panels, persistent settings, exit
- Toolbar: quick access to open CBZ and panel toggles
- Left panel: scrollable page thumbnails for navigation; the current page is
  highlighted (collapsible). Each thumbnail shows its resolution (top-right
  corner) and, when mokuro text is loaded, the number of text items on that
  page (bottom-right corner). Pages whose text blocks have overlapping bounding
  boxes are flagged with a warning marker (top-left corner)
- Center area: displays the selected page with drag-to-pan and mouse-wheel
  zoom. When mokuro text is loaded, each text block's bounding box is drawn over
  the page; the selected box is highlighted in a different color
- Right panel ("Text"): displays and edits the mokuro OCR text blocks for the
  current page (collapsible). Has its own toolbar to add, remove, and reorder
  (move up/down) text items. Adding an item prompts you to draw its rectangle
  on the page. Items whose bounding box overlaps another item are flagged with a
  warning marker in their header

## Requirements

- Python 3.9+
- Pillow

```bash
pip install -r requirements.txt
```

tkinter ships with most Python installations. On some Linux distros you may
need to install it separately (e.g. `sudo apt install python3-tk`).

## Running

```bash
python3 main.py
```

or

```bash
./start.sh
```

## Usage

- **Open CBZ**: File menu → *Open CBZ...* (or Ctrl+O), or the toolbar button.
- **Open Folder**: File menu → *Open Folder...* (or Ctrl+Shift+O), or the
  toolbar button. Loads all images in the selected directory as pages.
- **Open Mokuro**: File menu → *Open Mokuro...* (or Ctrl+M), or the toolbar
  button. Loads the OCR text for the volume; open the matching CBZ or image
  folder to see each page's text blocks in the "Text" panel.
- **Settings**: the Settings menu has *Auto-load matching Mokuro file*. When
  enabled (the default), opening `manga.cbz` or a folder named `manga`
  automatically loads a sibling `manga.mokuro` if present. This preference is
  saved to `~/.config/mogura/settings.json` and persists between runs. The
  directory of the last opened/saved file is also remembered there and used to
  seed the open and save dialogs.
- **Navigate**: click a thumbnail in the left panel, use the previous/next
  buttons in the toolbar, or press Page Up / Page Down.
- **Pan**: click and drag inside the central page view.
- **Zoom**: scroll the mouse wheel over the page. The current zoom level is
  shown at the far right of the toolbar; click it to toggle between 100% and
  fit-to-window.
- **Toggle bounding boxes**: the ⬚ toolbar button or View menu → *Show
  Bounding Boxes* turns the text-block overlays on and off.
- **Move / resize a box**: select a text item, then press the move/resize button
  in the Text panel toolbar. The selected box gains drag handles — drag a handle
  to resize, or drag inside the box to move it. The mode turns off when you press
  the button again, select another item, or change page.
- **Select a text block**: click its bounding box on the page (the selection
  commits on mouse-up; if you start dragging to pan, it is cancelled), or click
  the block in the "Text" panel. The selection is synchronized both ways: the
  selected box is drawn in red (others in blue) and the matching panel entry is
  highlighted and scrolled into view.
- **Add a text item**: press the add button in the Text panel toolbar, then
  draw a rectangle on the page to define the item's area. The new item is
  inserted after the current selection. Pressing add again before drawing (or
  clicking without dragging out a rectangle) cancels the operation.
- **Remove / reorder text items**: use the delete and up/down buttons in the
  Text panel toolbar.
- **Detailed edit**: click the edit button on a text item to open a dialog that
  shows the original image region beside an approximate render of the stored
  text (side by side for vertical text, stacked for horizontal). There you can
  edit the text, switch orientation, and enter exact bounding box coordinates.
- **Combine text items**: tick the checkbox on two or more items, then press the
  combine button in the Text panel toolbar. A dialog shows each source (original
  with its render overlaid in red), lets you correct the merged text and pick an
  orientation, and lets you choose the resulting bounding box: combine into the
  union of the sources (default) or reuse one specific item's box, via radio
  buttons. A live result preview (the chosen region with the combined text
  rendered over it in blue, versus red for the sources) updates as you edit.
  Confirm to replace the selected items with a single combined one.
  Normal single-click selection still works as before; checkboxes are only for
  building a multi-item selection.
- **Split a text item**: select one item and press the split button in the Text
  panel toolbar. A dialog shows two output panes (for vertical text the first
  piece is on the left, for horizontal text on the right). Click a preview to
  set that piece's cutting point (click, or press and drag to adjust it live),
  which divides the box into four quarters;
  choose which quarter to keep and edit the piece's text. The piece's text is
  rendered over its selected quarter (in red) so you can compare against the
  original, updating live as you edit. Confirm to replace the original item with
  the two pieces.
- **Save**: File menu → *Save Mokuro* (Ctrl+S) or the toolbar save button
  writes to the current mokuro file; *Save Mokuro As...* (Ctrl+Shift+S) prompts
  for a new path. Unsaved changes are marked with a `*` in the window title, and
  Mogura prompts to save (Yes/No/Cancel) before opening another file or exiting.
- **Toggle panels**: View menu or toolbar buttons (drag the sashes to resize).

## Development helper

`make_sample.py` generates a small `sample.cbz` for testing:

```bash
python3 make_sample.py
```

## Project layout

```
main.py              # entry point
mogura/
  __init__.py
  app.py             # main window: menu, toolbar, panels, wiring
  page_source.py     # page-source interface + folder-of-images source
  cbz.py             # CBZ (zip) archive reader
  mokuro.py          # mokuro (.mokuro JSON) parser + serializer
  text_panel.py      # right panel: view/edit mokuro text blocks
  settings.py        # persistent user settings (JSON in ~/.config/mogura)
  page_list.py       # left panel thumbnail navigation
  page_view.py       # central pannable/zoomable page canvas
  edit_dialog.py     # detailed per-item edit dialog (text/orientation/box)
  text_render.py     # approximate render of mokuro text for comparison
  icons.py           # PNG icon loading/resizing/caching
icons/               # PNG toolbar and marker icons
```
