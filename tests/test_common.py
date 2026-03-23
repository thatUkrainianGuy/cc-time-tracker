"""Tests for cc_time_tracker.common"""

import json
import tempfile
from pathlib import Path

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
