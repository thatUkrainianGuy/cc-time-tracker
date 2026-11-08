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
from cc_time_tracker.active_time import measure, session_timestamps

HOOK_LOCK_TIMEOUT_SECONDS = 2


def find_and_remove_active(active_file, session_id: str) -> tuple[dict | None, list[dict]]:
    """Return (earliest matching start record or None, remaining active records).

    Removes ALL start records for this session_id, not just the first. Claude
    Code re-fires SessionStart for one running session (compact/clear/resume
    reuse the same session_id), so duplicate start records can pile up in
    active.jsonl. If any were left behind they'd later be billed from their old
    start time by start_hook's orphan-cleanup, inflating totals by hours. The
    real session began at the earliest start, so duration is measured from that.
    """
    matches: list[dict] = []
    remaining: list[dict] = []
    for record in load_jsonl(active_file):
        if (
            record.get("session_id") == session_id
            and record.get("event") == EVENT_START
        ):
            matches.append(record)
        else:
            remaining.append(record)
    if not matches:
        return None, remaining
    earliest = min(
        matches,
        key=lambda r: coerce_float(r.get("timestamp_unix"), default=float("inf")),
    )
    return earliest, remaining


def main():
    input_data = read_hook_input()

    session_id = strip_control(str(input_data.get("session_id", "unknown")), max_len=128)
    cwd = strip_control(str(input_data.get("cwd", os.getcwd())), max_len=4096)
    reason = strip_control(str(input_data.get("reason", "unknown")), max_len=64)

    transcript_path = input_data.get("transcript_path")

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()

    # Parsed before taking the lock so a big transcript doesn't stall other hooks.
    timestamps = session_timestamps(
        session_id, cwd, transcript_path if isinstance(transcript_path, str) else None,
    )

    with acquire_lock(timeout=HOOK_LOCK_TIMEOUT_SECONDS):
        start_record, remaining = find_and_remove_active(ACTIVE_FILE, session_id)

        # coerce_float prevents a poisoned active.jsonl record (e.g.
        # ``timestamp_unix: "x"``) from blowing up the SessionEnd hook.
        start_ts = coerce_float(start_record.get("timestamp_unix")) if start_record else 0.0
        timing = measure(timestamps, start_ts, now_ts) if start_ts else {"duration_seconds": None}
        project = (start_record or {}).get("project") or extract_project_name(cwd)

        record = {
            "event": EVENT_END,
            "session_id": session_id,
            "cwd": cwd,
            "project": project,
            "reason": reason,
            "timestamp": now.isoformat(),
            "timestamp_unix": now_ts,
            **timing,
        }

        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

        with open(ACTIVE_FILE, "w") as f:
            for rec in remaining:
                f.write(json.dumps(rec) + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
