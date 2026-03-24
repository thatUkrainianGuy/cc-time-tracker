# Cumulative Tracking & Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the menubar app from today-only to cumulative project tracking with archive management and export reports.

**Architecture:** All changes are in `cc-time-menubar.py` (standalone). New pure functions for projects.json I/O, cumulative data loading, report generation. Existing `build_project_data` signature changes to return `(name, today_seconds, total_seconds, is_active)`. Menu UI rebuilt in `refresh()` to show today/total, archive submenu, and export options.

**Tech Stack:** Python 3, rumps, AppKit (NSSavePanel), json, pathlib

**Spec:** `docs/superpowers/specs/2026-03-24-cumulative-tracking-and-export-design.md`

---

### Task 1: Add `load_all_completed_sessions` and update `build_project_data`

**Files:**
- Modify: `cc-time-menubar.py:117-172` (add function, change signature)
- Test: `tests/test_menubar.py`

- [ ] **Step 1: Write failing test for `load_all_completed_sessions`**

In `tests/test_menubar.py`, add a new test class after `TestLoadTodaySessions`:

```python
class TestLoadAllCompletedSessions:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.sessions_file = Path(self.tmpdir) / "sessions.jsonl"

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def test_returns_all_end_events(self):
        now = self._now_unix()
        old = now - 86400 * 30  # 30 days ago
        lines = [
            make_start_record("s1", "proj", "/tmp/proj", old),
            make_end_record("s1", "proj", "/tmp/proj", old + 3600, 3600),
            make_start_record("s2", "proj", "/tmp/proj", now - 3600),
            make_end_record("s2", "proj", "/tmp/proj", now, 1800),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_all_completed_sessions(self.sessions_file)
        assert len(result) == 2
        assert all(r["event"] == "end" for r in result)

    def test_excludes_start_events(self):
        now = self._now_unix()
        lines = [
            make_start_record("s1", "proj", "/tmp/proj", now - 3600),
            make_end_record("s1", "proj", "/tmp/proj", now, 3600),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        result = self.mod.load_all_completed_sessions(self.sessions_file)
        assert len(result) == 1
        assert result[0]["event"] == "end"

    def test_empty_file(self):
        self.sessions_file.write_text("")
        assert self.mod.load_all_completed_sessions(self.sessions_file) == []

    def test_no_file(self):
        nonexistent = Path(self.tmpdir) / "nope.jsonl"
        assert self.mod.load_all_completed_sessions(nonexistent) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_menubar.py::TestLoadAllCompletedSessions -v`
Expected: FAIL with `AttributeError: module has no attribute 'load_all_completed_sessions'`

- [ ] **Step 3: Implement `load_all_completed_sessions`**

In `cc-time-menubar.py`, add after `load_today_sessions` (after line 125):

```python
def load_all_completed_sessions(sessions_file: Path) -> list[dict]:
    """Load all completed sessions (end events only) from JSONL file, no date filter."""
    return [
        r for r in _read_jsonl(sessions_file)
        if r.get("event") == "end"
        and r.get("duration_seconds") is not None
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_menubar.py::TestLoadAllCompletedSessions -v`
Expected: PASS

- [ ] **Step 5: Write failing test for new `build_project_data` signature**

Update `TestBuildProjectData` in `tests/test_menubar.py`. The new signature is `build_project_data(today_sessions, all_sessions, active_sessions)` returning `(name, today_seconds, total_seconds, is_active)` tuples. Replace the entire class. Note: the old tests for `has_completed` and `test_multiple_active_sessions_same_project` are intentionally dropped — `has_completed` no longer exists in the return type, and the multi-active-session scenario is covered by `test_combined_completed_and_active`:

