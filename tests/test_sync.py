import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from cc_time_tracker import sync


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "TRACKING_DIR", tmp_path)
    monkeypatch.setattr(sync, "SESSIONS_FILE", tmp_path / "sessions.jsonl")
    monkeypatch.setattr(sync, "CURSOR_FILE", tmp_path / "sync-cursor.json")
    monkeypatch.setattr(sync, "CONFIG_FILE", tmp_path / "sync-config.json")
    (tmp_path / "sync-config.json").write_text(
        json.dumps({"endpoint": "https://example.test/api/sync", "api_key": "k"})
    )
    return tmp_path


def write_sessions(p: Path, records):
    with p.open("a") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _key(sid: str, end_at: float) -> str:
    """Cursor key format used by sync: 'session_id|end_at'."""
    return f"{sid}|{end_at}"


def test_collects_only_completed_sessions(workdir):
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {"event": "start", "session_id": "a", "project": "x", "timestamp_unix": 1.0},
            {
                "event": "end",
                "session_id": "a",
                "project": "x",
                "timestamp_unix": 2.0,
                "duration_seconds": 1.0,
            },
            {"event": "start", "session_id": "b", "project": "y", "timestamp_unix": 3.0},
        ],
    )
    pending = sync.collect_pending(workdir / "sessions.jsonl", set())
    assert len(pending) == 1
    assert pending[0]["session_id"] == "a"


def test_collects_every_end_event_for_same_session_id(workdir):
    """A session_id with multiple end events (e.g. /clear then prompt_exit)
    produces multiple pending records — each end event is its own row server-side."""
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {"event": "end", "session_id": "a", "project": "x",
             "timestamp_unix": 100.0, "duration_seconds": 100.0},
            {"event": "end", "session_id": "a", "project": "x",
             "timestamp_unix": 350.0, "duration_seconds": 150.0},
        ],
    )
    pending = sync.collect_pending(workdir / "sessions.jsonl", set())
    assert len(pending) == 2
    assert {p["end_at"] for p in pending} == {100.0, 350.0}
    assert all(p["session_id"] == "a" for p in pending)


def test_skips_already_pushed_event(workdir):
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {
                "event": "end",
                "session_id": "a",
                "project": "x",
                "timestamp_unix": 2.0,
                "duration_seconds": 1.0,
            },
        ],
    )
    pending = sync.collect_pending(workdir / "sessions.jsonl", {_key("a", 2.0)})
    assert pending == []


def test_skips_pushed_event_keeps_unpushed_end_for_same_session(workdir):
    """If only one of two end events for the same session_id was previously
    pushed, the other still gets re-sent."""
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {"event": "end", "session_id": "a", "project": "x",
             "timestamp_unix": 100.0, "duration_seconds": 100.0},
            {"event": "end", "session_id": "a", "project": "x",
             "timestamp_unix": 350.0, "duration_seconds": 150.0},
        ],
    )
    pending = sync.collect_pending(workdir / "sessions.jsonl", {_key("a", 100.0)})
    assert len(pending) == 1
    assert pending[0]["end_at"] == 350.0


def test_push_uses_bearer_auth_and_marks_event_key_pushed(workdir):
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {
                "event": "end",
                "session_id": "a",
                "project": "x",
                "timestamp_unix": 2.0,
                "duration_seconds": 1.0,
            },
        ],
    )
    fake_resp = MagicMock(status=200)
    fake_resp.read.return_value = b'{"ingested":1,"skipped":0}'
    with patch.object(sync, "_http_post", return_value=fake_resp) as p:
        rc = sync.run_once(dry_run=False)
    assert rc == 0
    p.assert_called_once()
    args, kwargs = p.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer k"
    cur = json.loads((workdir / "sync-cursor.json").read_text())
    assert _key("a", 2.0) in cur["pushed_events"]


def test_dry_run_does_not_post(workdir):
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {
                "event": "end",
                "session_id": "a",
                "project": "x",
                "timestamp_unix": 2.0,
                "duration_seconds": 1.0,
            },
        ],
    )
    with patch.object(sync, "_http_post") as p:
        rc = sync.run_once(dry_run=True)
    assert rc == 0
    p.assert_not_called()
    assert not (workdir / "sync-cursor.json").exists()


def test_rejects_plain_http_endpoint(workdir):
    (workdir / "sync-config.json").write_text(
        json.dumps({"endpoint": "http://example.test/api/sync", "api_key": "k"})
    )
    with pytest.raises(SystemExit, match="endpoint must be https"):
        sync.run_once(dry_run=True)


def test_allows_localhost_http_endpoint(workdir):
    (workdir / "sync-config.json").write_text(
        json.dumps({"endpoint": "http://localhost:8787/api/sync", "api_key": "k"})
    )
    rc = sync.run_once(dry_run=True)
    assert rc == 0


def test_rejects_placeholder_api_key(workdir):
    (workdir / "sync-config.json").write_text(
        json.dumps({"endpoint": "https://example.test/api/sync", "api_key": "REPLACE_ME"})
    )
    with pytest.raises(SystemExit, match="missing api_key"):
        sync.run_once(dry_run=True)


