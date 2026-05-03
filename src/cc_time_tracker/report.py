#!/usr/bin/env python3
"""cc-time-report — CLI viewer for Claude Code session time tracking."""

import json
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from cc_time_tracker import __version__
from cc_time_tracker.common import (
    SESSIONS_FILE, ACTIVE_FILE, EVENT_START, EVENT_END,
    load_jsonl, acquire_lock, atomic_write_text,
    BOLD, DIM, GREEN, CYAN, YELLOW, RED, RESET, UNDERLINE,
)


def load_sessions(after_ts: float | None = None) -> list[dict]:
    return load_jsonl(SESSIONS_FILE, after_ts=after_ts)

def load_active() -> list[dict]:
    return load_jsonl(ACTIVE_FILE)


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
    hours = seconds / 3600
    return f"{hours:.2f}h"


def filter_by_time(sessions: list[dict], after: datetime) -> list[dict]:
    """Filter sessions to those ending after a given datetime."""
    after_ts = after.timestamp()
    return [s for s in sessions if s.get("timestamp_unix", 0) >= after_ts]


def get_start_of_today() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_start_of_week() -> datetime:
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def get_start_of_month() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def aggregate_by_project(sessions: list[dict]) -> dict[str, dict]:
    """Aggregate duration and session count by project."""
    projects = defaultdict(lambda: {"total_seconds": 0, "session_count": 0, "cwd": ""})
    for s in sessions:
        proj = s.get("project", "unknown")
        dur = s.get("duration_seconds", 0) or 0
        projects[proj]["total_seconds"] += dur
        projects[proj]["session_count"] += 1
        projects[proj]["cwd"] = s.get("cwd", "")
    return dict(projects)


def aggregate_by_day(sessions: list[dict]) -> dict[str, dict[str, float]]:
    """Aggregate duration by date → project."""
    days = defaultdict(lambda: defaultdict(float))
    for s in sessions:
        ts = s.get("timestamp_unix", 0)
        if ts:
            day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            proj = s.get("project", "unknown")
            dur = s.get("duration_seconds", 0) or 0
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

    # Sort by total time descending
    sorted_projects = sorted(projects.items(), key=lambda x: x[1]["total_seconds"], reverse=True)

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
            print(f"    {proj:<20} {format_duration(dur):>10}  {DIM}{bar}{RESET}")


def print_active_sessions(active: list[dict] | None = None):
    print_header("Active Sessions")

    if active is None:
        active = load_active()
    if not active:
        print(f"  {DIM}No active sessions.{RESET}")
        return

    now = datetime.now(timezone.utc).timestamp()

    for s in active:
        start_ts = s.get("timestamp_unix", 0)
        elapsed = now - start_ts if start_ts else 0
        project = s.get("project", "unknown")
        sid_short = s.get("session_id", "???")[:12]
        print(
            f"  {GREEN}●{RESET} {BOLD}{project}{RESET}"
            f"  {YELLOW}{format_duration(elapsed)}{RESET} elapsed"
            f"  {DIM}({sid_short}…){RESET}"
        )
        print(f"    {DIM}{s.get('cwd', '')}{RESET}")


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
        active = load_active()
    active_ids = {a.get("session_id") for a in active}
    orphans = {sid: r for sid, r in starts.items() if sid not in active_ids}

    if not orphans:
        print(f"  {GREEN}No orphaned sessions — all clean!{RESET}")
        return

    for sid, r in sorted(orphans.items(), key=lambda x: x[1].get("timestamp_unix", 0), reverse=True):
        ts = r.get("timestamp", "?")
        project = r.get("project", "unknown")
        print(f"  {RED}○{RESET} {project}  started {ts}  {DIM}({sid[:12]}…){RESET}")

    print(f"\n  {DIM}Tip: These may be crashed sessions. They don't count in totals.{RESET}")


def merge_project_sessions(source: str, target: str) -> int:
    """Rewrite all sessions for source project to target project in sessions.jsonl.

    Returns number of records rewritten.
    """
    with acquire_lock():
        records = load_jsonl(SESSIONS_FILE)
        if not records:
            return 0

        rewritten = 0
        for record in records:
            if record.get("project") == source:
                record["project"] = target
                rewritten += 1

        atomic_write_text(
            SESSIONS_FILE,
            "\n".join(json.dumps(r) for r in records) + "\n",
        )
        return rewritten


def export_csv(sessions: list[dict]):
    """Export completed sessions as CSV to stdout."""
    print("date,project,cwd,session_id,duration_seconds,duration_hours,reason")
    for s in sessions:
        ts = s.get("timestamp_unix", 0)
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        dur = s.get("duration_seconds", 0) or 0
        hours = f"{dur / 3600:.4f}"
        proj = s.get("project", "").replace(",", ";")
        cwd = s.get("cwd", "").replace(",", ";")
        sid = s.get("session_id", "")
        reason = s.get("reason", "")
        print(f"{date},{proj},{cwd},{sid},{dur},{hours},{reason}")


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

    # Time-bounded commands load only records after the cutoff
    cutoff = None
    if command == "today":
        cutoff = get_start_of_today()
    elif command == "week":
        cutoff = get_start_of_week()
    elif command == "month":
        cutoff = get_start_of_month()
    elif command == "summary":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7))

    cutoff_ts = cutoff.timestamp() if cutoff else None
    records = load_sessions(after_ts=cutoff_ts)
    completed = get_completed_sessions(records)

    if command == "today":
        projects = aggregate_by_project(completed)
        print_project_table(projects, "Today")

    elif command == "week":
        projects = aggregate_by_project(completed)
        days = aggregate_by_day(completed)
        print_project_table(projects, "This Week")
        print_daily_breakdown(days)

    elif command == "month":
        projects = aggregate_by_project(completed)
        days = aggregate_by_day(completed)
        print_project_table(projects, "This Month")
        print_daily_breakdown(days)

    elif command == "all":
        projects = aggregate_by_project(completed)
        print_project_table(projects, "All Time")

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
        active = load_active()
        active_projects = {a.get("project") for a in active}
        if source in active_projects:
            print(f"{RED}Cannot merge '{source}' — it has an active session.{RESET}")
            sys.exit(1)

        count = merge_project_sessions(source, target)
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
        active = load_active()
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
