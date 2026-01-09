"""End-to-end tests for multi-clone sync scenarios."""
import subprocess
import importlib
import time
import pytest


def setup_two_clones(tmp_path):
    """Set up a bare remote and two clones (alice and bob)."""
    real_run = subprocess._original_run

    remote = tmp_path / "remote.git"
    alice = tmp_path / "alice"
    bob = tmp_path / "bob"

    # Create bare remote
    real_run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    # Create alice clone
    real_run(["git", "clone", str(remote), str(alice)], check=True, capture_output=True)
    real_run(["git", "config", "user.email", "alice@test.com"], cwd=alice, check=True, capture_output=True)
    real_run(["git", "config", "user.name", "Alice"], cwd=alice, check=True, capture_output=True)
    real_run(["git", "commit", "--allow-empty", "-m", "init"], cwd=alice, check=True, capture_output=True)
    real_run(["git", "push", "-u", "origin", "master"], cwd=alice, check=True, capture_output=True)

    # Create bob clone
    real_run(["git", "clone", str(remote), str(bob)], check=True, capture_output=True)
    real_run(["git", "config", "user.email", "bob@test.com"], cwd=bob, check=True, capture_output=True)
    real_run(["git", "config", "user.name", "Bob"], cwd=bob, check=True, capture_output=True)

    return remote, alice, bob


def get_backend_for_path(path, monkeypatch):
    """Get a fresh git backend configured for the given path."""
    real_run = subprocess._original_run

    def patched_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[0] == "git":
            kwargs.setdefault("cwd", path)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", patched_run)

    import issue_tracker.store.git as git_backend
    importlib.reload(git_backend)
    return git_backend


def wait_for_fetch(backend):
    """Wait for any background fetch to complete."""
    if backend._fetch_thread and backend._fetch_thread.is_alive():
        backend._fetch_thread.join(timeout=5)


def test_e2e_basic_sync(tmp_path, monkeypatch):
    """Alice creates issue, Bob sees it after fetch."""
    remote, alice, bob = setup_two_clones(tmp_path)

    # Alice creates an issue
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.save({"id": "issue1", "title": "Alice's Issue", "status": "draft", "owner": "alice"})

    # Bob lists issues - first call triggers fetch, second shows results
    bob_backend = get_backend_for_path(bob, monkeypatch)
    issues = bob_backend.all_issues()
    assert len(issues) == 1
    assert issues[0]["title"] == "Alice's Issue"


def test_e2e_bidirectional_sync(tmp_path, monkeypatch):
    """Alice and Bob both create issues, both see all issues."""
    remote, alice, bob = setup_two_clones(tmp_path)

    # Alice creates first issue
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.save({"id": "issue1", "title": "From Alice", "status": "draft", "owner": "alice"})

    # Bob creates second issue (fetches Alice's first)
    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_backend.save({"id": "issue2", "title": "From Bob", "status": "draft", "owner": "bob"})

    # Both should see both issues
    bob_issues = bob_backend.all_issues()
    assert len(bob_issues) == 2

    # Alice needs two reads: first kicks off fetch, second merges
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.all_issues()  # Triggers background fetch
    wait_for_fetch(alice_backend)
    alice_issues = alice_backend.all_issues()  # Merges fetched changes
    assert len(alice_issues) == 2


def test_e2e_concurrent_edits_different_fields(tmp_path, monkeypatch):
    """Alice adds label, Bob adds priority to same issue - both preserved."""
    remote, alice, bob = setup_two_clones(tmp_path)

    # Alice creates issue
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.save({
        "id": "shared",
        "title": "Shared Issue",
        "status": "draft",
        "owner": "alice",
        "labels": [],
    })

    # Bob fetches the issue
    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_issue = bob_backend.load("shared")
    assert bob_issue is not None

    # Alice adds a label
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_issue = alice_backend.load("shared")
    alice_issue["labels"] = ["bug"]
    alice_backend.save(alice_issue)

    # Bob adds priority (before fetching Alice's change)
    # Reset Bob's local to before Alice's label change to simulate concurrent edit
    real_run = subprocess._original_run
    bob_commit = real_run(
        ["git", "rev-parse", "issues~1"], cwd=bob, capture_output=True, text=True
    ).stdout.strip()
    real_run(["git", "update-ref", "refs/heads/issues", bob_commit], cwd=bob, check=True, capture_output=True)

    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_issue = bob_backend.load("shared")
    bob_issue["priority"] = 5
    bob_backend.save(bob_issue)  # This should merge with Alice's change

    # Verify both changes present
    final = bob_backend.load("shared")
    assert final["labels"] == ["bug"], "Alice's label should be preserved"
    assert final["priority"] == 5, "Bob's priority should be preserved"

    # Alice needs two reads to see Bob's changes
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.load("shared")  # Triggers background fetch
    wait_for_fetch(alice_backend)
    alice_final = alice_backend.load("shared")  # Merges fetched changes
    assert alice_final["labels"] == ["bug"]
    assert alice_final["priority"] == 5


