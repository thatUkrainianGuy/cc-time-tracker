# Claude Code Time Tracker

Automatically tracks time spent in Claude Code sessions per project, using the native hooks system.

## How It Works

```
You launch CC in ~/projects/streetkast/
  → SessionStart hook fires
  → Records: {session_id, project: "streetkast", start_time}

You work for 45 minutes, then /exit
  → SessionEnd hook fires
  → Calculates: 45m 12s
  → Writes completed session to ~/.claude/time-tracking/sessions.jsonl

Meanwhile, another CC instance is running in ~/projects/crewshift/
  → Tracked independently (different session_id)
  → Both durations are summed per-project in reports
```

## Installation

```bash
git clone <this-repo> ~/cc-time-tracker  # or copy the files
cd ~/cc-time-tracker
chmod +x install.sh
./install.sh
```

The installer:
1. Copies hook scripts to `~/.claude/hooks/`
2. Installs `cc-time-report` to `~/.local/bin/`
3. Safely merges hooks into `~/.claude/settings.json`
4. Creates `~/.claude/time-tracking/` directory

## Usage

```bash
cc-time-report              # Last 7 days summary + active sessions
cc-time-report today        # Today only
cc-time-report week         # This week (Mon–Sun) with daily breakdown
cc-time-report month        # This month
cc-time-report all          # All time
cc-time-report project X    # Filter by project name (fuzzy)
cc-time-report active       # Show currently running sessions
cc-time-report csv          # Export as CSV (pipe to file)
cc-time-report orphans      # Find sessions that started but never ended
cc-time-report raw          # Raw JSONL dump
```

## Example Output

```
Claude Code Time Tracker
Last 7 days  •  47 total sessions recorded

Active Sessions

  ● streetkast  1h 23m elapsed  (abc123def45…)
    /home/igor/projects/streetkast

Last 7 Days

  Project               Time      Hours  Sessions
  ────────────────  ──────────  ────────  ────────
  streetkast          8h 42m      8.70h        12
  crewshift           3h 15m      3.25h         8
  social-media-saas   2h 30m      2.50h         6
  bs-films            1h 05m      1.08h         4
  ────────────────  ──────────  ────────  ────────
  TOTAL              15h 32m     15.53h        30
```

## Data Format

Sessions are stored in `~/.claude/time-tracking/sessions.jsonl`:

```jsonl
{"event":"start","session_id":"abc123","cwd":"/home/igor/projects/streetkast","project":"streetkast","source":"startup","timestamp":"2026-03-23T10:00:00+00:00","timestamp_unix":1711184400.0}
{"event":"end","session_id":"abc123","cwd":"/home/igor/projects/streetkast","project":"streetkast","reason":"user_exit","timestamp":"2026-03-23T10:45:12+00:00","timestamp_unix":1711187112.0,"duration_seconds":2712.0}
```

## Multiple Instances

Each Claude Code session gets a unique `session_id`. If you run 3 instances:
- Terminal 1: `cd ~/streetkast && claude` → session A starts
- Terminal 2: `cd ~/crewshift && claude` → session B starts  
- Terminal 3: `cd ~/streetkast && claude` → session C starts

All three track independently. The report sums A+C under "streetkast" and B under "crewshift".

## Edge Cases

- **Crashed sessions** (no SessionEnd): Show up in `cc-time-report orphans`. Don't count in totals.
- **`/clear` or context compaction**: SessionStart fires again with `source: "clear"` or `"compact"`. The existing active session is effectively re-started.
- **`/resume`**: SessionStart fires with `source: "resume"`. Tracked as a new timing segment.
- **Timeout safety**: Both hooks have 5s timeout (SessionEnd default is only 1.5s — we override it). Writing JSONL is <1ms.

## Optional: filelock

For maximum safety with many concurrent sessions, install `filelock`:

```bash
pip install filelock
```

Without it, the scripts still work (race conditions are extremely unlikely with JSONL appends on modern filesystems).

## Uninstall

```bash
rm ~/.claude/hooks/cc-time-start.py
rm ~/.claude/hooks/cc-time-end.py
rm ~/.local/bin/cc-time-report
# Manually remove SessionStart/SessionEnd hooks from ~/.claude/settings.json
# Optionally: rm -rf ~/.claude/time-tracking/
```

## License

Do whatever you want with it.
