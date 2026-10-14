#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")"
# Pinned like the sync agent: Homebrew relinks python3 to new versions that lack rumps.
/opt/homebrew/opt/python@3.14/bin/python3.14 cc-time-menubar.py &
disown
osascript -e 'tell application "Terminal" to close front window' &
