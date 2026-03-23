"""SessionEnd hook — records when a Claude Code session ends."""

import json
import os
import sys
from datetime import datetime, timezone

from cc_time_tracker.common import (
    TRACKING_DIR, SESSIONS_FILE, ACTIVE_FILE, LOCK_FILE,
    acquire_lock, extract_project_name, load_jsonl,
)


def find_start_record(session_id: str) -> dict | None:
    """Find the most recent start record for this session_id in active.jsonl."""
    for record in load_jsonl(ACTIVE_FILE):
        if record.get("session_id") == session_id and record.get("event") == "start":
            return record
    return None


def remove_from_active(session_id: str) -> None:
    """Remove a session from the active tracker. Preserves malformed lines."""
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
                remaining.append(line)  # preserve malformed lines
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
    reason = input_data.get("reason", "unknown")

    now = datetime.now(timezone.utc)

    with acquire_lock():
        start_record = find_start_record(session_id)

        if start_record:
            start_ts = start_record.get("timestamp_unix", 0)
            duration_seconds = now.timestamp() - start_ts
        else:
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

        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

        remove_from_active(session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
