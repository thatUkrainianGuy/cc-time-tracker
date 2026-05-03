"""Tests for cc_time_tracker.common"""

import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

from cc_time_tracker.common import (
    PROJECT_NAME_MAX_LEN,
    extract_project_name,
    load_jsonl,
    ensure_dir,
    acquire_lock,
    is_tracker_hook_group,
    strip_control,
    csv_safe,
    md_safe,
    clamp_project_name,
    coerce_float,
    coerce_int,
)


def test_extract_project_name_simple():
    assert extract_project_name("/home/user/projects/myapp") == "myapp"


def test_extract_project_name_trailing_slash():
    assert extract_project_name("/home/user/projects/myapp/") == "myapp"


def test_extract_project_name_root():
    assert extract_project_name("/") == ""


def test_extract_project_name_walks_up_to_git_dir(tmp_path):
    """A subfolder of a git repo should resolve to the repo root's basename."""
    repo = tmp_path / "myapp"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "workers"
    sub.mkdir()

    with patch("cc_time_tracker.common.Path.home", return_value=tmp_path):
        assert extract_project_name(str(sub)) == "myapp"


def test_extract_project_name_walks_up_to_git_file(tmp_path):
    """A `.git` file (worktree pointer) should be detected, not just dirs."""
    repo = tmp_path / "myapp"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /elsewhere\n")
    sub = repo / "deep" / "nested"
    sub.mkdir(parents=True)

    with patch("cc_time_tracker.common.Path.home", return_value=tmp_path):
        assert extract_project_name(str(sub)) == "myapp"


def test_extract_project_name_cc_project_override(tmp_path):
    """`.cc-project` contents should override the directory basename."""
    repo = tmp_path / "myapp"
    repo.mkdir()
    (repo / ".cc-project").write_text("custom-name\n")
    sub = repo / "workers"
    sub.mkdir()

    with patch("cc_time_tracker.common.Path.home", return_value=tmp_path):
        assert extract_project_name(str(sub)) == "custom-name"


def test_extract_project_name_cc_project_empty_uses_dir(tmp_path):
    """An empty `.cc-project` marker should use the marker's directory name."""
    repo = tmp_path / "no-git-project"
    repo.mkdir()
    (repo / ".cc-project").write_text("")
    sub = repo / "subdir"
    sub.mkdir()

    with patch("cc_time_tracker.common.Path.home", return_value=tmp_path):
        assert extract_project_name(str(sub)) == "no-git-project"


def test_extract_project_name_cc_project_beats_git(tmp_path):
    """When both markers exist, `.cc-project` wins (explicit > implicit)."""
    repo = tmp_path / "myapp"
    (repo / ".git").mkdir(parents=True)
    (repo / ".cc-project").write_text("renamed\n")

    with patch("cc_time_tracker.common.Path.home", return_value=tmp_path):
        assert extract_project_name(str(repo)) == "renamed"


def test_extract_project_name_no_marker_falls_back(tmp_path):
    """Without any marker, fall back to basename(cwd)."""
    sub = tmp_path / "loose" / "folder"
    sub.mkdir(parents=True)

    with patch("cc_time_tracker.common.Path.home", return_value=tmp_path):
        assert extract_project_name(str(sub)) == "folder"


def test_extract_project_name_stops_at_home(tmp_path):
    """Walk must not cross $HOME — a `.git` in home shouldn't claim sessions."""
    home = tmp_path
    (home / ".git").mkdir()  # dotfiles repo at $HOME
    sub = home / "scratch" / "experiment"
    sub.mkdir(parents=True)

    with patch("cc_time_tracker.common.Path.home", return_value=home):
        # Should NOT return "tmp_path basename" — should fall back to "experiment"
        assert extract_project_name(str(sub)) == "experiment"


