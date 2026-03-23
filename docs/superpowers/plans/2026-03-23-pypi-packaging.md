# PyPI Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert cc-time-tracker from loose scripts + bash installer into a pip-installable PyPI package.

**Architecture:** src-layout Python package with `common.py` extracting shared code, hook modules callable via `python3 -m`, and three console_scripts entry points (`cc-time-report`, `cc-time-setup`, `cc-time-uninstall`). Hooks are registered in `~/.claude/settings.json` using the absolute path to `sys.executable`.

**Tech Stack:** Python 3.10+, hatchling build backend, optional filelock dependency.

**Spec:** `docs/superpowers/specs/2026-03-23-pypi-packaging-design.md`

---

### Task 1: Create package scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/cc_time_tracker/__init__.py`
- Create: `LICENSE`

- [ ] **Step 1: Create pyproject.toml**

Uses hatch dynamic versioning to read `__version__` from `__init__.py` — single source of truth.

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cc-time-tracker"
dynamic = ["version"]
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

[tool.hatch.version]
path = "src/cc_time_tracker/__init__.py"
```

- [ ] **Step 2: Create `src/cc_time_tracker/__init__.py`**

```python
"""Claude Code Time Tracker — automatic session time tracking."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create LICENSE and .gitignore**

MIT license with Igor Riabchuk, 2026. Also create/update `.gitignore` to include:
```
dist/
*.egg-info/
__pycache__/
.eggs/
build/
```

- [ ] **Step 4: Verify the build works**

Run: `pip install -e . && python -c "import cc_time_tracker; print(cc_time_tracker.__version__)"`
Expected: `0.1.0`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/cc_time_tracker/__init__.py LICENSE
git commit -m "feat: add pyproject.toml and package scaffolding"
```

---

### Task 2: Extract common.py

**Files:**
- Create: `src/cc_time_tracker/common.py`
- Create: `tests/test_common.py`

- [ ] **Step 1: Write tests for common.py**

```python
"""Tests for cc_time_tracker.common"""

import json
import tempfile
from pathlib import Path

from cc_time_tracker.common import (
    extract_project_name,
    load_jsonl,
    ensure_dir,
    acquire_lock,
)


def test_extract_project_name_simple():
    assert extract_project_name("/home/user/projects/myapp") == "myapp"


def test_extract_project_name_trailing_slash():
    assert extract_project_name("/home/user/projects/myapp/") == "myapp"


def test_extract_project_name_root():
    assert extract_project_name("/") == ""


def test_load_jsonl_empty_file(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text("")
    assert load_jsonl(f) == []


def test_load_jsonl_with_records(tmp_path):
    f = tmp_path / "test.jsonl"
    records = [{"a": 1}, {"b": 2}]
    f.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    assert load_jsonl(f) == records


def test_load_jsonl_skips_bad_lines(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text('{"a": 1}\ngarbage\n{"b": 2}\n')
    assert load_jsonl(f) == [{"a": 1}, {"b": 2}]


def test_load_jsonl_missing_file(tmp_path):
    f = tmp_path / "nonexistent.jsonl"
    assert load_jsonl(f) == []


def test_ensure_dir(tmp_path):
    d = tmp_path / "sub" / "dir"
    ensure_dir(d)
    assert d.is_dir()


def test_acquire_lock_returns_context_manager():
    lock = acquire_lock(Path(tempfile.gettempdir()) / "test.lock")
    with lock:
        pass  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cc_time_tracker.common'`

- [ ] **Step 3: Implement common.py**

```python
"""Shared constants and utilities for cc-time-tracker."""

import json
import os
from pathlib import Path


TRACKING_DIR = Path.home() / ".claude" / "time-tracking"
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
ACTIVE_FILE = TRACKING_DIR / "active.jsonl"
LOCK_FILE = TRACKING_DIR / ".lock"


def ensure_dir(path: Path | None = None) -> None:
    """Create the tracking directory if it doesn't exist."""
    (path or TRACKING_DIR).mkdir(parents=True, exist_ok=True)


