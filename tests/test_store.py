import pytest
from issue_tracker.store import load, save, all_issues, index, num, resolve

def test_save_and_load():
    issue = {
        "id": "abc123",
        "title": "Test",
        "status": "draft",
        "owner": "me",
    }
    save(issue)
    loaded = load("abc123")
    assert loaded["title"] == "Test"
    assert "updated" in loaded

def test_all_issues_empty():
    assert all_issues() == []

def test_all_issues_returns_sorted():
    save({"id": "bbb", "title": "B", "status": "draft", "owner": "x"})
    save({"id": "aaa", "title": "A", "status": "draft", "owner": "x"})
    issues = all_issues()
    assert len(issues) == 2
    assert issues[0]["id"] == "aaa"

def test_index_and_num():
    save({"id": "first", "title": "First", "status": "draft", "owner": "x"})
    save({"id": "second", "title": "Second", "status": "draft", "owner": "x"})
    idx = index()
    assert len(idx) == 2
    assert num("first") in [1, 2]
    assert num("second") in [1, 2]

def test_resolve_by_number():
    save({"id": "myid123", "title": "Test", "status": "draft", "owner": "x"})
    idx = index()
    n = num("myid123")
    assert resolve(str(n)) == "myid123"

def test_resolve_by_uuid():
    # UUID is 32 chars
    uid = "a" * 32
    save({"id": uid, "title": "Test", "status": "draft", "owner": "x"})
    assert resolve(uid) == uid

def test_resolve_invalid():
    assert resolve("999") is None
    assert resolve("notauuid") is None

def test_resolve_by_alias():
    save({"id": "aliased123", "title": "Test", "status": "draft", "owner": "x", "alias": "myfeature"})
    assert resolve("myfeature") == "aliased123"
    assert resolve("nonexistent") is None
