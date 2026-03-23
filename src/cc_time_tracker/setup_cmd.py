"""cc-time-setup — register time-tracking hooks in Claude Code settings."""

import json
import sys
from pathlib import Path

from cc_time_tracker.common import TRACKING_DIR, ensure_dir

SETTINGS_FILE = Path.home() / ".claude" / "settings.json"
OLD_HOOK_FILES = [
    Path.home() / ".claude" / "hooks" / "cc-time-start.py",
    Path.home() / ".claude" / "hooks" / "cc-time-end.py",
]
OLD_BIN_FILE = Path.home() / ".local" / "bin" / "cc-time-report"

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def is_already_installed(settings_file: Path) -> bool:
    """Check if cc-time-tracker hooks are already in settings."""
    if not settings_file.exists():
        return False
    try:
        settings = json.loads(settings_file.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    for group in settings.get("hooks", {}).get("SessionStart", []):
        for hook in group.get("hooks", []):
            if "cc_time_tracker" in hook.get("command", ""):
                return True
    return False


def merge_hooks(settings_file: Path, python_path: str) -> None:
    """Merge time-tracking hooks into settings.json."""
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except json.JSONDecodeError:
            settings = {}
    else:
        settings = {}

    if is_already_installed(settings_file):
        print(f"  {YELLOW}⚠ Hooks already registered — skipping{RESET}")
        return

    new_hooks = {
        "SessionStart": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{python_path} -m cc_time_tracker.start_hook",
                "timeout": 5,
            }],
        }],
        "SessionEnd": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"{python_path} -m cc_time_tracker.end_hook",
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
    print(f"  {GREEN}✓ Created {TRACKING_DIR}/{RESET}")

    python_path = sys.executable
    merge_hooks(SETTINGS_FILE, python_path)

    warn_old_install()

    print(f"\n  {GREEN}{BOLD}Done!{RESET} Time tracking is now active for all Claude Code sessions.")
    print(f"  Run {BOLD}cc-time-report{RESET} to see your stats.\n")


if __name__ == "__main__":
    main()
