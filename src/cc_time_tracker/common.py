"""Shared constants and utilities for cc-time-tracker."""

import json
import os
import re
from pathlib import Path


TRACKING_DIR = Path.home() / ".claude" / "time-tracking"
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
ACTIVE_FILE = TRACKING_DIR / "active.jsonl"
LOCK_FILE = TRACKING_DIR / ".lock"
SETTINGS_FILE = Path.home() / ".claude" / "settings.json"

# Event/reason names used in the JSONL records.
EVENT_START = "start"
EVENT_END = "end"
REASON_ORPHAN_CLEANUP = "orphan_cleanup"

# Hook command tokens used to identify our hooks in settings.json. Matched
# as whole substrings — bare "cc_time_tracker" was too loose.
TRACKER_HOOK_TOKENS = (
    "-m cc_time_tracker.start_hook",
    "-m cc_time_tracker.end_hook",
)

# Bounds applied to project names before persisting/printing them. Project
# names originate from .cc-project marker files or directory basenames, which
# are attacker-controllable from any cloned repo.
PROJECT_NAME_MAX_LEN = 64
CC_PROJECT_READ_LIMIT = 4096  # bytes — first non-empty line is taken

# ANSI escape codes
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
UNDERLINE = "\033[4m"


class _NoLock:
    def __enter__(self): return self
    def __exit__(self, *a): pass


def ensure_dir(path: Path | None = None) -> None:
    """Create the tracking directory with 0700 perms (owner-only)."""
    target = path or TRACKING_DIR
    target.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass


def harden_file_perms(path: Path) -> None:
    """Tighten an existing data file to 0600 (owner-only). Best-effort."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def acquire_lock(lock_path: Path | None = None, timeout: float = 5):
    """Return a file lock (or no-op if filelock not installed)."""
    try:
        from filelock import FileLock
        return FileLock(str(lock_path or LOCK_FILE), timeout=timeout)
    except ImportError:
        return _NoLock()


def atomic_write_text(path: Path, content: str) -> None:
    """Write content to path via temp file + os.replace (POSIX-atomic).

    The temp file inherits a 0600 mask before being moved into place, so
    paths created/replaced through this helper land owner-only.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def is_tracker_hook_group(group: dict) -> bool:
    """True if any hook in the group invokes one of our hook modules.

    Matches the exact ``-m cc_time_tracker.<module>`` token to avoid sweeping
    up unrelated hooks that merely mention the package name (e.g. comments).
    """
    for h in group.get("hooks", []):
        cmd = h.get("command", "")
        if any(tok in cmd for tok in TRACKER_HOOK_TOKENS):
            return True
    return False


# ─── Sanitization ──────────────────────────────────────────────────────

# Strip CSI/OSC and stray C0 control bytes (except \t, \n, \r which we drop
# explicitly below) from text that originated outside our process.
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def strip_control(text: str, *, max_len: int | None = None) -> str:
    """Remove ANSI escape sequences and C0/DEL control chars from text.

    Used before printing attacker-controllable values to a terminal or
    embedding them in CSV/Markdown — prevents cursor/clipboard manipulation
    via OSC, fake hyperlinks, screen clears, and table/heading injection.
    """
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    cleaned = _ANSI_RE.sub("", text)
    cleaned = _CTRL_RE.sub("", cleaned)
    if max_len is not None and len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned


# Spreadsheet formula-leading characters per OWASP CSV-Injection guidance.
_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Coerce ``value`` to a CSV-safe string.

    1. Stringify and strip control chars (which already removes \\t / \\r).
    2. If the result still starts with a spreadsheet formula lead char,
       prefix a single quote so Excel/Sheets render it as text.
    """
    text = strip_control("" if value is None else str(value))
    if text and text[0] in _FORMULA_LEADS:
        text = "'" + text
    return text


def md_safe(value) -> str:
    """Coerce ``value`` for safe inclusion in a Markdown table cell.

    Strips control chars, escapes pipe characters that would break the
    table, and collapses any remaining newlines to spaces.
    """
    text = strip_control("" if value is None else str(value))
    return text.replace("|", r"\|")


def clamp_project_name(name: str) -> str:
    """Clean and bound a project-name string for storage/display."""
    return strip_control(name, max_len=PROJECT_NAME_MAX_LEN).strip()


# ─── JSON record validation ────────────────────────────────────────────

def coerce_float(value, default: float = 0.0) -> float:
    """Best-effort coerce to float. Returns ``default`` on bad input."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def coerce_int(value, default: int | None = None) -> int | None:
    """Best-effort coerce to int. Returns ``default`` on bad input."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == value and abs(value) < float("inf") else default
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def extract_project_name(cwd: str) -> str:
    """Derive a project name for cwd, walking up to find a project root.

    Resolution order, walking up from cwd:
      1. ``.cc-project`` marker — if it has content, the first non-empty line
         becomes the project name; if empty, the marker's directory is the root.
      2. ``.git`` (file or directory) — the containing directory's basename.

    The walk stops at ``$HOME`` (exclusive) or the filesystem root. If nothing
    is found, falls back to ``basename(cwd)`` — preserving prior behavior for
    ad-hoc directories.

    All returned names are run through ``clamp_project_name`` so a malicious
    repo cannot inject ANSI escapes or unbounded strings into our JSONL.
    """
    fallback = clamp_project_name(os.path.basename(os.path.normpath(cwd)))
    # Hooks must never raise — fall back silently on any FS error.
    try:
        start = Path(cwd).resolve()
    except (OSError, RuntimeError):
        return fallback
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None

    current = start
    while True:
        if home is not None and current == home:
            break

        marker = current / ".cc-project"
        if marker.is_file():
            first_line = ""
            try:
                # Bounded read defends against a repo shipping a multi-MB
                # marker that would block the SessionStart hook.
                with open(marker, "r", errors="replace") as fh:
                    chunk = fh.read(CC_PROJECT_READ_LIMIT)
                first_line = chunk.split("\n", 1)[0].strip()
            except OSError:
                first_line = ""
            cleaned = clamp_project_name(first_line)
            if cleaned:
                return cleaned
            return clamp_project_name(current.name) or fallback

        if (current / ".git").exists():
            return clamp_project_name(current.name) or fallback

        parent = current.parent
        if parent == current:
            break
        current = parent

    return fallback


def load_settings(path: Path) -> dict:
    """Read a JSON settings file, returning {} on missing/malformed files."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def read_hook_input() -> dict:
    """Read JSON from stdin for hook scripts. Exits 1 on bad input."""
    import sys
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(1)
    return data if isinstance(data, dict) else {}


def load_jsonl(path: Path, after_ts: float | None = None) -> list[dict]:
    """Read a JSONL file, returning a list of parsed dicts. Skips bad lines.

    Records that don't parse as JSON, aren't dicts, or (when ``after_ts`` is
    set) carry a non-numeric ``timestamp_unix`` are silently skipped — a single
    poisoned line cannot crash a hook or report.
    """
    try:
        f = open(path, "r")
    except FileNotFoundError:
        return []
    records = []
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if after_ts is not None:
                ts = coerce_float(record.get("timestamp_unix"), default=0.0)
                if ts < after_ts:
                    continue
            records.append(record)
    return records
