# Menu Bar App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS menu bar app that shows today's Claude Code session time and per-project breakdown.

**Architecture:** Single-file Python script using `rumps`. Reads JSONL data files directly every 30s via `rumps.Timer`. One class `CCTimeMenuBar(rumps.App)` handles everything.

**Tech Stack:** Python 3, rumps

**Spec:** `docs/superpowers/specs/2026-03-23-menubar-app-design.md`

---

### File Structure

- **Create:** `cc-time-menubar.py` — the menu bar app (single file, all logic inlined)
- **Create:** `tests/test_menubar.py` — unit tests for data parsing and formatting logic
- **Modify:** `CLAUDE.md` — add menu bar app to project overview

---

### Task 1: Set up test file and test data helpers

**Files:**
- Create: `tests/test_menubar.py`

- [ ] **Step 1: Create test file with helpers for generating JSONL test data**

```python
"""Tests for cc-time-menubar.py data parsing and formatting logic."""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


def make_start_record(session_id, project, cwd, ts_unix):
    return json.dumps({
        "event": "start",
        "session_id": session_id,
        "cwd": cwd,
        "project": project,
        "source": "startup",
        "timestamp": datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat(),
        "timestamp_unix": ts_unix,
    })


def make_end_record(session_id, project, cwd, ts_unix, duration_seconds):
    return json.dumps({
        "event": "end",
        "session_id": session_id,
        "cwd": cwd,
        "project": project,
        "reason": "user_exit",
        "timestamp": datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat(),
        "timestamp_unix": ts_unix,
        "duration_seconds": duration_seconds,
    })
```

- [ ] **Step 2: Verify the test file is valid Python**

Run: `python3 -c "import ast; ast.parse(open('tests/test_menubar.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/test_menubar.py
git commit -m "test: add test helpers for menubar data parsing"
```

---

### Task 2: Implement and test `format_duration`

**Files:**
- Modify: `tests/test_menubar.py`
- Create: `cc-time-menubar.py`

- [ ] **Step 1: Write failing tests for format_duration**

Append to `tests/test_menubar.py`:

```python
# Import will be added once the module exists
from importlib.machinery import SourceFileLoader
import importlib

def load_menubar():
    """Load cc-time-menubar.py as a module (it has a hyphenated name)."""
    loader = SourceFileLoader("cc_time_menubar", "cc-time-menubar.py")
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("cc_time_menubar", loader))
    loader.exec_module(mod)
    return mod


class TestFormatDuration:
    def setup_method(self):
        self.mod = load_menubar()

    def test_zero(self):
        assert self.mod.format_duration(0) == "0m"

    def test_seconds_rounds_to_zero_minutes(self):
        assert self.mod.format_duration(30) == "0m"

    def test_minutes_only(self):
        assert self.mod.format_duration(2520) == "42m"

    def test_hours_and_minutes(self):
        assert self.mod.format_duration(13320) == "3h 42m"

    def test_exact_hour(self):
        assert self.mod.format_duration(3600) == "1h 0m"
```

- [ ] **Step 2: Create cc-time-menubar.py with minimal format_duration**

```python
#!/usr/bin/env python3
"""
macOS menu bar app for Claude Code time tracking.
Shows today's total session time in the menu bar.
Click to see per-project breakdown with active session indicators.

Usage:
    python3 cc-time-menubar.py

Requires: pip install rumps
"""


def format_duration(seconds: float) -> str:
    """Format seconds into menu-bar-friendly duration string.

    Unlike cc-time-report.py, this skips seconds entirely to avoid
    visual noise in the menu bar. Always shows at least '0m'.
    """
    total_minutes = int(seconds // 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m"
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_menubar.py::TestFormatDuration -v`
Expected: All 5 tests PASS

- [ ] **Step 4: Commit**

```bash
git add cc-time-menubar.py tests/test_menubar.py
git commit -m "feat: add format_duration for menu bar display"
```

---

### Task 3: Implement and test `load_today_sessions`

**Files:**
- Modify: `tests/test_menubar.py`
- Modify: `cc-time-menubar.py`

- [ ] **Step 1: Write failing tests for load_today_sessions**

Append to `tests/test_menubar.py`:

