#!/usr/bin/env python3
"""
Claude Code SessionEnd hook — records when a session ends.
Matches the session_id from the start record, calculates duration,
and writes a completed session record.

Must be FAST — SessionEnd has a 1.5s default timeout.
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


def acquire_lock():
    try:
        from filelock import FileLock as FL
        return FL(str(LOCK_FILE), timeout=2)
    except ImportError:
        class NoLock:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return NoLock()


def extract_project_name(cwd: str) -> str:
    return os.path.basename(os.path.normpath(cwd))


def find_start_record(session_id: str) -> dict | None:
    """Find the most recent start record for this session_id."""
    if not ACTIVE_FILE.exists():
        return None

    # Read active sessions, find our match
    match = None
    with open(ACTIVE_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("session_id") == session_id and record.get("event") == "start":
                    match = record
            except json.JSONDecodeError:
                continue
    return match


def remove_from_active(session_id: str):
    """Remove a session from the active tracker."""
    if not ACTIVE_FILE.exists():
        return

    remaining = []
    with open(ACTIVE_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("session_id") != session_id:
                    remaining.append(line)
            except json.JSONDecodeError:
                remaining.append(line)

    with open(ACTIVE_FILE, "w") as f:
        for line in remaining:
            f.write(line + "\n")


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())
    reason = input_data.get("reason", "unknown")  # user_exit | interrupt | other

    now = datetime.now(timezone.utc)

    with acquire_lock():
        start_record = find_start_record(session_id)

        if start_record:
            start_ts = start_record.get("timestamp_unix", 0)
            duration_seconds = now.timestamp() - start_ts
        else:
            # No matching start — log anyway with unknown duration
            duration_seconds = None

        record = {
            "event": "end",
            "session_id": session_id,
            "cwd": cwd,
            "project": extract_project_name(cwd),
            "reason": reason,
            "timestamp": now.isoformat(),
            "timestamp_unix": now.timestamp(),
            "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
        }

        # Append to full session log
        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

        # Remove from active sessions
        remove_from_active(session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
