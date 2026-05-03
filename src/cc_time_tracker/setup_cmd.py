"""cc-time-setup — register time-tracking hooks in Claude Code settings."""

import json
import shlex
import sys
from pathlib import Path

from cc_time_tracker.common import (
    TRACKING_DIR, SETTINGS_FILE, ensure_dir, harden_file_perms,
    load_settings, is_tracker_hook_group,
    BOLD, GREEN, YELLOW, DIM, RESET,
)

OLD_HOOK_FILES = [
    Path.home() / ".claude" / "hooks" / "cc-time-start.py",
    Path.home() / ".claude" / "hooks" / "cc-time-end.py",
]
OLD_BIN_FILE = Path.home() / ".local" / "bin" / "cc-time-report"


def _has_tracker_hooks(settings: dict) -> bool:
    """True if any SessionStart group in settings is one of ours."""
    return any(
        is_tracker_hook_group(group)
        for group in settings.get("hooks", {}).get("SessionStart", [])
    )


def is_already_installed(settings_file: Path) -> bool:
    return _has_tracker_hooks(load_settings(settings_file))


def merge_hooks(settings_file: Path, python_path: str) -> None:
    """Merge time-tracking hooks into settings.json."""
    settings = load_settings(settings_file)

    if _has_tracker_hooks(settings):
        print(f"  {YELLOW}⚠ Hooks already registered — skipping{RESET}")
        return

    # Hooks run via the shell, so shell-quote the interpreter path. Avoids
    # breakage when sys.executable lives under a path with spaces or shell
    # metacharacters (e.g. "/Applications/My Apps/python3").
    py = shlex.quote(python_path)
    new_hooks = {
        "SessionStart": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{py} -m cc_time_tracker.start_hook",
                "timeout": 5,
            }],
        }],
        "SessionEnd": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{py} -m cc_time_tracker.end_hook",
                "timeout": 5,
            }],
        }],
    }

    if "hooks" not in settings:
        settings["hooks"] = {}

    for event, hook_configs in new_hooks.items():
        if event not in settings["hooks"]:
            settings["hooks"][event] = []
        settings["hooks"][event].extend(hook_configs)

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  {GREEN}✓ Registered hooks in {settings_file}{RESET}")


def warn_old_install() -> None:
    """Detect and warn about old-style hook files."""
    old_found = [p for p in OLD_HOOK_FILES + [OLD_BIN_FILE] if p.exists()]
    if old_found:
        print(f"\n  {YELLOW}⚠ Old install detected. You can remove these:{RESET}")
        for p in old_found:
            print(f"    rm {p}")
        print()


def main():
    print(f"\n{BOLD}Claude Code Time Tracker — Setup{RESET}\n")

    ensure_dir()
    # Tighten any pre-existing data files left from older versions that
    # created them with the umask-derived (often world-readable) mode.
    for name in ("sessions.jsonl", "active.jsonl", "projects.json"):
        p = TRACKING_DIR / name
        if p.exists():
            harden_file_perms(p)
    print(f"  {GREEN}✓ Created {TRACKING_DIR}/{RESET}")

    python_path = sys.executable
    merge_hooks(SETTINGS_FILE, python_path)

    warn_old_install()

    print(f"\n  {GREEN}{BOLD}Done!{RESET} Time tracking is now active for all Claude Code sessions.")
    print(f"  Run {BOLD}cc-time-report{RESET} to see your stats.\n")


if __name__ == "__main__":
    main()