def acquire_lock(lock_path: Path | None = None):
    """Return a file lock (or no-op if filelock not installed)."""
    try:
        from filelock import FileLock
        return FileLock(str(lock_path or LOCK_FILE), timeout=5)
    except ImportError:
        class _NoLock:
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return _NoLock()


def extract_project_name(cwd: str) -> str:
    """Derive project name from the last directory component."""
    return os.path.basename(os.path.normpath(cwd))


def load_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, returning a list of parsed dicts. Skips bad lines."""
    if not path.exists():
        return []
    records = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_common.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/cc_time_tracker/common.py tests/test_common.py
git commit -m "feat: extract common.py with shared constants and helpers"
```

---

### Task 3: Refactor start_hook.py

**Files:**
- Create: `src/cc_time_tracker/start_hook.py`
- Create: `tests/test_start_hook.py`

- [ ] **Step 1: Write tests for start_hook**

```python
"""Tests for cc_time_tracker.start_hook"""

import json
from io import StringIO
from unittest.mock import patch

from cc_time_tracker.common import ACTIVE_FILE, SESSIONS_FILE
from cc_time_tracker.start_hook import main


def test_start_hook_writes_records(tmp_path):
    """Start hook should write to both sessions.jsonl and active.jsonl."""
    sessions = tmp_path / "sessions.jsonl"
    active = tmp_path / "active.jsonl"

    input_data = json.dumps({
        "session_id": "test-123",
        "cwd": "/home/user/myproject",
        "source": "startup",
    })

    with (
        patch("cc_time_tracker.common.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.common.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.common.ACTIVE_FILE", active),
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.start_hook.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.start_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.start_hook.ACTIVE_FILE", active),
        patch("cc_time_tracker.start_hook.LOCK_FILE", tmp_path / ".lock"),
        patch("sys.stdin", StringIO(input_data)),
    ):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0

    # Verify sessions.jsonl
    session_records = [json.loads(l) for l in sessions.read_text().strip().split("\n")]
    assert len(session_records) == 1
    assert session_records[0]["event"] == "start"
    assert session_records[0]["session_id"] == "test-123"
    assert session_records[0]["project"] == "myproject"

    # Verify active.jsonl
    active_records = [json.loads(l) for l in active.read_text().strip().split("\n")]
    assert len(active_records) == 1
    assert active_records[0]["session_id"] == "test-123"


def test_start_hook_bad_stdin():
    """Start hook should exit 1 on bad JSON input."""
    with patch("sys.stdin", StringIO("not json")):
        try:
            main()
        except SystemExit as e:
            assert e.code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_start_hook.py -v`
Expected: FAIL

- [ ] **Step 3: Implement start_hook.py**

Refactor from `cc-time-start.py`, importing from `common.py`:

```python
"""SessionStart hook — records when a Claude Code session begins."""

import json
import os
import sys
from datetime import datetime, timezone

from cc_time_tracker.common import (
    TRACKING_DIR, SESSIONS_FILE, ACTIVE_FILE, LOCK_FILE,
    ensure_dir, acquire_lock, extract_project_name,
)


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())
    source = input_data.get("source", "startup")

    now = datetime.now(timezone.utc)

    record = {
        "event": "start",
        "session_id": session_id,
        "cwd": cwd,
        "project": extract_project_name(cwd),
        "source": source,
        "timestamp": now.isoformat(),
        "timestamp_unix": now.timestamp(),
    }

    ensure_dir()

    with acquire_lock():
        with open(ACTIVE_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_start_hook.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/cc_time_tracker/start_hook.py tests/test_start_hook.py
git commit -m "feat: refactor start hook into package module"
```

---

### Task 4: Refactor end_hook.py

**Files:**
- Create: `src/cc_time_tracker/end_hook.py`
- Create: `tests/test_end_hook.py`

- [ ] **Step 1: Write tests for end_hook**

```python
"""Tests for cc_time_tracker.end_hook"""

import json
import time
from io import StringIO
from unittest.mock import patch

from cc_time_tracker.end_hook import main


def test_end_hook_calculates_duration(tmp_path):
    """End hook should find start record, calculate duration, write end record."""
    sessions = tmp_path / "sessions.jsonl"
    active = tmp_path / "active.jsonl"

    start_ts = time.time() - 300  # 5 minutes ago
    start_record = json.dumps({
        "event": "start",
        "session_id": "test-123",
        "cwd": "/home/user/myproject",
        "project": "myproject",
        "source": "startup",
        "timestamp": "2026-03-23T10:00:00+00:00",
        "timestamp_unix": start_ts,
    })
    active.write_text(start_record + "\n")

    input_data = json.dumps({
        "session_id": "test-123",
        "cwd": "/home/user/myproject",
        "reason": "user_exit",
    })

    with (
        patch("cc_time_tracker.common.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.common.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.common.ACTIVE_FILE", active),
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.end_hook.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.end_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.end_hook.ACTIVE_FILE", active),
        patch("cc_time_tracker.end_hook.LOCK_FILE", tmp_path / ".lock"),
        patch("sys.stdin", StringIO(input_data)),
    ):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0

    # Verify end record written
    records = [json.loads(l) for l in sessions.read_text().strip().split("\n")]
    assert len(records) == 1
    assert records[0]["event"] == "end"
    assert records[0]["duration_seconds"] is not None
    assert records[0]["duration_seconds"] > 200  # ~5 min

    # Verify removed from active
    assert active.read_text().strip() == ""


def test_end_hook_no_matching_start(tmp_path):
    """End hook should still write record even without a matching start."""
    sessions = tmp_path / "sessions.jsonl"
    active = tmp_path / "active.jsonl"
    active.write_text("")

    input_data = json.dumps({
        "session_id": "orphan-456",
        "cwd": "/tmp/test",
        "reason": "user_exit",
    })

    with (
        patch("cc_time_tracker.common.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.common.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.common.ACTIVE_FILE", active),
        patch("cc_time_tracker.common.LOCK_FILE", tmp_path / ".lock"),
        patch("cc_time_tracker.end_hook.TRACKING_DIR", tmp_path),
        patch("cc_time_tracker.end_hook.SESSIONS_FILE", sessions),
        patch("cc_time_tracker.end_hook.ACTIVE_FILE", active),
        patch("cc_time_tracker.end_hook.LOCK_FILE", tmp_path / ".lock"),
        patch("sys.stdin", StringIO(input_data)),
    ):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0

    records = [json.loads(l) for l in sessions.read_text().strip().split("\n")]
    assert records[0]["duration_seconds"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_end_hook.py -v`
Expected: FAIL

- [ ] **Step 3: Implement end_hook.py**

Refactor from `cc-time-end.py`, importing from `common.py`:

```python
"""SessionEnd hook — records when a Claude Code session ends."""

import json
import os
import sys
from datetime import datetime, timezone

from cc_time_tracker.common import (
    TRACKING_DIR, SESSIONS_FILE, ACTIVE_FILE, LOCK_FILE,
    acquire_lock, extract_project_name, load_jsonl,
)


def find_start_record(session_id: str) -> dict | None:
    """Find the most recent start record for this session_id in active.jsonl."""
    for record in load_jsonl(ACTIVE_FILE):
        if record.get("session_id") == session_id and record.get("event") == "start":
            return record
    return None


def remove_from_active(session_id: str) -> None:
    """Remove a session from the active tracker. Preserves malformed lines."""
    if not ACTIVE_FILE.exists():
        return
    remaining = []
    with open(ACTIVE_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if record.get("session_id") != session_id:
                    remaining.append(line)
            except json.JSONDecodeError:
                remaining.append(line)  # preserve malformed lines
    with open(ACTIVE_FILE, "w") as f:
        for line in remaining:
            f.write(line + "\n")


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(1)

    session_id = input_data.get("session_id", "unknown")
    cwd = input_data.get("cwd", os.getcwd())
    reason = input_data.get("reason", "unknown")

    now = datetime.now(timezone.utc)

    with acquire_lock():
        start_record = find_start_record(session_id)

        if start_record:
            start_ts = start_record.get("timestamp_unix", 0)
            duration_seconds = now.timestamp() - start_ts
        else:
            duration_seconds = None

        record = {
            "event": "end",
            "session_id": session_id,
            "cwd": cwd,
            "project": extract_project_name(cwd),
            "reason": reason,
            "timestamp": now.isoformat(),
            "timestamp_unix": now.timestamp(),
            "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
        }

        with open(SESSIONS_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")

        remove_from_active(session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_end_hook.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/cc_time_tracker/end_hook.py tests/test_end_hook.py
git commit -m "feat: refactor end hook into package module"
```

---

### Task 5: Refactor report.py

**Files:**
- Create: `src/cc_time_tracker/report.py`

- [ ] **Step 1: Copy cc-time-report.py to src/cc_time_tracker/report.py and apply these changes**

**Exact changes (line-by-line):**

1. **Replace imports block** (lines 1-24 of original). Remove the standalone constants. New top of file:

```python
#!/usr/bin/env python3
"""cc-time-report — CLI viewer for Claude Code session time tracking."""

import json
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from cc_time_tracker import __version__
from cc_time_tracker.common import SESSIONS_FILE, ACTIVE_FILE, load_jsonl
```

2. **Replace `load_sessions()` and `load_active()` functions** (original lines 30-61) with thin wrappers:

```python
def load_sessions() -> list[dict]:
    return load_jsonl(SESSIONS_FILE)

def load_active() -> list[dict]:
    return load_jsonl(ACTIVE_FILE)
```

3. **Add `--version` support** in `main()`, right after `args = sys.argv[1:]`:

```python
if "--version" in args:
    print(f"cc-time-report {__version__}")
    sys.exit(0)
```

4. **Keep everything else unchanged:** `get_completed_sessions`, `format_duration`, `format_duration_hours`, `filter_by_time`, `get_start_of_today`, `get_start_of_week`, `get_start_of_month`, `aggregate_by_project`, `aggregate_by_day`, all ANSI constants, all `print_*` functions, `export_csv`, and the command dispatch in `main()`. Remove `import os` (no longer needed — `extract_project_name` was never used in report).

- [ ] **Step 2: Verify report works**

Run: `pip install -e . && cc-time-report --version`
Expected: `cc-time-report 0.1.0`

- [ ] **Step 3: Commit**

```bash
git add src/cc_time_tracker/report.py
git commit -m "feat: refactor report CLI into package module"
```

---

### Task 6: Implement setup_cmd.py

**Files:**
- Create: `src/cc_time_tracker/setup_cmd.py`
- Create: `tests/test_setup_cmd.py`

- [ ] **Step 1: Write tests for setup_cmd**

```python
"""Tests for cc_time_tracker.setup_cmd"""

import json
from pathlib import Path
from unittest.mock import patch

from cc_time_tracker.setup_cmd import merge_hooks, is_already_installed


def test_merge_hooks_fresh_settings(tmp_path):
    """Should create hooks section in empty settings."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")

    merge_hooks(settings_file, "/usr/bin/python3")

    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings
    assert "SessionStart" in settings["hooks"]
    assert "SessionEnd" in settings["hooks"]
    assert "/usr/bin/python3 -m cc_time_tracker.start_hook" in settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]


