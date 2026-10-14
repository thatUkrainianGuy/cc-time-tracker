#!/usr/bin/env python3
"""cc-time-report — CLI viewer for Claude Code session time tracking."""

import csv
import json
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from cc_time_tracker import __version__, sync
from cc_time_tracker.common import (
    SESSIONS_FILE, ACTIVE_FILE, EVENT_START, EVENT_END,
    load_jsonl, acquire_lock, rewrite_jsonl,
    coerce_float, csv_safe, strip_control,
    BOLD, DIM, GREEN, CYAN, YELLOW, RED, RESET, UNDERLINE,
)


# Display caps for attacker-controllable strings printed to the terminal.
# Project names are already clamped to 64 at write time, but cwd is stored
# verbatim and a malicious repo can sit deep under e.g. ~/giant-prefix/...
_DISPLAY_PROJECT_MAX = 64
_DISPLAY_CWD_MAX = 200
_DISPLAY_REASON_MAX = 64
_DISPLAY_TS_MAX = 32


def get_completed_sessions(records: list[dict]) -> list[dict]:
    """Extract completed sessions (end events with duration)."""
    return [r for r in records if r.get("event") == EVENT_END and r.get("duration_seconds") is not None]


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def format_duration_hours(seconds: float) -> str:
    """Format as decimal hours for billing-style reports."""
    return f"{seconds / 3600:.2f}h"


def aggregate_by_project(sessions: list[dict]) -> dict[str, dict]:
    """Aggregate duration and session count by project."""
    projects = defaultdict(lambda: {"total_seconds": 0.0, "session_count": 0, "cwd": ""})
    for s in sessions:
        proj = s.get("project", "unknown")
        dur = coerce_float(s.get("duration_seconds"))
        projects[proj]["total_seconds"] += dur
        projects[proj]["session_count"] += 1
        projects[proj]["cwd"] = s.get("cwd", "")
    return dict(projects)


def aggregate_by_day(sessions: list[dict]) -> dict[str, dict[str, float]]:
    """Aggregate duration by date → project."""
    days = defaultdict(lambda: defaultdict(float))
    for s in sessions:
        ts = coerce_float(s.get("timestamp_unix"))
        if ts:
            day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            proj = s.get("project", "unknown")
            dur = coerce_float(s.get("duration_seconds"))
            days[day][proj] += dur
    return dict(days)


# ─── Display Functions ────────────────────────────────────────────────


def print_header(title: str):
    print(f"\n{BOLD}{UNDERLINE}{title}{RESET}\n")


def print_project_table(projects: dict[str, dict], title: str = "Projects"):
    print_header(title)

    if not projects:
        print(f"  {DIM}No sessions recorded.{RESET}")
        return

    # Sort by total time descending. Sanitize names up-front so attacker
    # ANSI escapes don't reach the terminal — and so column widths reflect
    # the *displayed* string, not the raw one.
    sorted_projects = sorted(
        ((strip_control(name, max_len=_DISPLAY_PROJECT_MAX), data) for name, data in projects.items()),
        key=lambda x: x[1]["total_seconds"],
        reverse=True,
    )

    total_all = sum(p["total_seconds"] for _, p in sorted_projects)

    # Column widths
    max_name = max(len(name) for name, _ in sorted_projects)
    max_name = max(max_name, 7)  # minimum "Project" header width

    print(f"  {BOLD}{'Project':<{max_name}}  {'Time':>10}  {'Hours':>8}  {'Sessions':>8}{RESET}")
    print(f"  {'─' * max_name}  {'─' * 10}  {'─' * 8}  {'─' * 8}")

    for name, data in sorted_projects:
        dur = data["total_seconds"]

        # Color based on time spent
        if dur > 3600:
            color = GREEN
        elif dur > 600:
            color = CYAN
        else:
            color = DIM

        print(
            f"  {color}{name:<{max_name}}{RESET}"
            f"  {format_duration(dur):>10}"
            f"  {format_duration_hours(dur):>8}"
            f"  {data['session_count']:>8}"
        )

    print(f"  {'─' * max_name}  {'─' * 10}  {'─' * 8}  {'─' * 8}")
    total_sessions = sum(p["session_count"] for _, p in sorted_projects)
    print(
        f"  {BOLD}{'TOTAL':<{max_name}}"
        f"  {format_duration(total_all):>10}"
        f"  {format_duration_hours(total_all):>8}"
        f"  {total_sessions:>8}{RESET}"
    )


