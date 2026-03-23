"""SessionStart hook — records when a Claude Code session begins."""

import json
import os
import sys
from datetime import datetime, timezone

from cc_time_tracker.common import (
    SESSIONS_FILE, ACTIVE_FILE,
    ensure_dir, acquire_lock, extract_project_name,
)


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())
    source = input_data.get("source", "startup")

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
        with open(ACTIVE_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
