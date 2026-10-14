#!/usr/bin/env python3
"""
macOS menu bar app for Claude Code time tracking.
Shows cumulative project time in the menu bar with today/total breakdown.
Click to see per-project breakdown, archive projects, or export reports.

Usage:
    python3 cc-time-menubar.py

Requires: pip install rumps
"""

import csv
import io
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run straight from the repo checkout: import the package from ./src.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cc_time_tracker.common import (  # noqa: E402
    TRACKING_DIR, SESSIONS_FILE, ACTIVE_FILE, EVENT_END,
    acquire_lock, atomic_write_text, coerce_float, coerce_int, csv_safe,
    load_jsonl, md_safe, pid_alive, rewrite_jsonl, strip_control,
)
from cc_time_tracker.report import merge_project_sessions  # noqa: E402,F401
from cc_time_tracker.sync import CURSOR_FILE as SYNC_CURSOR_FILE, evict_session_ids_from_cursor  # noqa: E402

PROJECTS_META_FILE = TRACKING_DIR / "projects.json"
REFRESH_INTERVAL = 30  # seconds


def format_duration(seconds: float) -> str:
    """Skips seconds (unlike cc-time-report.py) to avoid menu bar noise."""
    total_minutes = int(seconds // 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m"


def load_projects_meta(projects_file: Path, lock_path: Path | None = None) -> dict:
    with acquire_lock(lock_path):
        try:
            return json.loads(projects_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}


def save_projects_meta(projects_file: Path, meta: dict, lock_path: Path | None = None) -> None:
    """Write projects.json atomically under lock."""
    with acquire_lock(lock_path):
        atomic_write_text(projects_file, json.dumps(meta, indent=2) + "\n")


def is_archived(meta: dict, project: str) -> bool:
    return meta.get(project, {}).get("archived", False)


def set_archived(meta: dict, project: str, archived: bool) -> None:
    if project not in meta:
        meta[project] = {}
    meta[project]["archived"] = archived


def remove_project_meta(meta: dict, project: str) -> None:
    meta.pop(project, None)


def _aggregate_sessions_by_date(project: str, sessions: list[dict]) -> list[tuple[str, int, float]]:
    """Aggregate sessions for a project by date (local time).

    Returns sorted list of (date_str, session_count, total_seconds).
    """
    days: dict[str, list[float]] = {}
    for s in sessions:
        if s.get("project") != project:
            continue
        ts = coerce_float(s.get("timestamp_unix"))
        if not ts:
            continue
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        days.setdefault(day, []).append(coerce_float(s.get("duration_seconds")))

    return sorted(
        [(day, len(durations), sum(durations)) for day, durations in days.items()]
    )


def _row_totals(rows: list[tuple[str, int, float]]) -> tuple[int, float]:
    """Sum session counts and seconds across aggregated day rows."""
    return sum(c for _, c, _ in rows), sum(s for _, _, s in rows)


def generate_csv_report(project: str, sessions: list[dict]) -> str:
    """Generate a CSV report for a project.

    Uses ``csv.writer`` for proper quoting and routes the project name
    through ``csv_safe`` so a project called e.g. ``=HYPERLINK(...)``
    doesn't fire a formula when the file is opened in Excel/Sheets.
    """
    rows = _aggregate_sessions_by_date(project, sessions)
    safe_project = csv_safe(project)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["Date", "Project", "Sessions", "Duration", "Hours"])
    for day, count, secs in rows:
        writer.writerow([day, safe_project, count, format_duration(secs), f"{secs / 3600:.2f}"])
    total_sessions, total_seconds = _row_totals(rows)
    writer.writerow(["Total", "", total_sessions, format_duration(total_seconds), f"{total_seconds / 3600:.2f}"])
    return buf.getvalue()


def generate_md_report(project: str, sessions: list[dict]) -> str:
    """Generate a Markdown report for a project.

    Project names go through ``md_safe`` (escapes ``|``, strips control
    chars and embedded newlines) so a project name can't break out of the
    table or inject extra headings.
    """
    rows = _aggregate_sessions_by_date(project, sessions)
    today = datetime.now().strftime("%Y-%m-%d")
    safe_project = md_safe(project)
    lines = [
        f"# {safe_project} — Time Report",
        "",
        f"Generated: {today}",
        "",
        "| Date | Sessions | Duration | Hours |",
        "|------|----------|----------|-------|",
    ]
    for day, count, secs in rows:
        lines.append(f"| {day} | {count} | {format_duration(secs)} | {secs / 3600:.2f} |")
    total_sessions, total_seconds = _row_totals(rows)
    lines.append(
        f"| **Total** | **{total_sessions}** | **{format_duration(total_seconds)}** | **{total_seconds / 3600:.2f}** |"
    )
    return "\n".join(lines) + "\n"