def print_daily_breakdown(days: dict[str, dict[str, float]]):
    print_header("Daily Breakdown")

    if not days:
        print(f"  {DIM}No sessions recorded.{RESET}")
        return

    for day in sorted(days.keys(), reverse=True):
        projects = days[day]
        day_total = sum(projects.values())
        print(f"  {BOLD}{day}{RESET}  {CYAN}{format_duration(day_total)}{RESET}  ({format_duration_hours(day_total)})")
        for proj, dur in sorted(projects.items(), key=lambda x: x[1], reverse=True):
            bar_len = int(min(dur / 600, 30))  # 10 min = 1 char, max 30
            bar = "█" * bar_len
            safe_proj = strip_control(proj, max_len=_DISPLAY_PROJECT_MAX)
            print(f"    {safe_proj:<20} {format_duration(dur):>10}  {DIM}{bar}{RESET}")


def print_active_sessions(active: list[dict] | None = None):
    print_header("Active Sessions")

    if active is None:
        active = load_jsonl(ACTIVE_FILE)
    if not active:
        print(f"  {DIM}No active sessions.{RESET}")
        return

    now = datetime.now(timezone.utc).timestamp()

    for s in active:
        start_ts = coerce_float(s.get("timestamp_unix"))
        elapsed = now - start_ts if start_ts else 0
        project = strip_control(s.get("project", "unknown"), max_len=_DISPLAY_PROJECT_MAX)
        sid_short = strip_control(s.get("session_id", "???"), max_len=12)
        cwd = strip_control(s.get("cwd", ""), max_len=_DISPLAY_CWD_MAX)
        print(
            f"  {GREEN}●{RESET} {BOLD}{project}{RESET}"
            f"  {YELLOW}{format_duration(elapsed)}{RESET} elapsed"
            f"  {DIM}({sid_short}…){RESET}"
        )
        print(f"    {DIM}{cwd}{RESET}")


def print_orphans(records: list[dict], active: list[dict] | None = None):
    """Find start events with no matching end event."""
    print_header("Orphaned Sessions (no end recorded)")

    starts = {}
    for r in records:
        sid = r.get("session_id")
        if r.get("event") == EVENT_START:
            starts[sid] = r
        elif r.get("event") == EVENT_END and sid in starts:
            del starts[sid]

    if active is None:
        active = load_jsonl(ACTIVE_FILE)
    active_ids = {a.get("session_id") for a in active}
    orphans = {sid: r for sid, r in starts.items() if sid not in active_ids}

    if not orphans:
        print(f"  {GREEN}No orphaned sessions — all clean!{RESET}")
        return

    for sid, r in sorted(
        orphans.items(),
        key=lambda x: coerce_float(x[1].get("timestamp_unix")),
        reverse=True,
    ):
        ts = strip_control(r.get("timestamp", "?"), max_len=_DISPLAY_TS_MAX)
        project = strip_control(r.get("project", "unknown"), max_len=_DISPLAY_PROJECT_MAX)
        sid_short = strip_control(sid, max_len=12)
        print(f"  {RED}○{RESET} {project}  started {ts}  {DIM}({sid_short}…){RESET}")

    print(f"\n  {DIM}Tip: These may be crashed sessions. They don't count in totals.{RESET}")


def merge_project_sessions(
    sessions_file,
    source: str,
    target: str,
    lock_path=None,
    sync_cursor_path=None,
) -> int:
    """Rewrite all sessions for source project to target project.

    Returns number of records rewritten. Also evicts the affected session_ids
    from the sync cursor so the next sync re-pushes them under the new project
    name (otherwise the server would keep them under the old name forever).
    Shared with the menubar app.
    """
    affected_ids: list[str] = []

    def transform(record):
        if record.get("project") == source:
            sid = record.get("session_id")
            if isinstance(sid, str):
                affected_ids.append(sid)
            return {**record, "project": target}
        return record

    with acquire_lock(lock_path):
        rewritten = rewrite_jsonl(sessions_file, transform)
        if affected_ids:
            sync.evict_session_ids_from_cursor(sync_cursor_path or sync.CURSOR_FILE, affected_ids)
        return rewritten


