#!/usr/bin/env bash
#
# install.sh — Install Claude Code time tracker hooks (standalone/curl method)
#
# ┌──────────────────────────────────────────────────────────────────┐
# │  Prefer: pip install cc-time-tracker && cc-time-setup           │
# │  This script is for users who don't want to use pip.            │
# └──────────────────────────────────────────────────────────────────┘
#
# What it does:
#   1. Copies hook scripts to ~/.claude/hooks/
#   2. Installs cc-time-report to ~/.local/bin/
#   3. Merges hook config into ~/.claude/settings.json
#   4. Creates the tracking directory
#
# Usage:
#   chmod +x install.sh && ./install.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOKS_DIR="$HOME/.claude/hooks"
TRACKING_DIR="$HOME/.claude/time-tracking"
SETTINGS_FILE="$HOME/.claude/settings.json"
BIN_DIR="$HOME/.local/bin"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

echo -e "${BOLD}Claude Code Time Tracker — Standalone Installer${RESET}"
echo -e "${DIM}Prefer: pip install cc-time-tracker && cc-time-setup${RESET}\n"

# ── 1. Create directories ────────────────────────────────────────────
echo -e "${DIM}Creating directories...${RESET}"
mkdir -p "$HOOKS_DIR"
mkdir -p "$TRACKING_DIR"
mkdir -p "$BIN_DIR"

# ── 2. Copy hook scripts ─────────────────────────────────────────────
echo -e "${DIM}Installing hook scripts to ${HOOKS_DIR}/${RESET}"
cp "$SCRIPT_DIR/src/cc_time_tracker/start_hook.py" "$HOOKS_DIR/cc-time-start.py"
cp "$SCRIPT_DIR/src/cc_time_tracker/end_hook.py" "$HOOKS_DIR/cc-time-end.py"
chmod +x "$HOOKS_DIR/cc-time-start.py"
chmod +x "$HOOKS_DIR/cc-time-end.py"

# ── 3. Install report CLI ────────────────────────────────────────────
echo -e "${DIM}Installing cc-time-report to ${BIN_DIR}/${RESET}"
cp "$SCRIPT_DIR/src/cc_time_tracker/report.py" "$BIN_DIR/cc-time-report"
chmod +x "$BIN_DIR/cc-time-report"

# ── 4. Merge hooks into settings.json ────────────────────────────────
echo -e "${DIM}Configuring hooks in ${SETTINGS_FILE}${RESET}"

if [ ! -f "$SETTINGS_FILE" ]; then
    # No existing settings — create with our hooks
    python3 << 'PYCREATE'
import json
from pathlib import Path

settings = {
    "hooks": {
        "SessionStart": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": "python3 ~/.claude/hooks/cc-time-start.py",
                "timeout": 5
            }]
        }],
        "SessionEnd": [{
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": "python3 ~/.claude/hooks/cc-time-end.py",
                "timeout": 5
            }]
        }]
    }
}

settings_path = Path.home() / ".claude" / "settings.json"
settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print("✓ Created settings.json with time-tracking hooks")
PYCREATE

else
    # Existing settings — need to merge
    python3 << 'PYMERGE'
import json
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"

with open(settings_path) as f:
    settings = json.load(f)

new_hooks = {
    "SessionStart": [{
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/hooks/cc-time-start.py",
            "timeout": 5
        }]
    }],
    "SessionEnd": [{
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/hooks/cc-time-end.py",
            "timeout": 5
        }]
    }]
}

if "hooks" not in settings:
    settings["hooks"] = {}

# Check if already installed (both old-style and new pip-style)
existing_start = settings["hooks"].get("SessionStart", [])
already_installed = any(
    "cc-time-start" in str(h) or "cc_time_tracker" in str(h)
    for group in existing_start
    for h in group.get("hooks", [])
)

if already_installed:
    print("⚠ Time-tracking hooks already present in settings.json — skipping merge")
else:
    for event, hook_configs in new_hooks.items():
        if event not in settings["hooks"]:
            settings["hooks"][event] = []
        settings["hooks"][event].extend(hook_configs)

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
    print("✓ Merged time-tracking hooks into settings.json")
PYMERGE

fi

# ── 5. Check PATH ────────────────────────────────────────────────────
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "\n${YELLOW}⚠ ${BIN_DIR} is not in your PATH.${RESET}"
    echo -e "  Add this to your ~/.bashrc or ~/.zshrc:"
    echo -e "  ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${RESET}"
fi

# ── 6. Optional: install filelock for safer concurrent sessions ──────
echo ""
if python3 -c "import filelock" 2>/dev/null; then
    echo -e "${GREEN}✓ filelock already installed${RESET}"
else
    echo -e "${YELLOW}Optional: install 'filelock' for safer concurrent session tracking:${RESET}"
    echo -e "  ${BOLD}pip install filelock${RESET}"
    echo -e "  ${DIM}(Works without it, but concurrent sessions are safer with it)${RESET}"
fi

# ── Done ──────────────────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}✓ Installation complete!${RESET}\n"
echo -e "  ${BOLD}Commands:${RESET}"
echo -e "  cc-time-report              Last 7 days summary"
echo -e "  cc-time-report today        Today only"
echo -e "  cc-time-report week         This week (Mon-Sun)"
echo -e "  cc-time-report month        This month"
echo -e "  cc-time-report all          All recorded time"
echo -e "  cc-time-report project X    Filter by project name"
echo -e "  cc-time-report active       Show running sessions"
echo -e "  cc-time-report csv          Export as CSV"
echo -e "  cc-time-report orphans      Find crashed sessions\n"
echo -e "  ${DIM}Data stored in: ~/.claude/time-tracking/${RESET}"
echo -e "  ${DIM}Hooks config:   ~/.claude/settings.json${RESET}\n"