def delete_project_sessions(
    sessions_file: Path,
    project: str,
    today_only: bool,
    lock_path: Path | None = None,
    sync_cursor_path: Path | None = None,
) -> int:
    """Remove sessions for a project from the JSONL file.

    Returns number of records removed. Also evicts the deleted session_ids
    from the sync cursor to keep it tidy (the server still keeps a copy —
    deletion does not propagate over the wire).
    """
    today_start = get_today_start_unix() if today_only else None
    affected_ids: list[str] = []

    def transform(record):
        if record.get("project") == project:
            if not today_only or record.get("timestamp_unix", 0) >= today_start:
                sid = record.get("session_id")
                if isinstance(sid, str):
                    affected_ids.append(sid)
                return None
        return record

    with acquire_lock(lock_path):
        removed = rewrite_jsonl(sessions_file, transform)
        if affected_ids:
            evict_session_ids_from_cursor(sync_cursor_path or SYNC_CURSOR_FILE, affected_ids)
        return removed


def get_today_start_unix() -> float:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today.timestamp()


def load_all_completed_sessions(sessions_file: Path) -> list[dict]:
    """Load all completed sessions (end events only) from JSONL file, no date filter."""
    return [
        r for r in load_jsonl(sessions_file)
        if r.get("event") == EVENT_END
        and r.get("duration_seconds") is not None
    ]


def load_active_sessions(active_file: Path) -> list[dict]:
    return load_jsonl(active_file)


