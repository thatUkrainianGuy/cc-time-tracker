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
    try:
        raw_lines = sessions_file.read_text().strip().split("\n")
    except FileNotFoundError:
        return 0

    if not any(l.strip() for l in raw_lines):
        return 0

    today_start = get_today_start_unix() if today_only else None
    kept_lines = []
    removed = 0

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            kept_lines.append(stripped)
            continue

        if record.get("project") == project:
            if today_only:
                if record.get("timestamp_unix", 0) >= today_start:
                    removed += 1
                    continue
            else:
                removed += 1
                continue
        kept_lines.append(stripped)

    lock_path = sessions_file.parent / ".lock"
    with _acquire_lock(lock_path):
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


def load_active_sessions(active_file: Path) -> list[dict]:
    return _read_jsonl(active_file)


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


def main():
    """rumps is imported here (not at module level) so pure functions
    above can be tested without rumps installed.
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
            self.refresh(None)

        def refresh(self, _):
            completed = load_today_sessions(SESSIONS_FILE)
            active = load_active_sessions(ACTIVE_FILE)
            projects, total = build_project_data(completed, active)

            self.title = f"⏱ {format_duration(total)}"
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
                        "Delete all sessions",
                        callback=lambda _, p=name: self._delete_sessions(p, today_only=False),
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

        def _delete_sessions(self, project, today_only):
            scope = "today's" if today_only else "ALL"
            msg = f"Delete {scope} sessions for '{project}'?"
            if not today_only:
                msg += "\nThis cannot be undone."
            response = rumps.alert(
                title="Confirm Delete",
                message=msg,
                ok="Delete",
                cancel="Cancel",
            )
            if response == 1:  # OK clicked
                delete_project_sessions(SESSIONS_FILE, project, today_only)
                self.refresh(None)

        def quit_app(self, _):
            rumps.quit_application()

    CCTimeMenuBar().run()


if __name__ == "__main__":
    main()
