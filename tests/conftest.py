import pytest
from pathlib import Path
import issue_tracker.utils as utils

@pytest.fixture(autouse=True)
def isolate_issues(tmp_path, monkeypatch):
    """Use a temp directory for .issues in all tests."""
    monkeypatch.setattr(utils, "DIR", tmp_path / ".issues")
    monkeypatch.setattr("issue_tracker.store.DIR", tmp_path / ".issues")
    monkeypatch.setattr("issue_tracker.cli.commands.DIR", tmp_path / ".issues")

@pytest.fixture
def mock_user(monkeypatch):
    """Mock git user to 'testuser'."""
    monkeypatch.setattr(utils, "user", lambda: "testuser")
    monkeypatch.setattr("issue_tracker.cli.views.user", lambda: "testuser")
    monkeypatch.setattr("issue_tracker.cli.commands.user", lambda: "testuser")
