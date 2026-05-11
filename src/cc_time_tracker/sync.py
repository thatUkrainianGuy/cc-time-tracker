"""Push completed cc-time-tracker sessions to the client portal."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from .common import load_jsonl, ensure_dir, atomic_write_text, harden_file_perms, strip_control

TRACKING_DIR = Path(os.environ.get("CC_TIME_TRACKING_DIR", str(Path.home() / ".claude" / "time-tracking")))
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
CURSOR_FILE = TRACKING_DIR / "sync-cursor.json"
CONFIG_FILE = TRACKING_DIR / "sync-config.json"

BATCH_SIZE = 100

# The cursor tracks every end event the client has already pushed. Each entry
# is f"{session_id}|{end_at}" — Claude Code's session_id is not unique on its
# own because /clear and prompt-exit both fire SessionEnd, so the same
# session_id can produce multiple end events that we must each push as a
# separate row server-side.
_CURSOR_KEY = "pushed_events"
_LEGACY_CURSOR_KEY = "pushed_session_ids"


def _event_key(session_id: str, end_at: float) -> str:
    return f"{session_id}|{end_at}"


def _load_config() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        raise SystemExit(f"missing config: {CONFIG_FILE}\nCreate it with {{\"endpoint\": ..., \"api_key\": ...}}")
    cfg = json.loads(CONFIG_FILE.read_text())
    if not isinstance(cfg, dict):
        raise SystemExit(f"invalid config: {CONFIG_FILE}")
    endpoint = str(cfg.get("endpoint") or "")
    parsed = urllib.parse.urlparse(endpoint)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise SystemExit("sync endpoint must be https://, except localhost for development")
    api_key = str(cfg.get("api_key") or "")
    if not api_key or api_key == "REPLACE_ME":
        raise SystemExit(f"missing api_key in {CONFIG_FILE}")
    return {"endpoint": endpoint, "api_key": api_key}


def _load_cursor() -> dict[str, Any]:
    """Read the cursor file. A legacy cursor with only `pushed_session_ids`
    cannot be translated to the new event-key format (we don't know which
    end_at value each pre-migration push had), so we discard it and let the
    next sync re-push everything. The server is idempotent on
    (session_id, end_at) so re-push is safe."""
    if not CURSOR_FILE.exists():
        return {_CURSOR_KEY: []}
    try:
        cursor = json.loads(CURSOR_FILE.read_text())
    except Exception:
        return {_CURSOR_KEY: []}
    if not isinstance(cursor, dict):
        return {_CURSOR_KEY: []}
    if _CURSOR_KEY not in cursor and _LEGACY_CURSOR_KEY in cursor:
        # Legacy cursor — drop the old field, start with an empty event list.
        cursor = {_CURSOR_KEY: []}
    cursor.setdefault(_CURSOR_KEY, [])
    return cursor


def _save_cursor(cursor: dict[str, Any]) -> None:
    ensure_dir(TRACKING_DIR)
    cursor.pop(_LEGACY_CURSOR_KEY, None)
    atomic_write_text(CURSOR_FILE, json.dumps(cursor))
    harden_file_perms(CURSOR_FILE)


def evict_session_ids_from_cursor(cursor_path: Path, session_ids: Iterable[str]) -> int:
    """Remove every cursor entry whose session_id is in `session_ids`,
    returning the count actually dropped. Used by merge/delete so the next
    sync re-pushes the affected records. A local merge changes the project
    field on every end event for a session_id, so all those event keys must
    be evicted together. Caller must hold the tracking-dir lock. No-op if
    the cursor file is missing, malformed, or uses the legacy format
    (which is also wiped, forcing the next sync to reconcile)."""
    ids = set(session_ids)
    if not ids:
        return 0
    try:
        raw = cursor_path.read_text()
    except FileNotFoundError:
        return 0
    try:
        cursor = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(cursor, dict):
        return 0
    if _CURSOR_KEY not in cursor and _LEGACY_CURSOR_KEY in cursor:
        # Wipe the legacy cursor entirely — we can't selectively evict because
        # the old format lacks end_at; next sync re-pushes everything.
        new_cursor = {k: v for k, v in cursor.items() if k != _LEGACY_CURSOR_KEY}
        new_cursor[_CURSOR_KEY] = []
        ensure_dir(cursor_path.parent)
        atomic_write_text(cursor_path, json.dumps(new_cursor))
        harden_file_perms(cursor_path)
        return 0
    pushed = cursor.get(_CURSOR_KEY) or []
    if not isinstance(pushed, list):
        return 0
    kept: list[str] = []
    removed = 0
    for entry in pushed:
        if not isinstance(entry, str):
            continue
        sid_part = entry.split("|", 1)[0]
        if sid_part in ids:
            removed += 1
        else:
            kept.append(entry)
    if removed == 0:
        return 0
    cursor[_CURSOR_KEY] = sorted(kept)
    ensure_dir(cursor_path.parent)
    atomic_write_text(cursor_path, json.dumps(cursor))
    harden_file_perms(cursor_path)
    return removed


def collect_pending(sessions_file: Path, pushed: set[str]) -> list[dict[str, Any]]:
    """Emit one pending dict per end event not yet in the cursor. Distinct
    end events for the same session_id (e.g. two /clear ends) produce
    separate pending dicts because server identity is (session_id, end_at)."""
    if not sessions_file.exists():
        return []
    pending: list[dict[str, Any]] = []
    for rec in load_jsonl(sessions_file):
        if not isinstance(rec, dict):
            continue
        if rec.get("event") != "end":
            continue
        sid = rec.get("session_id")
        if not isinstance(sid, str):
            continue
        safe_sid = strip_control(sid, max_len=128)
        if not safe_sid:
            continue
        try:
            end_at = float(rec.get("timestamp_unix") or 0)
        except (TypeError, ValueError):
            continue
        if not end_at:
            continue
        if _event_key(safe_sid, end_at) in pushed:
            continue
        try:
            duration = float(rec.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        start_at = end_at - duration
        pending.append(
            {
                "session_id": safe_sid,
                "tracker_name": strip_control(str(rec.get("project") or "unknown"), max_len=64) or "unknown",
                "start_at": start_at,
                "end_at": end_at,
                "duration_seconds": duration,
            }
        )
    return pending


def _http_post(url: str, data: bytes, headers: dict[str, str], timeout: float = 30.0):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 -- url comes from local config


def run_once(dry_run: bool = False) -> int:
    cfg = _load_config()
    cursor = _load_cursor()
    pushed: set[str] = set(cursor.get(_CURSOR_KEY) or [])
    pending = collect_pending(SESSIONS_FILE, pushed)
    if not pending:
        print("nothing to sync")
        return 0
    if dry_run:
        print(f"would push {len(pending)} session(s)")
        for p in pending[:5]:
            print(f"  - {p['session_id']} ({p['tracker_name']}, {p['duration_seconds']:.1f}s)")
        if len(pending) > 5:
            print(f"  ... and {len(pending) - 5} more")
        return 0

    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
        # Default Python-urllib UA is flagged by Cloudflare Browser Integrity Check (error 1010).
        "User-Agent": "cc-time-sync/1.0 (+https://github.com/riabchuk/cc-time-tracker)",
    }
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i : i + BATCH_SIZE]
        body = json.dumps({"sessions": batch}).encode("utf-8")
        try:
            resp = _http_post(cfg["endpoint"], body, headers=headers)
        except urllib.error.HTTPError as e:
            status = e.code
            text = (e.read() or b"").decode(errors="replace")
            print(f"HTTP {status}: {text}", file=sys.stderr)
            if 400 <= status < 500:
                return 2
            return 3
        except (urllib.error.URLError, OSError) as e:
            print(f"network error: {e}", file=sys.stderr)
            return 3
        status = getattr(resp, "status", 200)
        if status >= 500:
            print(f"server {status}", file=sys.stderr)
            return 3
        if status >= 400:
            print(f"client error {status}", file=sys.stderr)
            return 2
        for rec in batch:
            pushed.add(_event_key(rec["session_id"], rec["end_at"]))
        cursor[_CURSOR_KEY] = sorted(pushed)
        _save_cursor(cursor)
        print(f"pushed {len(batch)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="cc-time-sync")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reset", action="store_true", help="forget cursor, resend all (server dedupes by (session_id, end_at))")
    args = p.parse_args()
    if args.reset and CURSOR_FILE.exists():
        CURSOR_FILE.unlink()
        print("cursor reset")
    return run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
