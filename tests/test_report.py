"""Tests for cc_time_tracker.report — focused on sanitization behavior."""

import io
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
