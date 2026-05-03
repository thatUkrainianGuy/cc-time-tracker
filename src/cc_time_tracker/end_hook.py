"""SessionEnd hook — records when a Claude Code session ends."""

import json
import os
import sys
from datetime import datetime, timezone

from cc_time_tracker.common import (
    SESSIONS_FILE, ACTIVE_FILE, EVENT_START, EVENT_END,
    acquire_lock, extract_project_name, load_jsonl, read_hook_input,
    coerce_float, strip_control,
)

HOOK_LOCK_TIMEOUT_SECONDS = 2


def find_and_remove_active(active_file, session_id: str) -> tuple[dict | None, list[dict]]:
    """Return (matching start record or None, remaining active records)."""
    match: dict | None = None
    remaining: list[dict] = []
    for record in load_jsonl(active_file):
        if (
            match is None
            and record.get("session_id") == session_id
            and record.get("event") == EVENT_START
        ):
            match = record
        else:
            remaining.append(record)
    return match, remaining


def main():
    input_data = read_hook_input()

    session_id = strip_control(str(input_data.get("session_id", "unknown")), max_len=128)
    cwd = strip_control(str(input_data.get("cwd", os.getcwd())), max_len=4096)
    reason = strip_control(str(input_data.get("reason", "unknown")), max_len=64)

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()

    with acquire_lock(timeout=HOOK_LOCK_TIMEOUT_SECONDS):
        start_record, remaining = find_and_remove_active(ACTIVE_FILE, session_id)

        if start_record:
            # coerce_float prevents a poisoned active.jsonl record (e.g.
            # ``timestamp_unix: "x"``) from blowing up the SessionEnd hook.
            start_ts = coerce_float(start_record.get("timestamp_unix"))
            duration_seconds = now_ts - start_ts if start_ts else None
            project = start_record.get("project") or extract_project_name(cwd)
        else:
            duration_seconds = None
            project = extract_project_name(cwd)

        record = {
            "event": EVENT_END,
            "session_id": session_id,
            "cwd": cwd,
            "project": project,
            "reason": reason,
            "timestamp": now.isoformat(),
            "timestamp_unix": now_ts,
            "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
        }

        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

        with open(ACTIVE_FILE, "w") as f:
            for rec in remaining:
                f.write(json.dumps(rec) + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
