#!/usr/bin/env python3
"""
macOS menu bar app for Claude Code time tracking.
Shows cumulative project time in the menu bar with today/total breakdown.
Click to see per-project breakdown, archive projects, or export reports.

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
PROJECTS_META_FILE = TRACKING_DIR / "projects.json"
LOCK_PATH = TRACKING_DIR / ".lock"
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


def load_projects_meta(projects_file: Path, lock_path: Path) -> dict:
    """Load projects.json metadata. Returns {} if missing or invalid."""
    with _acquire_lock(lock_path):
        try:
            return json.loads(projects_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}


def save_projects_meta(projects_file: Path, meta: dict, lock_path: Path) -> None:
    """Write projects.json atomically under lock."""
    with _acquire_lock(lock_path):
        projects_file.write_text(json.dumps(meta, indent=2) + "\n")


def is_archived(meta: dict, project: str) -> bool:
    """Check if a project is archived. Defaults to False if absent."""
    return meta.get(project, {}).get("archived", False)


def set_archived(meta: dict, project: str, archived: bool) -> None:
    """Set archived status for a project in the meta dict (in-place)."""
    if project not in meta:
        meta[project] = {}
    meta[project]["archived"] = archived


def remove_project_meta(meta: dict, project: str) -> None:
    """Remove a project's metadata entry (in-place). No-op if absent."""
    meta.pop(project, None)


def _aggregate_sessions_by_date(project: str, sessions: list[dict]) -> list[tuple[str, int, float]]:
    """Aggregate sessions for a project by date (local time).

    Returns sorted list of (date_str, session_count, total_seconds).
    """
    days: dict[str, list[float]] = {}
    for s in sessions:
        if s.get("project") != project:
            continue
        ts = s.get("timestamp_unix", 0)
        if not ts:
            continue
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        days.setdefault(day, []).append(s.get("duration_seconds", 0) or 0)

    return sorted(
        [(day, len(durations), sum(durations)) for day, durations in days.items()]
    )


def generate_csv_report(project: str, sessions: list[dict]) -> str:
    """Generate a CSV report for a project."""
    rows = _aggregate_sessions_by_date(project, sessions)
    lines = ["Date,Project,Sessions,Duration,Hours"]
    total_sessions = 0
    total_seconds = 0.0
    for day, count, secs in rows:
        total_sessions += count
        total_seconds += secs
        lines.append(f"{day},{project},{count},{format_duration(secs)},{secs / 3600:.2f}")
    lines.append(f"Total,,{total_sessions},{format_duration(total_seconds)},{total_seconds / 3600:.2f}")
    return "\n".join(lines) + "\n"


def generate_md_report(project: str, sessions: list[dict]) -> str:
    """Generate a Markdown report for a project."""
    rows = _aggregate_sessions_by_date(project, sessions)
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# {project} — Time Report",
        "",
        f"Generated: {today}",
        "",
        "| Date | Sessions | Duration | Hours |",
        "|------|----------|----------|-------|",
    ]
    total_sessions = 0
    total_seconds = 0.0
    for day, count, secs in rows:
        total_sessions += count
        total_seconds += secs
        lines.append(f"| {day} | {count} | {format_duration(secs)} | {secs / 3600:.2f} |")
    lines.append(
        f"| **Total** | **{total_sessions}** | **{format_duration(total_seconds)}** | **{total_seconds / 3600:.2f}** |"
    )
    return "\n".join(lines) + "\n"


