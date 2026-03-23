# Menubar App Beautification & Delete Feature

## Summary

Improve the `cc-time-menubar.py` menu bar app with emoji indicators, tab-aligned columns, and per-project delete functionality.

## Changes

### 1. Menu Item Layout

Each project row uses two columns separated by a tab character (`\t`) for native macOS right-alignment:

- **Active projects:** `🟢 project-name\tduration`
- **Inactive projects:** `   project-name\tduration` (3 spaces to match emoji width)
- **Today total:** `   Today: duration` (unchanged except spacing)

### 2. Delete Functionality

Clicking an **inactive** project opens a submenu with:

- **"Delete today's sessions"** — removes all records (start + end) from `sessions.jsonl` where project matches and timestamp falls within today. Refreshes menu.
- **"Delete all sessions"** — removes ALL records for that project from `sessions.jsonl`. Project disappears from menu.

Constraints:
- **Active projects have no submenu** — running sessions cannot be deleted.
- A `rumps.alert()` confirmation dialog before each delete action.
- Delete rewrites `sessions.jsonl` by reading all lines, filtering out matches, and writing back. Uses the existing optional filelock.

### 3. Pure Function: `delete_project_sessions`

A new pure function (no rumps dependency) for the filtering logic:

```python
def delete_project_sessions(
    sessions_file: Path,
    project: str,
    today_only: bool,
) -> int:
    """Remove sessions for a project from the JSONL file.

    Args:
        sessions_file: Path to sessions.jsonl
        project: Project name to delete
        today_only: If True, only delete today's records. If False, delete all.

    Returns:
        Number of records removed.
    """
```

This function:
- Reads all records from `sessions.jsonl`
- Filters out records matching the project (and today's date if `today_only=True`)
- Writes remaining records back to the file
- Uses filelock if available
- Returns count of removed records

### 4. Menu Construction Changes

In `CCTimeMenuBar.refresh()`:

- For **active** projects: `rumps.MenuItem` with `callback=None` (no click action)
- For **inactive** projects: `rumps.MenuItem` with a submenu containing the two delete options
- Delete callbacks call `delete_project_sessions()`, then `self.refresh(None)` to update the menu

### 5. Testing

Extend `tests/test_menubar.py` with tests for `delete_project_sessions`:

- Delete today's sessions for a project (leaves other days and other projects intact)
- Delete all sessions for a project (removes everything for that project)
- Delete from empty/missing file (no error)
- Verify record count returned

## Files Modified

- `cc-time-menubar.py` — layout changes, delete function, submenu wiring
- `tests/test_menubar.py` — new tests for delete logic

## No New Dependencies

All changes use existing dependencies (rumps, optional filelock). Tab alignment is native macOS `NSMenu` behavior.