def test_merge_hooks_preserves_existing(tmp_path):
    """Should not overwrite existing hooks."""
    settings_file = tmp_path / "settings.json"
    existing = {
        "hooks": {
            "PreToolUse": [{"matcher": "Write", "hooks": [{"type": "prompt", "prompt": "check"}]}]
        },
        "other_setting": True,
    }
    settings_file.write_text(json.dumps(existing))

    merge_hooks(settings_file, "/usr/bin/python3")

    settings = json.loads(settings_file.read_text())
    assert "PreToolUse" in settings["hooks"]
    assert settings["other_setting"] is True
    assert "SessionStart" in settings["hooks"]


def test_merge_hooks_idempotent(tmp_path):
    """Running merge twice should not duplicate hooks."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")

    merge_hooks(settings_file, "/usr/bin/python3")
    merge_hooks(settings_file, "/usr/bin/python3")

    settings = json.loads(settings_file.read_text())
    assert len(settings["hooks"]["SessionStart"]) == 1


def test_is_already_installed_true(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings = {"hooks": {"SessionStart": [{"hooks": [{"command": "/usr/bin/python3 -m cc_time_tracker.start_hook"}]}]}}
    settings_file.write_text(json.dumps(settings))
    assert is_already_installed(settings_file) is True


def test_is_already_installed_false(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    assert is_already_installed(settings_file) is False


def test_merge_hooks_creates_settings_file(tmp_path):
    """Should create settings.json if it doesn't exist."""
    settings_file = tmp_path / "settings.json"
    merge_hooks(settings_file, "/usr/bin/python3")
    assert settings_file.exists()
    settings = json.loads(settings_file.read_text())
    assert "SessionStart" in settings["hooks"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_setup_cmd.py -v`
Expected: FAIL

- [ ] **Step 3: Implement setup_cmd.py**

```python
"""cc-time-setup — register time-tracking hooks in Claude Code settings."""

import json
import sys
from pathlib import Path

from cc_time_tracker.common import TRACKING_DIR, ensure_dir

SETTINGS_FILE = Path.home() / ".claude" / "settings.json"
OLD_HOOK_FILES = [
    Path.home() / ".claude" / "hooks" / "cc-time-start.py",
    Path.home() / ".claude" / "hooks" / "cc-time-end.py",
]
OLD_BIN_FILE = Path.home() / ".local" / "bin" / "cc-time-report"

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def is_already_installed(settings_file: Path) -> bool:
    """Check if cc-time-tracker hooks are already in settings."""
    if not settings_file.exists():
        return False
    try:
        settings = json.loads(settings_file.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    for group in settings.get("hooks", {}).get("SessionStart", []):
        for hook in group.get("hooks", []):
            if "cc_time_tracker" in hook.get("command", ""):
                return True
    return False


def merge_hooks(settings_file: Path, python_path: str) -> None:
    """Merge time-tracking hooks into settings.json."""
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            settings = {}
    else:
        settings = {}

    if is_already_installed(settings_file):
        print(f"  {YELLOW}⚠ Hooks already registered — skipping{RESET}")
        return

    new_hooks = {
        "SessionStart": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{python_path} -m cc_time_tracker.start_hook",
                "timeout": 5,
            }],
        }],
        "SessionEnd": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{python_path} -m cc_time_tracker.end_hook",
                "timeout": 5,
            }],
        }],
    }

    if "hooks" not in settings:
        settings["hooks"] = {}

    for event, hook_configs in new_hooks.items():
        if event not in settings["hooks"]:
            settings["hooks"][event] = []
        settings["hooks"][event].extend(hook_configs)

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  {GREEN}✓ Registered hooks in {settings_file}{RESET}")


