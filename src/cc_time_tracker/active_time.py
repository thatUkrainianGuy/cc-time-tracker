"""Active time of a session window, from Claude Code transcript timestamps.

Active time sums the gaps between consecutive transcript events inside the
window, each gap capped at the idle cap, so an open-but-idle session stops
billing after the cap. Events from subagent/workflow transcripts count too:
during a Task or workflow run the main transcript is silent while they work.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from cc_time_tracker.common import coerce_int

PROJECTS_DIR = Path.home() / ".claude" / "projects"
IDLE_CAP_SECONDS = max(coerce_int(os.environ.get("CC_TIME_IDLE_CAP"), 900) or 900, 1)
WALL_CAP_SECONDS = 4 * 3600  # billed when no transcript can be read
SOURCE_TRANSCRIPT = "transcript"
SOURCE_WALL_CAPPED = "wall_capped"

_SLUG_RE = re.compile(r"[^A-Za-z0-9]")
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9-]+")  # safe to put in a glob


def transcript_files(session_id: str, cwd: str = "", transcript_path: str | None = None,
                     projects_dir: Path | None = None) -> list[Path]:
    """Main transcript plus every .jsonl under its <session_id>/ dir.

    Lookup order: the hook's transcript_path, the slug of cwd (Claude Code
    replaces every non-alphanumeric char with '-'), then any project dir
    holding <session_id>.jsonl (cwd may be a subdir of the project root).
    """
    root = projects_dir or PROJECTS_DIR
    candidates = []
    if transcript_path:
        candidates.append(Path(transcript_path))
    if cwd:
        candidates.append(root / _SLUG_RE.sub("-", cwd) / f"{session_id}.jsonl")
    main = next((p for p in candidates if p.is_file()), None)
    if main is None and _SESSION_ID_RE.fullmatch(session_id or ""):
        main = next(root.glob(f"*/{session_id}.jsonl"), None)
    if main is None:
        return []
    side = main.with_suffix("")  # <dir>/<session_id>/
    return [main, *sorted(side.rglob("*.jsonl"))] if side.is_dir() else [main]


def read_timestamps(paths: list[Path]) -> list[float]:
    """Top-level `timestamp` of every event line, as unix seconds."""
    out: list[float] = []
    for path in paths:
        with open(path, "rb") as f:
            for line in f:
                if b'"timestamp"' not in line:
                    continue
                try:
                    ts = json.loads(line).get("timestamp")
                    if isinstance(ts, str):
                        out.append(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
                except (ValueError, AttributeError, TypeError):
                    continue
    return out


def active_seconds(timestamps: list[float], start: float, end: float,
                   idle_cap: float = IDLE_CAP_SECONDS) -> float:
    """Sum of capped gaps between consecutive events inside [start, end]."""
    ts = sorted(t for t in timestamps if start <= t <= end)
    return sum(min(b - a, idle_cap) for a, b in zip(ts, ts[1:]))


def measure(timestamps: list[float] | None, start: float, end: float,
            idle_cap: float = IDLE_CAP_SECONDS) -> dict:
    """Fields for an end record: duration_seconds, wall_seconds, active_source.

    `timestamps=None` means no transcript was found or it failed to parse.
    """
    wall = max(end - start, 0.0)
    if timestamps is None:
        return {"duration_seconds": round(min(wall, WALL_CAP_SECONDS), 1),
                "wall_seconds": round(wall, 1), "active_source": SOURCE_WALL_CAPPED}
    return {"duration_seconds": round(active_seconds(timestamps, start, end, idle_cap), 1),
            "wall_seconds": round(wall, 1), "active_source": SOURCE_TRANSCRIPT}


def session_timestamps(session_id: str, cwd: str = "", transcript_path: str | None = None,
                       projects_dir: Path | None = None) -> list[float] | None:
    """Timestamps for a session, or None if no transcript exists or it can't
    be read. Never raises: hooks call this and must not fail the session."""
    try:
        paths = transcript_files(session_id, cwd, transcript_path, projects_dir)
        return read_timestamps(paths) if paths else None
    except Exception:  # noqa: BLE001 -- any failure falls back to wall_capped
        return None
