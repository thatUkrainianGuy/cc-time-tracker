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


def test_rejects_plain_http_endpoint(workdir, capsys):
    (workdir / "sync-config.json").write_text(
        json.dumps({"endpoint": "http://example.test/api/sync", "api_key": "k"})
    )
    assert sync.run_once(dry_run=True) == 2
    assert "endpoint must be https" in capsys.readouterr().err


def test_allows_localhost_http_endpoint(workdir):
    (workdir / "sync-config.json").write_text(
        json.dumps({"endpoint": "http://localhost:8787/api/sync", "api_key": "k"})
    )
    rc = sync.run_once(dry_run=True)
    assert rc == 0


def test_rejects_placeholder_api_key(workdir, capsys):
    (workdir / "sync-config.json").write_text(
        json.dumps({"endpoint": "https://example.test/api/sync", "api_key": "REPLACE_ME"})
    )
    assert sync.run_once(dry_run=True) == 2
    assert "missing api_key" in capsys.readouterr().err


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


def test_start_at_uses_wall_seconds_not_active_duration(workdir):
    write_sessions(workdir / "sessions.jsonl", [
        {"event": "end", "session_id": "a", "project": "x", "timestamp_unix": 10_000.0,
         "duration_seconds": 600.0, "wall_seconds": 7200.0, "active_source": "transcript"},
        # Legacy record: no wall_seconds, duration is wall time.
        {"event": "end", "session_id": "b", "project": "x", "timestamp_unix": 10_000.0,
         "duration_seconds": 300.0},
    ])
    a, b = sync.collect_pending(workdir / "sessions.jsonl", set())
    assert (a["start_at"], a["duration_seconds"]) == (2800.0, 600.0)
    assert (b["start_at"], b["duration_seconds"]) == (9700.0, 300.0)


# ── multiple targets ───────────────────────────────────────────────────────

UNI = "https://unicorni.sh/api/sync"
PORTAL = "https://example.test/api/sync"


def _end(sid, project, t):
    return {"event": "end", "session_id": sid, "project": project,
            "timestamp_unix": t, "duration_seconds": 10.0}


@pytest.fixture
def multi(workdir):
    key = workdir / "uni-key"
    key.write_text("uni-secret\n")
    key.chmod(0o600)
    (workdir / "sync-config.json").write_text(json.dumps({
        "endpoint": PORTAL, "api_key": "k",
        "targets": [{"name": "unicornish", "endpoint": UNI, "api_key_file": str(key),
                     "include": ["heerish", "mcxfirstcohort", "Peerish"]}],
    }))
    write_sessions(workdir / "sessions.jsonl", [
        _end("a", "heerish", 100.0), _end("b", "AcmeClient", 200.0),
        _end("c", "Peerish", 300.0), _end("d", "peerish", 400.0),
    ])
    return workdir


def _ok():
    return MagicMock(status=200)


def _bodies(post, url):
    return [c.args[1] for c in post.call_args_list if c.args[0] == url]


def test_legacy_config_is_portal_target_without_filter(workdir):
    write_sessions(workdir / "sessions.jsonl", [_end("a", "AcmeClient", 1.0)])
    with patch.object(sync, "_http_post", return_value=_ok()) as post:
        assert sync.run_once() == 0
    assert [c.args[0] for c in post.call_args_list] == [PORTAL]
    cur = json.loads((workdir / "sync-cursor.json").read_text())
    assert cur == {"pushed_events": [_key("a", 1.0)]}


def test_include_filter_on_the_wire(multi):
    with patch.object(sync, "_http_post", return_value=_ok()) as post:
        assert sync.run_once() == 0
    (uni_body,) = _bodies(post, UNI)
    assert b"AcmeClient" not in uni_body and b"peerish" not in uni_body  # exact, case-sensitive
    names = {s["tracker_name"] for s in json.loads(uni_body)["sessions"]}
    assert names == {"heerish", "Peerish"}
    assert post.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer uni-secret"
    (portal_body,) = _bodies(post, PORTAL)
    assert len(json.loads(portal_body)["sessions"]) == 4