```python
class TestBuildProjectData:
    def setup_method(self):
        self.mod = load_menubar()

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def test_empty_inputs(self):
        projects, today_total = self.mod.build_project_data([], [], [])
        assert projects == []
        assert today_total == 0

    def test_today_and_all_time(self):
        today = [
            {"project": "proj-a", "duration_seconds": 1800},
        ]
        all_time = [
            {"project": "proj-a", "duration_seconds": 1800},
            {"project": "proj-a", "duration_seconds": 3600},
        ]
        projects, today_total = self.mod.build_project_data(today, all_time, [])
        assert len(projects) == 1
        name, today_secs, total_secs, is_active = projects[0]
        assert name == "proj-a"
        assert today_secs == 1800
        assert total_secs == 5400
        assert is_active is False
        assert today_total == 1800

    def test_all_time_only_no_today(self):
        """Project with past sessions but none today still appears."""
        all_time = [
            {"project": "proj-a", "duration_seconds": 7200},
        ]
        projects, today_total = self.mod.build_project_data([], all_time, [])
        assert len(projects) == 1
        name, today_secs, total_secs, is_active = projects[0]
        assert name == "proj-a"
        assert today_secs == 0
        assert total_secs == 7200
        assert today_total == 0

    def test_active_sessions_add_elapsed(self):
        now = self._now_unix()
        active = [
            {"project": "proj-a", "timestamp_unix": now - 600},
        ]
        projects, today_total = self.mod.build_project_data([], [], active)
        assert len(projects) == 1
        name, today_secs, total_secs, is_active = projects[0]
        assert name == "proj-a"
        assert is_active is True
        assert 595 <= today_secs <= 610
        assert 595 <= total_secs <= 610

    def test_combined_completed_and_active(self):
        now = self._now_unix()
        today = [{"project": "proj-a", "duration_seconds": 3600}]
        all_time = [
            {"project": "proj-a", "duration_seconds": 3600},
            {"project": "proj-a", "duration_seconds": 7200},
        ]
        active = [{"project": "proj-a", "timestamp_unix": now - 600}]
        projects, today_total = self.mod.build_project_data(today, all_time, active)
        assert len(projects) == 1
        name, today_secs, total_secs, is_active = projects[0]
        assert is_active is True
        # today: 3600 completed + ~600 active
        assert 4195 <= today_secs <= 4210
        # all-time: 3600 + 7200 completed + ~600 active
        assert 11395 <= total_secs <= 11410

    def test_sorted_by_total_descending(self):
        all_time = [
            {"project": "small", "duration_seconds": 100},
            {"project": "big", "duration_seconds": 9000},
        ]
        projects, _ = self.mod.build_project_data([], all_time, [])
        assert projects[0][0] == "big"
        assert projects[1][0] == "small"

    def test_multiple_projects(self):
        today = [
            {"project": "proj-a", "duration_seconds": 1800},
            {"project": "proj-b", "duration_seconds": 600},
        ]
        all_time = [
            {"project": "proj-a", "duration_seconds": 1800},
            {"project": "proj-a", "duration_seconds": 3600},
            {"project": "proj-b", "duration_seconds": 600},
            {"project": "proj-b", "duration_seconds": 1200},
        ]
        projects, today_total = self.mod.build_project_data(today, all_time, [])
        assert len(projects) == 2
        assert today_total == 2400
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python3 -m pytest tests/test_menubar.py::TestBuildProjectData -v`
Expected: FAIL (signature mismatch — `build_project_data` takes 2 args, not 3)

- [ ] **Step 7: Implement new `build_project_data`**

Replace the existing `build_project_data` function in `cc-time-menubar.py` (lines 132-172):

```python
def build_project_data(
    today_sessions: list[dict],
    all_sessions: list[dict],
    active_sessions: list[dict],
) -> tuple[list[tuple[str, float, float, bool]], float]:
    """Aggregate per-project rows with today and all-time totals.

    Returns:
        (projects, today_total) where projects is a list of
        (name, today_seconds, total_seconds, is_active) sorted by total desc.
    """
    now = datetime.now(timezone.utc).timestamp()

    today_time: dict[str, float] = {}
    total_time: dict[str, float] = {}
    project_is_active: dict[str, bool] = {}

    for s in today_sessions:
        proj = s.get("project", "unknown")
        dur = s.get("duration_seconds", 0) or 0
        today_time[proj] = today_time.get(proj, 0) + dur

    for s in all_sessions:
        proj = s.get("project", "unknown")
        dur = s.get("duration_seconds", 0) or 0
        total_time[proj] = total_time.get(proj, 0) + dur

    for s in active_sessions:
        proj = s.get("project", "unknown")
        start_ts = s.get("timestamp_unix", now)
        elapsed = max(0, now - start_ts)
        today_time[proj] = today_time.get(proj, 0) + elapsed
        total_time[proj] = total_time.get(proj, 0) + elapsed
        project_is_active[proj] = True

    all_projects = set(today_time) | set(total_time)
    today_total = sum(today_time.values())

    projects = sorted(
        [
            (
                name,
                today_time.get(name, 0),
                total_time.get(name, 0),
                project_is_active.get(name, False),
            )
            for name in all_projects
        ],
        key=lambda x: x[2],  # sort by total_seconds
        reverse=True,
    )

    return projects, today_total
```

