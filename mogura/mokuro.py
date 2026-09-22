"""Mokuro file handling.

A ``.mokuro`` file is JSON produced by the mokuro OCR tool. It contains volume
metadata plus a list of pages; each page holds a set of text *blocks* detected
on that page. This module parses such a file into light dataclasses and can
serialize the (possibly edited) data back to disk.

Reference structure (mokuro 0.2.5)::

    {
      "version": "0.2.5",
      "title": "...", "title_uuid": "...",
      "volume": "...", "volume_uuid": "...",
      "pages": [
        {
          "version": "0.2.5",
          "img_width": 1013, "img_height": 1440,
          "blocks": [
            {
              "box": [x1, y1, x2, y2],
              "vertical": true,
              "font_size": 64,
              "lines_coords": [[[x, y], ...], ...],
              "lines": ["...", "..."]
            }
          ],
          "img_path": "01.png"
        }
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TextBlock:
    """A single OCR text block on a page."""

    box: List[float]
    vertical: bool
    font_size: float
    lines: List[str]
    lines_coords: List[Any] = field(default_factory=list)
    # Preserve any extra keys we do not model so round-tripping is lossless.
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TextBlock":
        known = {"box", "vertical", "font_size", "lines", "lines_coords"}
        return cls(
            box=list(data.get("box", [])),
            vertical=bool(data.get("vertical", False)),
            font_size=data.get("font_size", 0),
            lines=list(data.get("lines", [])),
            lines_coords=data.get("lines_coords", []),
            extra={k: v for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "box": self.box,
            "vertical": self.vertical,
            "font_size": self.font_size,
            "lines_coords": self.lines_coords,
            "lines": self.lines,
        }
        result.update(self.extra)
        return result


@dataclass
class MokuroPage:
    """One page of a mokuro volume, identified by its image path."""

    img_path: str
    img_width: int
    img_height: int
    blocks: List[TextBlock] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MokuroPage":
        known = {"img_path", "img_width", "img_height", "blocks"}
        return cls(
            img_path=data.get("img_path", ""),
            img_width=int(data.get("img_width", 0)),
            img_height=int(data.get("img_height", 0)),
            blocks=[TextBlock.from_dict(b) for b in data.get("blocks", [])],
            extra={k: v for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "img_width": self.img_width,
            "img_height": self.img_height,
            "blocks": [b.to_dict() for b in self.blocks],
            "img_path": self.img_path,
        }
        result.update(self.extra)
        return result

    @staticmethod
    def _boxes_overlap(a, b) -> bool:
        """True if boxes ``a`` and ``b`` share interior area (touching edges
        do not count)."""
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        return ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2

    def has_overlapping_boxes(self) -> bool:
        """Return True if any two block bounding boxes overlap."""
        boxes = [b.box for b in self.blocks if len(b.box) == 4]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if self._boxes_overlap(boxes[i], boxes[j]):
                    return True
        return False

    def overlapping_block_indices(self) -> set:
        """Return the set of block indices whose box overlaps another block."""
        boxes = [b.box if len(b.box) == 4 else None for b in self.blocks]
        result: set = set()
        for i in range(len(boxes)):
            if boxes[i] is None:
                continue
            for j in range(i + 1, len(boxes)):
                if boxes[j] is None:
                    continue
                if self._boxes_overlap(boxes[i], boxes[j]):
                    result.add(i)
                    result.add(j)
        return result


class MokuroData:
    """Parsed mokuro volume with lookup of pages by image path."""

    def __init__(self, path: str, raw: Dict[str, Any]):
        self.path = path
        self._raw = raw
        self.pages: List[MokuroPage] = [
            MokuroPage.from_dict(p) for p in raw.get("pages", [])
        ]
        # Index pages by their image path for quick association with the
        # image source. Both the full path and the basename are indexed so we
        # can match regardless of how the image source names its pages.
        self._by_path: Dict[str, MokuroPage] = {}
        for page in self.pages:
            self._by_path[page.img_path] = page
            self._by_path.setdefault(page.img_path.rsplit("/", 1)[-1], page)

    @property
    def title(self) -> str:
        return self._raw.get("title", "")

    @property
    def volume(self) -> str:
        return self._raw.get("volume", "")

    def page_for(self, img_name: str):
        """Return the page whose image path matches ``img_name`` (or None)."""
        if img_name in self._by_path:
            return self._by_path[img_name]
        return self._by_path.get(img_name.rsplit("/", 1)[-1])

    @classmethod
    def load(cls, path: str) -> "MokuroData":
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if "pages" not in raw:
            raise ValueError("Not a valid mokuro file (no 'pages').")
        return cls(path, raw)

    def save(self, path: str | None = None) -> None:
        """Serialize back to a ``.mokuro`` file."""
        target = path or self.path
        self._raw["pages"] = [p.to_dict() for p in self.pages]
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(self._raw, handle, ensure_ascii=False)
