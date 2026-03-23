"""Tests for cc_time_tracker.uninstall_cmd"""

import json
from pathlib import Path

from cc_time_tracker.uninstall_cmd import remove_hooks


def test_remove_hooks_cleans_settings(tmp_path):
    """Should remove cc_time_tracker hooks from settings."""
    settings_file = tmp_path / "settings.json"
    settings = {
        "hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": "/usr/bin/python3 -m cc_time_tracker.start_hook"}]},
            ],
            "SessionEnd": [
                {"matcher": "", "hooks": [{"type": "command", "command": "/usr/bin/python3 -m cc_time_tracker.end_hook"}]},
            ],
            "PreToolUse": [
                {"matcher": "Write", "hooks": [{"type": "prompt", "prompt": "check"}]},
            ],
        },
        "other": True,
    }
    settings_file.write_text(json.dumps(settings))

    remove_hooks(settings_file)

    result = json.loads(settings_file.read_text())
    assert result["other"] is True
    assert "PreToolUse" in result["hooks"]
    assert result["hooks"]["SessionStart"] == []
    assert result["hooks"]["SessionEnd"] == []


def test_remove_hooks_no_settings_file(tmp_path):
    """Should handle missing settings.json gracefully."""
    settings_file = tmp_path / "settings.json"
    remove_hooks(settings_file)  # should not raise


def test_remove_hooks_preserves_other_session_hooks(tmp_path):
    """Should only remove cc_time_tracker hooks, not other SessionStart hooks."""
    settings_file = tmp_path / "settings.json"
    settings = {
        "hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": "some-other-hook"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": "/usr/bin/python3 -m cc_time_tracker.start_hook"}]},
            ],
        },
    }
    settings_file.write_text(json.dumps(settings))

    remove_hooks(settings_file)

    result = json.loads(settings_file.read_text())
    assert len(result["hooks"]["SessionStart"]) == 1
    assert "some-other-hook" in result["hooks"]["SessionStart"][0]["hooks"][0]["command"]
