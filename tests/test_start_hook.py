"""Tests for cc_time_tracker.start_hook"""

import json
from io import StringIO
from unittest.mock import patch

from cc_time_tracker.common import ACTIVE_FILE, SESSIONS_FILE
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
        patch("cc_time_tracker.start_hook.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.start_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.start_hook.ACTIVE_FILE", active),
        patch("cc_time_tracker.start_hook.LOCK_FILE", tmp_path / ".lock"),
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


def test_start_hook_bad_stdin():
    """Start hook should exit 1 on bad JSON input."""
    with patch("sys.stdin", StringIO("not json")):
        try:
            main()
        except SystemExit as e:
            assert e.code == 1
