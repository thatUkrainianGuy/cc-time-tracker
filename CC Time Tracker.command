#!/bin/bash
cd "$(dirname "$0")"
python3 cc-time-menubar.py &
disown
osascript -e 'tell application "Terminal" to close front window' &
