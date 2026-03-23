# PyPI Packaging Design — cc-time-tracker

## Goal

Make cc-time-tracker installable via `pip install cc-time-tracker` so any Claude Code user can set it up in two commands.

## Package Structure

```
cc-time-tracker/
├── pyproject.toml
├── src/
│   └── cc_time_tracker/
│       ├── __init__.py         # __version__ string
│       ├── start_hook.py       # SessionStart hook
│       ├── end_hook.py         # SessionEnd hook
│       ├── report.py           # CLI report tool
│       ├── setup_cmd.py        # cc-time-setup command
│       ├── uninstall_cmd.py    # cc-time-uninstall command
│       └── common.py           # Shared constants and helpers
├── install.sh                  # Curl fallback (kept as-is)
├── tests/
├── README.md
└── LICENSE
```

Uses the **src layout** (standard Python packaging practice).

## Module Breakdown

### common.py

Shared constants and utilities currently duplicated across start/end scripts:

- `TRACKING_DIR = Path.home() / ".claude" / "time-tracking"`
- `SESSIONS_FILE`, `ACTIVE_FILE`, `LOCK_FILE`
- `ensure_dir()` — creates `TRACKING_DIR` if it doesn't exist
- `acquire_lock()` — returns `FileLock` if available, no-op context manager otherwise
- `extract_project_name(cwd)` — `os.path.basename(os.path.normpath(cwd))`
- `load_jsonl(path)` — reads a JSONL file, returns list of dicts (shared by hooks and report)

### start_hook.py

Refactored from `cc-time-start.py`. Imports constants/helpers from `common.py`. Each hook module has an `if __name__ == "__main__": main()` block. No `__main__.py` is needed because we invoke specific submodules, not the package itself.

### end_hook.py

Refactored from `cc-time-end.py`. Imports from `common.py`. Same execution model.

### report.py

Refactored from `cc-time-report.py`. Exposed as `cc-time-report` console script.

### setup_cmd.py

New. Performs first-time setup:

1. Creates `~/.claude/time-tracking/` directory.
2. Detects the correct Python interpreter via `sys.executable` and writes the **absolute path** into hook commands. This ensures hooks work regardless of how the package was installed (pipx, venv, system pip). Example: `/opt/homebrew/bin/python3.14 -m cc_time_tracker.start_hook`.
3. Merges hook entries into `~/.claude/settings.json`:
   - SessionStart: `{sys.executable} -m cc_time_tracker.start_hook` (timeout: 5)
   - SessionEnd: `{sys.executable} -m cc_time_tracker.end_hook` (timeout: 5)
4. Uses the same safe merge logic from current `install.sh` — checks for existing hooks, appends without overwriting.
5. Detects old-style hook files (`~/.claude/hooks/cc-time-start.py`, `~/.local/bin/cc-time-report`) and warns if found, offering to clean them up.
6. Prints success message with usage hints.

Idempotent — running it twice doesn't duplicate hooks.

### uninstall_cmd.py

New. Reverses setup:

1. Removes cc-time-tracker hook entries from `~/.claude/settings.json`.
2. Prompts whether to delete `~/.claude/time-tracking/` (default: no, since it contains user data).
3. Prints a reminder: `Run 'pip uninstall cc-time-tracker' to remove the package.`

## Hook Registration

Hooks call `{sys.executable} -m cc_time_tracker.start_hook` and `{sys.executable} -m cc_time_tracker.end_hook` directly from the installed package. **No files are copied to `~/.claude/hooks/`.** The `{sys.executable}` is resolved to an absolute path at setup time (e.g., `/opt/homebrew/bin/python3.14`) to ensure the correct interpreter is used regardless of `$PATH` at hook execution time.

This means `pip install --upgrade cc-time-tracker` updates hook logic without re-running setup.

Settings.json entries (example with resolved interpreter):

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "/opt/homebrew/bin/python3.14 -m cc_time_tracker.start_hook",
        "timeout": 5
      }]
    }],
    "SessionEnd": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "/opt/homebrew/bin/python3.14 -m cc_time_tracker.end_hook",
        "timeout": 5
      }]
    }]
  }
}
```

## pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cc-time-tracker"
version = "0.1.0"
description = "Automatic time tracking for Claude Code sessions"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [{ name = "Igor Riabchuk" }]
keywords = ["claude-code", "time-tracking", "productivity"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "Topic :: Software Development :: Libraries :: Python Modules",
]

[project.scripts]
cc-time-report = "cc_time_tracker.report:main"
cc-time-setup = "cc_time_tracker.setup_cmd:main"
cc-time-uninstall = "cc_time_tracker.uninstall_cmd:main"

[project.optional-dependencies]
lock = ["filelock"]

[project.urls]
Homepage = "https://github.com/riabchuk/cc-time-tracker"
Issues = "https://github.com/riabchuk/cc-time-tracker/issues"
```

## User Experience

### Install

```bash
pip install cc-time-tracker
cc-time-setup
```

Output:
```
Claude Code Time Tracker — Setup
✓ Created ~/.claude/time-tracking/
✓ Registered hooks in ~/.claude/settings.json

Done! Time tracking is now active for all Claude Code sessions.
Run `cc-time-report` to see your stats.
```

### Upgrade

```bash
pip install --upgrade cc-time-tracker
# No re-setup needed — hooks call the package directly
```

### Uninstall

```bash
cc-time-uninstall
pip uninstall cc-time-tracker
```

### Curl Fallback

`install.sh` remains as a **standalone alternative** for users who prefer not to use pip. It copies scripts directly to `~/.claude/hooks/` (a different mechanism from the pip package). These two install methods are **mutually exclusive** — the README should make this clear. `cc-time-setup` detects and warns if old-style hook files exist.

## Menubar App

`cc-time-menubar.py` is **not** included in the pip package (requires `rumps`, macOS-only). Mentioned in README as an optional extra.

## README Structure

1. One-sentence description
2. Quick start (2-line pip install)
3. Usage (`cc-time-report` subcommands)
4. Example output
5. Alternative install (curl one-liner)
6. How it works (brief architecture)
7. Uninstall
8. License (MIT)

## Testing

- Existing menubar tests continue to work.
- **Required before first PyPI release:**
  - `common.py` — unit tests for `acquire_lock()`, `extract_project_name()`, `load_jsonl()`, `ensure_dir()`
  - `start_hook.py` / `end_hook.py` — unit tests with mocked stdin and filesystem
  - `setup_cmd.py` / `uninstall_cmd.py` — unit tests that mock settings.json read/write
- `report.py` — existing manual testing is acceptable initially; add tests incrementally.
- `cc-time-report --version` should be supported for debugging.

## Migration

For existing users (i.e., you): after installing via pip and running `cc-time-setup`, remove the old hook files from `~/.claude/hooks/` and `~/.local/bin/cc-time-report`. The setup command could detect and warn about these.
