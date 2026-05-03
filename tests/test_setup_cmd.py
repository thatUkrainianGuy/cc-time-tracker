"""Tests for cc_time_tracker.setup_cmd"""

import json
from pathlib import Path
from unittest.mock import patch

from cc_time_tracker.setup_cmd import merge_hooks, is_already_installed


def test_merge_hooks_fresh_settings(tmp_path):
    """Should create hooks section in empty settings."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")

    merge_hooks(settings_file, "/usr/bin/python3")

    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings
    assert "SessionStart" in settings["hooks"]
    assert "SessionEnd" in settings["hooks"]
    assert "/usr/bin/python3 -m cc_time_tracker.start_hook" in settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]


def test_merge_hooks_preserves_existing(tmp_path):
    """Should not overwrite existing hooks."""
    settings_file = tmp_path / "settings.json"
    existing = {
        "hooks": {
            "PreToolUse": [{"matcher": "Write", "hooks": [{"type": "prompt", "prompt": "check"}]}]
        },
        "other_setting": True,
    }
    settings_file.write_text(json.dumps(existing))

    merge_hooks(settings_file, "/usr/bin/python3")

    settings = json.loads(settings_file.read_text())
    assert "PreToolUse" in settings["hooks"]
    assert settings["other_setting"] is True
    assert "SessionStart" in settings["hooks"]


def test_merge_hooks_idempotent(tmp_path):
    """Running merge twice should not duplicate hooks."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")

    merge_hooks(settings_file, "/usr/bin/python3")
    merge_hooks(settings_file, "/usr/bin/python3")

    settings = json.loads(settings_file.read_text())
    assert len(settings["hooks"]["SessionStart"]) == 1


def test_is_already_installed_true(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings = {"hooks": {"SessionStart": [{"hooks": [{"command": "/usr/bin/python3 -m cc_time_tracker.start_hook"}]}]}}
    settings_file.write_text(json.dumps(settings))
    assert is_already_installed(settings_file) is True


def test_is_already_installed_false(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}")
    assert is_already_installed(settings_file) is False


def test_merge_hooks_creates_settings_file(tmp_path):
    """Should create settings.json if it doesn't exist."""
    settings_file = tmp_path / "settings.json"
    merge_hooks(settings_file, "/usr/bin/python3")
    assert settings_file.exists()
    settings = json.loads(settings_file.read_text())
    assert "SessionStart" in settings["hooks"]


def test_merge_hooks_quotes_python_path_with_spaces(tmp_path):
    """A Python path containing spaces must be shell-quoted in the command."""
    settings_file = tmp_path / "settings.json"
    weird_path = "/Applications/My Apps/python3"
    merge_hooks(settings_file, weird_path)

    settings = json.loads(settings_file.read_text())
    cmd = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    # shlex.quote wraps in single quotes when whitespace is present.
    assert cmd.startswith("'/Applications/My Apps/python3'")
    assert cmd.endswith("-m cc_time_tracker.start_hook")