def test_per_target_cursor_and_lossless_migration(multi):
    old = {"pushed_events": [_key("a", 100.0), _key("zz", 1.0)], "extra": 1}
    (multi / "sync-cursor.json").write_text(json.dumps(old))
    with patch.object(sync, "_http_post", return_value=_ok()) as post:
        assert sync.run_once() == 0
    cur = json.loads((multi / "sync-cursor.json").read_text())
    assert set(old["pushed_events"]) <= set(cur["pushed_events"])  # nothing lost
    assert cur["extra"] == 1
    assert len(json.loads(_bodies(post, PORTAL)[0])["sessions"]) == 3  # "a" not re-pushed
    assert cur["targets"]["unicornish"]["pushed_events"] == [_key("a", 100.0), _key("c", 300.0)]
    with patch.object(sync, "_http_post", return_value=_ok()) as post:
        assert sync.run_once() == 0
    post.assert_not_called()


def test_one_target_failing_does_not_block_others(multi):
    def post(url, data, headers):
        if url == PORTAL:
            raise sync.urllib.error.URLError("down")
        return _ok()
    with patch.object(sync, "_http_post", side_effect=post):
        assert sync.run_once() == 3
    cur = json.loads((multi / "sync-cursor.json").read_text())
    assert cur["pushed_events"] == []
    assert len(cur["targets"]["unicornish"]["pushed_events"]) == 2


def test_bad_target_config_does_not_block_others(multi, capsys):
    (multi / "uni-key").unlink()
    with patch.object(sync, "_http_post", return_value=_ok()) as post:
        assert sync.run_once() == 2
    assert [c.args[0] for c in post.call_args_list] == [PORTAL]
    assert "[unicornish] cannot read api_key_file" in capsys.readouterr().err


def test_api_key_file_must_be_private(multi, capsys):
    (multi / "uni-key").chmod(0o644)
    with patch.object(sync, "_http_post", return_value=_ok()) as post:
        assert sync.run_once(only="unicornish") == 2
    post.assert_not_called()
    assert "chmod 600" in capsys.readouterr().err


def test_api_key_file_expands_home(multi, monkeypatch):
    monkeypatch.setenv("HOME", str(multi))
    cfg = json.loads((multi / "sync-config.json").read_text())
    cfg["targets"][0]["api_key_file"] = "~/uni-key"
    (multi / "sync-config.json").write_text(json.dumps(cfg))
    with patch.object(sync, "_http_post", return_value=_ok()) as post:
        assert sync.run_once(only="unicornish") == 0
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer uni-secret"


def test_target_flag_and_per_target_dry_run(multi, capsys):
    with patch.object(sync, "_http_post") as post:
        assert sync.run_once(dry_run=True, only="unicornish") == 0
    post.assert_not_called()
    out = capsys.readouterr().out
    assert "[unicornish] would push 2 session(s)" in out and "AcmeClient" not in out
    assert "[portal]" not in out
    with pytest.raises(SystemExit, match="no target named"):
        sync.run_once(only="nope")


def test_reset_only_touches_selected_target(multi):
    (multi / "sync-cursor.json").write_text(json.dumps({
        "pushed_events": [_key("a", 100.0)],
        "targets": {"unicornish": {"pushed_events": [_key("a", 100.0)]}},
    }))
    with patch.object(sync, "_http_post"):
        sync.run_once(dry_run=True, only="unicornish", reset=True)
    cur = json.loads((multi / "sync-cursor.json").read_text())
    assert cur["pushed_events"] == [_key("a", 100.0)]
    assert cur["targets"]["unicornish"]["pushed_events"] == []


def test_duplicate_target_names_rejected(workdir):
    (workdir / "sync-config.json").write_text(json.dumps({
        "endpoint": PORTAL, "api_key": "k",
        "targets": [{"name": "portal", "endpoint": UNI, "api_key": "x"}],
    }))
    with pytest.raises(SystemExit, match="unique name"):
        sync.run_once(dry_run=True)


def test_evict_covers_every_target_cursor(tmp_path):
    cursor = tmp_path / "sync-cursor.json"
    cursor.write_text(json.dumps({
        "pushed_events": [_key("a", 1.0), _key("b", 2.0)],
        "targets": {"unicornish": {"pushed_events": [_key("a", 1.0), _key("c", 3.0)]}},
    }))
    assert sync.evict_session_ids_from_cursor(cursor, ["a"]) == 2
    cur = json.loads(cursor.read_text())
    assert cur["pushed_events"] == [_key("b", 2.0)]
    assert cur["targets"]["unicornish"]["pushed_events"] == [_key("c", 3.0)]
