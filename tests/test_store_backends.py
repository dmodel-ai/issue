"""Tests for both git and file storage backends."""
import pytest
import subprocess
from pathlib import Path

def test_git_backend_used_in_git_repo(tmp_path, monkeypatch):
    """Git backend is selected when in a git repo."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)

    original_run = subprocess.run
    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", tmp_path)
        return original_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", patched_run)

    # Force reimport to pick up patched subprocess
    import importlib
    import issue_tracker.store as store_pkg
    importlib.reload(store_pkg)

    from issue_tracker.store.git import save, load, all_issues

    save({"id": "gittest", "title": "Git Test", "status": "draft", "owner": "x"})

    # Verify issue saved to git branch
    result = subprocess.run(
        ["git", "show", "issues:gittest.yaml"],
        cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Git Test" in result.stdout

    # Verify no .issues directory created
    assert not (tmp_path / ".issues").exists()

def test_file_backend_used_outside_git_repo(tmp_path, monkeypatch):
    """File backend is selected when not in a git repo."""
    monkeypatch.chdir(tmp_path)

    # Patch subprocess.run to fail git commands (simulate non-git dir)
    original_run = subprocess.run
    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git" and "rev-parse" in cmd:
            result = original_run.__class__
            class FakeResult:
                returncode = 1
                stdout = ""
                stderr = "not a git repo"
            return FakeResult()
        return original_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", patched_run)

    from issue_tracker.store.file import save, load, all_issues, DIR
    monkeypatch.setattr("issue_tracker.store.file.DIR", tmp_path / ".issues")

    save({"id": "filetest", "title": "File Test", "status": "draft", "owner": "x"})

    # Verify issue saved to filesystem
    assert (tmp_path / ".issues" / "filetest.yaml").exists()
    content = (tmp_path / ".issues" / "filetest.yaml").read_text()
    assert "File Test" in content

def test_file_backend_respects_issue_dir_env(tmp_path, monkeypatch):
    """File backend uses ISSUE_DIR env var."""
    custom_dir = tmp_path / "custom_issues"
    monkeypatch.setenv("ISSUE_DIR", str(custom_dir))

    # Reimport to pick up env var
    import importlib
    import issue_tracker.store.file as file_backend
    importlib.reload(file_backend)

    file_backend.save({"id": "envtest", "title": "Env Test", "status": "draft", "owner": "x"})

    assert (custom_dir / "envtest.yaml").exists()

def test_git_backend_respects_issue_branch_env(tmp_path, monkeypatch):
    """Git backend uses ISSUE_BRANCH env var."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)

    monkeypatch.setenv("ISSUE_BRANCH", "custom-issues")

    original_run = subprocess.run
    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", tmp_path)
        return original_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", patched_run)

    # Reimport to pick up env var
    import importlib
    import issue_tracker.store.git as git_backend
    importlib.reload(git_backend)

    git_backend.save({"id": "branchtest", "title": "Branch Test", "status": "draft", "owner": "x"})

    # Verify custom branch exists
    result = subprocess.run(
        ["git", "branch", "--list", "custom-issues"],
        cwd=tmp_path, capture_output=True, text=True
    )
    assert "custom-issues" in result.stdout

def test_read_raw_write_raw_git(tmp_path, monkeypatch):
    """read_raw/write_raw work with git backend."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)

    original_run = subprocess.run
    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", tmp_path)
        return original_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", patched_run)

    import importlib
    import issue_tracker.store.git as git_backend
    importlib.reload(git_backend)

    # Write via save
    git_backend.save({"id": "rawtest", "title": "Raw Test", "status": "draft", "owner": "x"})

    # Read raw
    content = git_backend.read_raw("rawtest")
    assert "Raw Test" in content

    # Write raw (simulating editor save)
    new_content = content.replace("Raw Test", "Edited Test")
    git_backend.write_raw("rawtest", new_content)

    # Verify change
    updated = git_backend.read_raw("rawtest")
    assert "Edited Test" in updated

def test_read_raw_write_raw_file(tmp_path, monkeypatch):
    """read_raw/write_raw work with file backend."""
    import issue_tracker.store.file as file_backend
    monkeypatch.setattr(file_backend, "DIR", tmp_path / ".issues")

    # Write via save
    file_backend.save({"id": "rawtest", "title": "Raw Test", "status": "draft", "owner": "x"})

    # Read raw
    content = file_backend.read_raw("rawtest")
    assert "Raw Test" in content

    # Write raw
    new_content = content.replace("Raw Test", "Edited Test")
    file_backend.write_raw("rawtest", new_content)

    # Verify change
    updated = file_backend.read_raw("rawtest")
    assert "Edited Test" in updated
