"""SessionStart hook — records when a Claude Code session begins."""

import json
import os
import sys
from datetime import datetime, timezone

from cc_time_tracker.common import (
    SESSIONS_FILE, ACTIVE_FILE, EVENT_START, EVENT_END, REASON_ORPHAN_CLEANUP,
    ensure_dir, acquire_lock, extract_project_name, load_jsonl, read_hook_input,
)

ORPHAN_THRESHOLD_SECONDS = 24 * 3600  # fallback for records without a pid
HOOK_LOCK_TIMEOUT_SECONDS = 2  # leaves slack under CC's 5s hook timeout


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _cleanup_orphans(now_ts: float) -> tuple[list[dict], list[dict]]:
    """Scan active.jsonl, partitioning into (kept, orphan_end_records).

    A record is an orphan if its recorded pid is no longer alive. For legacy
    records without a pid, fall back to the 24h age threshold.
    """
    kept: list[dict] = []
    orphan_ends: list[dict] = []
    for rec in load_jsonl(ACTIVE_FILE):
        start_ts = rec.get("timestamp_unix", now_ts)
        pid = rec.get("pid")
        if pid is not None:
            is_orphan = not _pid_alive(int(pid))
        else:
            is_orphan = now_ts - start_ts > ORPHAN_THRESHOLD_SECONDS
        if is_orphan:
            orphan_ends.append({
                "event": EVENT_END,
                "session_id": rec.get("session_id", "unknown"),
                "cwd": rec.get("cwd", ""),
                "project": rec.get("project", "unknown"),
                "reason": REASON_ORPHAN_CLEANUP,
                "timestamp": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
                "timestamp_unix": now_ts,
                "duration_seconds": round(now_ts - start_ts, 1),
            })
        else:
            kept.append(rec)
    return kept, orphan_ends


def main():
    input_data = read_hook_input()

    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())
    source = input_data.get("source", "startup")

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()

    record = {
        "event": EVENT_START,
        "session_id": session_id,
        "cwd": cwd,
        "project": extract_project_name(cwd),
        "source": source,
        "timestamp": now.isoformat(),
        "timestamp_unix": now_ts,
        "pid": os.getppid(),
    }

    ensure_dir()

    with acquire_lock(timeout=HOOK_LOCK_TIMEOUT_SECONDS):
        kept, orphan_ends = _cleanup_orphans(now_ts)

        if orphan_ends:
            with open(SESSIONS_FILE, "a") as f:
                for end_rec in orphan_ends:
                    f.write(json.dumps(end_rec) + "\n")
            with open(ACTIVE_FILE, "w") as f:
                for rec in kept:
                    f.write(json.dumps(rec) + "\n")
                f.write(json.dumps(record) + "\n")
        else:
            with open(ACTIVE_FILE, "a") as f:
                f.write(json.dumps(record) + "\n")

        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