def test_e2e_concurrent_edits_same_field_same_value(tmp_path, monkeypatch):
    """Both change same field to same value - no conflict."""
    remote, alice, bob = setup_two_clones(tmp_path)

    # Alice creates issue
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.save({
        "id": "sameval",
        "title": "Same Value Test",
        "status": "draft",
        "owner": "alice",
    })

    # Bob fetches
    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_backend.load("sameval")

    # Both change status to "pqa"
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_issue = alice_backend.load("sameval")
    alice_issue["status"] = "pqa"
    alice_backend.save(alice_issue)

    # Reset Bob to before Alice's change
    real_run = subprocess._original_run
    bob_commit = real_run(
        ["git", "rev-parse", "issues~1"], cwd=bob, capture_output=True, text=True
    ).stdout.strip()
    real_run(["git", "update-ref", "refs/heads/issues", bob_commit], cwd=bob, check=True, capture_output=True)

    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_issue = bob_backend.load("sameval")
    bob_issue["status"] = "pqa"  # Same value as Alice
    bob_backend.save(bob_issue)

    # Should merge cleanly
    final = bob_backend.load("sameval")
    assert final["status"] == "pqa"


def test_e2e_fast_forward_on_read(tmp_path, monkeypatch):
    """Reading issues fast-forwards local branch to remote."""
    remote, alice, bob = setup_two_clones(tmp_path)
    real_run = subprocess._original_run

    # Alice creates multiple issues
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.save({"id": "ff1", "title": "FF 1", "status": "draft", "owner": "alice"})
    alice_backend.save({"id": "ff2", "title": "FF 2", "status": "draft", "owner": "alice"})
    alice_backend.save({"id": "ff3", "title": "FF 3", "status": "draft", "owner": "alice"})

    # Bob reads - should fast-forward
    bob_backend = get_backend_for_path(bob, monkeypatch)
    issues = bob_backend.all_issues()
    assert len(issues) == 3

    # Verify Bob's local branch matches remote
    bob_local = real_run(
        ["git", "rev-parse", "issues"], cwd=bob, capture_output=True, text=True
    ).stdout.strip()
    bob_remote = real_run(
        ["git", "rev-parse", "origin/issues"], cwd=bob, capture_output=True, text=True
    ).stdout.strip()
    assert bob_local == bob_remote


def test_e2e_offline_then_sync(tmp_path, monkeypatch):
    """Work offline, then sync when connection restored."""
    remote, alice, bob = setup_two_clones(tmp_path)
    real_run = subprocess._original_run

    # Alice creates initial issue
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.save({"id": "online1", "title": "Online Issue", "status": "draft", "owner": "alice"})

    # Bob goes "offline" by breaking his remote URL
    real_run(
        ["git", "remote", "set-url", "origin", "/nonexistent/path"],
        cwd=bob, check=True, capture_output=True
    )

    # Bob creates issue while offline
    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_backend.save({"id": "offline1", "title": "Offline Issue", "status": "draft", "owner": "bob"})

    # Verify Bob's issue is saved locally
    bob_issue = bob_backend.load("offline1")
    assert bob_issue["title"] == "Offline Issue"

    # Bob comes back online
    real_run(
        ["git", "remote", "set-url", "origin", str(remote)],
        cwd=bob, check=True, capture_output=True
    )

    # Bob syncs by saving another change
    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_issue = bob_backend.load("offline1")
    bob_issue["labels"] = ["was-offline"]
    bob_backend.save(bob_issue)

    # Verify Bob now has Alice's issue too
    bob_issues = bob_backend.all_issues()
    assert len(bob_issues) == 2

    # Alice needs two reads to see Bob's offline issue
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.all_issues()  # Triggers background fetch
    wait_for_fetch(alice_backend)
    alice_issues = alice_backend.all_issues()  # Merges fetched changes
    assert len(alice_issues) == 2
    offline_issue = next(i for i in alice_issues if i["id"] == "offline1")
    assert offline_issue["labels"] == ["was-offline"]


def test_e2e_three_way_merge_lists(tmp_path, monkeypatch):
    """Three-way merge correctly unions list fields."""
    remote, alice, bob = setup_two_clones(tmp_path)
    real_run = subprocess._original_run

    # Alice creates issue with initial labels
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_backend.save({
        "id": "lists",
        "title": "List Merge Test",
        "status": "draft",
        "owner": "alice",
        "labels": ["initial"],
        "cc": [],
    })

    # Bob fetches
    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_backend.load("lists")

    # Alice adds a label
    alice_backend = get_backend_for_path(alice, monkeypatch)
    alice_issue = alice_backend.load("lists")
    alice_issue["labels"] = ["initial", "alice-added"]
    alice_backend.save(alice_issue)

    # Reset Bob to before Alice's change
    bob_commit = real_run(
        ["git", "rev-parse", "issues~1"], cwd=bob, capture_output=True, text=True
    ).stdout.strip()
    real_run(["git", "update-ref", "refs/heads/issues", bob_commit], cwd=bob, check=True, capture_output=True)

    # Bob adds different label and cc
    bob_backend = get_backend_for_path(bob, monkeypatch)
    bob_issue = bob_backend.load("lists")
    bob_issue["labels"] = ["initial", "bob-added"]
    bob_issue["cc"] = ["reviewer@test.com"]
    bob_backend.save(bob_issue)

    # Verify all additions are present (union)
    final = bob_backend.load("lists")
    assert set(final["labels"]) == {"initial", "alice-added", "bob-added"}
    assert final["cc"] == ["reviewer@test.com"]
