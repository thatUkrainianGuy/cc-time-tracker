# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Code Time Tracker — a set of Python hooks that automatically track time spent in Claude Code sessions per project. Uses Claude Code's native hooks system (`SessionStart`/`SessionEnd`) to record session durations to `~/.claude/time-tracking/sessions.jsonl`.

## Architecture

Installable Python package (`src/cc_time_tracker/`) plus a standalone menubar app:

- **`src/cc_time_tracker/common.py`** — Shared constants (`TRACKING_DIR`, `SESSIONS_FILE`, `ACTIVE_FILE`, `LOCK_FILE`, `SETTINGS_FILE`, `TRACKER_HOOK_TOKENS`, `PROJECT_NAME_MAX_LEN`, `CC_PROJECT_READ_LIMIT`), I/O utilities (`load_jsonl`, `load_settings`, `read_hook_input`, `acquire_lock`, `atomic_write_text`, `ensure_dir`, `harden_file_perms`), name resolution (`extract_project_name`, `clamp_project_name`), sanitization (`strip_control`, `csv_safe`, `md_safe`), type coercion (`coerce_float`, `coerce_int`), and ANSI codes.
- **`src/cc_time_tracker/start_hook.py`** — SessionStart hook. Writes start record to both `active.jsonl` and `sessions.jsonl`.
- **`src/cc_time_tracker/end_hook.py`** — SessionEnd hook. Finds matching start in `active.jsonl`, calculates duration, appends end record to `sessions.jsonl`, removes from `active.jsonl`.
- **`src/cc_time_tracker/report.py`** — CLI report tool (`cc-time-report`). Subcommands: `today`, `week`, `month`, `all`, `project <name>`, `active`, `csv`, `orphans`, `raw`, `summary` (default).
- **`src/cc_time_tracker/setup_cmd.py`** — Registers hooks in `~/.claude/settings.json`.
- **`src/cc_time_tracker/uninstall_cmd.py`** — Removes hooks from settings.
- **`cc-time-menubar.py`** — macOS menu bar app (requires `pip install rumps`). Shows cumulative project time (today/total) with emoji indicators (🟢/⚪), per-project breakdown, archive/unarchive, CSV/Markdown export. Uses mtime-based caching to avoid re-parsing files every 30s refresh. **Intentionally standalone** — duplicates `_read_jsonl`, `_acquire_lock`, `_coerce_float`, `_strip_control`, `_csv_safe`, `_md_safe` rather than importing from `src/` to avoid package dependencies. Keep these copies in sync with `common.py` when sanitization rules change.

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

- Requires Python 3.10+. Use `python3 -m pip` for installs.
- On systems with PEP 668, `--break-system-packages` may be required for pip installs.

## Important Constraints

- SessionEnd hook must be fast — default CC timeout is 1.5s (overridden to 5s by `setup_cmd.merge_hooks` when registering). `HOOK_LOCK_TIMEOUT_SECONDS = 2` in start/end hooks leaves slack under that 5s ceiling.
- Hook scripts receive session context as JSON on stdin, not as CLI args.
- **Project name resolution** (`extract_project_name`): walk up from `cwd`, stopping at `$HOME` (exclusive). First match wins: (1) `.cc-project` — first non-empty line, read up to `CC_PROJECT_READ_LIMIT` bytes; (2) `.git` (file or dir) — directory's basename. Falls back to `basename(cwd)`. Result is always run through `clamp_project_name` (strips control chars, caps at `PROJECT_NAME_MAX_LEN = 64`).
- All timestamps are UTC. The report tool uses `timezone.utc` throughout. **Exception:** menubar uses local time for "today" (`datetime.now()`) — this is intentional for user-facing display but means CLI and menubar disagree on day boundaries for non-UTC users.
- No external dependencies required (filelock is optional).
- `load_jsonl` supports `after_ts` filter for bounded reads — time-scoped commands (`today`, `week`, `month`, `summary`) use this to skip old records during parsing.
- `delete_project_sessions` takes an explicit `lock_path` parameter (defaults to `LOCK_PATH`) — callers in tests must pass their own.
- **Untrusted inputs:** project names (from `.cc-project` or directory basename) and JSONL records are attacker-controllable from any cloned repo. Sanitize through `strip_control` / `csv_safe` / `md_safe` before printing or exporting; coerce numeric fields via `coerce_float` / `coerce_int`. `load_jsonl` already drops non-dict records and tolerates non-numeric `timestamp_unix` when filtering by `after_ts`.
- **CSV/Markdown exports:** use `csv.writer` + `csv_safe()` for CSV (escapes formula leads `= + - @ \t \r`); use `md_safe()` for Markdown table cells (escapes `|`, strips newlines and control chars). Never f-string interpolate user-supplied fields into either format.
- **File permissions:** tracking dir is `0o700`, data files `0o600`. New writes should go through `atomic_write_text` (sets 0o600 on temp before rename) or call `harden_file_perms` after creation.
- **Hook detection** (`is_tracker_hook_group`): matches the exact module tokens in `TRACKER_HOOK_TOKENS` (`-m cc_time_tracker.start_hook` / `.end_hook`) — not the substring `cc_time_tracker`. Don't loosen this when adding new hooks.
- **Setup command quoting:** `setup_cmd.merge_hooks` runs `shlex.quote(sys.executable)` before embedding the interpreter path in the hook command — paths with spaces (e.g. `/Applications/My Apps/python3`) work. Preserve when editing the hook-registration template.
- **Hooks must never raise:** start/end hooks swallow FS errors and only `SystemExit(1)` on malformed stdin JSON. When reading prior records (e.g. `active.jsonl` orphan cleanup), coerce field types defensively so a poisoned record can't crash the hook.
