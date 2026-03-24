# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Code Time Tracker — a set of Python hooks that automatically track time spent in Claude Code sessions per project. Uses Claude Code's native hooks system (`SessionStart`/`SessionEnd`) to record session durations to `~/.claude/time-tracking/sessions.jsonl`.

## Architecture

Installable Python package (`src/cc_time_tracker/`) plus a standalone menubar app:

- **`src/cc_time_tracker/common.py`** — Shared constants (`TRACKING_DIR`, `SESSIONS_FILE`, `ACTIVE_FILE`, `LOCK_FILE`, `SETTINGS_FILE`), utilities (`load_jsonl`, `load_settings`, `read_hook_input`, `acquire_lock`, `ensure_dir`, `extract_project_name`), ANSI codes.
- **`src/cc_time_tracker/start_hook.py`** — SessionStart hook. Writes start record to both `active.jsonl` and `sessions.jsonl`.
- **`src/cc_time_tracker/end_hook.py`** — SessionEnd hook. Finds matching start in `active.jsonl`, calculates duration, appends end record to `sessions.jsonl`, removes from `active.jsonl`.
- **`src/cc_time_tracker/report.py`** — CLI report tool (`cc-time-report`). Subcommands: `today`, `week`, `month`, `all`, `project <name>`, `active`, `csv`, `orphans`, `raw`, `summary` (default).
- **`src/cc_time_tracker/setup_cmd.py`** — Registers hooks in `~/.claude/settings.json`.
- **`src/cc_time_tracker/uninstall_cmd.py`** — Removes hooks from settings.
- **`cc-time-menubar.py`** — macOS menu bar app (requires `pip install rumps`). Shows cumulative project time (today/total) with emoji indicators (🟢/⚪), per-project breakdown, archive/unarchive, CSV/Markdown export. Uses mtime-based caching to avoid re-parsing files every 30s refresh. **Intentionally standalone** — duplicates `_read_jsonl` and `_acquire_lock` rather than importing from `src/` to avoid package dependencies.

## Key Data Paths (at runtime)

- `~/.claude/time-tracking/sessions.jsonl` — append-only log of all start/end events
- `~/.claude/time-tracking/active.jsonl` — currently running sessions (start records only, removed on end)
- `~/.claude/time-tracking/projects.json` — per-project metadata (archived status)
- `~/.claude/time-tracking/.lock` — filelock file for concurrent session safety

## Concurrency Model

Both hooks use optional `filelock` (pip package). Without it, a no-op context manager is used — safe enough for JSONL appends on modern filesystems but not guaranteed under heavy concurrent writes. For read-modify-write operations (e.g. `delete_project_sessions`), the entire read+filter+write cycle must be inside the lock to avoid TOCTOU races.

## Testing

- Run all tests: `python3 -m pytest tests/ -v`
- `tests/test_menubar.py` uses `SourceFileLoader` to import `cc-time-menubar.py` (hyphenated filename can't be a normal import)
- Hook tests use `unittest.mock.patch` to redirect file constants to `tmp_path`; must patch both `cc_time_tracker.common.X` and `cc_time_tracker.<module>.X` for each constant.
- Menubar tests that call `delete_project_sessions` must pass `lock_path=` pointing to the test tmpdir.

## Environment

- System python3 is 3.14 (Homebrew). `pip3` points to 3.9 — always use `python3 -m pip`.
- `--break-system-packages` required for pip installs (PEP 668).

## Important Constraints

- SessionEnd hook must be fast — default CC timeout is 1.5s (overridden to 5s in hooks-config.json).
- Hook scripts receive session context as JSON on stdin, not as CLI args.
- Project name is derived from the last component of `cwd` (`os.path.basename`).
- All timestamps are UTC. The report tool uses `timezone.utc` throughout. **Exception:** menubar uses local time for "today" (`datetime.now()`) — this is intentional for user-facing display but means CLI and menubar disagree on day boundaries for non-UTC users.
- No external dependencies required (filelock is optional).
- `load_jsonl` supports `after_ts` filter for bounded reads — time-scoped commands (`today`, `week`, `month`, `summary`) use this to skip old records during parsing.
- `delete_project_sessions` takes an explicit `lock_path` parameter (defaults to `LOCK_PATH`) — callers in tests must pass their own.
