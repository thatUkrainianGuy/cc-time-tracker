"""Tests for cc-time-menubar.py data parsing and formatting logic."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


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

    def _today_start_unix(self):
        """Midnight local time today, as unix timestamp."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return today.timestamp()

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
        projects, total = self.mod.build_project_data([], [])
        assert projects == []
        assert total == 0

    def test_completed_sessions_only(self):
        sessions = [
            {"project": "proj-a", "duration_seconds": 3600},
            {"project": "proj-a", "duration_seconds": 1800},
            {"project": "proj-b", "duration_seconds": 600},
        ]
        projects, total = self.mod.build_project_data(sessions, [])
        assert total == 6000
        # Sorted descending by time
        assert projects[0] == ("proj-a", 5400, True, False)
        assert projects[1] == ("proj-b", 600, True, False)

    def test_active_sessions_add_elapsed(self):
        now = self._now_unix()
        sessions = []
        active = [
            {"project": "proj-a", "timestamp_unix": now - 600},
        ]
        projects, total = self.mod.build_project_data(sessions, active)
        assert len(projects) == 1
        name, secs, has_completed, is_active = projects[0]
        assert name == "proj-a"
        assert is_active is True
        assert 595 <= secs <= 610

    def test_multiple_active_sessions_same_project(self):
        now = self._now_unix()
        sessions = []
        active = [
            {"project": "proj-a", "timestamp_unix": now - 600},
            {"project": "proj-a", "timestamp_unix": now - 300},
        ]
        projects, total = self.mod.build_project_data(sessions, active)
        assert len(projects) == 1
        name, secs, _, is_active = projects[0]
        assert name == "proj-a"
        assert is_active is True
        assert 895 <= secs <= 910

    def test_combined_completed_and_active(self):
        now = self._now_unix()
        sessions = [
            {"project": "proj-a", "duration_seconds": 3600},
        ]
        active = [
            {"project": "proj-a", "timestamp_unix": now - 600},
        ]
        projects, total = self.mod.build_project_data(sessions, active)
        assert len(projects) == 1
        name, secs, _, is_active = projects[0]
        assert name == "proj-a"
        assert is_active is True
        assert 4195 <= secs <= 4210
