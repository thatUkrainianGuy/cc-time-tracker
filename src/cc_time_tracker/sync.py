"""Push completed cc-time-tracker sessions to each sync target in sync-config.json."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from .common import (
    TRACKING_DIR, SESSIONS_FILE, EVENT_END,
    load_jsonl, ensure_dir, atomic_write_text, harden_file_perms, strip_control, coerce_float,
)

CURSOR_FILE = TRACKING_DIR / "sync-cursor.json"
CONFIG_FILE = TRACKING_DIR / "sync-config.json"

BATCH_SIZE = 100

# The cursor tracks every end event the client has already pushed. Each entry
# is f"{session_id}|{end_at}" — Claude Code's session_id is not unique on its
# own because /clear and prompt-exit both fire SessionEnd, so the same
# session_id can produce multiple end events that we must each push as a
# separate row server-side.
_CURSOR_KEY = "pushed_events"


def _event_key(session_id: str, end_at: float) -> str:
    return f"{session_id}|{end_at}"


LEGACY_TARGET = "portal"


class TargetError(Exception):
    """A target's config is unusable; that target fails, the others still run."""


def _load_targets() -> list[dict[str, Any]]:
    """Raw target dicts. Legacy top-level endpoint/api_key is the `portal` target."""
    if not CONFIG_FILE.exists():
        raise SystemExit(f"missing config: {CONFIG_FILE}\nCreate it with {{\"endpoint\": ..., \"api_key\": ...}}")
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except ValueError as e:
        raise SystemExit(f"invalid config: {CONFIG_FILE}: {e}")
    if not isinstance(cfg, dict) or not isinstance(cfg.get("targets", []), list):
        raise SystemExit(f"invalid config: {CONFIG_FILE}")
    targets = []
    if "endpoint" in cfg or "targets" not in cfg:
        # Legacy target never has an include filter.
        targets.append({"name": LEGACY_TARGET, **{k: cfg[k] for k in ("endpoint", "api_key", "api_key_file") if k in cfg}})
    for i, t in enumerate(cfg.get("targets", [])):
        if not isinstance(t, dict):
            raise SystemExit(f"invalid target #{i} in {CONFIG_FILE}")
        targets.append(t)
    names = [t.get("name") for t in targets]
    if not all(isinstance(n, str) and n for n in names) or len(set(names)) != len(names):
        raise SystemExit(f"every target in {CONFIG_FILE} needs a unique name")
    return targets


def _resolve_target(t: dict[str, Any]) -> dict[str, Any]:
    """Validate one target: https endpoint, api key (inline or 0600 file), include list."""
    endpoint = str(t.get("endpoint") or "")
    parsed = urllib.parse.urlparse(endpoint)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise TargetError("sync endpoint must be https://, except localhost for development")
    if t.get("api_key_file"):
        key_path = Path(str(t["api_key_file"])).expanduser()
        try:
            if key_path.stat().st_mode & 0o077:
                raise TargetError(f"api_key_file {key_path} must be chmod 600")
            api_key = key_path.read_text().strip()
        except OSError as e:
            raise TargetError(f"cannot read api_key_file {key_path}: {e.strerror}")
    else:
        api_key = str(t.get("api_key") or "")
    if not api_key or api_key == "REPLACE_ME":
        raise TargetError(f"missing api_key in {CONFIG_FILE}")
    include = t.get("include")
    if include is not None and not (isinstance(include, list) and all(isinstance(n, str) for n in include)):
        raise TargetError("include must be a list of tracker names")
    return {"name": t["name"], "endpoint": endpoint, "api_key": api_key,
            "include": None if include is None else set(include)}


def _load_cursor() -> dict[str, Any]:
    """Read the cursor file; missing or malformed means nothing pushed yet.
    Re-pushing is safe because the server is idempotent on (session_id, end_at)."""
    try:
        cursor = json.loads(CURSOR_FILE.read_text())
    except (OSError, ValueError):
        return {_CURSOR_KEY: []}
    if not isinstance(cursor, dict):
        return {_CURSOR_KEY: []}
    cursor.setdefault(_CURSOR_KEY, [])
    return cursor


def _pushed_lists(cursor: dict[str, Any]) -> list[tuple[dict[str, Any], list]]:
    """Every (holder, pushed_events list) in the cursor: top level for `portal`,
    then targets.<name>.pushed_events for the others."""
    out = []
    if isinstance(cursor.get(_CURSOR_KEY), list):
        out.append((cursor, cursor[_CURSOR_KEY]))
    targets = cursor.get("targets")
    for holder in (targets.values() if isinstance(targets, dict) else []):
        if isinstance(holder, dict) and isinstance(holder.get(_CURSOR_KEY), list):
            out.append((holder, holder[_CURSOR_KEY]))
    return out


def _target_cursor(cursor: dict[str, Any], name: str) -> dict[str, Any]:
    """The dict holding `name`'s pushed_events. `portal` keeps the legacy top-level
    key so an old cursor needs no migration; other targets are added alongside it."""
    if name == LEGACY_TARGET:
        holder = cursor
    else:
        targets = cursor.get("targets")
        if not isinstance(targets, dict):
            targets = cursor["targets"] = {}
        holder = targets.get(name)
        if not isinstance(holder, dict):
            holder = targets[name] = {}
    if not isinstance(holder.get(_CURSOR_KEY), list):
        holder[_CURSOR_KEY] = []
    return holder


def _save_cursor(cursor: dict[str, Any], path: Path | None = None) -> None:
    path = path or CURSOR_FILE
    ensure_dir(path.parent)
    atomic_write_text(path, json.dumps(cursor))
    harden_file_perms(path)