def test_collect_pending_sanitizes_uploaded_identifiers(workdir):
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {
                "event": "end",
                "session_id": "abc\x1b[31m123",
                "project": "\x1b]8;;https://evil/\x1b\\client\x1b]8;;\x1b\\",
                "timestamp_unix": 2.0,
                "duration_seconds": 1.0,
            },
        ],
    )
    pending = sync.collect_pending(workdir / "sessions.jsonl", set())
    assert pending[0]["session_id"] == "abc123"
    assert pending[0]["tracker_name"] == "client"


def test_collect_pending_uses_sanitized_session_id_for_cursor_key(workdir):
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {
                "event": "end",
                "session_id": "abc\x1b[31m123",
                "project": "x",
                "timestamp_unix": 2.0,
                "duration_seconds": 1.0,
            },
        ],
    )
    pending = sync.collect_pending(workdir / "sessions.jsonl", {_key("abc123", 2.0)})
    assert pending == []


def test_5xx_keeps_cursor_unchanged(workdir):
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {
                "event": "end",
                "session_id": "a",
                "project": "x",
                "timestamp_unix": 2.0,
                "duration_seconds": 1.0,
            },
        ],
    )
    fake_resp = MagicMock(status=503)
    fake_resp.read.return_value = b"oops"
    with patch.object(sync, "_http_post", return_value=fake_resp):
        rc = sync.run_once(dry_run=False)
    assert rc != 0
    assert not (workdir / "sync-cursor.json").exists()


def test_legacy_cursor_with_only_session_ids_is_treated_as_empty(workdir):
    """Cursor written by the pre-composite-PK client used pushed_session_ids.
    Reading such a cursor must not skip events — the new format keys by
    (session_id, end_at) and the old data is insufficient to reconstruct
    those keys. Re-pushing is safe because the server handles idempotency."""
    cursor = workdir / "sync-cursor.json"
    cursor.write_text(json.dumps({"pushed_session_ids": ["a", "b"]}))
    write_sessions(
        workdir / "sessions.jsonl",
        [
            {"event": "end", "session_id": "a", "project": "x",
             "timestamp_unix": 2.0, "duration_seconds": 1.0},
        ],
    )
    fake_resp = MagicMock(status=200)
    fake_resp.read.return_value = b'{"ingested":1,"skipped":0}'
    with patch.object(sync, "_http_post", return_value=fake_resp) as p:
        rc = sync.run_once(dry_run=False)
    assert rc == 0
    p.assert_called_once()  # event was sent, not skipped
    cur = json.loads(cursor.read_text())
    assert "pushed_session_ids" not in cur  # legacy field dropped
    assert _key("a", 2.0) in cur["pushed_events"]


# ── evict_session_ids_from_cursor ──────────────────────────────────────────


def test_evict_removes_all_events_for_given_session_ids(workdir):
    cursor = workdir / "sync-cursor.json"
    cursor.write_text(json.dumps({"pushed_events": [
        _key("a", 100.0), _key("a", 200.0), _key("b", 50.0), _key("c", 10.0),
    ]}))
    removed = sync.evict_session_ids_from_cursor(cursor, ["a", "c"])
    assert removed == 3  # two for a + one for c
    cur = json.loads(cursor.read_text())
    assert cur["pushed_events"] == [_key("b", 50.0)]


def test_evict_returns_zero_when_no_ids_match(workdir):
    cursor = workdir / "sync-cursor.json"
    cursor.write_text(json.dumps({"pushed_events": [_key("a", 1.0), _key("b", 2.0)]}))
    removed = sync.evict_session_ids_from_cursor(cursor, ["x", "y"])
    assert removed == 0
    cur = json.loads(cursor.read_text())
    assert sorted(cur["pushed_events"]) == sorted([_key("a", 1.0), _key("b", 2.0)])


def test_evict_tolerates_missing_cursor(tmp_path):
    cursor = tmp_path / "nope.json"
    removed = sync.evict_session_ids_from_cursor(cursor, ["a"])
    assert removed == 0
    assert not cursor.exists()


def test_evict_tolerates_malformed_cursor(tmp_path):
    cursor = tmp_path / "sync-cursor.json"
    cursor.write_text("not json at all")
    removed = sync.evict_session_ids_from_cursor(cursor, ["a"])
    assert removed == 0


def test_evict_empty_ids_is_noop(workdir):
    cursor = workdir / "sync-cursor.json"
    cursor.write_text(json.dumps({"pushed_events": [_key("a", 1.0)]}))
    removed = sync.evict_session_ids_from_cursor(cursor, [])
    assert removed == 0
    cur = json.loads(cursor.read_text())
    assert cur["pushed_events"] == [_key("a", 1.0)]


def test_evict_handles_legacy_cursor_format(workdir):
    """A merge running against a pre-migration cursor file (still using
    pushed_session_ids) should not crash; the cursor is essentially
    invalidated, which is fine — next sync re-pushes everything."""
    cursor = workdir / "sync-cursor.json"
    cursor.write_text(json.dumps({"pushed_session_ids": ["a", "b"]}))
    # Must not raise.
    sync.evict_session_ids_from_cursor(cursor, ["a"])