def warn_old_install() -> None:
    """Detect and warn about old-style hook files."""
    old_found = [p for p in OLD_HOOK_FILES + [OLD_BIN_FILE] if p.exists()]
    if old_found:
        print(f"\n  {YELLOW}⚠ Old install detected. You can remove these:{RESET}")
        for p in old_found:
            print(f"    rm {p}")
        print()


def main():
    print(f"\n{BOLD}Claude Code Time Tracker — Setup{RESET}\n")

    ensure_dir()
    print(f"  {GREEN}✓ Created {TRACKING_DIR}/{RESET}")

    python_path = sys.executable
    merge_hooks(SETTINGS_FILE, python_path)

    warn_old_install()

    print(f"\n  {GREEN}{BOLD}Done!{RESET} Time tracking is now active for all Claude Code sessions.")
    print(f"  Run {BOLD}cc-time-report{RESET} to see your stats.\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_setup_cmd.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/cc_time_tracker/setup_cmd.py tests/test_setup_cmd.py
git commit -m "feat: implement cc-time-setup command"
```

---

### Task 7: Implement uninstall_cmd.py

**Files:**
- Create: `src/cc_time_tracker/uninstall_cmd.py`
- Create: `tests/test_uninstall_cmd.py`

- [ ] **Step 1: Write tests for uninstall_cmd**

```python
"""Tests for cc_time_tracker.uninstall_cmd"""

import json
from pathlib import Path

from cc_time_tracker.uninstall_cmd import remove_hooks


def test_remove_hooks_cleans_settings(tmp_path):
    """Should remove cc_time_tracker hooks from settings."""
    settings_file = tmp_path / "settings.json"
    settings = {
        "hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": "/usr/bin/python3 -m cc_time_tracker.start_hook"}]},
            ],
            "SessionEnd": [
                {"matcher": "", "hooks": [{"type": "command", "command": "/usr/bin/python3 -m cc_time_tracker.end_hook"}]},
            ],
            "PreToolUse": [
                {"matcher": "Write", "hooks": [{"type": "prompt", "prompt": "check"}]},
            ],
        },
        "other": True,
    }
    settings_file.write_text(json.dumps(settings))

    remove_hooks(settings_file)

    result = json.loads(settings_file.read_text())
    assert result["other"] is True
    assert "PreToolUse" in result["hooks"]
    assert result["hooks"]["SessionStart"] == []
    assert result["hooks"]["SessionEnd"] == []


