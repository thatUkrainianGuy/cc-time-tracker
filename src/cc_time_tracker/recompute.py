"""cc-time-recompute — rewrite past end events to active time from transcripts.

Backs up sessions.jsonl, rewrites duration_seconds / wall_seconds /
active_source in place under the tracking lock, and evicts the changed
session_ids from the sync cursor so the next cc-time-sync re-pushes them
(the server upserts on (session_id, end_at)). Safe to re-run: the window
comes from wall_seconds once a record has it.
"""

import argparse
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone

from cc_time_tracker import active_time, sync
from cc_time_tracker.common import (
    SESSIONS_FILE, EVENT_END, acquire_lock, coerce_float, load_jsonl, rewrite_jsonl,
)

FIELDS = ("duration_seconds", "wall_seconds", "active_source")
NO_TRANSCRIPT_BEFORE = datetime(2026, 10, 21, tzinfo=timezone.utc).timestamp()


def _key(rec: dict):
    return rec.get("session_id"), coerce_float(rec.get("timestamp_unix"))


def compute(records: list[dict], idle_cap: float, projects_dir=None) -> list[tuple[dict, dict]]:
    """(record, new fields) for every end event that has a window."""
    ends = [
        r for r in records
        if r.get("event") == EVENT_END and isinstance(r.get("session_id"), str)
        and r.get("duration_seconds") is not None and coerce_float(r.get("timestamp_unix"))
    ]
    ends.sort(key=lambda r: coerce_float(r.get("timestamp_unix")))
    cache: dict[str, list[float] | None] = {}
    prev_end: dict[str, float] = {}
    out = []
    for r in ends:
        sid, end = _key(r)
        wall = coerce_float(r.get("wall_seconds"), default=coerce_float(r.get("duration_seconds")))
        if sid not in cache:
            cache[sid] = active_time.session_timestamps(sid, str(r.get("cwd") or ""),
                                                        projects_dir=projects_dir)
        # Clip to the previous end of the same session so a window overlap
        # left by old bugs is never billed twice. wall_seconds stays as
        # recorded so the synced start_at doesn't move.
        start = max(end - wall, prev_end.get(sid, float("-inf")))
        prev_end[sid] = end
        fields = active_time.measure(cache[sid], min(start, end), end, idle_cap)
        fields["wall_seconds"] = round(wall, 1)
        out.append((r, fields))
    return out


def summarize(results: list[tuple[dict, dict]]) -> str:
    rows = defaultdict(lambda: {"n": 0, "wall": 0.0, "old": 0.0, "active": 0.0,
                                "capped": 0, "old_missing": 0})
    for rec, new in results:
        row = rows[str(rec.get("project") or "unknown")]
        row["n"] += 1
        row["wall"] += new["wall_seconds"]
        row["old"] += coerce_float(rec.get("duration_seconds"))
        row["active"] += new["duration_seconds"]
        if new["active_source"] == active_time.SOURCE_WALL_CAPPED:
            row["capped"] += 1
            if coerce_float(rec.get("timestamp_unix")) < NO_TRANSCRIPT_BEFORE:
                row["old_missing"] += 1
    total = {k: sum(r[k] for r in rows.values()) for k in ("n", "wall", "old", "active", "capped", "old_missing")}
    w = max([len(p) for p in rows] + [7])
    lines = [f"{'project':<{w}}  {'ends':>5}  {'wall h':>8}  {'billed h':>8}  {'active h':>8}  "
             f"{'capped':>6}  {'<10-21 none':>11}"]
    for name, r in sorted(rows.items(), key=lambda kv: -kv[1]["wall"]) + [("TOTAL", total)]:
        lines.append(f"{name:<{w}}  {r['n']:>5}  {r['wall'] / 3600:>8.2f}  {r['old'] / 3600:>8.2f}  "
                     f"{r['active'] / 3600:>8.2f}  {r['capped']:>6}  {r['old_missing']:>11}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cc-time-recompute", description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    p.add_argument("--idle-cap", type=int, default=active_time.IDLE_CAP_SECONDS,
                   help="max seconds billed for one gap between events (default %(default)s)")
    args = p.parse_args(argv)
    if args.idle_cap <= 0:
        p.error("--idle-cap must be positive")

    results = compute(load_jsonl(SESSIONS_FILE), args.idle_cap)
    changed = {_key(rec): new for rec, new in results
               if any(rec.get(f) != new[f] for f in FIELDS)}
    print(summarize(results))
    print(f"\nidle cap {args.idle_cap}s; {len(changed)} of {len(results)} end events change")
    if args.dry_run or not changed:
        return 0

    with acquire_lock(timeout=30):
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = SESSIONS_FILE.with_name(f"{SESSIONS_FILE.name}.bak-{stamp}")
        shutil.copy2(SESSIONS_FILE, backup)

        def transform(rec):
            new = changed.get(_key(rec)) if rec.get("event") == EVENT_END else None
            return {**rec, **new} if new else rec

        n = rewrite_jsonl(SESSIONS_FILE, transform)
        evicted = sync.evict_session_ids_from_cursor(sync.CURSOR_FILE, {sid for sid, _ in changed})
    print(f"backup {backup}\nrewrote {n} records; evicted {evicted} cursor entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
