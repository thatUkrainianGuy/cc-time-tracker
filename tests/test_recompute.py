"""Tests for cc_time_tracker.recompute (the active-time backfill)."""

import json
from datetime import datetime, timezone

import pytest

from cc_time_tracker import recompute, sync

T0 = 1_793_000_000.0  # 2026-10-26, after the no-transcript cutoff


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@pytest.fixture
def env(tmp_path, monkeypatch, _isolated_projects_dir):
    sessions = tmp_path / "sessions.jsonl"
    cursor = tmp_path / "sync-cursor.json"
    monkeypatch.setattr(recompute, "SESSIONS_FILE", sessions)
    monkeypatch.setattr(sync, "CURSOR_FILE", cursor)
    monkeypatch.setattr("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock")
    proj = _isolated_projects_dir / "-p"
    proj.mkdir()
    # Session "a": 2 min of work, then idle; a subagent works at +1h.
    (proj / "a.jsonl").write_text("".join(
        json.dumps({"timestamp": _iso(T0 + s)}) + "\n" for s in (0, 60, 120)))
    (proj / "a" / "subagents").mkdir(parents=True)
    (proj / "a" / "subagents" / "agent-x.jsonl").write_text(
        json.dumps({"timestamp": _iso(T0 + 3600)}) + "\n")
    records = [
        {"event": "start", "session_id": "a", "cwd": "/p", "project": "p", "timestamp_unix": T0},
        # /clear at +30 min, then the same session_id ends again at +2h.
        {"event": "end", "session_id": "a", "cwd": "/p", "project": "p",
         "timestamp_unix": T0 + 1800, "duration_seconds": 1800.0},
        {"event": "end", "session_id": "a", "cwd": "/p", "project": "p",
         "timestamp_unix": T0 + 7200, "duration_seconds": 5400.0},
        # No transcript, open 10h.
        {"event": "end", "session_id": "b", "cwd": "/q", "project": "q",
         "timestamp_unix": T0 + 36000, "duration_seconds": 36000.0},
        {"event": "end", "session_id": "c", "cwd": "/q", "project": "q",
         "timestamp_unix": T0, "duration_seconds": None},
    ]
    sessions.write_text("".join(json.dumps(r) + "\n" for r in records))
    cursor.write_text(json.dumps({"pushed_events": [
        f"a|{T0 + 1800}", f"a|{T0 + 7200}", f"b|{T0 + 36000}", "z|1.0"],
        "targets": {"unicornish": {"pushed_events": [f"a|{T0 + 1800}", "z|1.0"]}}}))
    return sessions, cursor


def _ends(sessions):
    return [json.loads(l) for l in sessions.read_text().splitlines() if '"end"' in l]


def test_dry_run_writes_nothing(env, capsys):
    sessions, cursor = env
    before = sessions.read_text(), cursor.read_text()
    assert recompute.main(["--dry-run"]) == 0
    assert (sessions.read_text(), cursor.read_text()) == before
    assert not list(sessions.parent.glob("sessions.jsonl.bak-*"))
    assert "3 of 3 end events change" in capsys.readouterr().out


def test_backfill_rewrites_windows_backs_up_and_evicts(env):
    sessions, cursor = env
    original = sessions.read_text()
    assert recompute.main([]) == 0

    a1, a2, b, c = _ends(sessions)
    # First window [T0, T0+1800]: events at 0/60/120 -> 120s.
    assert (a1["duration_seconds"], a1["wall_seconds"], a1["active_source"]) == (120, 1800, "transcript")
    # Second window [T0+1800, T0+7200]: only the subagent event -> 0s, nothing counted twice.
    assert (a2["duration_seconds"], a2["wall_seconds"]) == (0, 5400)
    assert (b["duration_seconds"], b["wall_seconds"], b["active_source"]) == (4 * 3600, 36000, "wall_capped")
    assert c["duration_seconds"] is None and "active_source" not in c

    [backup] = sessions.parent.glob("sessions.jsonl.bak-*")
    assert backup.read_text() == original
    cur = json.loads(cursor.read_text())
    assert cur["pushed_events"] == ["z|1.0"]
    assert cur["targets"]["unicornish"]["pushed_events"] == ["z|1.0"]
    # The re-push sends the original window start, not end - active.
    pending = {p["end_at"]: p for p in sync.collect_pending(sessions, set())}
    assert pending[T0 + 7200]["start_at"] == T0 + 1800


def test_backfill_is_idempotent(env, capsys):
    sessions, _ = env
    recompute.main([])
    after = sessions.read_text()
    capsys.readouterr()
    recompute.main([])
    assert sessions.read_text() == after
    assert "0 of 3 end events change" in capsys.readouterr().out


def test_union_with_subagent_inside_window(env):
    """One window over the whole session counts the subagent event."""
    sessions, _ = env
    sessions.write_text(json.dumps({
        "event": "end", "session_id": "a", "cwd": "/p", "project": "p",
        "timestamp_unix": T0 + 7200, "duration_seconds": 7200.0}) + "\n")
    recompute.main(["--idle-cap", "900"])
    [a] = _ends(sessions)
    assert a["duration_seconds"] == 120 + 900  # 2 min of work + capped gap to the subagent event


def test_idle_cap_must_be_positive(env):
    with pytest.raises(SystemExit):
        recompute.main(["--idle-cap", "0"])
