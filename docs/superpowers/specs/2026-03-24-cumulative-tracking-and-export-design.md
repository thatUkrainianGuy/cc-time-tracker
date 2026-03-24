# Cumulative Project Tracking & Export Reports

## Problem

The menubar app only shows today's projects, making the tool useful only for daily tracking. It should function as a cumulative project time log with export capabilities.

## Design

### 1. Data Model — `projects.json`

New file: `~/.claude/time-tracking/projects.json`

```json
{
  "cc-time-tracker": { "archived": true },
  "my-app": { "archived": false }
}
```

- Dict keyed by project name, value is a metadata object.
- Only field for now: `archived` (bool).
- Projects absent from the file default to `archived: false`.
- Read by menubar and report tool. Written by menubar (archive/unarchive actions).
- Uses the existing `.lock` file for concurrent safety. All reads and writes of `projects.json` must be inside the lock to avoid reading a partially-written file.
- "Delete project" must also remove the project's entry from `projects.json`.

### 2. Menubar Changes

#### Project list

- Shows all **non-archived** projects with cumulative all-time totals.
- Row format: `🟢 project-name  45m today / 12h 35m total` (active) or `⚪ project-name  0m today / 3h 20m total` (inactive).
- Active projects always shown regardless of archive status.

#### Auto-unarchive

- During `refresh`, if an active session's project is marked `archived: true` in `projects.json`, automatically flip it to `archived: false`.

#### Project submenu (hover)

**Inactive projects:**
- Export as CSV
- Export as Markdown
- Archive
- Delete today's sessions
- Delete project

**Active projects:**
- Export as CSV
- Export as Markdown
(No delete/archive while active)

**Archived projects (inside "Show archived" submenu):**
- Export as CSV
- Export as Markdown
- Unarchive
- Delete project

#### Menu bottom section

- `Today: 1h 25m`
- `Show archived (N)` — submenu listing archived projects with cumulative totals
- `Quit`

### 3. Export Reports

#### Trigger

User clicks "Export as CSV" or "Export as Markdown" in a project's submenu. A native macOS file save dialog opens with suggested filename: `{project}_report_{date}.csv` or `.md`.

#### CSV format

```
Date,Project,Sessions,Duration,Hours
2026-03-20,cc-time-tracker,3,2h 15m,2.25
2026-03-21,cc-time-tracker,5,4h 02m,4.03
...
Total,,12,12h 35m,12.58
```

#### Markdown format

```markdown
# cc-time-tracker — Time Report

Generated: 2026-03-24

| Date | Sessions | Duration | Hours |
|------|----------|----------|-------|
| 2026-03-20 | 3 | 2h 15m | 2.25 |
| 2026-03-21 | 5 | 4h 02m | 4.03 |
| **Total** | **12** | **12h 35m** | **12.58** |
```

Both formats: all-time data for the project, sorted by date ascending, total row at bottom.

### 4. What changes, what doesn't

**Changes:**
- `cc-time-menubar.py`:
  - New `load_all_completed_sessions(path) -> list[dict]` — returns all `end` events with `duration_seconds` from `sessions.jsonl` (no date filter). The existing `load_today_sessions` is kept and used alongside it.
  - `build_project_data` signature changes to accept both today's and all-time completed sessions. New return type: `(name, today_seconds, total_seconds, is_active)` tuples. Existing tests in `tests/test_menubar.py` must be updated to match.
  - New `load_projects_meta` / `save_projects_meta` for `projects.json` read/write.
  - Archive/unarchive logic, export actions, `NSSavePanel` integration.
  - Export save dialog: call `_bring_to_front()` then invoke `NSSavePanel` synchronously on the main thread (same pattern as existing delete confirmations).

**Doesn't change:**
- Hook scripts (`src/cc_time_tracker/start_hook.py`, `src/cc_time_tracker/end_hook.py`) — no modifications needed.
- `sessions.jsonl` / `active.jsonl` format — unchanged.
- `cc-time-report` CLI — unchanged (already has cumulative capabilities).

### 5. Constraints

- Menubar app remains standalone — duplicates utilities rather than importing from `src/`.
- Export uses `rumps` for dialog triggering and `AppKit`'s `NSSavePanel` for native file save dialog.
- All timestamps remain UTC internally; reports show dates in local time for readability.
- For large JSONL files, full reload every 30s is acceptable for now. Can add mtime-based caching later if needed.
