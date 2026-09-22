"""Page source abstraction.

A *page source* provides ordered, lazy access to the image pages of a comic.
Concrete sources include :class:`~mogura.cbz.CbzArchive` (a CBZ/ZIP file) and
:class:`FolderSource` (a directory of image files). Both share the same
interface so the rest of the app is agnostic about where pages come from.
"""

from __future__ import annotations

import os
import re
from typing import List

from PIL import Image

# Image extensions we treat as comic pages.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")


def natural_key(name: str):
    """Sort key that orders embedded numbers naturally (page2 < page10)."""
    parts = re.split(r"(\d+)", name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


class PageSource:
    """Base class defining the page-source interface and shared helpers."""

    @property
    def page_count(self) -> int:
        raise NotImplementedError

    def page_name(self, index: int) -> str:
        raise NotImplementedError

    def load_image(self, index: int) -> Image.Image:
        """Load and decode the page at ``index`` as a PIL image."""
        raise NotImplementedError

    def load_thumbnail(self, index: int, size: int = 160) -> Image.Image:
        """Load a page and shrink it to fit within a ``size`` px box."""
        image = self.load_image(index)
        image = image.convert("RGB")
        image.thumbnail((size, size), Image.LANCZOS)
        return image

    def load_thumbnail_with_size(self, index: int, size: int = 160):
        """Return ``(thumbnail, (width, height))`` for the page.

        The size is the resolution of the *original* full-size page, not the
        shrunken thumbnail.
        """
        image = self.load_image(index)
        original_size = image.size
        image = image.convert("RGB")
        image.thumbnail((size, size), Image.LANCZOS)
        return image, original_size

    def close(self) -> None:
        pass

    def __enter__(self) -> "PageSource":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class FolderSource(PageSource):
    """Page source backed by a directory of image files."""

    def __init__(self, path: str):
        self.path = path
        self._names: List[str] = self._collect_page_names()
        if not self._names:
            raise ValueError("No image files found in folder.")

    def _collect_page_names(self) -> List[str]:
        try:
            entries = os.listdir(self.path)
        except OSError as exc:
            raise ValueError(f"Cannot read folder: {exc}") from exc
        names = [
            name
            for name in entries
            if name.lower().endswith(IMAGE_EXTENSIONS)
            and os.path.isfile(os.path.join(self.path, name))
        ]
        names.sort(key=natural_key)
        return names

    @property
    def page_count(self) -> int:
        return len(self._names)

    def page_name(self, index: int) -> str:
        return self._names[index]

    def load_image(self, index: int) -> Image.Image:
        full_path = os.path.join(self.path, self._names[index])
        image = Image.open(full_path)
        image.load()
        return image
