# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Code Time Tracker — a set of Python hooks that automatically track time spent in Claude Code sessions per project. Uses Claude Code's native hooks system (`SessionStart`/`SessionEnd`) to record session durations to `~/.claude/time-tracking/sessions.jsonl`.

## Architecture

Three Python scripts, an installer, and a hooks config:

- **`cc-time-start.py`** — SessionStart hook. Reads JSON from stdin (`session_id`, `cwd`, `source`), writes a start record to both `active.jsonl` and `sessions.jsonl`.
- **`cc-time-end.py`** — SessionEnd hook. Finds the matching start record in `active.jsonl`, calculates duration, appends an end record to `sessions.jsonl`, removes from `active.jsonl`.
- **`cc-time-report.py`** — CLI report tool (installed as `cc-time-report`). Reads `sessions.jsonl` and `active.jsonl`, supports subcommands: `today`, `week`, `month`, `all`, `project <name>`, `active`, `csv`, `orphans`, `raw`.
- **`install.sh`** — Copies hooks to `~/.claude/hooks/`, installs report CLI to `~/.local/bin/`, merges hook config into `~/.claude/settings.json`.
- **`hooks-config.json`** — Hook definitions for SessionStart/SessionEnd with 5s timeout.
- **`cc-time-menubar.py`** — macOS menu bar app (requires `pip install rumps`). Shows today's total time in the menu bar, click for per-project breakdown with active session indicators. Reads JSONL files directly every 30s.

## Key Data Paths (at runtime)

- `~/.claude/time-tracking/sessions.jsonl` — append-only log of all start/end events
- `~/.claude/time-tracking/active.jsonl` — currently running sessions (start records only, removed on end)
- `~/.claude/time-tracking/.lock` — filelock file for concurrent session safety

## Concurrency Model

Both hooks use optional `filelock` (pip package). Without it, a no-op context manager is used — safe enough for JSONL appends on modern filesystems but not guaranteed under heavy concurrent writes.

## Testing

No test suite exists. To manually test:
```bash
# Simulate a SessionStart
echo '{"session_id":"test123","cwd":"/tmp/test-project","source":"startup"}' | python3 cc-time-start.py

# Simulate a SessionEnd
echo '{"session_id":"test123","cwd":"/tmp/test-project","reason":"user_exit"}' | python3 cc-time-end.py

# Check results
python3 cc-time-report.py
```

## Important Constraints

- SessionEnd hook must be fast — default CC timeout is 1.5s (overridden to 5s in hooks-config.json).
- Hook scripts receive session context as JSON on stdin, not as CLI args.
- Project name is derived from the last component of `cwd` (`os.path.basename`).
- All timestamps are UTC. The report tool uses `timezone.utc` throughout.
- No external dependencies required (filelock is optional).
