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


# Constants
TRACKING_DIR = Path.home() / ".claude" / "time-tracking"
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
ACTIVE_FILE = TRACKING_DIR / "active.jsonl"

REFRESH_INTERVAL = 30  # seconds


def main():
    """Entry point — imports rumps and runs the menu bar app.

    rumps is imported here (not at module level) so that the pure functions
    above can be imported and tested without rumps installed.
    """
    try:
        import rumps
    except ImportError:
        print("ERROR: rumps is required. Install with: pip install rumps")
        print("Then run: python3 cc-time-menubar.py")
        raise SystemExit(1)

    class CCTimeMenuBar(rumps.App):
        def __init__(self):
            super().__init__("⏱ 0m", quit_button=None)
            self.timer = rumps.Timer(self.refresh, REFRESH_INTERVAL)
            self.timer.start()
            self.refresh(None)  # initial load

        def refresh(self, _):
            """Reload data from JSONL files and update the menu bar."""
            completed = load_today_sessions(SESSIONS_FILE)
            active = load_active_sessions(ACTIVE_FILE)
            projects, total = build_project_data(completed, active)

            # Update title
            self.title = f"⏱ {format_duration(total)}"

            # Rebuild menu
            self.menu.clear()

            for name, secs, _has_completed, is_active in projects:
                prefix = "● " if is_active else "  "
                label = f"{prefix}{name}    {format_duration(secs)}"
                item = rumps.MenuItem(label, callback=None)
                self.menu.add(item)

            if projects:
                self.menu.add(rumps.separator)

            total_item = rumps.MenuItem(f"  Today: {format_duration(total)}", callback=None)
            self.menu.add(total_item)
            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("Quit", callback=self.quit_app))

        def quit_app(self, _):
            rumps.quit_application()

    CCTimeMenuBar().run()


if __name__ == "__main__":
    main()