- [ ] **Step 8: Run all tests to verify everything passes**

Run: `python3 -m pytest tests/test_menubar.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add cc-time-menubar.py tests/test_menubar.py
git commit -m "feat: add load_all_completed_sessions and update build_project_data for cumulative tracking"
```

---

### Task 2: Add `projects.json` I/O (load/save/archive)

**Files:**
- Modify: `cc-time-menubar.py` (add new functions after constants, around line 20)
- Test: `tests/test_menubar.py`

- [ ] **Step 1: Write failing tests for projects.json I/O**

Add constant and new test class to `tests/test_menubar.py`:

```python
class TestProjectsMeta:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.projects_file = Path(self.tmpdir) / "projects.json"
        self.lock_path = Path(self.tmpdir) / ".lock"

    def test_load_missing_file(self):
        nonexistent = Path(self.tmpdir) / "nope.json"
        result = self.mod.load_projects_meta(nonexistent, self.lock_path)
        assert result == {}

    def test_load_existing(self):
        self.projects_file.write_text('{"proj-a": {"archived": true}}')
        result = self.mod.load_projects_meta(self.projects_file, self.lock_path)
        assert result == {"proj-a": {"archived": True}}

    def test_save_and_load_roundtrip(self):
        data = {"proj-a": {"archived": True}, "proj-b": {"archived": False}}
        self.mod.save_projects_meta(self.projects_file, data, self.lock_path)
        result = self.mod.load_projects_meta(self.projects_file, self.lock_path)
        assert result == data

    def test_is_archived_true(self):
        meta = {"proj-a": {"archived": True}}
        assert self.mod.is_archived(meta, "proj-a") is True

    def test_is_archived_false(self):
        meta = {"proj-a": {"archived": False}}
        assert self.mod.is_archived(meta, "proj-a") is False

    def test_is_archived_missing_project(self):
        assert self.mod.is_archived({}, "proj-a") is False

    def test_set_archived(self):
        meta = {}
        self.mod.set_archived(meta, "proj-a", True)
        assert meta == {"proj-a": {"archived": True}}

    def test_set_archived_preserves_other_fields(self):
        meta = {"proj-a": {"archived": False, "custom": "data"}}
        self.mod.set_archived(meta, "proj-a", True)
        assert meta["proj-a"]["archived"] is True
        assert meta["proj-a"]["custom"] == "data"

    def test_remove_project_meta(self):
        meta = {"proj-a": {"archived": True}, "proj-b": {"archived": False}}
        self.mod.remove_project_meta(meta, "proj-a")
        assert "proj-a" not in meta
        assert "proj-b" in meta

    def test_remove_project_meta_missing_key(self):
        meta = {"proj-a": {"archived": True}}
        self.mod.remove_project_meta(meta, "nonexistent")
        assert meta == {"proj-a": {"archived": True}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_menubar.py::TestProjectsMeta -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement projects.json functions**

Add a new constant in `cc-time-menubar.py` after line 19 (`ACTIVE_FILE`):

```python
PROJECTS_META_FILE = TRACKING_DIR / "projects.json"
```

Add these functions after `_acquire_lock` (after line 65):

```python
def load_projects_meta(projects_file: Path, lock_path: Path) -> dict:
    """Load projects.json metadata. Returns {} if missing or invalid."""
    with _acquire_lock(lock_path):
        try:
            return json.loads(projects_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}


def save_projects_meta(projects_file: Path, meta: dict, lock_path: Path) -> None:
    """Write projects.json atomically under lock."""
    with _acquire_lock(lock_path):
        projects_file.write_text(json.dumps(meta, indent=2) + "\n")


def is_archived(meta: dict, project: str) -> bool:
    """Check if a project is archived. Defaults to False if absent."""
    return meta.get(project, {}).get("archived", False)


def set_archived(meta: dict, project: str, archived: bool) -> None:
    """Set archived status for a project in the meta dict (in-place)."""
    if project not in meta:
        meta[project] = {}
    meta[project]["archived"] = archived


