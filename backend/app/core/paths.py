"""Filesystem path helpers for the backend package."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Bundle identifier used by the Tauri desktop app. The OS-specific application
# data directory is derived from this so browser mode (uvicorn) and the desktop
# app resolve to the *same* location and share conversation history.
APP_IDENTIFIER = "com.quantscript.desktop"


def app_data_dir() -> Path:
    """Return the per-user application data directory for QuantScript.

    Mirrors Tauri's ``app_data_dir()`` conventions so the browser backend and
    the packaged desktop app agree on one location:

    - macOS:   ~/Library/Application Support/com.quantscript.desktop
    - Windows: %APPDATA%/com.quantscript.desktop
    - Linux:   $XDG_DATA_HOME/com.quantscript.desktop (or ~/.local/share/...)
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (base / APP_IDENTIFIER).resolve()


def default_conversations_storage_path() -> Path:
    """Canonical conversation directory shared by browser and desktop modes."""
    return app_data_dir() / "storage" / "conversations"


def resolve_conversations_storage_path() -> Path:
    """Return the directory where conversation JSON files are stored.

    Defaults to ``<app-data>/com.quantscript.desktop/storage/conversations`` so
    browser mode and the desktop app share one location. Set
    ``QUANTSCRIPT_CONVERSATIONS_DIR`` to override (e.g. for tests or a custom
    data layout).
    """
    explicit = os.environ.get("QUANTSCRIPT_CONVERSATIONS_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return default_conversations_storage_path()
