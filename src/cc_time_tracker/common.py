"""Shared constants and utilities for cc-time-tracker."""

import json
import os
from pathlib import Path


TRACKING_DIR = Path.home() / ".claude" / "time-tracking"
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
ACTIVE_FILE = TRACKING_DIR / "active.jsonl"
LOCK_FILE = TRACKING_DIR / ".lock"
SETTINGS_FILE = Path.home() / ".claude" / "settings.json"

# Event/reason names used in the JSONL records.
EVENT_START = "start"
EVENT_END = "end"
REASON_ORPHAN_CLEANUP = "orphan_cleanup"
TRACKER_HOOK_MARKER = "cc_time_tracker"

# ANSI escape codes
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
UNDERLINE = "\033[4m"


class _NoLock:
    def __enter__(self): return self
    def __exit__(self, *a): pass


def ensure_dir(path: Path | None = None) -> None:
    """Create the tracking directory if it doesn't exist."""
    (path or TRACKING_DIR).mkdir(parents=True, exist_ok=True)


def acquire_lock(lock_path: Path | None = None, timeout: float = 5):
    """Return a file lock (or no-op if filelock not installed)."""
    try:
        from filelock import FileLock
        return FileLock(str(lock_path or LOCK_FILE), timeout=timeout)
    except ImportError:
        return _NoLock()


def atomic_write_text(path: Path, content: str) -> None:
    """Write content to path via temp file + os.replace (POSIX-atomic)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def is_tracker_hook_group(group: dict) -> bool:
    """True if any hook in the group's command references cc_time_tracker."""
    return any(
        TRACKER_HOOK_MARKER in h.get("command", "")
        for h in group.get("hooks", [])
    )


def extract_project_name(cwd: str) -> str:
    """Derive a project name for cwd, walking up to find a project root.

    Resolution order, walking up from cwd:
      1. ``.cc-project`` marker — if it has content, the first non-empty line
         becomes the project name; if empty, the marker's directory is the root.
      2. ``.git`` (file or directory) — the containing directory's basename.

    The walk stops at ``$HOME`` (exclusive) or the filesystem root. If nothing
    is found, falls back to ``basename(cwd)`` — preserving prior behavior for
    ad-hoc directories.
    """
    fallback = os.path.basename(os.path.normpath(cwd))
    # Hooks must never raise — fall back silently on any FS error.
    try:
        start = Path(cwd).resolve()
    except (OSError, RuntimeError):
        return fallback
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None

    current = start
    while True:
        if home is not None and current == home:
            break

        marker = current / ".cc-project"
        if marker.is_file():
            try:
                first_line = marker.read_text().split("\n", 1)[0].strip()
            except OSError:
                first_line = ""
            return first_line or current.name or fallback

        if (current / ".git").exists():
            return current.name or fallback

        parent = current.parent
        if parent == current:
            break
        current = parent

    return fallback


def load_settings(path: Path) -> dict:
    """Read a JSON settings file, returning {} on missing/malformed files."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def read_hook_input() -> dict:
    """Read JSON from stdin for hook scripts. Exits 1 on bad input."""
    import sys
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(1)


def load_jsonl(path: Path, after_ts: float | None = None) -> list[dict]:
    """Read a JSONL file, returning a list of parsed dicts. Skips bad lines.

    If after_ts is given, only records with timestamp_unix >= after_ts are returned.
    """
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
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if after_ts is not None and record.get("timestamp_unix", 0) < after_ts:
                continue
            records.append(record)
    return records
