"""Shared constants and utilities for cc-time-tracker."""

import json
import os
from pathlib import Path


TRACKING_DIR = Path.home() / ".claude" / "time-tracking"
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
ACTIVE_FILE = TRACKING_DIR / "active.jsonl"
LOCK_FILE = TRACKING_DIR / ".lock"
SETTINGS_FILE = Path.home() / ".claude" / "settings.json"

# ANSI escape codes
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
UNDERLINE = "\033[4m"


def ensure_dir(path: Path | None = None) -> None:
    """Create the tracking directory if it doesn't exist."""
    (path or TRACKING_DIR).mkdir(parents=True, exist_ok=True)


def acquire_lock(lock_path: Path | None = None):
    """Return a file lock (or no-op if filelock not installed)."""
    try:
        from filelock import FileLock
        return FileLock(str(lock_path or LOCK_FILE), timeout=5)
    except ImportError:
        class _NoLock:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return _NoLock()


def extract_project_name(cwd: str) -> str:
    """Derive project name from the last directory component."""
    return os.path.basename(os.path.normpath(cwd))


def load_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, returning a list of parsed dicts. Skips bad lines."""
    try:
        f = open(path, "r")
    except FileNotFoundError:
        return []
    records = []
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
