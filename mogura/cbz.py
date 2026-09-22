"""CBZ archive handling.

A CBZ file is just a ZIP archive containing image files (the pages of a
comic/manga). This module exposes a small wrapper that opens such an archive
and provides lazy access to the individual page images.
"""

from __future__ import annotations

import io
import zipfile
from typing import List

from PIL import Image

from .page_source import IMAGE_EXTENSIONS, PageSource, natural_key


class CbzArchive(PageSource):
    """Lazy reader over the image pages inside a CBZ (ZIP) file."""

    def __init__(self, path: str):
        self.path = path
        self._zip = zipfile.ZipFile(path, "r")
        self._names: List[str] = self._collect_page_names()
        if not self._names:
            self._zip.close()
            raise ValueError("No image pages found in archive.")

    def _collect_page_names(self) -> List[str]:
        names = [
            info.filename
            for info in self._zip.infolist()
            if not info.is_dir()
            and info.filename.lower().endswith(IMAGE_EXTENSIONS)
        ]
        names.sort(key=natural_key)
        return names

    @property
    def page_count(self) -> int:
        return len(self._names)

    def page_name(self, index: int) -> str:
        return self._names[index]

    def load_image(self, index: int) -> Image.Image:
        """Load and decode the page at ``index`` as a PIL image."""
        data = self._zip.read(self._names[index])
        image = Image.open(io.BytesIO(data))
        image.load()
        return image

    def close(self) -> None:
        try:
            self._zip.close()
        except Exception:
            pass
