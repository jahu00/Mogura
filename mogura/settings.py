"""Persistent application settings.

Settings are stored as JSON in the user's config directory so they survive
between runs. The location follows platform conventions where practical and
falls back to ``~/.config/mogura`` otherwise.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

_APP_DIR_NAME = "mogura"
_SETTINGS_FILE = "settings.json"

# Default values for every known setting.
_DEFAULTS: Dict[str, Any] = {
    "auto_load_mokuro": True,
    # Directory of the most recently opened file, used to seed file dialogs.
    "last_dir": "",
}


def _config_dir() -> str:
    """Return the directory where settings are stored, creating it if needed."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, _APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


class Settings:
    """In-memory settings backed by a JSON file on disk."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(_config_dir(), _SETTINGS_FILE)
        self._values: Dict[str, Any] = dict(_DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, dict):
                # Only keep known keys, falling back to defaults otherwise.
                for key in _DEFAULTS:
                    if key in stored:
                        self._values[key] = stored[key]
        except (OSError, ValueError):
            # Missing or corrupt file: keep defaults.
            pass

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(self._values, handle, indent=2)
        except OSError:
            pass

    def get(self, key: str) -> Any:
        return self._values.get(key, _DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value
        self.save()