def remove_project_meta(meta: dict, project: str) -> None:
    """Remove a project's metadata entry (in-place). No-op if absent."""
    meta.pop(project, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_menubar.py::TestProjectsMeta -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add cc-time-menubar.py tests/test_menubar.py
git commit -m "feat: add projects.json I/O for archive metadata"
```

---

### Task 3: Add report generation functions (CSV and Markdown)

**Files:**
- Modify: `cc-time-menubar.py` (add functions after projects.json functions)
- Test: `tests/test_menubar.py`

- [ ] **Step 1: Write failing tests for report generation**

Add to `tests/test_menubar.py`:

```python
class TestGenerateReport:
    def setup_method(self):
        self.mod = load_menubar()

    def _make_sessions(self):
        """Create test sessions spanning multiple days."""
        return [
            {"project": "proj-a", "event": "end", "duration_seconds": 3600,
             "timestamp_unix": 1742515200.0,  # 2025-03-21 00:00:00 UTC
             "session_id": "s1", "reason": "user_exit"},
            {"project": "proj-a", "event": "end", "duration_seconds": 1800,
             "timestamp_unix": 1742515200.0 + 7200,  # same day
             "session_id": "s2", "reason": "user_exit"},
            {"project": "proj-a", "event": "end", "duration_seconds": 5400,
             "timestamp_unix": 1742601600.0,  # 2025-03-22 00:00:00 UTC
             "session_id": "s3", "reason": "user_exit"},
        ]

    def test_generate_csv_report(self):
        sessions = self._make_sessions()
        csv = self.mod.generate_csv_report("proj-a", sessions)
        lines = csv.strip().split("\n")
        assert lines[0] == "Date,Project,Sessions,Duration,Hours"
        assert len(lines) == 4  # header + 2 days + total
        assert lines[-1].startswith("Total,")

    def test_generate_md_report(self):
        sessions = self._make_sessions()
        md = self.mod.generate_md_report("proj-a", sessions)
        assert "# proj-a" in md
        assert "| Date |" in md
        assert "**Total**" in md

    def test_generate_csv_empty(self):
        csv = self.mod.generate_csv_report("proj-a", [])
        lines = csv.strip().split("\n")
        assert lines[0] == "Date,Project,Sessions,Duration,Hours"
        assert lines[1].startswith("Total,")

    def test_generate_md_empty(self):
        md = self.mod.generate_md_report("proj-a", [])
        assert "**Total**" in md
        assert "0.00" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_menubar.py::TestGenerateReport -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement report generation**

Add to `cc-time-menubar.py` after the projects meta functions:

```python
def _aggregate_sessions_by_date(project: str, sessions: list[dict]) -> list[tuple[str, int, float]]:
    """Aggregate sessions for a project by date (local time).

    Returns sorted list of (date_str, session_count, total_seconds).
    """
    days: dict[str, list[float]] = {}
    for s in sessions:
        if s.get("project") != project:
            continue
        ts = s.get("timestamp_unix", 0)
        if not ts:
            continue
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        days.setdefault(day, []).append(s.get("duration_seconds", 0) or 0)

    return sorted(
        [(day, len(durations), sum(durations)) for day, durations in days.items()]
    )


def generate_csv_report(project: str, sessions: list[dict]) -> str:
    """Generate a CSV report for a project."""
    rows = _aggregate_sessions_by_date(project, sessions)
    lines = ["Date,Project,Sessions,Duration,Hours"]
    total_sessions = 0
    total_seconds = 0.0
    for day, count, secs in rows:
        total_sessions += count
        total_seconds += secs
        lines.append(f"{day},{project},{count},{format_duration(secs)},{secs / 3600:.2f}")
    lines.append(f"Total,,{total_sessions},{format_duration(total_seconds)},{total_seconds / 3600:.2f}")
    return "\n".join(lines) + "\n"


def generate_md_report(project: str, sessions: list[dict]) -> str:
    """Generate a Markdown report for a project."""
    rows = _aggregate_sessions_by_date(project, sessions)
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# {project} — Time Report",
        "",
        f"Generated: {today}",
        "",
        "| Date | Sessions | Duration | Hours |",
        "|------|----------|----------|-------|",
    ]
    total_sessions = 0
    total_seconds = 0.0
    for day, count, secs in rows:
        total_sessions += count
        total_seconds += secs
        lines.append(f"| {day} | {count} | {format_duration(secs)} | {secs / 3600:.2f} |")
    lines.append(
        f"| **Total** | **{total_sessions}** | **{format_duration(total_seconds)}** | **{total_seconds / 3600:.2f}** |"
    )
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_menubar.py::TestGenerateReport -v`
Expected: ALL PASS

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/test_menubar.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add cc-time-menubar.py tests/test_menubar.py
git commit -m "feat: add CSV and Markdown report generation"
```

---

### Task 4: Update `refresh()` for cumulative display, archive filtering, and auto-unarchive

**Files:**
- Modify: `cc-time-menubar.py:195-229` (the `refresh` method inside `CCTimeMenuBar`)

This task modifies the rumps UI class which cannot be unit-tested (requires macOS GUI). Changes are to the `refresh` method and the `_delete_project` callback.

- [ ] **Step 1: Update `refresh` method**

Replace the `refresh` method (lines 195-229) in `cc-time-menubar.py`:

```python
        def refresh(self, _):
            today_completed = load_today_sessions(SESSIONS_FILE)
            all_completed = load_all_completed_sessions(SESSIONS_FILE)
            active = load_active_sessions(ACTIVE_FILE)
            lock_path = TRACKING_DIR / ".lock"
            meta = load_projects_meta(PROJECTS_META_FILE, lock_path)

            # Auto-unarchive active projects
            meta_changed = False
            for s in active:
                proj = s.get("project", "unknown")
                if is_archived(meta, proj):
                    set_archived(meta, proj, False)
                    meta_changed = True
            if meta_changed:
                save_projects_meta(PROJECTS_META_FILE, meta, lock_path)

            projects, today_total = build_project_data(today_completed, all_completed, active)

            icon = "⏱" if active else "⏸"
            self.title = f"{icon} {format_duration(today_total)}"
            self.menu.clear()

            archived_projects = []

            for name, today_secs, total_secs, is_active in projects:
                if is_archived(meta, name) and not is_active:
                    archived_projects.append((name, today_secs, total_secs, is_active))
                    continue

                prefix = "🟢 " if is_active else "⚪ "
                today_str = format_duration(today_secs)
                total_str = format_duration(total_secs)
                label = f"{prefix}{name}\t{today_str} today / {total_str} total"

                if is_active:
                    item = rumps.MenuItem(label, callback=lambda _: None)
                    item.add(rumps.MenuItem(
                        "Export as CSV",
                        callback=lambda _, p=name: self._export_report(p, "csv"),
                    ))
                    item.add(rumps.MenuItem(
                        "Export as Markdown",
                        callback=lambda _, p=name: self._export_report(p, "md"),
                    ))
                else:
                    item = rumps.MenuItem(label)
                    item.add(rumps.MenuItem(
                        "Export as CSV",
                        callback=lambda _, p=name: self._export_report(p, "csv"),
                    ))
                    item.add(rumps.MenuItem(
                        "Export as Markdown",
                        callback=lambda _, p=name: self._export_report(p, "md"),
                    ))
                    item.add(rumps.MenuItem(
                        "Archive",
                        callback=lambda _, p=name: self._archive_project(p),
                    ))
                    item.add(rumps.MenuItem(
                        "Delete today's sessions",
                        callback=lambda _, p=name: self._delete_sessions(p, today_only=True),
                    ))
                    item.add(rumps.MenuItem(
                        "Delete project",
                        callback=lambda _, p=name: self._delete_project(p),
                    ))
                self.menu.add(item)

            if projects:
                self.menu.add(rumps.separator)

            total_item = rumps.MenuItem(
                f"Today: {format_duration(today_total)}", callback=None
            )
            self.menu.add(total_item)

            # Archived submenu
            if archived_projects:
                self.menu.add(rumps.separator)
                archived_menu = rumps.MenuItem(f"Show archived ({len(archived_projects)})")
                for name, today_secs, total_secs, _ in archived_projects:
                    total_str = format_duration(total_secs)
                    alabel = f"⚪ {name}\t{total_str} total"
                    aitem = rumps.MenuItem(alabel)
                    aitem.add(rumps.MenuItem(
                        "Export as CSV",
                        callback=lambda _, p=name: self._export_report(p, "csv"),
                    ))
                    aitem.add(rumps.MenuItem(
                        "Export as Markdown",
                        callback=lambda _, p=name: self._export_report(p, "md"),
                    ))
                    aitem.add(rumps.MenuItem(
                        "Unarchive",
                        callback=lambda _, p=name: self._unarchive_project(p),
                    ))
                    aitem.add(rumps.MenuItem(
                        "Delete project",
                        callback=lambda _, p=name: self._delete_project(p),
                    ))
                    archived_menu.add(aitem)
                self.menu.add(archived_menu)

            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("Quit", callback=self.quit_app))