def test_load_jsonl_empty_file(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text("")
    assert load_jsonl(f) == []


def test_load_jsonl_with_records(tmp_path):
    f = tmp_path / "test.jsonl"
    records = [{"a": 1}, {"b": 2}]
    f.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    assert load_jsonl(f) == records


def test_load_jsonl_skips_bad_lines(tmp_path):
    f = tmp_path / "test.jsonl"
    f.write_text('{"a": 1}\ngarbage\n{"b": 2}\n')
    assert load_jsonl(f) == [{"a": 1}, {"b": 2}]


def test_load_jsonl_missing_file(tmp_path):
    f = tmp_path / "nonexistent.jsonl"
    assert load_jsonl(f) == []


def test_ensure_dir(tmp_path):
    d = tmp_path / "sub" / "dir"
    ensure_dir(d)
    assert d.is_dir()


def test_acquire_lock_returns_context_manager():
    lock = acquire_lock(Path(tempfile.gettempdir()) / "test.lock")
    with lock:
        pass  # should not raise


# ─── Sanitization ──────────────────────────────────────────────────────


def test_strip_control_removes_ansi():
    assert strip_control("\x1b[31mred\x1b[0m") == "red"


def test_strip_control_removes_osc_hyperlink():
    """OSC 8 hyperlinks (used to spoof URLs) must be stripped."""
    s = "\x1b]8;;https://evil/\x1b\\click\x1b]8;;\x1b\\"
    assert strip_control(s) == "click"


def test_strip_control_removes_c0_and_del():
    assert strip_control("a\x00b\x07c\x7fd") == "abcd"


def test_strip_control_truncates():
    assert strip_control("a" * 200, max_len=10) == "a" * 10


def test_strip_control_handles_non_string():
    assert strip_control(None) == ""
    assert strip_control(42) == "42"


def test_csv_safe_escapes_formulas():
    """Formula-leading values must be neutralized for Excel/Sheets."""
    for lead in ("=", "+", "-", "@"):
        assert csv_safe(f"{lead}HYPERLINK").startswith("'"), lead


def test_csv_safe_strips_leading_tab_and_cr():
    """Tab/CR can prefix a formula in Excel — we drop them as control chars,
    which makes the resulting field unable to begin a formula at all."""
    assert csv_safe("\tcmd") == "cmd"
    assert csv_safe("\rcmd") == "cmd"
    assert csv_safe("\t=SUM(1)") == "'=SUM(1)"  # leading tab gone, then '=' escaped


def test_csv_safe_strips_control_chars():
    assert csv_safe("hello\x1b[31m\x00world") == "helloworld"


def test_csv_safe_passes_through_safe_text():
    assert csv_safe("my-project") == "my-project"


def test_md_safe_escapes_pipes():
    assert md_safe("a|b|c") == r"a\|b\|c"


def test_md_safe_strips_newlines():
    """Embedded newlines would let a project name break out of the table row."""
    assert "\n" not in md_safe("foo\n# heading")


def test_clamp_project_name_caps_length():
    assert len(clamp_project_name("x" * 500)) == PROJECT_NAME_MAX_LEN


def test_clamp_project_name_strips_ansi():
    assert clamp_project_name("\x1b[31mhostile\x1b[0m") == "hostile"


# ─── Type coercion ─────────────────────────────────────────────────────


def test_coerce_float_passes_numbers():
    assert coerce_float(3.14) == 3.14
    assert coerce_float(7) == 7.0


def test_coerce_float_parses_string():
    assert coerce_float("2.5") == 2.5


def test_coerce_float_returns_default_on_bad_input():
    assert coerce_float("nope", default=99.0) == 99.0
    assert coerce_float(None) == 0.0
    assert coerce_float({"a": 1}) == 0.0


def test_coerce_float_rejects_bool():
    """bool is a subclass of int — but 'True' as a timestamp is meaningless."""
    assert coerce_float(True, default=0.0) == 0.0


def test_coerce_int_handles_strings_and_bad_input():
    assert coerce_int("42") == 42
    assert coerce_int("not a pid") is None
    assert coerce_int(None) is None
    assert coerce_int(True) is None


# ─── Bounded .cc-project ───────────────────────────────────────────────


def test_extract_project_name_bounds_marker_read(tmp_path):
    """A multi-MB marker must not be read whole."""
    repo = tmp_path / "myapp"
    repo.mkdir()
    huge = "X" * (5 * 1024 * 1024)
    (repo / ".cc-project").write_text(huge)

    with patch("cc_time_tracker.common.Path.home", return_value=tmp_path):
        result = extract_project_name(str(repo))
    # Should be clamped to PROJECT_NAME_MAX_LEN, not the original 5MB blob
    assert len(result) <= PROJECT_NAME_MAX_LEN
    assert result == "X" * PROJECT_NAME_MAX_LEN


def test_extract_project_name_strips_control_chars(tmp_path):
    """A marker with ANSI escapes shouldn't yield a project name that prints them."""
    repo = tmp_path / "myapp"
    repo.mkdir()
    (repo / ".cc-project").write_text("\x1b[31mhostile\x1b[0m\n")

    with patch("cc_time_tracker.common.Path.home", return_value=tmp_path):
        result = extract_project_name(str(repo))
    assert result == "hostile"


# ─── load_jsonl validation ─────────────────────────────────────────────


def test_load_jsonl_skips_non_dict_records(tmp_path):
    """Lists, scalars, and nulls at top level must not pollute results."""
    f = tmp_path / "test.jsonl"
    f.write_text('{"a": 1}\n[1,2,3]\n42\nnull\n"string"\n{"b": 2}\n')
    assert load_jsonl(f) == [{"a": 1}, {"b": 2}]


def test_load_jsonl_after_ts_tolerates_bad_timestamp(tmp_path):
    """A poisoned ``timestamp_unix`` (string) must not crash time-bounded reads."""
    f = tmp_path / "test.jsonl"
    f.write_text(
        json.dumps({"timestamp_unix": "x", "k": 1}) + "\n"
        + json.dumps({"timestamp_unix": 100, "k": 2}) + "\n"
        + json.dumps({"timestamp_unix": 200, "k": 3}) + "\n"
    )
    # Bad ts coerces to 0.0 which is < 150, so record 1 is filtered like an
    # old record. Records 2 (100 < 150) is also filtered. Only 3 remains.
    assert load_jsonl(f, after_ts=150) == [{"timestamp_unix": 200, "k": 3}]


# ─── Hook detection ────────────────────────────────────────────────────


def test_is_tracker_hook_group_matches_module_token():
    group = {"hooks": [{"command": "/usr/bin/python3 -m cc_time_tracker.start_hook"}]}
    assert is_tracker_hook_group(group) is True


def test_is_tracker_hook_group_ignores_substring_only_match():
    """A user hook that merely mentions 'cc_time_tracker' must not be claimed."""
    group = {"hooks": [{"command": "echo 'see cc_time_tracker for inspiration'"}]}
    assert is_tracker_hook_group(group) is False


def test_is_tracker_hook_group_detects_end_hook():
    group = {"hooks": [{"command": "python3 -m cc_time_tracker.end_hook"}]}
    assert is_tracker_hook_group(group) is True


# ─── Permissions ───────────────────────────────────────────────────────


def test_ensure_dir_uses_0700(tmp_path):
    target = tmp_path / "tracking"
    ensure_dir(target)
    mode = stat.S_IMODE(os.stat(target).st_mode)
    # owner-only — no group/other bits
    assert mode & 0o077 == 0
    assert mode & 0o700 == 0o700
