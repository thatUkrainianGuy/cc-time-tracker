# Claude Code Time Tracker

Automatically tracks time spent in [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions per project, using the native hooks system.

<img src="preview.png" alt="Menu bar app showing per-project time tracking" width="400">

## Quick Start

```bash
pip install cc-time-tracker
cc-time-setup
```

That's it. Every Claude Code session is now timed automatically.

## Usage

```bash
cc-time-report              # Default: last 7 days summary + active sessions
cc-time-report summary      # Same as above
cc-time-report today        # Today only
cc-time-report week         # This week (Mon–Sun) with daily breakdown
cc-time-report month        # This month
cc-time-report all          # All time
cc-time-report project X    # Filter by project name (fuzzy)
cc-time-report active       # Show currently running sessions
cc-time-report csv          # Export as CSV (pipe to file)
cc-time-report orphans      # Find sessions that started but never ended
cc-time-report raw          # Raw JSONL dump
cc-time-report --version    # Show version
```

## Example Output

```
Claude Code Time Tracker
Last 7 days  •  47 total sessions recorded

Active Sessions

  ● my-app  1h 23m elapsed  (abc123def45…)
    ~/projects/my-app

Last 7 Days

  Project          Time      Hours  Sessions
  ─────────────  ──────────  ─────  ────────
  my-app           8h 42m    8.70h       12
  api-server       3h 15m    3.25h        8
  landing-page     2h 30m    2.50h        6
  cli-tool         1h 05m    1.08h        4
  ─────────────  ──────────  ─────  ────────
  TOTAL           15h 32m   15.53h       30
```

## How It Works

```
You launch Claude Code in ~/projects/my-app/
  → SessionStart hook fires
  → Records: {session_id, project: "my-app", start_time}

You work for 45 minutes, then /exit
  → SessionEnd hook fires
  → Calculates: 45m 12s
  → Writes completed session to ~/.claude/time-tracking/sessions.jsonl

Meanwhile, another instance is running in ~/projects/api-server/
  → Tracked independently (different session_id)
  → Both durations are summed per-project in reports
```

`cc-time-setup` registers two hooks in `~/.claude/settings.json`:
- **SessionStart** → `python3 -m cc_time_tracker.start_hook`
- **SessionEnd** → `python3 -m cc_time_tracker.end_hook`

Sessions are stored in `~/.claude/time-tracking/sessions.jsonl` (append-only JSONL).

### Active time, not wall time

A session left open while you do something else should not bill. `duration_seconds` is **active time**: the SessionEnd hook reads the event timestamps of the session's transcript (`~/.claude/projects/<slug>/<session_id>.jsonl` plus every subagent/workflow transcript under `<session_id>/`), keeps those inside the session window, and sums the gaps between them, each gap capped at 15 minutes (`CC_TIME_IDLE_CAP=<seconds>` to change). Each end record also stores `wall_seconds` (start → end) and `active_source`: `transcript`, or `wall_capped` when no transcript could be read, in which case wall time is billed up to 4 hours.

To recompute older records (backs up `sessions.jsonl`, rewrites in place, and marks the changed sessions for re-sync):

```bash
cc-time-recompute --dry-run      # per-project wall vs active hours, writes nothing
cc-time-recompute [--idle-cap N]
```

### Project name resolution

For each session, the project name is resolved by walking up from the session's `cwd` (stopping at `$HOME`) and using the first match:

1. `.cc-project` file — first non-empty line is used as the project name (override).
2. `.git` (file or directory) — the containing directory's name is used.
3. Otherwise — `basename(cwd)`.

Drop a `.cc-project` file at a repo root to give it a friendlier name than its directory.

## Multiple Instances

Each Claude Code session gets a unique `session_id`. If you run 3 instances:
- Terminal 1: `cd ~/my-app && claude` → session A starts
- Terminal 2: `cd ~/api-server && claude` → session B starts
- Terminal 3: `cd ~/my-app && claude` → session C starts

All three track independently. The report sums A+C under "my-app" and B under "api-server".

## Edge Cases

- **Crashed sessions** (no SessionEnd): Auto-cleaned on the next SessionStart. Each active session records its parent pid; if that process is gone, the session is closed out as a completed record (`reason: "orphan_cleanup"`, window = start → cleanup time, billed as active time) and *does* count in totals. Records without a pid (legacy) fall back to a 24h age threshold. View leftovers with `cc-time-report orphans`.
- **`/clear` or context compaction**: SessionStart fires again with `source: "clear"` or `"compact"`. The existing active session is effectively re-started.
- **`/resume`**: SessionStart fires with `source: "resume"`. Tracked as a new timing segment.
- **Timeout safety**: Both hooks have 5s timeout (SessionEnd default is only 1.5s — we override it). Writing JSONL is <1ms; reading transcript timestamps takes ~0.1s per 15 MB and happens before the lock is taken.

## Optional: Menu Bar App (macOS)

A standalone menu bar app with cumulative per-project tracking:

```bash
pip install rumps
python3 cc-time-menubar.py
```

Or double-click `CC Time Tracker.command` to launch it from Finder.

Features:
- Today / total time per project, with 🟢 active and ⚪ idle indicators
- Archive / unarchive projects to declutter the list
- Merge projects (reassign all sessions from one project name to another)
- Delete a project's sessions
- Export reports as CSV or Markdown

## Optional: Sync to a server

`cc-time-sync` pushes every end event to one or more HTTP endpoints as `POST {"sessions": [{session_id, tracker_name, start_at, end_at, duration_seconds}]}` with `Authorization: Bearer <key>`. The server must be idempotent on `(session_id, end_at)`. Config lives in `~/.claude/time-tracking/sync-config.json`:

```json
{
  "endpoint": "https://portal.example/api/sync", "api_key": "...",
  "targets": [
    {"name": "dashboard", "endpoint": "https://dash.example/api/sync",
     "api_key_file": "~/.config/dash/sync-key",
     "include": ["projectA", "projectB"]}
  ]
}
```

- Top-level `endpoint`/`api_key` is the target `portal` (no filter); a config with only those keys still works as before.
- `api_key_file` (chmod 600, `~` expanded) can replace `api_key`.
- `include` lists exact tracker names; other projects are dropped before the request body is built. Leave it out to send everything.
- Endpoints must be `https://` (plain `http://` only for localhost).
- One cursor per target in `sync-cursor.json`: `portal` keeps the top-level `pushed_events`, the others go under `targets.<name>.pushed_events`.
- A failing target doesn't stop the others; the exit code is non-zero if any target failed.

```bash
cc-time-sync --dry-run                 # what each target would receive
cc-time-sync --target dashboard        # one target only
cc-time-sync --target dashboard --reset  # forget that target's cursor and resend
```

Merging or deleting a project, and `cc-time-recompute`, evict the affected sessions from every target's cursor, so they get re-pushed.

## Uninstall

```bash
cc-time-uninstall
pip uninstall cc-time-tracker
# Optionally: rm -rf ~/.claude/time-tracking/
```

## License

MIT
