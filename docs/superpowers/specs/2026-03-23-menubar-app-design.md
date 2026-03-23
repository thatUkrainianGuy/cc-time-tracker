# macOS Menu Bar App for CC Time Tracker

## Overview

A macOS menu bar app that shows today's Claude Code session time next to the battery icon. Clicking it reveals a dropdown with per-project breakdowns, active session indicators, and a daily total.

## Technology

- **Python + rumps** (`pip install rumps`)
- Single file: `cc-time-menubar.py`
- Direct file reads from `~/.claude/time-tracking/` (no CLI subprocess, no shared module)
- Launched manually (`python3 cc-time-menubar.py` or added to Login Items by the user)

## Data Layer

Reads two files directly:

- `~/.claude/time-tracking/sessions.jsonl` — filter `event=="end"` records where timestamp falls within today (local time midnight to now)
- `~/.claude/time-tracking/active.jsonl` — all records represent currently running sessions

Parsing is inlined (~20 lines), duplicated from `cc-time-report.py`. This is intentional — keeps the script self-contained and matches the project convention of independent scripts.

"Today" uses **local time** midnight as the cutoff (not UTC), since the user wants to see their local day's work. This intentionally diverges from the existing CLI and hooks which use UTC throughout — the menu bar is a personal dashboard where local time is more intuitive.

**Concurrent read safety:** The app reads without acquiring the filelock. The hooks hold the lock during writes, but since the app only reads and skips malformed JSON lines, a partial read during a mid-write is harmless — the incomplete line is silently ignored and picked up on the next 30s refresh.

## Menu Bar Title

Updated every 30 seconds via `rumps.Timer`.

- Format: `⏱ Xh Ym` (e.g., `⏱ 3h 42m`)
- Under 1 hour: `⏱ 42m`
- No sessions: `⏱ 0m`
- Active sessions' elapsed time is included in the total so the number ticks up live

## Dropdown Menu

```
● cc-time-tracker    1h 23m      <- active session (dot prefix)
  streetkast           45m       <- completed today
  other-project        12m
  ─────────────────────
  Today: 2h 20m                  <- total
  ─────────────────────
  Quit
```

- Active sessions: `● ` prefix, elapsed = now minus start timestamp
- Completed projects: name + today's aggregated duration
- If a project has both completed and active time, it appears once with the dot prefix; the displayed time is completed + active elapsed summed together
- Projects sorted by total time descending
- Separator → total row → separator → Quit
- Project rows are display-only (no click action)
- Menu rebuilds every 30s alongside the title

## Architecture

Single class `CCTimeMenuBar(rumps.App)`:

- `__init__`: set title to `⏱ 0m`, build initial menu, start `rumps.Timer(self.refresh, 30)`
- `refresh(self, _)`: reads both JSONL files, computes today's totals + active elapsed, updates `self.title`, rebuilds menu items
- `@rumps.clicked("Quit")`: calls `rumps.quit_application()`

## Error Handling

- Files don't exist yet: show `⏱ 0m` with empty project list
- Malformed JSONL lines: skip silently (same as existing scripts)
- No crash dialogs or alerts

## Dependencies

- `rumps` (pip install)
- Python 3.x (already required by the existing hooks)
- No other dependencies

## Out of Scope

- LaunchAgent auto-start (user adds to Login Items manually if desired)
- Week/month/all-time views (CLI covers these)
- Settings or preferences UI
- Notifications
