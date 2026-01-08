import pytest
from issue_tracker.machine import StateMachine
from issue_tracker.workflows import kanban

m = StateMachine(kanban)


def make_issue(**kw):
    return {
        "id": "test123",
        "status": "backlog",
        "owner": "alice",
        "attention": [],
        "blocked_by": [],
        "blocks": [],
        **kw,
    }


def test_groom_moves_to_ready():
    issue = make_issue()
    m.transition(issue, "groom")
    assert issue["status"] == "ready"
    assert issue["attention"] == ["alice"]


def test_start_assigns_and_moves_to_in_progress():
    issue = make_issue(status="ready")
    m.transition(issue, "start", u="bob")
    assert issue["status"] == "in_progress"
    assert issue["assignee"] == "bob"
    assert issue["attention"] == ["bob"]


def test_block_moves_to_blocked():
    issue = make_issue(status="in_progress", assignee="bob")
    m.transition(issue, "block", reason="waiting on API")
    assert issue["status"] == "blocked"
    assert issue["block_reason"] == "waiting on API"
    assert issue["attention"] == ["alice"]


def test_unblock_moves_to_in_progress():
    issue = make_issue(status="blocked", assignee="bob", block_reason="x")
    m.transition(issue, "unblock")
    assert issue["status"] == "in_progress"
    assert "block_reason" not in issue
    assert issue["attention"] == ["bob"]


def test_finish_moves_to_done():
    issue = make_issue(status="in_progress")
    m.transition(issue, "finish")
    assert issue["status"] == "done"
    assert issue["attention"] == []


def test_wontfix_from_any_active():
    for status in kanban.active:
        issue = make_issue(status=status)
        m.transition(issue, "wontfix")
        assert issue["status"] == "wontfix"


def test_reopen_from_terminal():
    for status in kanban.terminal:
        issue = make_issue(status=status)
        m.transition(issue, "reopen")
        assert issue["status"] == "backlog"


def test_invalid_transition():
    issue = make_issue(status="done")
    with pytest.raises(SystemExit):
        m.transition(issue, "finish")
