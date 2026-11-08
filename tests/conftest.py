import pytest


@pytest.fixture(autouse=True)
def _isolated_projects_dir(tmp_path, monkeypatch):
    """Keep transcript lookups away from the real ~/.claude/projects."""
    projects = tmp_path / "cc-projects"
    projects.mkdir()
    monkeypatch.setattr("cc_time_tracker.active_time.PROJECTS_DIR", projects)
    return projects
