#!/usr/bin/env python3
"""
macOS menu bar app for Claude Code time tracking.
Shows today's total session time in the menu bar.
Click to see per-project breakdown with active session indicators.

Usage:
    python3 cc-time-menubar.py

Requires: pip install rumps
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def format_duration(seconds: float) -> str:
    """Format seconds into menu-bar-friendly duration string.

    Unlike cc-time-report.py, this skips seconds entirely to avoid
    visual noise in the menu bar. Always shows at least '0m'.
    """
    total_minutes = int(seconds // 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m"


def get_today_start_unix() -> float:
    """Get midnight local time today as a unix timestamp."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today.timestamp()


def load_today_sessions(sessions_file: Path) -> list[dict]:
    """Load today's completed sessions (end events only) from JSONL file.

    Uses local time for 'today' cutoff. Skips malformed lines silently.
    """
    if not sessions_file.exists():
        return []

    today_start = get_today_start_unix()
    sessions = []

    with open(sessions_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                record.get("event") == "end"
                and record.get("duration_seconds") is not None
                and record.get("timestamp_unix", 0) >= today_start
            ):
                sessions.append(record)

    return sessions


def load_active_sessions(active_file: Path) -> list[dict]:
    """Load currently active sessions from JSONL file.

    All records in this file are start events for running sessions.
    Skips malformed lines silently.
    """
    if not active_file.exists():
        return []

    sessions = []
    with open(active_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sessions.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return sessions


def build_project_data(
    completed_sessions: list[dict],
    active_sessions: list[dict],
) -> tuple[list[tuple[str, float, bool, bool]], float]:
    """Aggregate today's data into per-project rows.

    Returns:
        (projects, total_seconds) where projects is a list of
        (name, total_seconds, has_completed, is_active) sorted by time desc.
    """
    now = datetime.now(timezone.utc).timestamp()

    project_time: dict[str, float] = {}
    project_has_completed: dict[str, bool] = {}
    project_is_active: dict[str, bool] = {}

    for s in completed_sessions:
        proj = s.get("project", "unknown")
        dur = s.get("duration_seconds", 0) or 0
        project_time[proj] = project_time.get(proj, 0) + dur
        project_has_completed[proj] = True

    for s in active_sessions:
        proj = s.get("project", "unknown")
        start_ts = s.get("timestamp_unix", now)
        elapsed = max(0, now - start_ts)
        project_time[proj] = project_time.get(proj, 0) + elapsed
        project_is_active[proj] = True

    total = sum(project_time.values())

    projects = sorted(
        [
            (name, secs, project_has_completed.get(name, False), project_is_active.get(name, False))
            for name, secs in project_time.items()
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    return projects, total
