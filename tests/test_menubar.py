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
