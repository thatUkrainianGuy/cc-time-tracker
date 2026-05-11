import json
import os
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


def test_skips_already_pushed(workdir):
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
    pending = sync.collect_pending(workdir / "sessions.jsonl", {"a"})
    assert pending == []


def test_push_uses_bearer_auth_and_marks_pushed(workdir):
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
    assert "a" in cur["pushed_session_ids"]


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


# ── evict_session_ids_from_cursor ──────────────────────────────────────────


def test_evict_removes_given_ids(workdir):
    cursor = workdir / "sync-cursor.json"
    cursor.write_text(
        json.dumps({"pushed_session_ids": ["a", "b", "c"], "last_pushed_at_unix": 0})
    )
    removed = sync.evict_session_ids_from_cursor(cursor, ["a", "c"])
    assert removed == 2
    cur = json.loads(cursor.read_text())
    assert cur["pushed_session_ids"] == ["b"]


def test_evict_returns_zero_when_no_ids_match(workdir):
    cursor = workdir / "sync-cursor.json"
    cursor.write_text(json.dumps({"pushed_session_ids": ["a", "b"]}))
    removed = sync.evict_session_ids_from_cursor(cursor, ["x", "y"])
    assert removed == 0
    cur = json.loads(cursor.read_text())
    assert sorted(cur["pushed_session_ids"]) == ["a", "b"]


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
    cursor.write_text(json.dumps({"pushed_session_ids": ["a"]}))
    removed = sync.evict_session_ids_from_cursor(cursor, [])
    assert removed == 0
    cur = json.loads(cursor.read_text())
    assert cur["pushed_session_ids"] == ["a"]
