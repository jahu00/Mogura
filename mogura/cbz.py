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

_MOKURO_EXT = ".mokuro"


class CbzArchive(PageSource):
    """Lazy reader over the image pages inside a CBZ (ZIP) file."""

    def __init__(self, path: str):
        self.path = path
        self._zip = zipfile.ZipFile(path, "r")
        self._names: List[str] = self._collect_page_names()
        self._mokuro_name = self._find_mokuro_name()
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

    def read_raw(self, index: int) -> bytes:
        """Return the raw, undecoded bytes of the page at ``index``."""
        return self._zip.read(self._names[index])

    # -------------------------------------------------------------- mokuro
    def _find_mokuro_name(self) -> str | None:
        """Return the archive entry name of an embedded ``.mokuro``, if any."""
        candidates = [
            info.filename
            for info in self._zip.infolist()
            if not info.is_dir()
            and info.filename.lower().endswith(_MOKURO_EXT)
        ]
        if not candidates:
            return None
        # Prefer a top-level file; otherwise the first (sorted) match.
        candidates.sort(key=lambda n: (n.count("/"), natural_key(n)))
        return candidates[0]

    @property
    def has_mokuro(self) -> bool:
        return self._mokuro_name is not None

    @property
    def mokuro_name(self) -> str | None:
        return self._mokuro_name

    def read_mokuro(self) -> str | None:
        """Return the text of the embedded mokuro file, or None."""
        if self._mokuro_name is None:
            return None
        return self._zip.read(self._mokuro_name).decode("utf-8")

    def write_mokuro(self, text: str, name: str | None = None) -> None:
        """Write ``text`` as the embedded mokuro file, rebuilding the archive.

        ZIP archives can't update a single entry in place, so this rewrites the
        whole archive to a temp file and atomically replaces the original. The
        embedded mokuro keeps its existing name, or ``name`` (or a default
        derived from the archive) if there was none.
        """
        target_name = self._mokuro_name or name or self._default_mokuro_name()

        # Snapshot all current entries except any existing mokuro, which we
        # replace with the new content.
        import os
        import tempfile

        entries = [
            info for info in self._zip.infolist()
            if info.filename != target_name
            and not info.filename.lower().endswith(_MOKURO_EXT)
        ]
        data = {info.filename: self._zip.read(info.filename) for info in entries}

        fd, tmp_path = tempfile.mkstemp(
            suffix=".cbz", dir=os.path.dirname(os.path.abspath(self.path)) or None
        )
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as out:
                for info in entries:
                    out.writestr(info, data[info.filename])
                out.writestr(target_name, text.encode("utf-8"))
            # Swap: close our handle, replace the file, then reopen.
            self._zip.close()
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            # Reopen the original so the object stays usable.
            self._zip = zipfile.ZipFile(self.path, "r")
            raise
        self._zip = zipfile.ZipFile(self.path, "r")
        self._mokuro_name = target_name

    def _default_mokuro_name(self) -> str:
        import os
        base = os.path.splitext(os.path.basename(self.path))[0]
        return base + _MOKURO_EXT

    def close(self) -> None:
        try:
            self._zip.close()
        except Exception:
            pass
