"""Tests for cc_time_tracker.report — focused on sanitization behavior."""

import io
import json
from contextlib import redirect_stdout

from cc_time_tracker.report import (
    aggregate_by_project,
    aggregate_by_day,
    export_csv,
)


def test_export_csv_neutralizes_formula_in_project():
    sessions = [{
        "event": "end",
        "project": "=HYPERLINK(\"http://x\")",
        "cwd": "/tmp",
        "session_id": "abc",
        "reason": "user_exit",
        "duration_seconds": 60,
        "timestamp_unix": 1742515200.0,
    }]
    buf = io.StringIO()
    with redirect_stdout(buf):
        export_csv(sessions)
    text = buf.getvalue()
    # Project field gets prefixed with ' so spreadsheets render it as text.
    # csv.writer wraps it in double quotes; the leading char inside is `'`.
    assert "\"'=HYPERLINK" in text


def test_export_csv_strips_ansi_from_cwd():
    sessions = [{
        "event": "end",
        "project": "p",
        "cwd": "\x1b[31m/tmp/evil\x1b[0m",
        "session_id": "abc",
        "reason": "ok",
        "duration_seconds": 30,
        "timestamp_unix": 1742515200.0,
    }]
    buf = io.StringIO()
    with redirect_stdout(buf):
        export_csv(sessions)
    text = buf.getvalue()
    assert "\x1b" not in text
    assert "/tmp/evil" in text


def test_export_csv_handles_commas_via_proper_quoting():
    """Old code replaced ',' with ';' — csv.writer should quote instead."""
    sessions = [{
        "event": "end",
        "project": "a,b,c",
        "cwd": "/tmp",
        "session_id": "abc",
        "reason": "ok",
        "duration_seconds": 10,
        "timestamp_unix": 1742515200.0,
    }]
    buf = io.StringIO()
    with redirect_stdout(buf):
        export_csv(sessions)
    text = buf.getvalue()
    # The project field must be properly quoted, not silently mutated.
    assert "\"a,b,c\"" in text


def test_aggregate_by_project_tolerates_bad_duration():
    """A poisoned duration_seconds (string) must not crash aggregation."""
    sessions = [
        {"project": "p", "duration_seconds": "garbage", "cwd": "/tmp"},
        {"project": "p", "duration_seconds": 60, "cwd": "/tmp"},
    ]
    result = aggregate_by_project(sessions)
    # Bad value coerces to 0; only the valid 60 contributes.
    assert result["p"]["total_seconds"] == 60.0
    assert result["p"]["session_count"] == 2


def test_aggregate_by_day_tolerates_bad_timestamp():
    """A poisoned timestamp_unix (string) must not crash aggregation."""
    sessions = [
        {"project": "p", "duration_seconds": 60, "timestamp_unix": "x"},
        {"project": "p", "duration_seconds": 60, "timestamp_unix": 1742515200.0},
    ]
    result = aggregate_by_day(sessions)
    # Bad ts coerces to 0 → falsy → record skipped. One day key remains.
    assert len(result) == 1


def test_merge_evicts_affected_session_ids_from_sync_cursor(tmp_path, monkeypatch):
    """Merging project records must remove their session_ids from the sync
    cursor, so the next sync re-pushes them under the new project name."""
    from cc_time_tracker import common, report, sync

    sessions_file = tmp_path / "sessions.jsonl"
    cursor_file = tmp_path / "sync-cursor.json"
    lock_file = tmp_path / ".lock"
    sessions_file.write_text(
        json.dumps({"event": "end", "session_id": "s1", "project": "old",
                    "duration_seconds": 100, "timestamp_unix": 1.0}) + "\n"
        + json.dumps({"event": "end", "session_id": "s2", "project": "old",
                      "duration_seconds": 200, "timestamp_unix": 2.0}) + "\n"
        + json.dumps({"event": "end", "session_id": "s3", "project": "keepme",
                      "duration_seconds": 50, "timestamp_unix": 3.0}) + "\n"
    )
    cursor_file.write_text(
        json.dumps({"pushed_events": ["s1|1.0", "s2|2.0", "s3|3.0"]})
    )

    monkeypatch.setattr(common, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(common, "LOCK_FILE", lock_file)
    monkeypatch.setattr(report, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sync, "CURSOR_FILE", cursor_file)

    count = report.merge_project_sessions("old", "new")
    assert count == 2

    cur = json.loads(cursor_file.read_text())
    assert cur["pushed_events"] == ["s3|3.0"]


def test_merge_tolerates_absent_sync_cursor(tmp_path, monkeypatch):
    """Merge must succeed even when no sync cursor exists yet."""
    from cc_time_tracker import common, report, sync

    sessions_file = tmp_path / "sessions.jsonl"
    cursor_file = tmp_path / "sync-cursor.json"  # never created
    lock_file = tmp_path / ".lock"
    sessions_file.write_text(
        json.dumps({"event": "end", "session_id": "s1", "project": "old",
                    "duration_seconds": 100, "timestamp_unix": 1.0}) + "\n"
    )

    monkeypatch.setattr(common, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(common, "LOCK_FILE", lock_file)
    monkeypatch.setattr(report, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sync, "CURSOR_FILE", cursor_file)

    assert report.merge_project_sessions("old", "new") == 1
    assert not cursor_file.exists()
