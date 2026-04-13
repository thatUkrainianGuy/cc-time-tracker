"""Tests for cc_time_tracker.start_hook"""

import json
from io import StringIO
from unittest.mock import patch

from cc_time_tracker.start_hook import main


def test_start_hook_writes_records(tmp_path):
    """Start hook should write to both sessions.jsonl and active.jsonl."""
    sessions = tmp_path / "sessions.jsonl"
    active = tmp_path / "active.jsonl"

    input_data = json.dumps({
        "session_id": "test-123",
        "cwd": "/home/user/myproject",
        "source": "startup",
    })

    with (
        patch("cc_time_tracker.common.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.common.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.common.ACTIVE_FILE", active),
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.start_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.start_hook.ACTIVE_FILE", active),
        patch("sys.stdin", StringIO(input_data)),
    ):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0

    # Verify sessions.jsonl
    session_records = [json.loads(l) for l in sessions.read_text().strip().split("\n")]
    assert len(session_records) == 1
    assert session_records[0]["event"] == "start"
    assert session_records[0]["session_id"] == "test-123"
    assert session_records[0]["project"] == "myproject"

    # Verify active.jsonl
    active_records = [json.loads(l) for l in active.read_text().strip().split("\n")]
    assert len(active_records) == 1
    assert active_records[0]["session_id"] == "test-123"


def test_start_hook_cleans_orphans(tmp_path):
    """Start hook should auto-close sessions older than 24h."""
    sessions = tmp_path / "sessions.jsonl"
    active = tmp_path / "active.jsonl"

    import time
    now_ts = time.time()
    orphan_ts = now_ts - 25 * 3600  # 25 hours ago
    fresh_ts = now_ts - 3600        # 1 hour ago

    orphan_rec = json.dumps({
        "event": "start", "session_id": "orphan-1",
        "cwd": "/home/user/old", "project": "old",
        "timestamp_unix": orphan_ts,
    })
    fresh_rec = json.dumps({
        "event": "start", "session_id": "fresh-1",
        "cwd": "/home/user/recent", "project": "recent",
        "timestamp_unix": fresh_ts,
    })
    active.write_text(orphan_rec + "\n" + fresh_rec + "\n")
    sessions.write_text("")

    input_data = json.dumps({
        "session_id": "new-1",
        "cwd": "/home/user/myproject",
        "source": "startup",
    })

    with (
        patch("cc_time_tracker.common.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.common.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.common.ACTIVE_FILE", active),
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.start_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.start_hook.ACTIVE_FILE", active),
        patch("sys.stdin", StringIO(input_data)),
    ):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0

    # Sessions should have: orphan end record + new start record
    sess_records = [json.loads(l) for l in sessions.read_text().strip().split("\n")]
    orphan_end = [r for r in sess_records if r.get("reason") == "orphan_cleanup"]
    assert len(orphan_end) == 1
    assert orphan_end[0]["session_id"] == "orphan-1"
    assert orphan_end[0]["duration_seconds"] > 24 * 3600

    # Active should have: fresh-1 + new-1 (orphan removed)
    active_records = [json.loads(l) for l in active.read_text().strip().split("\n")]
    active_ids = {r["session_id"] for r in active_records}
    assert "orphan-1" not in active_ids
    assert "fresh-1" in active_ids
    assert "new-1" in active_ids


def test_start_hook_bad_stdin():
    """Start hook should exit 1 on bad JSON input."""
    with patch("sys.stdin", StringIO("not json")):
        try:
            main()
        except SystemExit as e:
            assert e.code == 1
