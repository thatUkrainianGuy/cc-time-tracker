"""Tests for cc_time_tracker.common"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from cc_time_tracker.common import (
    extract_project_name,
    load_jsonl,
    ensure_dir,
    acquire_lock,
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
