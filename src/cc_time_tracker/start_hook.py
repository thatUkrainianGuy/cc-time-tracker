"""SessionStart hook — records when a Claude Code session begins."""

import json
import os
import sys
from datetime import datetime, timezone

from cc_time_tracker.common import (
    SESSIONS_FILE, ACTIVE_FILE,
    ensure_dir, acquire_lock, extract_project_name, read_hook_input,
)

ORPHAN_THRESHOLD_SECONDS = 24 * 3600  # 24 hours


def _cleanup_orphans(now_ts: float) -> tuple[list[str], list[dict]]:
    """Scan active.jsonl, return (kept_lines, orphan_end_records)."""
    kept = []
    orphan_ends = []
    try:
        f = open(ACTIVE_FILE, "r")
    except FileNotFoundError:
        return [], []
    with f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                kept.append(stripped)
                continue
            start_ts = rec.get("timestamp_unix", now_ts)
            if now_ts - start_ts > ORPHAN_THRESHOLD_SECONDS:
                orphan_ends.append({
                    "event": "end",
                    "session_id": rec.get("session_id", "unknown"),
                    "cwd": rec.get("cwd", ""),
                    "project": rec.get("project", "unknown"),
                    "reason": "orphan_cleanup",
                    "timestamp": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
                    "timestamp_unix": now_ts,
                    "duration_seconds": round(now_ts - start_ts, 1),
                })
            else:
                kept.append(stripped)
    return kept, orphan_ends


def main():
    input_data = read_hook_input()

    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())
    source = input_data.get("source", "startup")

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()

    record = {
        "event": "start",
        "session_id": session_id,
        "cwd": cwd,
        "project": extract_project_name(cwd),
        "source": source,
        "timestamp": now.isoformat(),
        "timestamp_unix": now_ts,
    }

    ensure_dir()

    with acquire_lock():
        kept_lines, orphan_ends = _cleanup_orphans(now_ts)

        if orphan_ends:
            # Write synthetic end records for orphaned sessions
            with open(SESSIONS_FILE, "a") as f:
                for end_rec in orphan_ends:
                    f.write(json.dumps(end_rec) + "\n")
            # Rewrite active.jsonl without orphans, then append new start
            with open(ACTIVE_FILE, "w") as f:
                for line in kept_lines:
                    f.write(line + "\n")
                f.write(json.dumps(record) + "\n")
        else:
            with open(ACTIVE_FILE, "a") as f:
                f.write(json.dumps(record) + "\n")

        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