def _process_cwd(pid: int):
    """Return the process's current working directory via lsof, or None.

    None means "could not determine" (lsof missing, failed, or no cwd row) —
    callers must treat that as verification failure, never as a pass.
    Absolute lsof path so a hostile PATH can't substitute the binary.
    """
    try:
        out = subprocess.run(
            ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def find_active_record_process(record: dict):
    """Validate that an active record's pid still belongs to its session.

    Returns (pid, None) when the process is safe to signal, else
    (None, reason). Guards against pid reuse: the live process must still
    have the cwd the session started in, otherwise refuse to touch it.
    pid <= 0 is rejected outright — os.kill(0)/os.kill(-n) signal whole
    process groups, not a single process.
    """
    pid = coerce_int(record.get("pid"))
    if pid is None or pid <= 0:
        return None, "No pid recorded for this session."
    if not pid_alive(pid):
        return None, (
            "Process is not running — the timer is an orphan and will be "
            "cleaned up on the next session start."
        )
    proc_cwd = _process_cwd(pid)
    if proc_cwd is None:
        return None, f"Could not verify what pid {pid} is — not touching it."
    rec_cwd = record.get("cwd")
    if not isinstance(rec_cwd, str) or not rec_cwd:
        return None, "Session record has no cwd to verify the process against."
    if os.path.realpath(proc_cwd) != os.path.realpath(rec_cwd):
        return None, (
            f"pid {pid} no longer matches this session (its working directory "
            f"changed) — the pid may have been reused. Not touching it."
        )
    return pid, None


def stop_session_process(record: dict, kill_func=os.kill):
    """SIGTERM the Claude process behind an active session record.

    Returns (ok, message). Always SIGTERM, never SIGKILL — a graceful
    shutdown fires the SessionEnd hook, which writes the end record and
    closes the timer; a hard kill would leave an orphan in active.jsonl.
    """
    pid, err = find_active_record_process(record)
    if pid is None:
        return False, err
    try:
        kill_func(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False, "Process already exited."
    except OSError as e:
        return False, f"Could not signal pid {pid}: {e}"
    return True, f"Sent SIGTERM to pid {pid} — the timer closes when the session ends."


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
        dur = coerce_float(s.get("duration_seconds"))
        today_time[proj] = today_time.get(proj, 0) + dur

    for s in all_sessions:
        proj = s.get("project", "unknown")
        dur = coerce_float(s.get("duration_seconds"))
        total_time[proj] = total_time.get(proj, 0) + dur

    for s in active_sessions:
        proj = s.get("project", "unknown")
        start_ts = coerce_float(s.get("timestamp_unix"), default=now)
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
            meta = load_projects_meta(PROJECTS_META_FILE)

            meta_changed = False
            for s in active:
                proj = s.get("project", "unknown")
                if is_archived(meta, proj):
                    set_archived(meta, proj, False)
                    meta_changed = True
            if meta_changed:
                save_projects_meta(PROJECTS_META_FILE, meta)

            projects, today_total = build_project_data(today_completed, all_completed, active)

            icon = "⏱" if active else "⏸"
            self.title = f"{icon} {format_duration(today_total)}"
            self.menu.clear()

            archived_projects = []
            all_project_names = [name for name, _, _, _ in projects]

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
                if is_active:
                    for rec in active:
                        if rec.get("project", "unknown") == name:
                            item.add(self._make_stop_item(rec))
                if not is_active:
                    merge_menu = rumps.MenuItem("Merge into...")
                    for target in all_project_names:
                        if target != name:
                            merge_menu.add(rumps.MenuItem(
                                target,
                                callback=lambda _, s=name, t=target: self._merge_project(s, t),
                            ))
                    if len(merge_menu) > 0:
                        item.add(merge_menu)
                    item.add(rumps.MenuItem(
                        "Archive",
                        callback=lambda _, p=name: self._set_project_archived(p, True),
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
                        callback=lambda _, p=name: self._set_project_archived(p, False),
                    ))
                    aitem.add(rumps.MenuItem(
                        "Delete project",
                        callback=lambda _, p=name: self._delete_project(p),
                    ))
                    archived_menu.add(aitem)
                self.menu.add(archived_menu)

            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("Quit", callback=rumps.quit_application))

        def _schedule_refresh(self, delay=0.1):
            """Defer refresh to next run loop iteration to avoid mutating menu mid-callback."""
            t = rumps.Timer(self._deferred_refresh, delay)
            t.start()

        def _deferred_refresh(self, timer):
            timer.stop()
            self.refresh(None)

        def _bring_to_front(self):
            from AppKit import NSApplication
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

        def _make_stop_item(self, record):
            pid = coerce_int(record.get("pid"))
            start_ts = coerce_float(record.get("timestamp_unix"))
            since = datetime.fromtimestamp(start_ts).strftime("%H:%M") if start_ts else "?"
            label = f"Stop session (pid {pid if pid is not None else '?'}, since {since})"
            return rumps.MenuItem(label, callback=lambda _, r=record: self._stop_session(r))

        def _stop_session(self, record):
            self._bring_to_front()
            project = strip_control(record.get("project", "unknown"))
            pid, err = find_active_record_process(record)
            if pid is None:
                rumps.alert(title="Cannot Stop Session", message=err)
                self._schedule_refresh()
                return
            response = rumps.alert(
                title="Confirm Stop",
                message=f"Stop the Claude Code session for '{project}' (pid {pid})?\n"
                        f"It gets a graceful shutdown so its time is recorded.",
                ok="Stop",
                cancel="Cancel",
            )
            if response == 1:
                ok, msg = stop_session_process(record)
                if not ok:
                    rumps.alert(title="Stop Failed", message=msg)
                # End hook needs a moment to write the end record after SIGTERM.
                self._schedule_refresh(delay=2.0)

        def _add_export_items(self, menu_item, project_name):
            menu_item.add(rumps.MenuItem(
                "Export as CSV",
                callback=lambda _, p=project_name: self._export_report(p, "csv"),
            ))
            menu_item.add(rumps.MenuItem(
                "Export as Markdown",
                callback=lambda _, p=project_name: self._export_report(p, "md"),
            ))

        def _merge_project(self, source, target):
            self._bring_to_front()
            response = rumps.alert(
                title="Confirm Merge",
                message=f"Merge all sessions from '{source}' into '{target}'?\n"
                        f"This will reassign all '{source}' records to '{target}' and cannot be undone.",
                ok="Merge",
                cancel="Cancel",
            )
            if response == 1:
                merge_project_sessions(SESSIONS_FILE, source, target)
                meta = load_projects_meta(PROJECTS_META_FILE)
                remove_project_meta(meta, source)
                save_projects_meta(PROJECTS_META_FILE, meta)
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
                meta = load_projects_meta(PROJECTS_META_FILE)
                remove_project_meta(meta, project)
                save_projects_meta(PROJECTS_META_FILE, meta)
                self._schedule_refresh()

        def _set_project_archived(self, project, archived):
            meta = load_projects_meta(PROJECTS_META_FILE)
            set_archived(meta, project, archived)
            save_projects_meta(PROJECTS_META_FILE, meta)
            self._schedule_refresh()

        def _export_report(self, project, fmt):
            self._bring_to_front()
            from AppKit import NSSavePanel

            if fmt == "csv":
                content = generate_csv_report(project, self._cached_all_completed)
                ext = "csv"
            else:
                content = generate_md_report(project, self._cached_all_completed)
                ext = "md"

            today = datetime.now().strftime("%Y-%m-%d")
            filename = f"{project}_report_{today}.{ext}"

            panel = NSSavePanel.savePanel()
            panel.setNameFieldStringValue_(filename)
            panel.setAllowedFileTypes_([ext])

            if panel.runModal() == 1:  # NSModalResponseOK
                path = panel.URL().path()
                Path(path).write_text(content, encoding="utf-8")

    CCTimeMenuBar().run()


if __name__ == "__main__":
    main()
