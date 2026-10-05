"""Your own pybasic settings, used for every project you open on this computer.

Saved as settings.json in the usual place for each system:

    Windows        %APPDATA%\\pybasic
    macOS          ~/Library/Application Support/pybasic
    Linux, WSL     ~/.config/pybasic  (or $XDG_CONFIG_HOME/pybasic)

PYBASIC_CONFIG_DIR, if set, is used instead (the tests use this).

Settings live in three places, each for one kind of thing: pyproject.toml for
what everyone working on a project shares; the project's .pybasic/local.json
for that project on this machine (like its Python interpreter); and this file
for your own preferences, in every project.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def folder():
    if os.environ.get("PYBASIC_CONFIG_DIR"):
        return Path(os.environ["PYBASIC_CONFIG_DIR"])
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "pybasic"


def load():
    path = folder() / "settings.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return {}  # a damaged file shouldn't stop the IDE; it's rewritten on the next change


def get(key, default=None):
    return load().get(key, default)


def set(key, value):
    """Set (or with None, remove) one of your settings."""
    data = load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / "settings.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
