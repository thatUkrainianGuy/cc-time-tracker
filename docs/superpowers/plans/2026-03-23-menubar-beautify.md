# Menubar Beautification & Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add emoji indicators, tab-aligned columns, and per-project delete functionality to `cc-time-menubar.py`.

**Architecture:** Add a pure `delete_project_sessions()` function for testable JSONL filtering. Update `refresh()` to use emoji prefixes + `\t` for alignment and wire submenus with delete callbacks for inactive projects.

**Tech Stack:** Python 3, rumps, optional filelock

**Spec:** `docs/superpowers/specs/2026-03-23-menubar-beautify-design.md`

---

### Task 1: Add `delete_project_sessions` pure function with tests

**Files:**
- Modify: `cc-time-menubar.py:51` (after `_read_jsonl`)
- Modify: `tests/test_menubar.py` (new test class)

- [ ] **Step 1: Write failing tests for `delete_project_sessions`**

Add to `tests/test_menubar.py`:

```python
class TestDeleteProjectSessions:
    def setup_method(self):
        self.mod = load_menubar()
        self.tmpdir = tempfile.mkdtemp()
        self.sessions_file = Path(self.tmpdir) / "sessions.jsonl"

    def _now_unix(self):
        return datetime.now(timezone.utc).timestamp()

    def test_delete_all_sessions_for_project(self):
        now = self._now_unix()
        yesterday = now - 86400 * 2
        lines = [
            make_start_record("s1", "proj-a", "/tmp/proj-a", now - 3600),
            make_end_record("s1", "proj-a", "/tmp/proj-a", now, 3600),
            make_start_record("s2", "proj-b", "/tmp/proj-b", now - 600),
            make_end_record("s2", "proj-b", "/tmp/proj-b", now, 600),
            make_end_record("s3", "proj-a", "/tmp/proj-a", yesterday, 100),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        removed = self.mod.delete_project_sessions(self.sessions_file, "proj-a", today_only=False)
        assert removed == 3
        remaining = self.mod._read_jsonl(self.sessions_file)
        assert len(remaining) == 2
        assert all(r["project"] == "proj-b" for r in remaining)

    def test_delete_today_only(self):
        now = self._now_unix()
        yesterday = now - 86400 * 2
        lines = [
            make_start_record("s1", "proj-a", "/tmp/proj-a", now - 3600),
            make_end_record("s1", "proj-a", "/tmp/proj-a", now, 3600),
            make_end_record("s3", "proj-a", "/tmp/proj-a", yesterday, 100),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        removed = self.mod.delete_project_sessions(self.sessions_file, "proj-a", today_only=True)
        assert removed == 2
        remaining = self.mod._read_jsonl(self.sessions_file)
        assert len(remaining) == 1
        assert remaining[0]["timestamp_unix"] == yesterday

    def test_delete_missing_file(self):
        nonexistent = Path(self.tmpdir) / "nope.jsonl"
        removed = self.mod.delete_project_sessions(nonexistent, "proj-a", today_only=False)
        assert removed == 0

    def test_delete_empty_file(self):
        self.sessions_file.write_text("")
        removed = self.mod.delete_project_sessions(self.sessions_file, "proj-a", today_only=False)
        assert removed == 0

    def test_preserves_malformed_lines(self):
        now = self._now_unix()
        lines = [
            "not json at all",
            make_end_record("s1", "proj-a", "/tmp/proj-a", now, 100),
            "{broken json",
            make_end_record("s2", "proj-b", "/tmp/proj-b", now, 200),
        ]
        self.sessions_file.write_text("\n".join(lines) + "\n")
        removed = self.mod.delete_project_sessions(self.sessions_file, "proj-a", today_only=False)
        assert removed == 1
        raw_lines = [l for l in self.sessions_file.read_text().strip().split("\n") if l.strip()]
        assert len(raw_lines) == 3
        assert raw_lines[0] == "not json at all"
        assert raw_lines[1] == "{broken json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_menubar.py::TestDeleteProjectSessions -v`
Expected: FAIL with `AttributeError: module has no attribute 'delete_project_sessions'`

- [ ] **Step 3: Implement `delete_project_sessions`**

Add to `cc-time-menubar.py` after the `_read_jsonl` function (after line 50):

