"""Central page view: displays a page with drag-to-pan and zoom support."""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from PIL import Image, ImageTk


class PageView(tk.Frame):
    """A canvas that shows a single page image, pannable and zoomable."""

    MIN_SCALE = 0.05
    MAX_SCALE = 8.0
    ZOOM_STEP = 1.1
    # Movement (in pixels) beyond which a press is treated as a drag/pan and
    # box selection is cancelled.
    DRAG_THRESHOLD = 4

    # Bounding box appearance.
    BOX_COLOR = "#00b0ff"
    BOX_WIDTH = 2
    BOX_SELECTED_COLOR = "#ff3b30"
    BOX_SELECTED_WIDTH = 3

    # Appearance of the rectangle being drawn for a new text item.
    DRAW_COLOR = "#00e676"
    DRAW_WIDTH = 2

    # Box-edit (move/resize) handles.
    HANDLE_HALF = 4       # half-size of a handle square, in canvas px
    HANDLE_HIT = 8        # hit tolerance around a handle, in canvas px
    HANDLE_FILL = "#ffffff"
    HANDLE_OUTLINE = "#ff3b30"
    MIN_BOX = 2           # minimum box size in image px

    # Which box edges each handle moves: (x1, y1, x2, y2).
    _HANDLE_EDGES = {
        "nw": (True, True, False, False),
        "n": (False, True, False, False),
        "ne": (False, True, True, False),
        "e": (False, False, True, False),
        "se": (False, False, True, True),
        "s": (False, False, False, True),
        "sw": (True, False, False, True),
        "w": (True, False, False, False),
    }

    def __init__(
        self,
        master,
        on_box_selected=None,
        on_zoom_changed=None,
        on_box_drawn=None,
        on_box_edited=None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)

        self.canvas = tk.Canvas(self, background="#2b2b2b", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self._source_image: Optional[Image.Image] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._image_id: Optional[int] = None

        self._scale = 1.0
        # Top-left position of the image on the canvas (in canvas coords).
        self._offset_x = 0.0
        self._offset_y = 0.0

        self._drag_start = (0, 0)
        self._drag_origin = (0.0, 0.0)
        # Box selection is committed on mouse-up, but only if the press did not
        # turn into a drag (pan). ``_pending_box`` holds the box under the
        # initial press; ``_dragged`` records whether movement exceeded the
        # threshold.
        self._pending_box: Optional[int] = None
        self._dragged: bool = False

        # Text bounding boxes: list of [x1, y1, x2, y2] in image pixel coords.
        self._boxes: list = []
        self._box_ids: list = []
        self._selected_box: Optional[int] = None
        self._boxes_visible: bool = True
        self._on_box_selected = on_box_selected
        self._on_zoom_changed = on_zoom_changed
        self._on_box_drawn = on_box_drawn
        self._on_box_edited = on_box_edited

        # Draw mode: when armed, the next drag draws a rectangle instead of
        # panning, and the resulting box (in image px) is reported.
        self._draw_mode: bool = False
        self._draw_start_canvas: Optional[tuple] = None
        self._draw_rect_id: Optional[int] = None

        # Box-edit mode: when active, the selected box shows drag handles;
        # dragging a handle resizes, dragging the interior moves.
        self._edit_mode: bool = False
        self._handle_ids: dict = {}
        self._active_handle: Optional[str] = None  # handle name or "move"
        self._edit_press = (0, 0)          # canvas coords at press
        self._edit_box_start: Optional[list] = None  # box (image px) at press

        self._bind_events()

    # ------------------------------------------------------------------ events
    def _bind_events(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._on_pan_start)
        self.canvas.bind("<B1-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_pan_release)

        # Zoom with the mouse wheel. Windows/macOS use <MouseWheel>; X11 uses
        # Button-4 (up) and Button-5 (down).
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self._on_wheel_zoom(e, 1))
        self.canvas.bind("<Button-5>", lambda e: self._on_wheel_zoom(e, -1))

        self.canvas.bind("<Configure>", self._on_resize)

    def _on_pan_start(self, event) -> None:
        if self._edit_mode and self._on_edit_press(event):
            return
        if self._draw_mode:
            self._on_draw_start(event)
            return
        self._drag_start = (event.x, event.y)
        self._drag_origin = (self._offset_x, self._offset_y)
        self._dragged = False
        # Remember which box (if any) is under the press; selection is only
        # committed on release if no drag occurs.
        if self._boxes_visible:
            self._pending_box = self._box_at(event.x, event.y)
        else:
            self._pending_box = None

    def _box_at(self, cx: float, cy: float) -> Optional[int]:
        """Return the index of the topmost box under canvas point (cx, cy)."""
        # Convert canvas coords to image pixel coords.
        if self._scale == 0:
            return None
        ix = (cx - self._offset_x) / self._scale
        iy = (cy - self._offset_y) / self._scale
        # Iterate in reverse so boxes drawn last (on top) win ties.
        for i in range(len(self._boxes) - 1, -1, -1):
            x1, y1, x2, y2 = self._boxes[i]
            if x1 <= ix <= x2 and y1 <= iy <= y2:
                return i
        return None

    def _on_pan_move(self, event) -> None:
        if self._edit_mode and self._active_handle is not None:
            self._on_edit_move(event)
            return
        if self._draw_mode:
            self._on_draw_move(event)
            return
        if self._source_image is None:
            return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        # Once movement passes the threshold, treat this as a pan and cancel
        # any pending box selection.
        if not self._dragged and (
            abs(dx) > self.DRAG_THRESHOLD or abs(dy) > self.DRAG_THRESHOLD
        ):
            self._dragged = True
            self._pending_box = None
        self._offset_x = self._drag_origin[0] + dx
        self._offset_y = self._drag_origin[1] + dy
        self._render()

    def _on_pan_release(self, event) -> None:
        if self._edit_mode and self._active_handle is not None:
            self._on_edit_release(event)
            return
        if self._draw_mode:
            self._on_draw_release(event)
            return
        # Commit box selection only for a click (no drag) on a box.
        if self._dragged:
            self._dragged = False
            self._pending_box = None
            return
        hit = self._pending_box
        self._pending_box = None
        if hit is not None:
            self.set_selected_box(hit)
            if self._on_box_selected is not None:
                self._on_box_selected(hit)

    # -------------------------------------------------------------- draw mode
    def begin_draw_mode(self) -> None:
        """Arm rectangle-drawing mode for creating a new text box."""
        if self._source_image is None:
            return
        self._draw_mode = True
        self.canvas.config(cursor="crosshair")

    def cancel_draw_mode(self) -> None:
        """Disarm draw mode without producing a box."""
        self._draw_mode = False
        self.canvas.config(cursor="")
        if self._draw_rect_id is not None:
            self.canvas.delete(self._draw_rect_id)
            self._draw_rect_id = None
        self._draw_start_canvas = None

    @property
    def in_draw_mode(self) -> bool:
        return self._draw_mode

    def _on_draw_start(self, event) -> None:
        self._draw_start_canvas = (event.x, event.y)
        self._draw_rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline=self.DRAW_COLOR, width=self.DRAW_WIDTH,
        )

    def _on_draw_move(self, event) -> None:
        if self._draw_start_canvas is None or self._draw_rect_id is None:
            return
        x0, y0 = self._draw_start_canvas
        self.canvas.coords(self._draw_rect_id, x0, y0, event.x, event.y)

    def _on_draw_release(self, event) -> None:
        start = self._draw_start_canvas
        # Tear down the transient rectangle and exit draw mode.
        if self._draw_rect_id is not None:
            self.canvas.delete(self._draw_rect_id)
            self._draw_rect_id = None
        self._draw_mode = False
        self.canvas.config(cursor="")
        self._draw_start_canvas = None

        if start is None:
            self._notify_box_drawn(None)
            return
        # Convert both corners to image pixel coordinates and normalize.
        ix0, iy0 = self._canvas_to_image(*start)
        ix1, iy1 = self._canvas_to_image(event.x, event.y)
        x1, x2 = sorted((ix0, ix1))
        y1, y2 = sorted((iy0, iy1))
        # Clamp to the image bounds.
        iw, ih = self._source_image.size if self._source_image else (0, 0)
        x1 = max(0, min(iw, x1)); x2 = max(0, min(iw, x2))
        y1 = max(0, min(ih, y1)); y2 = max(0, min(ih, y2))
        # Reject a degenerate (zero-area) rectangle.
        if x2 - x1 < 1 or y2 - y1 < 1:
            self._notify_box_drawn(None)
            return
        self._notify_box_drawn([round(x1), round(y1), round(x2), round(y2)])

    def _canvas_to_image(self, cx: float, cy: float):
        if self._scale == 0:
            return (0.0, 0.0)
        return ((cx - self._offset_x) / self._scale,
                (cy - self._offset_y) / self._scale)

    def _notify_box_drawn(self, box) -> None:
        if self._on_box_drawn is not None:
            self._on_box_drawn(box)

    # -------------------------------------------------------------- edit mode
    def begin_edit_mode(self) -> None:
        """Show move/resize handles on the selected box."""
        if self._source_image is None or self._selected_box is None:
            return
        self._edit_mode = True
        self._render_handles()

    def end_edit_mode(self) -> None:
        """Leave box-edit mode and remove handles."""
        if not self._edit_mode:
            return
        self._edit_mode = False
        self._active_handle = None
        self._edit_box_start = None
        self.canvas.config(cursor="")
        self._clear_handles()

    @property
    def in_edit_mode(self) -> bool:
        return self._edit_mode

    def _handle_at(self, cx: float, cy: float) -> Optional[str]:
        """Return the name of the handle near (cx, cy), or None."""
        for name, item_id in self._handle_ids.items():
            hx1, hy1, hx2, hy2 = self.canvas.coords(item_id)
            if (
                hx1 - self.HANDLE_HIT <= cx <= hx2 + self.HANDLE_HIT
                and hy1 - self.HANDLE_HIT <= cy <= hy2 + self.HANDLE_HIT
            ):
                return name
        return None

    def _on_edit_press(self, event) -> bool:
        """Handle a press in edit mode. Returns True if it was consumed."""
        if self._selected_box is None:
            return False
        handle = self._handle_at(event.x, event.y)
        if handle is not None:
            self._active_handle = handle
        elif self._point_in_selected(event.x, event.y):
            self._active_handle = "move"
        else:
            return False
        self._edit_press = (event.x, event.y)
        self._edit_box_start = list(self._boxes[self._selected_box])
        return True

    def _point_in_selected(self, cx: float, cy: float) -> bool:
        if self._selected_box is None:
            return False
        x1, y1, x2, y2 = self._boxes[self._selected_box]
        ix, iy = self._canvas_to_image(cx, cy)
        return x1 <= ix <= x2 and y1 <= iy <= y2

    def _on_edit_move(self, event) -> None:
        if self._selected_box is None or self._edit_box_start is None:
            return
        # Movement in image pixels since press.
        dx = (event.x - self._edit_press[0]) / self._scale
        dy = (event.y - self._edit_press[1]) / self._scale
        x1, y1, x2, y2 = self._edit_box_start
        iw, ih = self._source_image.size

        if self._active_handle == "move":
            w, h = x2 - x1, y2 - y1
            nx1 = min(max(0, x1 + dx), iw - w)
            ny1 = min(max(0, y1 + dy), ih - h)
            new_box = [nx1, ny1, nx1 + w, ny1 + h]
        else:
            mx1, my1, mx2, my2 = self._HANDLE_EDGES[self._active_handle]
            nx1 = x1 + dx if mx1 else x1
            ny1 = y1 + dy if my1 else y1
            nx2 = x2 + dx if mx2 else x2
            ny2 = y2 + dy if my2 else y2
            # Clamp to image and keep a minimum size, preventing edge crossover.
            nx1 = min(max(0, nx1), nx2 - self.MIN_BOX) if mx1 else nx1
            ny1 = min(max(0, ny1), ny2 - self.MIN_BOX) if my1 else ny1
            nx2 = max(min(iw, nx2), nx1 + self.MIN_BOX) if mx2 else nx2
            ny2 = max(min(ih, ny2), ny1 + self.MIN_BOX) if my2 else ny2
            new_box = [nx1, ny1, nx2, ny2]

        self._boxes[self._selected_box] = new_box
        self._render_boxes()
        self._render_handles()

    def _on_edit_release(self, _event) -> None:
        self._active_handle = None
        self._edit_box_start = None
        if self._selected_box is None:
            return
        box = [int(round(v)) for v in self._boxes[self._selected_box]]
        self._boxes[self._selected_box] = box
        self._render_boxes()
        self._render_handles()
        if self._on_box_edited is not None:
            self._on_box_edited(self._selected_box, box)

    def _clear_handles(self) -> None:
        for item_id in self._handle_ids.values():
            self.canvas.delete(item_id)
        self._handle_ids = {}

    def _render_handles(self) -> None:
        self._clear_handles()
        if not self._edit_mode or self._selected_box is None:
            return
        if not (0 <= self._selected_box < len(self._boxes)):
            return
        x1, y1, x2, y2 = self._boxes[self._selected_box]
        cx1, cy1 = self._image_to_canvas(x1, y1)
        cx2, cy2 = self._image_to_canvas(x2, y2)
        mx, my = (cx1 + cx2) / 2, (cy1 + cy2) / 2
        points = {
            "nw": (cx1, cy1), "n": (mx, cy1), "ne": (cx2, cy1),
            "e": (cx2, my), "se": (cx2, cy2), "s": (mx, cy2),
            "sw": (cx1, cy2), "w": (cx1, my),
        }
        h = self.HANDLE_HALF
        for name, (px, py) in points.items():
            self._handle_ids[name] = self.canvas.create_rectangle(
                px - h, py - h, px + h, py + h,
                fill=self.HANDLE_FILL, outline=self.HANDLE_OUTLINE,
            )

    def _on_mousewheel(self, event) -> None:
        direction = 1 if event.delta > 0 else -1
        self._on_wheel_zoom(event, direction)

    def _on_wheel_zoom(self, event, direction: int) -> None:
        if self._source_image is None:
            return
        factor = self.ZOOM_STEP if direction > 0 else 1 / self.ZOOM_STEP
        self._zoom_at(event.x, event.y, factor)

    def _on_resize(self, _event) -> None:
        if self._source_image is not None:
            self._render()

    # ------------------------------------------------------------------ zoom
    def _zoom_at(self, cx: float, cy: float, factor: float) -> None:
        """Zoom by ``factor`` keeping the point under (cx, cy) fixed."""
        new_scale = max(self.MIN_SCALE, min(self.MAX_SCALE, self._scale * factor))
        if new_scale == self._scale:
            return
        # Keep the image point under the cursor stationary.
        real_factor = new_scale / self._scale
        self._offset_x = cx - (cx - self._offset_x) * real_factor
        self._offset_y = cy - (cy - self._offset_y) * real_factor
        self._scale = new_scale
        self._render()
        self._notify_zoom()

    def zoom_in(self) -> None:
        self._zoom_at(*self._canvas_center(), self.ZOOM_STEP)

    def zoom_out(self) -> None:
        self._zoom_at(*self._canvas_center(), 1 / self.ZOOM_STEP)

    def zoom_to_actual(self) -> None:
        """Set zoom to 100% (1 image pixel per screen pixel), centered."""
        if self._source_image is None:
            return
        cx, cy = self._canvas_center()
        # Scale about the canvas center so the view stays put.
        target = max(self.MIN_SCALE, min(self.MAX_SCALE, 1.0))
        self._zoom_at(cx, cy, target / self._scale)

    def _canvas_center(self):
        return (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)

    @property
    def scale(self) -> float:
        return self._scale

    def _notify_zoom(self) -> None:
        if self._on_zoom_changed is not None:
            self._on_zoom_changed(self._scale)

    # ------------------------------------------------------------------ public
    def show_image(self, image: Optional[Image.Image]) -> None:
        """Display a new page image and fit it to the view."""
        self._source_image = image
        if image is None:
            self.canvas.delete("all")
            self._image_id = None
            self._photo = None
            self._box_ids = []
            return
        self.fit_to_window()

    def set_boxes(self, boxes: list) -> None:
        """Set the text bounding boxes (each ``[x1, y1, x2, y2]`` in image px)."""
        self._boxes = [list(b) for b in boxes]
        self._selected_box = None
        # Changing the box set leaves edit mode (selection is gone).
        self.end_edit_mode()
        self._render()

    def set_selected_box(self, index: Optional[int]) -> None:
        """Highlight the box at ``index`` (or clear selection with None)."""
        if index == self._selected_box:
            return
        self._selected_box = index
        # Selecting another item exits box-edit mode.
        self.end_edit_mode()
        self._restyle_boxes()

    def set_boxes_visible(self, visible: bool) -> None:
        """Show or hide all bounding boxes."""
        if visible == self._boxes_visible:
            return
        self._boxes_visible = visible
        self._render_boxes()

    @property
    def boxes_visible(self) -> bool:
        return self._boxes_visible

    def clear(self) -> None:
        self._boxes = []
        self._box_ids = []
        self._selected_box = None
        self.show_image(None)

    def fit_to_window(self) -> None:
        """Scale the image to fit inside the canvas and center it."""
        if self._source_image is None:
            return
        self.update_idletasks()
        cw = self.canvas.winfo_width() or 1
        ch = self.canvas.winfo_height() or 1
        iw, ih = self._source_image.size
        if iw == 0 or ih == 0:
            return
        self._scale = min(cw / iw, ch / ih)
        self._scale = max(self.MIN_SCALE, min(self.MAX_SCALE, self._scale))
        self._offset_x = (cw - iw * self._scale) / 2
        self._offset_y = (ch - ih * self._scale) / 2
        self._render()
        self._notify_zoom()

    # ------------------------------------------------------------------ render
    def _render(self) -> None:
        if self._source_image is None:
            return
        iw, ih = self._source_image.size
        disp_w = max(1, int(iw * self._scale))
        disp_h = max(1, int(ih * self._scale))

        resized = self._source_image.resize((disp_w, disp_h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)

        if self._image_id is None:
            self._image_id = self.canvas.create_image(
                self._offset_x, self._offset_y, anchor=tk.NW, image=self._photo
            )
        else:
            self.canvas.itemconfigure(self._image_id, image=self._photo)
            self.canvas.coords(self._image_id, self._offset_x, self._offset_y)

        self._render_boxes()
        if self._edit_mode:
            self._render_handles()

    # ------------------------------------------------------------------ boxes
    def _image_to_canvas(self, x: float, y: float):
        return (self._offset_x + x * self._scale, self._offset_y + y * self._scale)

    def _render_boxes(self) -> None:
        """(Re)create the rectangle items for every bounding box."""
        for box_id in self._box_ids:
            self.canvas.delete(box_id)
        self._box_ids = []

        if not self._boxes_visible:
            return

        for i, (x1, y1, x2, y2) in enumerate(self._boxes):
            cx1, cy1 = self._image_to_canvas(x1, y1)
            cx2, cy2 = self._image_to_canvas(x2, y2)
            selected = i == self._selected_box
            box_id = self.canvas.create_rectangle(
                cx1,
                cy1,
                cx2,
                cy2,
                outline=self.BOX_SELECTED_COLOR if selected else self.BOX_COLOR,
                width=self.BOX_SELECTED_WIDTH if selected else self.BOX_WIDTH,
            )
            self._box_ids.append(box_id)
        # Keep the selected box on top so its outline isn't occluded.
        if self._selected_box is not None and 0 <= self._selected_box < len(
            self._box_ids
        ):
            self.canvas.tag_raise(self._box_ids[self._selected_box])

    def _restyle_boxes(self) -> None:
        """Update only the outline style of existing boxes (no re-layout)."""
        for i, box_id in enumerate(self._box_ids):
            selected = i == self._selected_box
            self.canvas.itemconfigure(
                box_id,
                outline=self.BOX_SELECTED_COLOR if selected else self.BOX_COLOR,
                width=self.BOX_SELECTED_WIDTH if selected else self.BOX_WIDTH,
            )
        if self._selected_box is not None and 0 <= self._selected_box < len(
            self._box_ids
        ):
            self.canvas.tag_raise(self._box_ids[self._selected_box])
