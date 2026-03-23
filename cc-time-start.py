#!/usr/bin/env python3
"""
Claude Code SessionStart hook — records when a session begins.
Receives JSON on stdin with session_id, cwd, source, etc.
Writes a start record to ~/.claude/time-tracking/sessions.jsonl
"""

import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
TRACKING_DIR = Path.home() / ".claude" / "time-tracking"
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
ACTIVE_FILE = TRACKING_DIR / "active.jsonl"
LOCK_FILE = TRACKING_DIR / ".lock"


def ensure_dir():
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)


def acquire_lock():
    """Simple file-based locking for concurrent session safety."""
    try:
        from filelock import FileLock as FL
        return FL(str(LOCK_FILE), timeout=5)
    except ImportError:
        # Fallback: no-op context manager
        class NoLock:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return NoLock()


def extract_project_name(cwd: str) -> str:
    """
    Derive a human-readable project name from the working directory.
    Uses the last directory component, e.g. /home/igor/projects/streetkast → streetkast
    """
    return os.path.basename(os.path.normpath(cwd))


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())
    source = input_data.get("source", "startup")  # startup | resume | clear | compact

    now = datetime.now(timezone.utc)

    record = {
        "event": "start",
        "session_id": session_id,
        "cwd": cwd,
        "project": extract_project_name(cwd),
        "source": source,
        "timestamp": now.isoformat(),
        "timestamp_unix": now.timestamp(),
    }

    ensure_dir()

    with acquire_lock():
        # Write to active sessions tracker
        with open(ACTIVE_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

        # Also append to the full session log
        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

    # Exit 0 = success, proceed normally
    sys.exit(0)


if __name__ == "__main__":
    main()
