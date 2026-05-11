"""Push completed cc-time-tracker sessions to the client portal."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from .common import load_jsonl, ensure_dir, atomic_write_text, harden_file_perms

TRACKING_DIR = Path(os.environ.get("CC_TIME_TRACKING_DIR", str(Path.home() / ".claude" / "time-tracking")))
SESSIONS_FILE = TRACKING_DIR / "sessions.jsonl"
CURSOR_FILE = TRACKING_DIR / "sync-cursor.json"
CONFIG_FILE = TRACKING_DIR / "sync-config.json"

BATCH_SIZE = 100


def _load_config() -> dict[str, str]:
    if not CONFIG_FILE.exists():
        raise SystemExit(f"missing config: {CONFIG_FILE}\nCreate it with {{\"endpoint\": ..., \"api_key\": ...}}")
    return json.loads(CONFIG_FILE.read_text())


def _load_cursor() -> dict[str, Any]:
    if not CURSOR_FILE.exists():
        return {"pushed_session_ids": [], "last_pushed_at_unix": 0}
    try:
        return json.loads(CURSOR_FILE.read_text())
    except Exception:
        return {"pushed_session_ids": [], "last_pushed_at_unix": 0}


def _save_cursor(cursor: dict[str, Any]) -> None:
    ensure_dir(TRACKING_DIR)
    atomic_write_text(CURSOR_FILE, json.dumps(cursor))
    harden_file_perms(CURSOR_FILE)


def evict_session_ids_from_cursor(cursor_path: Path, session_ids: Iterable[str]) -> int:
    """Remove the given session_ids from the sync cursor, returning the count
    actually dropped. Used by merge/delete in report.py and the menubar so the
    next sync re-pushes records whose project field changed locally after they
    were originally synced. Caller must hold the tracking-dir lock. No-op if
    the cursor file is missing or malformed.
    """
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
    pushed = cursor.get("pushed_session_ids") or []
    if not isinstance(pushed, list):
        return 0
    kept = [s for s in pushed if isinstance(s, str) and s not in ids]
    removed = len(pushed) - len(kept)
    if removed == 0:
        return 0
    cursor["pushed_session_ids"] = sorted(kept)
    ensure_dir(cursor_path.parent)
    atomic_write_text(cursor_path, json.dumps(cursor))
    harden_file_perms(cursor_path)
    return removed


def collect_pending(sessions_file: Path, pushed: set[str]) -> list[dict[str, Any]]:
    if not sessions_file.exists():
        return []
    pending: list[dict[str, Any]] = []
    seen_for_id: dict[str, dict[str, Any]] = {}
    for rec in load_jsonl(sessions_file):
        if not isinstance(rec, dict):
            continue
        sid = rec.get("session_id")
        if not isinstance(sid, str):
            continue
        if rec.get("event") == "end" and sid not in pushed:
            seen_for_id[sid] = rec
    for sid, rec in seen_for_id.items():
        # Find matching start to get start_at; fall back to end timestamp - duration
        end_at = float(rec.get("timestamp_unix") or 0)
        duration = float(rec.get("duration_seconds") or 0)
        start_at = end_at - duration
        pending.append(
            {
                "session_id": sid,
                "tracker_name": str(rec.get("project") or "unknown"),
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
    pushed: set[str] = set(cursor.get("pushed_session_ids") or [])
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
            pushed.add(rec["session_id"])
        cursor["pushed_session_ids"] = sorted(pushed)
        _save_cursor(cursor)
        print(f"pushed {len(batch)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="cc-time-sync")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reset", action="store_true", help="forget cursor, resend all (server is idempotent)")
    args = p.parse_args()
    if args.reset and CURSOR_FILE.exists():
        CURSOR_FILE.unlink()
        print("cursor reset")
    return run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
