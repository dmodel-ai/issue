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


def setup_git_repo_with_remote(tmp_path):
    """Helper to set up a git repo with a bare remote. Uses real subprocess to avoid conftest patch."""
    real_run = subprocess._original_run

    remote_path = tmp_path / "remote.git"
    local_path = tmp_path / "local"

    # Create bare remote
    real_run(["git", "init", "--bare", str(remote_path)], check=True, capture_output=True)

    # Create local repo
    real_run(["git", "clone", str(remote_path), str(local_path)], check=True, capture_output=True)
    real_run(["git", "config", "user.email", "test@test.com"], cwd=local_path, check=True, capture_output=True)
    real_run(["git", "config", "user.name", "Test"], cwd=local_path, check=True, capture_output=True)
    # Create initial commit
    real_run(["git", "commit", "--allow-empty", "-m", "init"], cwd=local_path, capture_output=True, check=True)

    return local_path, remote_path


def test_try_merge_fast_forward(tmp_path, monkeypatch):
    """_try_merge fast-forwards local when behind remote."""
    real_run = subprocess._original_run
    local_path, remote_path = setup_git_repo_with_remote(tmp_path)

    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", local_path)
        return real_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", patched_run)

    import importlib
    import issue_tracker.store.git as git_backend
    importlib.reload(git_backend)

    # Create issue on local
    git_backend.save({"id": "fftest", "title": "FF Test", "status": "draft", "owner": "x"})

    # Manually push the issues branch to remote (since _try_sync needs remote branch to exist)
    real_run(["git", "push", "-u", "origin", "issues"], cwd=local_path, check=True, capture_output=True)

    local_commit = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    # Simulate remote advancing: clone to another dir, make change, push
    other_path = tmp_path / "other"
    real_run(["git", "clone", str(remote_path), str(other_path)], check=True, capture_output=True)
    real_run(["git", "config", "user.email", "other@test.com"], cwd=other_path, check=True, capture_output=True)
    real_run(["git", "config", "user.name", "Other"], cwd=other_path, check=True, capture_output=True)
    real_run(["git", "fetch", "origin", "issues:issues"], cwd=other_path, check=True, capture_output=True)
    real_run(["git", "checkout", "issues"], cwd=other_path, check=True, capture_output=True)

    # Create another issue from other clone
    def other_patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", other_path)
        return real_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", other_patched_run)
    importlib.reload(git_backend)
    git_backend.save({"id": "fftest2", "title": "FF Test 2", "status": "draft", "owner": "y"})

    # Verify push worked (remote branch exists now, so _try_sync should push)
    remote_refs = real_run(
        ["git", "ls-remote", str(remote_path), "refs/heads/issues"], capture_output=True, text=True
    ).stdout.strip()
    assert remote_refs, "Remote should have issues branch after save"

    # Restore local patching
    monkeypatch.setattr(subprocess, "run", patched_run)
    importlib.reload(git_backend)

    # Reset local to before remote changes
    real_run(["git", "update-ref", "refs/heads/issues", local_commit], cwd=local_path, check=True, capture_output=True)

    # Fetch remote changes
    real_run(["git", "fetch", "origin", "issues:refs/remotes/origin/issues"], cwd=local_path, check=True, capture_output=True)

    before = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()
    remote_result = real_run(
        ["git", "rev-parse", "origin/issues"], cwd=local_path, capture_output=True, text=True
    )
    assert remote_result.returncode == 0, f"Failed to resolve origin/issues: {remote_result.stderr}"
    remote = remote_result.stdout.strip()

    assert before == local_commit
    assert before != remote

    # Call _try_merge
    git_backend._try_merge()

    after = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    assert after == remote, "Local should have fast-forwarded to remote"


