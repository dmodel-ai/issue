import pytest
import subprocess
import issue_tracker.utils as utils

# Save original run for tests that need it
subprocess._original_run = subprocess.run

@pytest.fixture(autouse=True)
def isolate_issues(tmp_path, monkeypatch):
    """Use a temp git repo with unique branch for all tests."""
    # Initialize a temp git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)

    # Patch git functions to run in temp repo
    original_run = subprocess.run

    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", tmp_path)
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", patched_run)

@pytest.fixture
def mock_user(monkeypatch):
    """Mock git user to 'testuser'."""
    monkeypatch.setattr(utils, "user", lambda: "testuser")
    monkeypatch.setattr("issue_tracker.cli.views.user", lambda: "testuser")
    monkeypatch.setattr("issue_tracker.cli.commands.user", lambda: "testuser")