```python
def _acquire_lock(lock_path):
    """Optional filelock context manager — no-op if filelock not installed."""
    try:
        from filelock import FileLock
        return FileLock(lock_path, timeout=5)
    except ImportError:
        from contextlib import contextmanager

        @contextmanager
        def _noop():
            yield

        return _noop()


def delete_project_sessions(
    sessions_file: Path,
    project: str,
    today_only: bool,
) -> int:
    """Remove sessions for a project from the JSONL file.

    Returns number of records removed.
    """
    try:
        raw_lines = sessions_file.read_text().strip().split("\n")
    except FileNotFoundError:
        return 0

    if not any(l.strip() for l in raw_lines):
        return 0

    today_start = get_today_start_unix() if today_only else None
    kept_lines = []
    removed = 0

    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            kept_lines.append(stripped)
            continue

        if record.get("project") == project:
            if today_only:
                if record.get("timestamp_unix", 0) >= today_start:
                    removed += 1
                    continue
            else:
                removed += 1
                continue
        kept_lines.append(stripped)

    lock_path = sessions_file.parent / ".lock"
    with _acquire_lock(lock_path):
        sessions_file.write_text("\n".join(kept_lines) + "\n" if kept_lines else "")

    return removed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_menubar.py::TestDeleteProjectSessions -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add cc-time-menubar.py tests/test_menubar.py
git commit -m "feat: add delete_project_sessions function with tests"
```

---

### Task 2: Update menu layout with emoji indicators and tab alignment

**Files:**
- Modify: `cc-time-menubar.py:134-154` (`refresh` method)

- [ ] **Step 1: Update `refresh()` to use emoji prefixes and tab alignment**

Replace the project loop and menu construction in `refresh()`:

```python
        def refresh(self, _):
            completed = load_today_sessions(SESSIONS_FILE)
            active = load_active_sessions(ACTIVE_FILE)
            projects, total = build_project_data(completed, active)

            self.title = f"⏱ {format_duration(total)}"
            self.menu.clear()

            for name, secs, _has_completed, is_active in projects:
                prefix = "🟢 " if is_active else "⚪ "
                label = f"{prefix}{name}\t{format_duration(secs)}"
                if is_active:
                    item = rumps.MenuItem(label, callback=lambda _: None)
                else:
                    item = rumps.MenuItem(label)
                    delete_today = rumps.MenuItem(
                        "Delete today's sessions",
                        callback=lambda _, p=name: self._delete_sessions(p, today_only=True),
                    )
                    delete_all = rumps.MenuItem(
                        "Delete all sessions",
                        callback=lambda _, p=name: self._delete_sessions(p, today_only=False),
                    )
                    item.add(delete_today)
                    item.add(delete_all)
                self.menu.add(item)

            if projects:
                self.menu.add(rumps.separator)

            total_item = rumps.MenuItem(f"Today: {format_duration(total)}", callback=None)
            self.menu.add(total_item)
            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("Quit", callback=self.quit_app))
```

- [ ] **Step 2: Add `_delete_sessions` method to `CCTimeMenuBar`**

Add after `refresh()`:

```python
        def _delete_sessions(self, project, today_only):
            scope = "today's" if today_only else "ALL"
            msg = f"Delete {scope} sessions for '{project}'?"
            if not today_only:
                msg += "\nThis cannot be undone."
            response = rumps.alert(
                title="Confirm Delete",
                message=msg,
                ok="Delete",
                cancel="Cancel",
            )
            if response == 1:  # OK clicked
                delete_project_sessions(SESSIONS_FILE, project, today_only)
                self.refresh(None)
```

- [ ] **Step 3: Run all tests to verify nothing is broken**

Run: `python3 -m pytest tests/test_menubar.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add cc-time-menubar.py
git commit -m "feat: emoji indicators, tab alignment, delete submenus"
```

---

### Task 3: Manual smoke test

- [ ] **Step 1: Run the menubar app**

```bash
python3 cc-time-menubar.py
```

- [ ] **Step 2: Verify visual layout**

Check that:
- Active projects show 🟢, inactive show ⚪
- Project names and durations are tab-aligned
- Inactive projects have a submenu arrow with delete options
- Active projects have no submenu
- "Today: Xh Ym" total line appears correctly

- [ ] **Step 3: Test delete flow**

- Click an inactive project → submenu appears
- Click "Delete today's sessions" → confirmation dialog → menu refreshes
- Click "Delete all sessions" → confirmation dialog → project disappears

- [ ] **Step 4: Final commit if any adjustments needed**

```bash
git add cc-time-menubar.py
git commit -m "fix: adjust menubar layout after smoke test"
```
