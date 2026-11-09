# cc-time-tracker

- With an editable install (`pip install -e .`), the installed SessionStart/SessionEnd hooks import `cc_time_tracker` straight from `src/`. A broken import silently stops time tracking in every Claude session, including the current one.
- The launchd sync agent does not run `src/`; it runs a snapshot in `~/.claude/time-tracking/agent-lib` (macOS TCC blocks LaunchAgents from reading protected folders like `~/Documents`). Re-run `cc-time-sync-install` after changing sync code.
- SessionStart re-fires with the same `session_id` on `/compact` and `/clear`, so hook changes must stay idempotent per session — breaking that caused the double-counting bug fixed in `8512170`.
- `sync-config.json` can hold several targets; the top-level `endpoint`/`api_key` is the target `portal`, whose cursor stays at the top-level `pushed_events` of `sync-cursor.json` (others under `targets.<name>`). Never move that key, or every past event re-pushes to the portal. A target's `include` filter must run before the request body is built: client project names must not reach a filtered target.
