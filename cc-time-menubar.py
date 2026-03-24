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

TRACKING_DIR = Path.home() / ".claude" / "time-tracking"
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
ACTIVE_FILE = TRACKING_DIR / "active.jsonl"
REFRESH_INTERVAL = 30  # seconds


def format_duration(seconds: float) -> str:
    """Skips seconds (unlike cc-time-report.py) to avoid menu bar noise."""
    total_minutes = int(seconds // 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m"


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, skipping malformed lines. Returns [] if file missing."""
    try:
        f = open(path, "r")
    except FileNotFoundError:
        return []

    records = []
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _acquire_lock(lock_path):
    """Optional filelock context manager — no-op if filelock not installed."""
    try:
        from filelock import FileLock
        return FileLock(lock_path, timeout=5)
    except ImportError:
        from contextlib import contextmanager

        @contextmanager
        def _noop():
            yield

        return _noop()


def delete_project_sessions(
    sessions_file: Path,
    project: str,
    today_only: bool,
) -> int:
    """Remove sessions for a project from the JSONL file.

    Returns number of records removed.
    """
    if not sessions_file.exists():
        return 0

    today_start = get_today_start_unix() if today_only else None
    lock_path = sessions_file.parent / ".lock"

    with _acquire_lock(lock_path):
        raw = sessions_file.read_text()
        if not raw.strip():
            return 0

        kept_lines = []
        removed = 0

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                kept_lines.append(line)
                continue

            if record.get("project") == project:
                if not today_only or record.get("timestamp_unix", 0) >= today_start:
                    removed += 1
                    continue
            kept_lines.append(line)

        sessions_file.write_text("\n".join(kept_lines) + "\n" if kept_lines else "")

    return removed


def get_today_start_unix() -> float:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today.timestamp()


def load_today_sessions(sessions_file: Path) -> list[dict]:
    """Load today's completed sessions (end events only) from JSONL file."""
    today_start = get_today_start_unix()
    return [
        r for r in _read_jsonl(sessions_file)
        if r.get("event") == "end"
        and r.get("duration_seconds") is not None
        and r.get("timestamp_unix", 0) >= today_start
    ]


def load_all_completed_sessions(sessions_file: Path) -> list[dict]:
    """Load all completed sessions (end events only) from JSONL file, no date filter."""
    return [
        r for r in _read_jsonl(sessions_file)
        if r.get("event") == "end"
        and r.get("duration_seconds") is not None
    ]


def load_active_sessions(active_file: Path) -> list[dict]:
    return _read_jsonl(active_file)


def build_project_data(
    today_sessions: list[dict],
    all_sessions: list[dict],
    active_sessions: list[dict],
) -> tuple[list[tuple[str, float, float, bool]], float]:
    """Aggregate per-project rows with today and all-time totals.

    Returns:
        (projects, today_total) where projects is a list of
        (name, today_seconds, total_seconds, is_active) sorted by total desc.
    """
    now = datetime.now(timezone.utc).timestamp()

    today_time: dict[str, float] = {}
    total_time: dict[str, float] = {}
    project_is_active: dict[str, bool] = {}

    for s in today_sessions:
        proj = s.get("project", "unknown")
        dur = s.get("duration_seconds", 0) or 0
        today_time[proj] = today_time.get(proj, 0) + dur

    for s in all_sessions:
        proj = s.get("project", "unknown")
        dur = s.get("duration_seconds", 0) or 0
        total_time[proj] = total_time.get(proj, 0) + dur

    for s in active_sessions:
        proj = s.get("project", "unknown")
        start_ts = s.get("timestamp_unix", now)
        elapsed = max(0, now - start_ts)
        today_time[proj] = today_time.get(proj, 0) + elapsed
        total_time[proj] = total_time.get(proj, 0) + elapsed
        project_is_active[proj] = True

    all_projects = set(today_time) | set(total_time)
    today_total = sum(today_time.values())

    projects = sorted(
        [
            (
                name,
                today_time.get(name, 0),
                total_time.get(name, 0),
                project_is_active.get(name, False),
            )
            for name in all_projects
        ],
        key=lambda x: x[2],  # sort by total_seconds
        reverse=True,
    )

    return projects, today_total


def main():
    """rumps is imported here (not at module level) so pure functions
    above can be tested without rumps installed.
    """
    try:
        import rumps
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
    except ImportError:
        print("ERROR: rumps is required. Install with: pip install rumps")
        print("Then run: python3 cc-time-menubar.py")
        raise SystemExit(1)

    class CCTimeMenuBar(rumps.App):
        def __init__(self):
            super().__init__("⏱ 0m", quit_button=None)
            self.timer = rumps.Timer(self.refresh, REFRESH_INTERVAL)
            self.timer.start()
            self.refresh(None)

        def refresh(self, _):
            completed = load_today_sessions(SESSIONS_FILE)
            active = load_active_sessions(ACTIVE_FILE)
            projects, total = build_project_data(completed, active)

            icon = "⏱" if active else "⏸"
            self.title = f"{icon} {format_duration(total)}"
            self.menu.clear()

            for name, secs, _has_completed, is_active in projects:
                prefix = "🟢 " if is_active else "⚪ "
                label = f"{prefix}{name}\t{format_duration(secs)}"
                if is_active:
                    item = rumps.MenuItem(label, callback=lambda _: None)
                else:
                    item = rumps.MenuItem(label)
                    delete_today = rumps.MenuItem(
                        "Delete today's sessions",
                        callback=lambda _, p=name: self._delete_sessions(p, today_only=True),
                    )
                    delete_all = rumps.MenuItem(
                        "Delete project",
                        callback=lambda _, p=name: self._delete_project(p),
                    )
                    item.add(delete_today)
                    item.add(delete_all)
                self.menu.add(item)

            if projects:
                self.menu.add(rumps.separator)

            total_item = rumps.MenuItem(f"Today: {format_duration(total)}", callback=None)
            self.menu.add(total_item)
            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("Quit", callback=self.quit_app))

        def _schedule_refresh(self):
            """Defer refresh to next run loop iteration to avoid mutating menu mid-callback."""
            t = rumps.Timer(self._deferred_refresh, 0.1)
            t.start()

        def _deferred_refresh(self, timer):
            timer.stop()
            self.refresh(None)

        def _bring_to_front(self):
            from AppKit import NSApplication, NSApplicationActivateIgnoringOtherApps
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        def _delete_sessions(self, project, today_only):
            self._bring_to_front()
            response = rumps.alert(
                title="Confirm Delete",
                message=f"Delete today's sessions for '{project}'?",
                ok="Delete",
                cancel="Cancel",
            )
            if response == 1:
                delete_project_sessions(SESSIONS_FILE, project, today_only=True)
                self._schedule_refresh()

        def _delete_project(self, project):
            self._bring_to_front()
            response = rumps.alert(
                title="Confirm Delete",
                message=f"Delete ALL data for '{project}'?\nThis cannot be undone.",
                ok="Delete",
                cancel="Cancel",
            )
            if response == 1:
                delete_project_sessions(SESSIONS_FILE, project, today_only=False)
                delete_project_sessions(ACTIVE_FILE, project, today_only=False)
                self._schedule_refresh()

        def quit_app(self, _):
            rumps.quit_application()

    CCTimeMenuBar().run()


if __name__ == "__main__":
    main()