def export_csv(sessions: list[dict]):
    """Export completed sessions as CSV to stdout.

    Uses ``csv.writer`` for proper quoting and routes every text field through
    ``csv_safe`` so that Excel/Sheets won't evaluate formula-leading values
    (``=``, ``+``, ``-``, ``@``, tab, CR) embedded in attacker-controllable
    fields like project name or cwd.
    """
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow([
        "date", "project", "cwd", "session_id",
        "duration_seconds", "duration_hours", "reason",
    ])
    for s in sessions:
        ts = coerce_float(s.get("timestamp_unix"))
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        dur = coerce_float(s.get("duration_seconds"))
        writer.writerow([
            date,
            csv_safe(s.get("project", "")),
            csv_safe(s.get("cwd", "")),
            csv_safe(s.get("session_id", "")),
            f"{dur:g}",
            f"{dur / 3600:.4f}",
            csv_safe(s.get("reason", "")),
        ])


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if "--version" in args:
        print(f"cc-time-report {__version__}")
        sys.exit(0)

    command = args[0] if args else "summary"

    if command == "active":
        print_active_sessions()
        print()
        return

    # Time-bounded commands load only records after the cutoff:
    # command -> (cutoff, table title, show daily breakdown)
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    periods = {
        "today": (midnight, "Today", False),
        "week": (midnight - timedelta(days=now.weekday()), "This Week", True),
        "month": (midnight.replace(day=1), "This Month", True),
        "all": (None, "All Time", False),
    }
    if command in periods:
        cutoff = periods[command][0]
    elif command == "summary":
        cutoff = now - timedelta(days=7)
    else:
        cutoff = None

    records = load_jsonl(SESSIONS_FILE, after_ts=cutoff.timestamp() if cutoff else None)
    completed = get_completed_sessions(records)

    if command in periods:
        _, title, show_days = periods[command]
        print_project_table(aggregate_by_project(completed), title)
        if show_days:
            print_daily_breakdown(aggregate_by_day(completed))

    elif command == "project":
        if len(args) < 2:
            print(f"{RED}Usage: cc-time-report project <name>{RESET}")
            sys.exit(1)
        name = args[1].lower()
        filtered = [s for s in completed if name in s.get("project", "").lower()]
        projects = aggregate_by_project(filtered)
        days = aggregate_by_day(filtered)
        print_project_table(projects, f"Project: {name}")
        print_daily_breakdown(days)

    elif command == "orphans":
        print_orphans(records)

    elif command == "merge":
        if len(args) < 3:
            print(f"{RED}Usage: cc-time-report merge <source> <target>{RESET}")
            sys.exit(1)
        source = args[1]
        target = args[2]

        # Check source isn't currently active
        active = load_jsonl(ACTIVE_FILE)
        active_projects = {a.get("project") for a in active}
        if source in active_projects:
            print(f"{RED}Cannot merge '{source}' — it has an active session.{RESET}")
            sys.exit(1)

        count = merge_project_sessions(SESSIONS_FILE, source, target)
        if count:
            print(f"{GREEN}Merged {count} records from '{source}' into '{target}'.{RESET}")
        else:
            print(f"{YELLOW}No records found for '{source}'.{RESET}")

    elif command == "csv":
        export_csv(completed)

    elif command == "raw":
        for r in records:
            print(json.dumps(r))

    elif command == "summary":
        active = load_jsonl(ACTIVE_FILE)
        projects = aggregate_by_project(completed)
        days = aggregate_by_day(completed)

        print(f"\n{BOLD}Claude Code Time Tracker{RESET}")
        print(f"{DIM}Last 7 days  •  {len(completed)} sessions{RESET}")

        print_active_sessions(active)
        print_project_table(projects, "Last 7 Days")
        print_daily_breakdown(days)

    else:
        print(__doc__)
        sys.exit(1)

    print()  # trailing newline


if __name__ == "__main__":
    main()