```python
class TestLoadTodaySessions:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.sessions_file = Path(self.tmpdir) / "sessions.jsonl"

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def _today_start_unix(self):
        """Midnight local time today, as unix timestamp."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return today.timestamp()

    def test_empty_file(self):
        self.sessions_file.write_text("")
        result = self.mod.load_today_sessions(self.sessions_file)
        assert result == []

    def test_no_file(self):
        nonexistent = Path(self.tmpdir) / "nope.jsonl"
        result = self.mod.load_today_sessions(nonexistent)
        assert result == []

    def test_filters_to_today_end_events(self):
        now = self._now_unix()
        yesterday = now - 86400 * 2
        lines = [
            make_start_record("s1", "proj", "/tmp/proj", now - 3600),
            make_end_record("s1", "proj", "/tmp/proj", now, 3600),
            make_end_record("s2", "old", "/tmp/old", yesterday, 100),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_today_sessions(self.sessions_file)
        assert len(result) == 1
        assert result[0]["project"] == "proj"
        assert result[0]["event"] == "end"

    def test_skips_malformed_lines(self):
        now = self._now_unix()
        lines = [
            "not json at all",
            make_end_record("s1", "proj", "/tmp/proj", now, 100),
            "{broken json",
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_today_sessions(self.sessions_file)
        assert len(result) == 1
```

- [ ] **Step 2: Implement load_today_sessions in cc-time-menubar.py**

Add to `cc-time-menubar.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path


def get_today_start_unix() -> float:
    """Get midnight local time today as a unix timestamp."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today.timestamp()


def load_today_sessions(sessions_file: Path) -> list[dict]:
    """Load today's completed sessions (end events only) from JSONL file.

    Uses local time for 'today' cutoff. Skips malformed lines silently.
    """
    if not sessions_file.exists():
        return []

    today_start = get_today_start_unix()
    sessions = []

    with open(sessions_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                record.get("event") == "end"
                and record.get("duration_seconds") is not None
                and record.get("timestamp_unix", 0) >= today_start
            ):
                sessions.append(record)

    return sessions
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_menubar.py::TestLoadTodaySessions -v`
Expected: All 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add cc-time-menubar.py tests/test_menubar.py
git commit -m "feat: add load_today_sessions with local-time filtering"
```

---

### Task 4: Implement and test `load_active_sessions`

**Files:**
- Modify: `tests/test_menubar.py`
- Modify: `cc-time-menubar.py`

- [ ] **Step 1: Write failing tests for load_active_sessions**

Append to `tests/test_menubar.py`:

```python
class TestLoadActiveSessions:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.active_file = Path(self.tmpdir) / "active.jsonl"

    def test_empty_file(self):
        self.active_file.write_text("")
        result = self.mod.load_active_sessions(self.active_file)
        assert result == []

    def test_no_file(self):
        nonexistent = Path(self.tmpdir) / "nope.jsonl"
        result = self.mod.load_active_sessions(nonexistent)
        assert result == []

    def test_loads_all_records(self):
        now = datetime.now(timezone.utc).timestamp()
        lines = [
            make_start_record("s1", "proj-a", "/tmp/proj-a", now - 3600),
            make_start_record("s2", "proj-b", "/tmp/proj-b", now - 600),
        ]
        self.active_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_active_sessions(self.active_file)
        assert len(result) == 2
        assert result[0]["project"] == "proj-a"
        assert result[1]["project"] == "proj-b"
