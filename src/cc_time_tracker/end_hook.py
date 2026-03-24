"""SessionEnd hook — records when a Claude Code session ends."""

import json
import os
import sys
from datetime import datetime, timezone

from cc_time_tracker.common import (
    SESSIONS_FILE, ACTIVE_FILE,
    acquire_lock, extract_project_name, read_hook_input,
)


def read_and_filter_active(active_file, session_id: str) -> tuple[dict | None, list[str]]:
    """Read active.jsonl once, returning the matching start record and remaining lines."""
    match = None
    remaining = []
    try:
        f = open(active_file, "r")
    except FileNotFoundError:
        return None, []
    with f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
                if record.get("session_id") == session_id and record.get("event") == "start":
                    match = record
                else:
                    remaining.append(stripped)
            except json.JSONDecodeError:
                remaining.append(stripped)
    return match, remaining


def main():
    input_data = read_hook_input()

    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())
    reason = input_data.get("reason", "unknown")

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()

    with acquire_lock():
        start_record, remaining_lines = read_and_filter_active(ACTIVE_FILE, session_id)

        if start_record:
            start_ts = start_record.get("timestamp_unix", 0)
            duration_seconds = now_ts - start_ts
        else:
            duration_seconds = None

        record = {
            "event": "end",
            "session_id": session_id,
            "cwd": cwd,
            "project": extract_project_name(cwd),
            "reason": reason,
            "timestamp": now.isoformat(),
            "timestamp_unix": now_ts,
            "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
        }

        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

        with open(ACTIVE_FILE, "w") as f:
            for line in remaining_lines:
                f.write(line + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