```

- [ ] **Step 2: Update `_delete_project` to clean up `projects.json`**

Replace the existing `_delete_project` method:

```python
        def _delete_project(self, project):
            self._bring_to_front()
            response = rumps.alert(
                title="Confirm Delete",
                message=f"Delete ALL data for '{project}'?\nThis cannot be undone.",
                ok="Delete",
                cancel="Cancel",
            )
            if response == 1:
                delete_project_sessions(SESSIONS_FILE, project, today_only=False)
                delete_project_sessions(ACTIVE_FILE, project, today_only=False)
                lock_path = TRACKING_DIR / ".lock"
                meta = load_projects_meta(PROJECTS_META_FILE, lock_path)
                remove_project_meta(meta, project)
                save_projects_meta(PROJECTS_META_FILE, meta, lock_path)
                self._schedule_refresh()
```

- [ ] **Step 3: Add `_archive_project` and `_unarchive_project` methods**

Add after `_delete_project`:

```python
        def _archive_project(self, project):
            lock_path = TRACKING_DIR / ".lock"
            meta = load_projects_meta(PROJECTS_META_FILE, lock_path)
            set_archived(meta, project, True)
            save_projects_meta(PROJECTS_META_FILE, meta, lock_path)
            self._schedule_refresh()

        def _unarchive_project(self, project):
            lock_path = TRACKING_DIR / ".lock"
            meta = load_projects_meta(PROJECTS_META_FILE, lock_path)
            set_archived(meta, project, False)
            save_projects_meta(PROJECTS_META_FILE, meta, lock_path)
            self._schedule_refresh()