def test_try_merge_already_in_sync(tmp_path, monkeypatch):
    """_try_merge does nothing when already in sync."""
    real_run = subprocess._original_run
    local_path, remote_path = setup_git_repo_with_remote(tmp_path)

    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", local_path)
        return real_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", patched_run)

    import importlib
    import issue_tracker.store.git as git_backend
    importlib.reload(git_backend)

    git_backend.save({"id": "synctest", "title": "Sync Test", "status": "draft", "owner": "x"})

    # Push to remote and fetch so origin/issues exists and matches local
    real_run(["git", "push", "-u", "origin", "issues"], cwd=local_path, check=True, capture_output=True)
    real_run(["git", "fetch", "origin", "issues:refs/remotes/origin/issues"], cwd=local_path, capture_output=True)

    before = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    git_backend._try_merge()

    after = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    assert before == after


def test_try_merge_local_ahead(tmp_path, monkeypatch):
    """_try_merge does nothing when local is ahead of remote."""
    real_run = subprocess._original_run
    local_path, remote_path = setup_git_repo_with_remote(tmp_path)

    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", local_path)
        return real_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", patched_run)

    import importlib
    import issue_tracker.store.git as git_backend
    importlib.reload(git_backend)

    # Create issue and push
    git_backend.save({"id": "aheadtest", "title": "Ahead Test", "status": "draft", "owner": "x"})
    real_run(["git", "push", "-u", "origin", "issues"], cwd=local_path, check=True, capture_output=True)

    pushed_commit = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    # Create another local commit without pushing (local ahead)
    monkeypatch.setenv("ISSUE_SYNC", "0")  # Disable auto-sync for this save
    importlib.reload(git_backend)
    git_backend.save({"id": "aheadtest2", "title": "Ahead Test 2", "status": "draft", "owner": "x"})

    # Fetch to make sure origin/issues exists
    real_run(["git", "fetch", "origin", "issues:refs/remotes/origin/issues"], cwd=local_path, capture_output=True)

    before = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    assert before != pushed_commit  # We're ahead

    monkeypatch.delenv("ISSUE_SYNC", raising=False)
    importlib.reload(git_backend)

    git_backend._try_merge()

    after = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    assert before == after, "Local ahead should not change"


def test_ensure_read_setup_triggers_merge(tmp_path, monkeypatch):
    """_ensure_read_setup triggers merge from previous fetch."""
    real_run = subprocess._original_run
    local_path, remote_path = setup_git_repo_with_remote(tmp_path)

    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", local_path)
        return real_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", patched_run)

    import importlib
    import issue_tracker.store.git as git_backend
    importlib.reload(git_backend)

    # Create initial issue and push
    git_backend.save({"id": "readtest", "title": "Read Test", "status": "draft", "owner": "x"})
    real_run(["git", "push", "-u", "origin", "issues"], cwd=local_path, check=True, capture_output=True)

    local_commit = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    # Simulate remote change via other clone
    other_path = tmp_path / "other"
    real_run(["git", "clone", str(remote_path), str(other_path)], check=True, capture_output=True)
    real_run(["git", "config", "user.email", "other@test.com"], cwd=other_path, check=True, capture_output=True)
    real_run(["git", "config", "user.name", "Other"], cwd=other_path, check=True, capture_output=True)
    real_run(["git", "fetch", "origin", "issues:issues"], cwd=other_path, check=True, capture_output=True)
    real_run(["git", "checkout", "issues"], cwd=other_path, check=True, capture_output=True)

    def other_patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", other_path)
        return real_run(cmd, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", other_patched_run)
    importlib.reload(git_backend)
    git_backend.save({"id": "readtest2", "title": "Read Test 2", "status": "draft", "owner": "y"})

    # Reset local and fetch
    monkeypatch.setattr(subprocess, "run", patched_run)
    importlib.reload(git_backend)
    real_run(["git", "update-ref", "refs/heads/issues", local_commit], cwd=local_path, check=True, capture_output=True)
    real_run(["git", "fetch", "origin", "issues:refs/remotes/origin/issues"], cwd=local_path, check=True, capture_output=True)

    remote_commit = real_run(
        ["git", "rev-parse", "origin/issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    # all_issues() should trigger merge via _ensure_read_setup
    issues = git_backend.all_issues()

    after = real_run(
        ["git", "rev-parse", "issues"], cwd=local_path, capture_output=True, text=True
    ).stdout.strip()

    assert after == remote_commit, "Read should have triggered merge"
    assert len(issues) == 2