```

- [ ] **Step 2: Implement load_active_sessions in cc-time-menubar.py**

Add to `cc-time-menubar.py`:

```python
def load_active_sessions(active_file: Path) -> list[dict]:
    """Load currently active sessions from JSONL file.

    All records in this file are start events for running sessions.
    Skips malformed lines silently.
    """
    if not active_file.exists():
        return []

    sessions = []
    with open(active_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sessions.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return sessions
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_menubar.py::TestLoadActiveSessions -v`
Expected: All 3 tests PASS

- [ ] **Step 4: Commit**

```bash
git add cc-time-menubar.py tests/test_menubar.py
git commit -m "feat: add load_active_sessions"
```

---

### Task 5: Implement and test `build_project_data`

**Files:**
- Modify: `tests/test_menubar.py`
- Modify: `cc-time-menubar.py`

- [ ] **Step 1: Write failing tests for build_project_data**

Append to `tests/test_menubar.py`:

```python
class TestBuildProjectData:
    def setup_method(self):
        self.mod = load_menubar()

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def test_empty_inputs(self):
        projects, total = self.mod.build_project_data([], [])
        assert projects == []
        assert total == 0

    def test_completed_sessions_only(self):
        sessions = [
            {"project": "proj-a", "duration_seconds": 3600},
            {"project": "proj-a", "duration_seconds": 1800},
            {"project": "proj-b", "duration_seconds": 600},
        ]
        projects, total = self.mod.build_project_data(sessions, [])
        assert total == 6000
        # Sorted descending by time
        assert projects[0] == ("proj-a", 5400, True, False)  # (name, seconds, has_completed, is_active)
        assert projects[1] == ("proj-b", 600, True, False)

    def test_active_sessions_add_elapsed(self):
        now = self._now_unix()
        sessions = []
        active = [
            {"project": "proj-a", "timestamp_unix": now - 600},  # 10 min ago
        ]
        projects, total = self.mod.build_project_data(sessions, active)
        assert len(projects) == 1
        name, secs, has_completed, is_active = projects[0]
        assert name == "proj-a"
        assert is_active is True
        assert 595 <= secs <= 610  # ~600s with timing tolerance

    def test_multiple_active_sessions_same_project(self):
        now = self._now_unix()
        sessions = []
        active = [
            {"project": "proj-a", "timestamp_unix": now - 600},
            {"project": "proj-a", "timestamp_unix": now - 300},
        ]
        projects, total = self.mod.build_project_data(sessions, active)
        assert len(projects) == 1
        name, secs, _, is_active = projects[0]
        assert name == "proj-a"
        assert is_active is True
        assert 895 <= secs <= 910  # ~600 + ~300

    def test_combined_completed_and_active(self):
        now = self._now_unix()
        sessions = [
            {"project": "proj-a", "duration_seconds": 3600},
        ]
        active = [
            {"project": "proj-a", "timestamp_unix": now - 600},
        ]
        projects, total = self.mod.build_project_data(sessions, active)
        assert len(projects) == 1
        name, secs, _, is_active = projects[0]
        assert name == "proj-a"
        assert is_active is True
        assert 4195 <= secs <= 4210  # 3600 + ~600
```

- [ ] **Step 2: Implement build_project_data in cc-time-menubar.py**

Add to `cc-time-menubar.py`:

```python
def build_project_data(
    completed_sessions: list[dict],
    active_sessions: list[dict],
) -> tuple[list[tuple[str, float, bool, bool]], float]:
    """Aggregate today's data into per-project rows.

    Returns:
        (projects, total_seconds) where projects is a list of
        (name, total_seconds, has_completed, is_active) sorted by time desc.
    """
    now = datetime.now(timezone.utc).timestamp()

    # Aggregate completed time per project
    project_time: dict[str, float] = {}
    project_has_completed: dict[str, bool] = {}
    project_is_active: dict[str, bool] = {}

    for s in completed_sessions:
        proj = s.get("project", "unknown")
        dur = s.get("duration_seconds", 0) or 0
        project_time[proj] = project_time.get(proj, 0) + dur
        project_has_completed[proj] = True

    # Add active session elapsed time
    for s in active_sessions:
        proj = s.get("project", "unknown")
        start_ts = s.get("timestamp_unix", now)
        elapsed = max(0, now - start_ts)
        project_time[proj] = project_time.get(proj, 0) + elapsed
        project_is_active[proj] = True

    total = sum(project_time.values())

    # Build sorted list
    projects = sorted(
        [
            (name, secs, project_has_completed.get(name, False), project_is_active.get(name, False))
            for name, secs in project_time.items()
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    return projects, total
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_menubar.py::TestBuildProjectData -v`
Expected: All 5 tests PASS

- [ ] **Step 4: Commit**

```bash
git add cc-time-menubar.py tests/test_menubar.py
git commit -m "feat: add build_project_data aggregation logic"
```

---

### Task 6: Implement the rumps App class

**Files:**
- Modify: `cc-time-menubar.py`

- [ ] **Step 1: Add the CCTimeMenuBar class and main block**

Add to the end of `cc-time-menubar.py`:

```python
# Constants (used by main() only, but defined at module level for clarity)
TRACKING_DIR = Path.home() / ".claude" / "time-tracking"
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
ACTIVE_FILE = TRACKING_DIR / "active.jsonl"

REFRESH_INTERVAL = 30  # seconds


def main():
    """Entry point — imports rumps and runs the menu bar app.

    rumps is imported here (not at module level) so that the pure functions
    above can be imported and tested without rumps installed.
    """
    try:
        import rumps
    except ImportError:
        print("ERROR: rumps is required. Install with: pip install rumps")
        print("Then run: python3 cc-time-menubar.py")
        raise SystemExit(1)

    class CCTimeMenuBar(rumps.App):
        def __init__(self):
            super().__init__("⏱ 0m", quit_button=None)
            self.timer = rumps.Timer(self.refresh, REFRESH_INTERVAL)
            self.timer.start()
            self.refresh(None)  # initial load

        def refresh(self, _):
            """Reload data from JSONL files and update the menu bar."""
            completed = load_today_sessions(SESSIONS_FILE)
            active = load_active_sessions(ACTIVE_FILE)
            projects, total = build_project_data(completed, active)

            # Update title
            self.title = f"⏱ {format_duration(total)}"

            # Rebuild menu
            self.menu.clear()

            for name, secs, _has_completed, is_active in projects:
                prefix = "● " if is_active else "  "
                label = f"{prefix}{name}    {format_duration(secs)}"
                item = rumps.MenuItem(label, callback=None)
                self.menu.add(item)

            if projects:
                self.menu.add(rumps.separator)

            total_item = rumps.MenuItem(f"  Today: {format_duration(total)}", callback=None)
            self.menu.add(total_item)
            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("Quit", callback=self.quit_app))

        def quit_app(self, _):
            rumps.quit_application()

    CCTimeMenuBar().run()


if __name__ == "__main__":
    main()
```

**Note:** The `rumps` import and `CCTimeMenuBar` class are inside `main()` so that the pure data functions (`format_duration`, `load_today_sessions`, etc.) can be imported and tested without `rumps` installed.

- [ ] **Step 2: Manually test the app launches**

Run: `python3 cc-time-menubar.py`
Expected: A `⏱` icon appears in the macOS menu bar. Click it to see the dropdown. Press Ctrl+C or click Quit to exit.

- [ ] **Step 3: Commit**

```bash
git add cc-time-menubar.py
git commit -m "feat: add CCTimeMenuBar rumps app with live-updating menu"
```

---

### Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add menu bar app to CLAUDE.md project overview**

In the Architecture section, after the `hooks-config.json` bullet, add:

```
- **`cc-time-menubar.py`** — macOS menu bar app (requires `pip install rumps`). Shows today's total time in the menu bar, click for per-project breakdown with active session indicators. Reads JSONL files directly every 30s.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add menu bar app to CLAUDE.md"
```

---

### Task 8: End-to-end manual verification

- [ ] **Step 1: Run all unit tests**

Run: `python3 -m pytest tests/test_menubar.py -v`
Expected: All tests PASS

- [ ] **Step 2: Simulate session data and verify menu bar**

Create a small Python script to generate test data in a temp directory, then launch the menu bar app pointing at it:

```python
# test_e2e.py — run once, then delete
import json, tempfile, os
from datetime import datetime, timezone
from pathlib import Path

tmpdir = tempfile.mkdtemp(prefix="cc-time-test-")
now = datetime.now(timezone.utc).timestamp()

sessions = Path(tmpdir) / "sessions.jsonl"
active = Path(tmpdir) / "active.jsonl"

sessions.write_text(json.dumps({
    "event": "end", "session_id": "test1", "cwd": "/tmp/my-project",
    "project": "my-project", "reason": "user_exit",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "timestamp_unix": now, "duration_seconds": 3600,
}) + "\n")

active.write_text(json.dumps({
    "event": "start", "session_id": "test-active", "cwd": "/tmp/active-proj",
    "project": "active-proj", "source": "startup",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "timestamp_unix": now - 3600,
}) + "\n")

print(f"Test data written to {tmpdir}")
print(f"To test, temporarily edit TRACKING_DIR in cc-time-menubar.py to point to: {tmpdir}")
```

Run: Edit `TRACKING_DIR` in `cc-time-menubar.py` to the temp path, run `python3 cc-time-menubar.py`, verify the menu bar shows `⏱ 2h 0m` with `● active-proj` and `my-project` in the dropdown. Then revert the `TRACKING_DIR` change.

- [ ] **Step 3: Clean up**

Revert any `TRACKING_DIR` changes. Delete the temp directory and `test_e2e.py`.