```

- [ ] **Step 4: Add `_export_report` method with NSSavePanel**

Add after `_unarchive_project`:

```python
        def _export_report(self, project, fmt):
            self._bring_to_front()
            from AppKit import NSSavePanel

            all_sessions = load_all_completed_sessions(SESSIONS_FILE)

            if fmt == "csv":
                content = generate_csv_report(project, all_sessions)
                ext = "csv"
            else:
                content = generate_md_report(project, all_sessions)
                ext = "md"

            today = datetime.now().strftime("%Y-%m-%d")
            filename = f"{project}_report_{today}.{ext}"

            panel = NSSavePanel.savePanel()
            panel.setNameFieldStringValue_(filename)
            panel.setAllowedFileTypes_([ext])

            if panel.runModal() == 1:  # NSModalResponseOK
                path = panel.URL().path()
                Path(path).write_text(content, encoding="utf-8")
```

- [ ] **Step 5: Run all tests to ensure nothing is broken**

Run: `python3 -m pytest tests/test_menubar.py -v`
Expected: ALL PASS (UI methods aren't tested but pure functions still pass)

- [ ] **Step 6: Commit**

```bash
git add cc-time-menubar.py
git commit -m "feat: cumulative display, archive/unarchive, export reports in menubar"
```

---

### Task 5: Update module docstring and manual smoke test

**Files:**
- Modify: `cc-time-menubar.py:1-11` (docstring)

- [ ] **Step 1: Update the docstring**

Replace the module docstring (lines 2-11):

```python
"""
macOS menu bar app for Claude Code time tracking.
Shows cumulative project time in the menu bar with today/total breakdown.
Click to see per-project breakdown, archive projects, or export reports.

Usage:
    python3 cc-time-menubar.py

Requires: pip install rumps
"""
```

- [ ] **Step 2: Run all tests one final time**

Run: `python3 -m pytest tests/test_menubar.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add cc-time-menubar.py
git commit -m "docs: update menubar docstring for cumulative tracking"
```

- [ ] **Step 4: Manual smoke test**

Run: `python3 cc-time-menubar.py`

Verify:
1. Menu bar shows `⏱ Xm` or `⏸ Xm` with today's total
2. Clicking shows all non-archived projects with "Xm today / Xh Ym total" format
3. Hovering over a project shows submenu: Export as CSV, Export as Markdown, Archive, Delete today's sessions, Delete project
4. "Archive" moves project to "Show archived (N)" submenu
5. "Export as CSV" opens save dialog and writes valid CSV
6. "Export as Markdown" opens save dialog and writes valid Markdown
