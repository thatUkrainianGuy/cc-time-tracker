"""Tests for cc_time_tracker.end_hook"""

import json
import time
from io import StringIO
from unittest.mock import patch

from cc_time_tracker.end_hook import main


def test_end_hook_calculates_duration(tmp_path):
    """End hook should find start record, calculate duration, write end record."""
    sessions = tmp_path / "sessions.jsonl"
    active = tmp_path / "active.jsonl"

    start_ts = time.time() - 300  # 5 minutes ago
    start_record = json.dumps({
        "event": "start",
        "session_id": "test-123",
        "cwd": "/home/user/myproject",
        "project": "myproject",
        "source": "startup",
        "timestamp": "2026-03-23T10:00:00+00:00",
        "timestamp_unix": start_ts,
    })
    active.write_text(start_record + "\n")

    input_data = json.dumps({
        "session_id": "test-123",
        "cwd": "/home/user/myproject",
        "reason": "user_exit",
    })

    with (
        patch("cc_time_tracker.common.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.common.ACTIVE_FILE", active),
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.end_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.end_hook.ACTIVE_FILE", active),
        patch("sys.stdin", StringIO(input_data)),
    ):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0

    # Verify end record written
    records = [json.loads(l) for l in sessions.read_text().strip().split("\n")]
    assert len(records) == 1
    assert records[0]["event"] == "end"
    assert records[0]["duration_seconds"] is not None
    assert records[0]["duration_seconds"] > 200  # ~5 min

    # Verify removed from active
    assert active.read_text().strip() == ""


def test_end_hook_removes_all_duplicate_starts(tmp_path):
    """Multiple start records for one session_id (from compacts) must all be
    removed on end, with duration measured from the earliest start."""
    sessions = tmp_path / "sessions.jsonl"
    active = tmp_path / "active.jsonl"

    now = time.time()
    starts = [
        json.dumps({
            "event": "start", "session_id": "dup-1",
            "cwd": "/home/user/proj", "project": "proj",
            "source": src, "timestamp_unix": now - age,
        })
        for src, age in (("startup", 600), ("compact", 400), ("compact", 120))
    ]
    other = json.dumps({
        "event": "start", "session_id": "other-1",
        "cwd": "/home/user/x", "project": "x", "timestamp_unix": now - 50,
    })
    active.write_text("\n".join(starts + [other]) + "\n")

    input_data = json.dumps({
        "session_id": "dup-1",
        "cwd": "/home/user/proj",
        "reason": "user_exit",
    })

    with (
        patch("cc_time_tracker.common.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.common.ACTIVE_FILE", active),
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.end_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.end_hook.ACTIVE_FILE", active),
        patch("sys.stdin", StringIO(input_data)),
    ):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0

    # Exactly one end record, billed from the earliest start (~600s ago).
    end_records = [json.loads(l) for l in sessions.read_text().strip().split("\n")]
    assert len(end_records) == 1
    assert end_records[0]["event"] == "end"
    assert end_records[0]["duration_seconds"] > 550

    # All dup-1 starts gone; the unrelated session survives.
    active_ids = [json.loads(l)["session_id"] for l in active.read_text().strip().split("\n")]
    assert "dup-1" not in active_ids
    assert active_ids == ["other-1"]


def test_end_hook_no_matching_start(tmp_path):
    """End hook should still write record even without a matching start."""
    sessions = tmp_path / "sessions.jsonl"
    active = tmp_path / "active.jsonl"
    active.write_text("")

    input_data = json.dumps({
        "session_id": "orphan-456",
        "cwd": "/tmp/test",
        "reason": "user_exit",
    })

    with (
        patch("cc_time_tracker.common.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.common.ACTIVE_FILE", active),
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.end_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.end_hook.ACTIVE_FILE", active),
        patch("sys.stdin", StringIO(input_data)),
    ):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0

    records = [json.loads(l) for l in sessions.read_text().strip().split("\n")]
    assert records[0]["duration_seconds"] is None