def evict_session_ids_from_cursor(cursor_path: Path, session_ids: Iterable[str]) -> int:
    """Remove every cursor entry whose session_id is in `session_ids`,
    returning the count actually dropped. Used by merge/delete so the next
    sync re-pushes the affected records. A local merge changes the project
    field on every end event for a session_id, so all those event keys must
    be evicted together. Caller must hold the tracking-dir lock. No-op if
    the cursor file is missing or malformed."""
    ids = set(session_ids)
    if not ids:
        return 0
    try:
        cursor = json.loads(cursor_path.read_text())
    except (OSError, ValueError):
        return 0
    if not isinstance(cursor, dict):
        return 0
    removed = 0
    for holder, pushed in _pushed_lists(cursor):  # every target's cursor
        entries = [e for e in pushed if isinstance(e, str)]
        kept = [e for e in entries if e.split("|", 1)[0] not in ids]
        if len(kept) != len(entries):
            removed += len(entries) - len(kept)
            holder[_CURSOR_KEY] = sorted(kept)
    if removed:
        _save_cursor(cursor, cursor_path)
    return removed


def collect_pending(sessions_file: Path, pushed: set[str]) -> list[dict[str, Any]]:
    """Emit one pending dict per end event not yet in the cursor. Distinct
    end events for the same session_id (e.g. two /clear ends) produce
    separate pending dicts because server identity is (session_id, end_at)."""
    pending: list[dict[str, Any]] = []
    for rec in load_jsonl(sessions_file):
        sid = rec.get("session_id")
        if rec.get("event") != EVENT_END or not isinstance(sid, str):
            continue
        safe_sid = strip_control(sid, max_len=128)
        end_at = coerce_float(rec.get("timestamp_unix"))
        if not safe_sid or not end_at or _event_key(safe_sid, end_at) in pushed:
            continue
        duration = coerce_float(rec.get("duration_seconds"))
        # duration is active time; the window start is end minus wall time.
        # Records from before active time have no wall_seconds and duration == wall.
        start_at = end_at - coerce_float(rec.get("wall_seconds"), default=duration)
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


def _push_target(target: dict[str, Any], cursor: dict[str, Any], dry_run: bool) -> int:
    tag = f"[{target['name']}]"
    holder = _target_cursor(cursor, target["name"])
    pushed: set[str] = set(holder[_CURSOR_KEY])
    pending = collect_pending(SESSIONS_FILE, pushed)
    include = target["include"]
    if include is not None:
        # Filter before anything reaches a request body: other tracker names must never leave the machine.
        pending = [p for p in pending if p["tracker_name"] in include]
    if not pending:
        print(f"{tag} nothing to sync")
        return 0
    if dry_run:
        print(f"{tag} would push {len(pending)} session(s) to {target['endpoint']}")
        for p in pending[:5]:
            print(f"  - {p['session_id']} ({p['tracker_name']}, {p['duration_seconds']:.1f}s)")
        if len(pending) > 5:
            print(f"  ... and {len(pending) - 5} more")
        return 0

    headers = {
        "Authorization": f"Bearer {target['api_key']}",
        "Content-Type": "application/json",
        # Default Python-urllib UA is flagged by Cloudflare Browser Integrity Check (error 1010).
        "User-Agent": "cc-time-sync/1.0 (+https://github.com/riabchuk/cc-time-tracker)",
    }
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i : i + BATCH_SIZE]
        body = json.dumps({"sessions": batch}).encode("utf-8")
        try:
            resp = _http_post(target["endpoint"], body, headers=headers)
        except urllib.error.HTTPError as e:
            status = e.code
            text = (e.read() or b"").decode(errors="replace")
            print(f"{tag} HTTP {status}: {text}", file=sys.stderr)
            if 400 <= status < 500:
                return 2
            return 3
        except (urllib.error.URLError, OSError) as e:
            print(f"{tag} network error: {e}", file=sys.stderr)
            return 3
        status = getattr(resp, "status", 200)
        if status >= 500:
            print(f"{tag} server {status}", file=sys.stderr)
            return 3
        if status >= 400:
            print(f"{tag} client error {status}", file=sys.stderr)
            return 2
        for rec in batch:
            pushed.add(_event_key(rec["session_id"], rec["end_at"]))
        holder[_CURSOR_KEY] = sorted(pushed)
        _save_cursor(cursor)
        print(f"{tag} pushed {len(batch)}")
    return 0


def run_once(dry_run: bool = False, only: str | None = None, reset: bool = False) -> int:
    """Push to every configured target (or just `only`). A failing target
    doesn't stop the rest; the return code is the worst one seen."""
    targets = _load_targets()
    if only is not None:
        targets = [t for t in targets if t["name"] == only]
        if not targets:
            raise SystemExit(f"no target named {only!r} in {CONFIG_FILE}")
    cursor = _load_cursor()
    if reset:
        for t in targets:
            _target_cursor(cursor, t["name"])[_CURSOR_KEY] = []
        _save_cursor(cursor)
        print("cursor reset: " + ", ".join(t["name"] for t in targets))
    rc = 0
    for raw in targets:
        try:
            target = _resolve_target(raw)
        except TargetError as e:
            print(f"[{raw['name']}] {e}", file=sys.stderr)
            rc = max(rc, 2)
            continue
        rc = max(rc, _push_target(target, cursor, dry_run))
    return rc


def main() -> int:
    p = argparse.ArgumentParser(prog="cc-time-sync")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--target", help="only this target (default: all in sync-config.json)")
    p.add_argument("--reset", action="store_true",
                   help="forget the cursor of the selected target(s), resend all (server dedupes by (session_id, end_at))")
    args = p.parse_args()
    return run_once(dry_run=args.dry_run, only=args.target, reset=args.reset)


if __name__ == "__main__":
    sys.exit(main())
