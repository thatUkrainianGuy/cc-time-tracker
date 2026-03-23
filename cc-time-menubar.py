#!/usr/bin/env python3
"""
macOS menu bar app for Claude Code time tracking.
Shows today's total session time in the menu bar.
Click to see per-project breakdown with active session indicators.

Usage:
    python3 cc-time-menubar.py

Requires: pip install rumps
"""


def format_duration(seconds: float) -> str:
    """Format seconds into menu-bar-friendly duration string.

    Unlike cc-time-report.py, this skips seconds entirely to avoid
    visual noise in the menu bar. Always shows at least '0m'.
    """
    total_minutes = int(seconds // 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes}m"
