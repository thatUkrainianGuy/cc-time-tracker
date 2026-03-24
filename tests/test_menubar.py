"""Tests for cc-time-menubar.py data parsing and formatting logic."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def make_start_record(session_id, project, cwd, ts_unix):
    return json.dumps({
        "event": "start",
        "session_id": session_id,
        "cwd": cwd,
        "project": project,
        "source": "startup",
        "timestamp": datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat(),
        "timestamp_unix": ts_unix,
    })


def make_end_record(session_id, project, cwd, ts_unix, duration_seconds):
    return json.dumps({
        "event": "end",
        "session_id": session_id,
        "cwd": cwd,
        "project": project,
        "reason": "user_exit",
        "timestamp": datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat(),
        "timestamp_unix": ts_unix,
        "duration_seconds": duration_seconds,
    })


from importlib.machinery import SourceFileLoader
import importlib


def load_menubar():
    """Load cc-time-menubar.py as a module (it has a hyphenated name)."""
    loader = SourceFileLoader("cc_time_menubar", "cc-time-menubar.py")
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("cc_time_menubar", loader))
    loader.exec_module(mod)
    return mod


class TestFormatDuration:
    def setup_method(self):
        self.mod = load_menubar()

    def test_zero(self):
        assert self.mod.format_duration(0) == "0m"

    def test_seconds_rounds_to_zero_minutes(self):
        assert self.mod.format_duration(30) == "0m"

    def test_minutes_only(self):
        assert self.mod.format_duration(2520) == "42m"

    def test_hours_and_minutes(self):
        assert self.mod.format_duration(13320) == "3h 42m"

    def test_exact_hour(self):
        assert self.mod.format_duration(3600) == "1h 0m"


class TestLoadTodaySessions:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.sessions_file = Path(self.tmpdir) / "sessions.jsonl"

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def test_empty_file(self):
        self.sessions_file.write_text("")
        result = self.mod.load_today_sessions(self.sessions_file)
        assert result == []

    def test_no_file(self):
        nonexistent = Path(self.tmpdir) / "nope.jsonl"
        result = self.mod.load_today_sessions(nonexistent)
        assert result == []

    def test_filters_to_today_end_events(self):
        now = self._now_unix()
        yesterday = now - 86400 * 2
        lines = [
            make_start_record("s1", "proj", "/tmp/proj", now - 3600),
            make_end_record("s1", "proj", "/tmp/proj", now, 3600),
            make_end_record("s2", "old", "/tmp/old", yesterday, 100),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_today_sessions(self.sessions_file)
        assert len(result) == 1
        assert result[0]["project"] == "proj"
        assert result[0]["event"] == "end"

    def test_skips_malformed_lines(self):
        now = self._now_unix()
        lines = [
            "not json at all",
            make_end_record("s1", "proj", "/tmp/proj", now, 100),
            "{broken json",
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_today_sessions(self.sessions_file)
        assert len(result) == 1


class TestLoadAllCompletedSessions:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.sessions_file = Path(self.tmpdir) / "sessions.jsonl"

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def test_returns_all_end_events(self):
        now = self._now_unix()
        old = now - 86400 * 30  # 30 days ago
        lines = [
            make_start_record("s1", "proj", "/tmp/proj", old),
            make_end_record("s1", "proj", "/tmp/proj", old + 3600, 3600),
            make_start_record("s2", "proj", "/tmp/proj", now - 3600),
            make_end_record("s2", "proj", "/tmp/proj", now, 1800),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_all_completed_sessions(self.sessions_file)
        assert len(result) == 2
        assert all(r["event"] == "end" for r in result)

    def test_excludes_start_events(self):
        now = self._now_unix()
        lines = [
            make_start_record("s1", "proj", "/tmp/proj", now - 3600),
            make_end_record("s1", "proj", "/tmp/proj", now, 3600),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_all_completed_sessions(self.sessions_file)
        assert len(result) == 1
        assert result[0]["event"] == "end"

    def test_empty_file(self):
        self.sessions_file.write_text("")
        assert self.mod.load_all_completed_sessions(self.sessions_file) == []

    def test_no_file(self):
        nonexistent = Path(self.tmpdir) / "nope.jsonl"
        assert self.mod.load_all_completed_sessions(nonexistent) == []


class TestLoadActiveSessions:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.active_file = Path(self.tmpdir) / "active.jsonl"

    def test_empty_file(self):
        self.active_file.write_text("")
        result = self.mod.load_active_sessions(self.active_file)
        assert result == []

    def test_no_file(self):
        nonexistent = Path(self.tmpdir) / "nope.jsonl"
        result = self.mod.load_active_sessions(nonexistent)
        assert result == []

    def test_loads_all_records(self):
        now = datetime.now(timezone.utc).timestamp()
        lines = [
            make_start_record("s1", "proj-a", "/tmp/proj-a", now - 3600),
            make_start_record("s2", "proj-b", "/tmp/proj-b", now - 600),
        ]
        self.active_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_active_sessions(self.active_file)
        assert len(result) == 2
        assert result[0]["project"] == "proj-a"
        assert result[1]["project"] == "proj-b"


class TestBuildProjectData:
    def setup_method(self):
        self.mod = load_menubar()

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def test_empty_inputs(self):
        projects, today_total = self.mod.build_project_data([], [], [])
        assert projects == []
        assert today_total == 0

    def test_today_and_all_time(self):
        today = [
            {"project": "proj-a", "duration_seconds": 1800},
        ]
        all_time = [
            {"project": "proj-a", "duration_seconds": 1800},
            {"project": "proj-a", "duration_seconds": 3600},
        ]
        projects, today_total = self.mod.build_project_data(today, all_time, [])
        assert len(projects) == 1
        name, today_secs, total_secs, is_active = projects[0]
        assert name == "proj-a"
        assert today_secs == 1800
        assert total_secs == 5400
        assert is_active is False
        assert today_total == 1800

    def test_all_time_only_no_today(self):
        """Project with past sessions but none today still appears."""
        all_time = [
            {"project": "proj-a", "duration_seconds": 7200},
        ]
        projects, today_total = self.mod.build_project_data([], all_time, [])
        assert len(projects) == 1
        name, today_secs, total_secs, is_active = projects[0]
        assert name == "proj-a"
        assert today_secs == 0
        assert total_secs == 7200
        assert today_total == 0

    def test_active_sessions_add_elapsed(self):
        now = self._now_unix()
        active = [
            {"project": "proj-a", "timestamp_unix": now - 600},
        ]
        projects, today_total = self.mod.build_project_data([], [], active)
        assert len(projects) == 1
        name, today_secs, total_secs, is_active = projects[0]
        assert name == "proj-a"
        assert is_active is True
        assert 595 <= today_secs <= 610
        assert 595 <= total_secs <= 610

    def test_combined_completed_and_active(self):
        now = self._now_unix()
        today = [{"project": "proj-a", "duration_seconds": 3600}]
        all_time = [
            {"project": "proj-a", "duration_seconds": 3600},
            {"project": "proj-a", "duration_seconds": 7200},
        ]
        active = [{"project": "proj-a", "timestamp_unix": now - 600}]
        projects, today_total = self.mod.build_project_data(today, all_time, active)
        assert len(projects) == 1
        name, today_secs, total_secs, is_active = projects[0]
        assert is_active is True
        # today: 3600 completed + ~600 active
        assert 4195 <= today_secs <= 4210
        # all-time: 3600 + 7200 completed + ~600 active
        assert 11395 <= total_secs <= 11410

    def test_sorted_by_total_descending(self):
        all_time = [
            {"project": "small", "duration_seconds": 100},
            {"project": "big", "duration_seconds": 9000},
        ]
        projects, _ = self.mod.build_project_data([], all_time, [])
        assert projects[0][0] == "big"
        assert projects[1][0] == "small"

    def test_multiple_projects(self):
        today = [
            {"project": "proj-a", "duration_seconds": 1800},
            {"project": "proj-b", "duration_seconds": 600},
        ]
        all_time = [
            {"project": "proj-a", "duration_seconds": 1800},
            {"project": "proj-a", "duration_seconds": 3600},
            {"project": "proj-b", "duration_seconds": 600},
            {"project": "proj-b", "duration_seconds": 1200},
        ]
        projects, today_total = self.mod.build_project_data(today, all_time, [])
        assert len(projects) == 2
        assert today_total == 2400


class TestDeleteProjectSessions:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.sessions_file = Path(self.tmpdir) / "sessions.jsonl"

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def test_delete_all_sessions_for_project(self):
        now = self._now_unix()
        yesterday = now - 86400 * 2
        lines = [
            make_start_record("s1", "proj-a", "/tmp/proj-a", now - 3600),
            make_end_record("s1", "proj-a", "/tmp/proj-a", now, 3600),
            make_start_record("s2", "proj-b", "/tmp/proj-b", now - 600),
            make_end_record("s2", "proj-b", "/tmp/proj-b", now, 600),
            make_end_record("s3", "proj-a", "/tmp/proj-a", yesterday, 100),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        removed = self.mod.delete_project_sessions(self.sessions_file, "proj-a", today_only=False)
        assert removed == 3
        remaining = self.mod._read_jsonl(self.sessions_file)
        assert len(remaining) == 2
        assert all(r["project"] == "proj-b" for r in remaining)

    def test_delete_today_only(self):
        now = self._now_unix()
        yesterday = now - 86400 * 2
        lines = [
            make_start_record("s1", "proj-a", "/tmp/proj-a", now - 3600),
            make_end_record("s1", "proj-a", "/tmp/proj-a", now, 3600),
            make_end_record("s3", "proj-a", "/tmp/proj-a", yesterday, 100),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        removed = self.mod.delete_project_sessions(self.sessions_file, "proj-a", today_only=True)
        assert removed == 2
        remaining = self.mod._read_jsonl(self.sessions_file)
        assert len(remaining) == 1
        assert remaining[0]["timestamp_unix"] == yesterday

    def test_delete_missing_file(self):
        nonexistent = Path(self.tmpdir) / "nope.jsonl"
        removed = self.mod.delete_project_sessions(nonexistent, "proj-a", today_only=False)
        assert removed == 0

    def test_delete_empty_file(self):
        self.sessions_file.write_text("")
        removed = self.mod.delete_project_sessions(self.sessions_file, "proj-a", today_only=False)
        assert removed == 0

    def test_preserves_malformed_lines(self):
        now = self._now_unix()
        lines = [
            "not json at all",
            make_end_record("s1", "proj-a", "/tmp/proj-a", now, 100),
            "{broken json",
            make_end_record("s2", "proj-b", "/tmp/proj-b", now, 200),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        removed = self.mod.delete_project_sessions(self.sessions_file, "proj-a", today_only=False)
        assert removed == 1
        raw_lines = [l for l in self.sessions_file.read_text().strip().split("\n") if l.strip()]
        assert len(raw_lines) == 3
        assert raw_lines[0] == "not json at all"
        assert raw_lines[1] == "{broken json"


class TestProjectsMeta:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.projects_file = Path(self.tmpdir) / "projects.json"
        self.lock_path = Path(self.tmpdir) / ".lock"

    def test_load_missing_file(self):
        nonexistent = Path(self.tmpdir) / "nope.json"
        result = self.mod.load_projects_meta(nonexistent, self.lock_path)
        assert result == {}

    def test_load_existing(self):
        self.projects_file.write_text('{"proj-a": {"archived": true}}')
        result = self.mod.load_projects_meta(self.projects_file, self.lock_path)
        assert result == {"proj-a": {"archived": True}}

    def test_save_and_load_roundtrip(self):
        data = {"proj-a": {"archived": True}, "proj-b": {"archived": False}}
        self.mod.save_projects_meta(self.projects_file, data, self.lock_path)
        result = self.mod.load_projects_meta(self.projects_file, self.lock_path)
        assert result == data

    def test_is_archived_true(self):
        meta = {"proj-a": {"archived": True}}
        assert self.mod.is_archived(meta, "proj-a") is True

    def test_is_archived_false(self):
        meta = {"proj-a": {"archived": False}}
        assert self.mod.is_archived(meta, "proj-a") is False

    def test_is_archived_missing_project(self):
        assert self.mod.is_archived({}, "proj-a") is False

    def test_set_archived(self):
        meta = {}
        self.mod.set_archived(meta, "proj-a", True)
        assert meta == {"proj-a": {"archived": True}}

    def test_set_archived_preserves_other_fields(self):
        meta = {"proj-a": {"archived": False, "custom": "data"}}
        self.mod.set_archived(meta, "proj-a", True)
        assert meta["proj-a"]["archived"] is True
        assert meta["proj-a"]["custom"] == "data"

    def test_remove_project_meta(self):
        meta = {"proj-a": {"archived": True}, "proj-b": {"archived": False}}
        self.mod.remove_project_meta(meta, "proj-a")
        assert "proj-a" not in meta
        assert "proj-b" in meta

    def test_remove_project_meta_missing_key(self):
        meta = {"proj-a": {"archived": True}}
        self.mod.remove_project_meta(meta, "nonexistent")
        assert meta == {"proj-a": {"archived": True}}


class TestGenerateReport:
    def setup_method(self):
        self.mod = load_menubar()

    def _make_sessions(self):
        """Create test sessions spanning multiple days."""
        return [
            {"project": "proj-a", "event": "end", "duration_seconds": 3600,
             "timestamp_unix": 1742515200.0,  # 2025-03-21 00:00:00 UTC
             "session_id": "s1", "reason": "user_exit"},
            {"project": "proj-a", "event": "end", "duration_seconds": 1800,
             "timestamp_unix": 1742515200.0 + 7200,  # same day
             "session_id": "s2", "reason": "user_exit"},
            {"project": "proj-a", "event": "end", "duration_seconds": 5400,
             "timestamp_unix": 1742601600.0,  # 2025-03-22 00:00:00 UTC
             "session_id": "s3", "reason": "user_exit"},
        ]

    def test_generate_csv_report(self):
        sessions = self._make_sessions()
        csv = self.mod.generate_csv_report("proj-a", sessions)
        lines = csv.strip().split("\n")
        assert lines[0] == "Date,Project,Sessions,Duration,Hours"
        assert len(lines) == 4  # header + 2 days + total
        assert lines[-1].startswith("Total,")

    def test_generate_md_report(self):
        sessions = self._make_sessions()
        md = self.mod.generate_md_report("proj-a", sessions)
        assert "# proj-a" in md
        assert "| Date |" in md
        assert "**Total**" in md

    def test_generate_csv_empty(self):
        csv = self.mod.generate_csv_report("proj-a", [])
        lines = csv.strip().split("\n")
        assert lines[0] == "Date,Project,Sessions,Duration,Hours"
        assert lines[1].startswith("Total,")

    def test_generate_md_empty(self):
        md = self.mod.generate_md_report("proj-a", [])
        assert "**Total**" in md
        assert "0.00" in md