def test_remove_hooks_no_settings_file(tmp_path):
    """Should handle missing settings.json gracefully."""
    settings_file = tmp_path / "settings.json"
    remove_hooks(settings_file)  # should not raise


def test_remove_hooks_preserves_other_session_hooks(tmp_path):
    """Should only remove cc_time_tracker hooks, not other SessionStart hooks."""
    settings_file = tmp_path / "settings.json"
    settings = {
        "hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": "some-other-hook"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": "/usr/bin/python3 -m cc_time_tracker.start_hook"}]},
            ],
        },
    }
    settings_file.write_text(json.dumps(settings))

    remove_hooks(settings_file)

    result = json.loads(settings_file.read_text())
    assert len(result["hooks"]["SessionStart"]) == 1
    assert "some-other-hook" in result["hooks"]["SessionStart"][0]["hooks"][0]["command"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_uninstall_cmd.py -v`
Expected: FAIL

- [ ] **Step 3: Implement uninstall_cmd.py**

```python
"""cc-time-uninstall — remove time-tracking hooks from Claude Code settings."""

import json
import sys
from pathlib import Path

from cc_time_tracker.common import TRACKING_DIR

SETTINGS_FILE = Path.home() / ".claude" / "settings.json"

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"


def remove_hooks(settings_file: Path) -> None:
    """Remove cc_time_tracker hook entries from settings.json."""
    if not settings_file.exists():
        print(f"  {DIM}No settings.json found — nothing to remove.{RESET}")
        return

    try:
        settings = json.loads(settings_file.read_text())
    except json.JSONDecodeError:
        print(f"  {RED}Could not parse {settings_file}{RESET}")
        return

    hooks = settings.get("hooks", {})
    changed = False

    for event in ("SessionStart", "SessionEnd"):
        if event in hooks:
            original_len = len(hooks[event])
            hooks[event] = [
                group for group in hooks[event]
                if not any("cc_time_tracker" in h.get("command", "") for h in group.get("hooks", []))
            ]
            if len(hooks[event]) != original_len:
                changed = True

    if changed:
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        print(f"  {GREEN}✓ Removed hooks from {settings_file}{RESET}")
    else:
        print(f"  {DIM}No cc-time-tracker hooks found in settings.json{RESET}")


def main():
    print(f"\n{BOLD}Claude Code Time Tracker — Uninstall{RESET}\n")

    remove_hooks(SETTINGS_FILE)

    if TRACKING_DIR.exists():
        answer = input(f"\n  Remove time tracking data ({TRACKING_DIR})? [y/N]: ").strip().lower()
        if answer == "y":
            import shutil
            shutil.rmtree(TRACKING_DIR)
            print(f"  {GREEN}✓ Removed {TRACKING_DIR}{RESET}")
        else:
            print(f"  {DIM}Kept {TRACKING_DIR}{RESET}")

    print(f"\n  {DIM}Run: pip uninstall cc-time-tracker{RESET}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_uninstall_cmd.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/cc_time_tracker/uninstall_cmd.py tests/test_uninstall_cmd.py
git commit -m "feat: implement cc-time-uninstall command"
```

---

### Task 8: Update README and final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite README.md**

Structure:
1. Title + one-sentence description
2. Quick start (`pip install` + `cc-time-setup`)
3. Usage (all subcommands — reuse existing content)
4. Example output (reuse existing)
5. Alternative install (`curl | bash` with note about mutual exclusivity)
6. How it works (brief architecture)
7. Optional: menubar app mention
8. Uninstall (both paths)
9. License (MIT)

Keep all existing usage/example content. Replace the install section with pip-first approach.

- [ ] **Step 2: Full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 3: Test the full install flow**

```bash
pip install -e .
cc-time-setup
cc-time-report --version
echo '{"session_id":"pip-test","cwd":"/tmp/test","source":"startup"}' | python3 -m cc_time_tracker.start_hook
echo '{"session_id":"pip-test","cwd":"/tmp/test","reason":"user_exit"}' | python3 -m cc_time_tracker.end_hook
cc-time-report
```

- [ ] **Step 4: Test build produces valid sdist/wheel**

Run: `pip install build && python3 -m build`
Expected: `dist/cc_time_tracker-0.1.0.tar.gz` and `dist/cc_time_tracker-0.1.0-py3-none-any.whl` created

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for PyPI distribution"
```

---

### Task 9: Clean up old files

**Files:**
- Remove: `cc-time-start.py` (replaced by `src/cc_time_tracker/start_hook.py`)
- Remove: `cc-time-end.py` (replaced by `src/cc_time_tracker/end_hook.py`)
- Remove: `cc-time-report.py` (replaced by `src/cc_time_tracker/report.py`)
- Remove: `hooks-config.json` (hooks now registered by `cc-time-setup`)
- Keep: `install.sh` (curl fallback)
- Keep: `cc-time-menubar.py` (standalone, not in package)

- [ ] **Step 1: Remove old scripts**

```bash
git rm cc-time-start.py cc-time-end.py cc-time-report.py hooks-config.json
```

- [ ] **Step 2: Update install.sh**

The curl fallback needs to copy from the new `src/` layout and use the new filenames. Key changes:

1. Add a banner at top: "Prefer: pip install cc-time-tracker && cc-time-setup"
2. Update copy sources from root to `src/cc_time_tracker/`:
   - `cp "$SCRIPT_DIR/src/cc_time_tracker/start_hook.py" "$HOOKS_DIR/cc-time-start.py"` (keep destination name for settings.json compatibility)
   - `cp "$SCRIPT_DIR/src/cc_time_tracker/end_hook.py" "$HOOKS_DIR/cc-time-end.py"`
   - `cp "$SCRIPT_DIR/src/cc_time_tracker/report.py" "$BIN_DIR/cc-time-report"`
3. The hooks in settings.json still use `python3 ~/.claude/hooks/cc-time-start.py` (file-based, not module-based) since curl users don't have the package installed
4. Add a note to the inline Python merge script: check for both old-style (`cc-time-start`) AND new-style (`cc_time_tracker`) hooks to avoid duplicates with pip install

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove old standalone scripts, update install.sh"
```
