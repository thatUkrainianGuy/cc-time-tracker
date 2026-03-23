# Claude Code Time Tracker

Automatically tracks time spent in Claude Code sessions per project, using the native hooks system.

## Quick Start

```bash
pip install cc-time-tracker
cc-time-setup
```

That's it. Every Claude Code session is now timed automatically.

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
cc-time-report --version    # Show version
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

`cc-time-setup` registers two hooks in `~/.claude/settings.json`:
- **SessionStart** → `python3 -m cc_time_tracker.start_hook`
- **SessionEnd** → `python3 -m cc_time_tracker.end_hook`

Sessions are stored in `~/.claude/time-tracking/sessions.jsonl` (append-only JSONL).

## Alternative Install (curl)

If you prefer not to use pip, the bash installer still works:

```bash
git clone https://github.com/riabchuk/cc-time-tracker.git ~/cc-time-tracker
cd ~/cc-time-tracker
chmod +x install.sh
./install.sh
```

> **Note:** Don't mix both methods. Use `cc-time-setup` for pip installs and `install.sh` for standalone installs.

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

For maximum safety with many concurrent sessions:

```bash
pip install cc-time-tracker[lock]
```

Without it, the scripts still work (race conditions are extremely unlikely with JSONL appends on modern filesystems).

## Optional: Menu Bar App (macOS)

A standalone menu bar app shows today's total time:

```bash
pip install rumps
python3 cc-time-menubar.py
```

## Uninstall

**pip install:**
```bash
cc-time-uninstall
pip uninstall cc-time-tracker
```

**Standalone install:**
```bash
rm ~/.claude/hooks/cc-time-start.py
rm ~/.claude/hooks/cc-time-end.py
rm ~/.local/bin/cc-time-report
# Manually remove SessionStart/SessionEnd hooks from ~/.claude/settings.json
# Optionally: rm -rf ~/.claude/time-tracking/
```

## License

MIT