def delete_project_sessions(
    sessions_file: Path,
    project: str,
    today_only: bool,
    lock_path: Path = LOCK_PATH,
) -> int:
    """Remove sessions for a project from the JSONL file.

    Returns number of records removed.
    """
    today_start = get_today_start_unix() if today_only else None

    with _acquire_lock(lock_path):
        try:
            raw = sessions_file.read_text()
        except FileNotFoundError:
            return 0
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
            self._sessions_mtime = 0.0
            self._active_mtime = 0.0
            self._cached_all_completed = []
            self._cached_active = []
            self.timer = rumps.Timer(self.refresh, REFRESH_INTERVAL)
            self.timer.start()
            self.refresh(None)

        def _file_mtime(self, path):
            try:
                return path.stat().st_mtime
            except FileNotFoundError:
                return 0.0

        def refresh(self, _):
            sessions_mt = self._file_mtime(SESSIONS_FILE)
            if sessions_mt != self._sessions_mtime:
                self._sessions_mtime = sessions_mt
                self._cached_all_completed = load_all_completed_sessions(SESSIONS_FILE)

            active_mt = self._file_mtime(ACTIVE_FILE)
            if active_mt != self._active_mtime:
                self._active_mtime = active_mt
                self._cached_active = load_active_sessions(ACTIVE_FILE)

            all_completed = self._cached_all_completed
            active = self._cached_active

            today_start = get_today_start_unix()
            today_completed = [
                r for r in all_completed
                if r.get("timestamp_unix", 0) >= today_start
            ]
            meta = load_projects_meta(PROJECTS_META_FILE, LOCK_PATH)
            self._all_completed = all_completed

            meta_changed = False
            for s in active:
                proj = s.get("project", "unknown")
                if is_archived(meta, proj):
                    set_archived(meta, proj, False)
                    meta_changed = True
            if meta_changed:
                save_projects_meta(PROJECTS_META_FILE, meta, LOCK_PATH)

            projects, today_total = build_project_data(today_completed, all_completed, active)

            icon = "⏱" if active else "⏸"
            self.title = f"{icon} {format_duration(today_total)}"
            self.menu.clear()

            archived_projects = []

            for name, today_secs, total_secs, is_active in projects:
                if is_archived(meta, name) and not is_active:
                    archived_projects.append((name, today_secs, total_secs, is_active))
                    continue

                prefix = "🟢 " if is_active else "⚪ "
                today_str = format_duration(today_secs)
                total_str = format_duration(total_secs)
                label = f"{prefix}{name}\t{today_str} today / {total_str} total"

                item = rumps.MenuItem(label, callback=lambda _: None) if is_active else rumps.MenuItem(label)
                self._add_export_items(item, name)
                if not is_active:
                    item.add(rumps.MenuItem(
                        "Archive",
                        callback=lambda _, p=name: self._archive_project(p),
                    ))
                    item.add(rumps.MenuItem(
                        "Delete today's sessions",
                        callback=lambda _, p=name: self._delete_sessions(p, today_only=True),
                    ))
                    item.add(rumps.MenuItem(
                        "Delete project",
                        callback=lambda _, p=name: self._delete_project(p),
                    ))
                self.menu.add(item)

            if projects:
                self.menu.add(rumps.separator)

            total_item = rumps.MenuItem(
                f"Today: {format_duration(today_total)}", callback=None
            )
            self.menu.add(total_item)

            if archived_projects:
                self.menu.add(rumps.separator)
                archived_menu = rumps.MenuItem(f"Show archived ({len(archived_projects)})")
                for name, today_secs, total_secs, _ in archived_projects:
                    total_str = format_duration(total_secs)
                    alabel = f"⚪ {name}\t{total_str} total"
                    aitem = rumps.MenuItem(alabel)
                    self._add_export_items(aitem, name)
                    aitem.add(rumps.MenuItem(
                        "Unarchive",
                        callback=lambda _, p=name: self._unarchive_project(p),
                    ))
                    aitem.add(rumps.MenuItem(
                        "Delete project",
                        callback=lambda _, p=name: self._delete_project(p),
                    ))
                    archived_menu.add(aitem)
                self.menu.add(archived_menu)

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
                delete_project_sessions(SESSIONS_FILE, project, today_only=today_only)
                self._schedule_refresh()

        def _add_export_items(self, menu_item, project_name):
            menu_item.add(rumps.MenuItem(
                "Export as CSV",
                callback=lambda _, p=project_name: self._export_report(p, "csv"),
            ))
            menu_item.add(rumps.MenuItem(
                "Export as Markdown",
                callback=lambda _, p=project_name: self._export_report(p, "md"),
            ))

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
                meta = load_projects_meta(PROJECTS_META_FILE, LOCK_PATH)
                remove_project_meta(meta, project)
                save_projects_meta(PROJECTS_META_FILE, meta, LOCK_PATH)
                self._schedule_refresh()

        def _archive_project(self, project):
            self._set_project_archived(project, True)

        def _unarchive_project(self, project):
            self._set_project_archived(project, False)

        def _set_project_archived(self, project, archived):
            meta = load_projects_meta(PROJECTS_META_FILE, LOCK_PATH)
            set_archived(meta, project, archived)
            save_projects_meta(PROJECTS_META_FILE, meta, LOCK_PATH)
            self._schedule_refresh()

        def _export_report(self, project, fmt):
            self._bring_to_front()
            from AppKit import NSSavePanel

            all_sessions = getattr(self, '_all_completed', None) or load_all_completed_sessions(SESSIONS_FILE)

            if fmt == "csv":
                content = generate_csv_report(project, all_sessions)
                ext = "csv"
            else:
                content = generate_md_report(project, all_sessions)
                ext = "md"

            today = datetime.now().strftime("%Y-%m-%d")
            filename = f"{project}_report_{today}.{ext}"

            panel = NSSavePanel.savePanel()
            panel.setNameFieldStringValue_(filename)
            panel.setAllowedFileTypes_([ext])

            if panel.runModal() == 1:  # NSModalResponseOK
                path = panel.URL().path()
                Path(path).write_text(content, encoding="utf-8")

        def quit_app(self, _):
            rumps.quit_application()

    CCTimeMenuBar().run()


if __name__ == "__main__":
    main()
