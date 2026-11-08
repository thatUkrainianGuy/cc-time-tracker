"""Tests for cc_time_tracker.active_time and its use in the SessionEnd hook."""

import json
import time
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch

from cc_time_tracker.active_time import (
    active_seconds, measure, session_timestamps, transcript_files,
)
from cc_time_tracker.end_hook import main as end_main

T0 = 1_790_000_000.0


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _write_transcript(path, timestamps, extra_lines=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "timestamp": _iso(t)}) for t in timestamps]
    path.write_text("\n".join([*lines, *extra_lines]) + "\n")


def test_gaps_are_capped_at_idle_cap():
    # 60s of work, a 3h idle gap (capped to 900s), then 30s of work.
    ts = [T0, T0 + 60, T0 + 60 + 3 * 3600, T0 + 90 + 3 * 3600]
    assert active_seconds(ts, T0, T0 + 4 * 3600, idle_cap=900) == 60 + 900 + 30


def test_only_events_inside_window_count():
    ts = [T0 - 100, T0, T0 + 50, T0 + 100, T0 + 500]
    assert active_seconds(ts, T0, T0 + 100, idle_cap=900) == 100


def test_window_per_end_event_never_counts_twice(_isolated_projects_dir):
    """Two end events of one session_id (e.g. /clear) split the transcript."""
    _write_transcript(_isolated_projects_dir / "-p" / "sid.jsonl",
                      [T0, T0 + 100, T0 + 200, T0 + 300])
    ts = session_timestamps("sid", "/p")
    first = measure(ts, T0, T0 + 150)["duration_seconds"]
    second = measure(ts, T0 + 150, T0 + 400)["duration_seconds"]
    assert (first, second) == (100, 100)
    assert first + second <= measure(ts, T0, T0 + 400)["duration_seconds"]


def test_union_of_main_and_subagent_transcripts(_isolated_projects_dir):
    """Main transcript is silent for an hour while a subagent works."""
    proj = _isolated_projects_dir / "-home-u-Projects-crew-shift-x"
    _write_transcript(proj / "sid.jsonl", [T0, T0 + 3600])
    sub = [T0 + 600 * i for i in range(1, 6)]
    _write_transcript(proj / "sid" / "subagents" / "agent-a1.jsonl", sub[:3])
    _write_transcript(proj / "sid" / "subagents" / "workflows" / "wf_1" / "agent-b2.jsonl", sub[3:])
    ts = session_timestamps("sid", "/home/u/Projects/crew_shift_x")
    assert len(ts) == 7
    # Main alone: one 3600s gap capped to 900. With subagents: six 600s gaps.
    assert measure(ts, T0, T0 + 3600, idle_cap=900)["duration_seconds"] == 3600


def test_slug_replaces_dots_and_underscores(_isolated_projects_dir):
    main = _isolated_projects_dir / "-home-u-Projects-websitebuilds-tei-com" / "s1.jsonl"
    _write_transcript(main, [T0])
    assert transcript_files("s1", "/home/u/Projects/websitebuilds/tei.com") == [main]


def test_finds_transcript_from_subdir_cwd_by_session_id(_isolated_projects_dir):
    main = _isolated_projects_dir / "-home-u-Peerish" / "s2.jsonl"
    _write_transcript(main, [T0])
    assert transcript_files("s2", "/home/u/Peerish/src/lib") == [main]


def test_bad_lines_and_non_string_timestamps_are_skipped(_isolated_projects_dir):
    _write_transcript(_isolated_projects_dir / "-p" / "s3.jsonl", [T0, T0 + 10],
                      extra_lines=["{not json", json.dumps({"timestamp": 123}), "[]"])
    assert session_timestamps("s3", "/p") == [T0, T0 + 10]


def test_missing_transcript_falls_back_to_capped_wall():
    assert session_timestamps("nope", "/nowhere") is None
    m = measure(None, T0, T0 + 10 * 3600)
    assert m == {"duration_seconds": 4 * 3600, "wall_seconds": 10 * 3600,
                 "active_source": "wall_capped"}
    assert measure(None, T0, T0 + 60)["duration_seconds"] == 60


def test_glob_metachars_in_session_id_do_not_match(_isolated_projects_dir):
    _write_transcript(_isolated_projects_dir / "-p" / "real.jsonl", [T0])
    assert transcript_files("*", "/elsewhere") == []


def _run_end_hook(tmp_path, input_data):
    sessions = tmp_path / "sessions.jsonl"
    with (
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.end_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.end_hook.ACTIVE_FILE", tmp_path / "active.jsonl"),
        patch("sys.stdin", StringIO(json.dumps(input_data))),
    ):
        try:
            end_main()
        except SystemExit as e:
            assert e.code == 0
    return [json.loads(l) for l in sessions.read_text().splitlines()]


def test_end_hook_records_active_time_from_transcript_path(tmp_path):
    now = time.time()
    start = now - 5 * 3600  # open 5h, but only 2 min of activity
    (tmp_path / "active.jsonl").write_text(json.dumps(
        {"event": "start", "session_id": "s", "project": "p", "timestamp_unix": start}) + "\n")
    transcript = tmp_path / "elsewhere" / "s.jsonl"
    _write_transcript(transcript, [start + 10, start + 70, start + 130])
    [rec] = _run_end_hook(tmp_path, {"session_id": "s", "cwd": "/x",
                                     "transcript_path": str(transcript)})
    assert rec["duration_seconds"] == 120
    assert rec["active_source"] == "transcript"
    assert abs(rec["wall_seconds"] - 5 * 3600) < 5


def test_end_hook_without_transcript_writes_wall_capped(tmp_path):
    start = time.time() - 6 * 3600
    (tmp_path / "active.jsonl").write_text(json.dumps(
        {"event": "start", "session_id": "s", "project": "p", "timestamp_unix": start}) + "\n")
    [rec] = _run_end_hook(tmp_path, {"session_id": "s", "cwd": "/x",
                                     "transcript_path": str(tmp_path / "gone.jsonl")})
    assert rec["duration_seconds"] == 4 * 3600
    assert rec["active_source"] == "wall_capped"


def test_end_hook_survives_unreadable_transcript(tmp_path):
    start = time.time() - 60
    (tmp_path / "active.jsonl").write_text(json.dumps(
        {"event": "start", "session_id": "s", "project": "p", "timestamp_unix": start}) + "\n")
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [start])
    with patch("cc_time_tracker.active_time.read_timestamps", side_effect=OSError("boom")):
        [rec] = _run_end_hook(tmp_path, {"session_id": "s", "cwd": "/x",
                                         "transcript_path": str(transcript)})
    assert rec["active_source"] == "wall_capped"
