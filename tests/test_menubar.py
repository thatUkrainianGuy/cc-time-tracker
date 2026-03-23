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
