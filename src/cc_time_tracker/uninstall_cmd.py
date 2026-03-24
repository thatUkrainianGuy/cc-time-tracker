"""cc-time-uninstall — remove time-tracking hooks from Claude Code settings."""

import json
import sys
from pathlib import Path

from cc_time_tracker.common import (
    TRACKING_DIR, SETTINGS_FILE, load_settings,
    BOLD, GREEN, RED, DIM, RESET,
)


def remove_hooks(settings_file: Path) -> None:
    """Remove cc_time_tracker hook entries from settings.json."""
    if not settings_file.exists():
        print(f"  {DIM}No settings.json found — nothing to remove.{RESET}")
        return

    settings = load_settings(settings_file)
    if not settings and settings_file.exists():
        print(f"  {RED}Could not parse {settings_file}{RESET}")
        return

    hooks = settings.get("hooks", {})
    changed = False

    for event in ("SessionStart", "SessionEnd"):
        if event in hooks:
            original_len = len(hooks[event])
            hooks[event] = [
                group for group in hooks[event]
                if not any("cc_time_tracker" in h.get("command", "") for h in group.get("hooks", []))
            ]
            if len(hooks[event]) != original_len:
                changed = True

    if changed:
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        print(f"  {GREEN}✓ Removed hooks from {settings_file}{RESET}")
    else:
        print(f"  {DIM}No cc-time-tracker hooks found in settings.json{RESET}")


def main():
    print(f"\n{BOLD}Claude Code Time Tracker — Uninstall{RESET}\n")

    remove_hooks(SETTINGS_FILE)

    if TRACKING_DIR.exists():
        answer = input(f"\n  Remove time tracking data ({TRACKING_DIR})? [y/N]: ").strip().lower()
        if answer == "y":
            import shutil
            shutil.rmtree(TRACKING_DIR)
            print(f"  {GREEN}✓ Removed {TRACKING_DIR}{RESET}")
        else:
            print(f"  {DIM}Kept {TRACKING_DIR}{RESET}")

    print(f"\n  {DIM}Run: pip uninstall cc-time-tracker{RESET}\n")


if __name__ == "__main__":
    main()
