import pytest
from issue_tracker.state import transition, pending


def make_issue(**kw):
    return {
        "id": "test123",
        "title": "Test",
        "status": "draft",
        "owner": "alice",
        "reviewers": [],
        "approved_by": [],
        "attention": ["alice"],
        "comments": [],
        "blocked_by": [],
        "blocks": [],
        **kw,
    }


def test_review_moves_to_review():
    issue = make_issue(reviewers=["bob"])
    transition(issue, "review")
    assert issue["status"] == "review"
    assert issue["attention"] == ["bob"]


def test_review_no_reviewers():
    issue = make_issue()
    transition(issue, "review")
    assert issue["status"] == "review"
    assert issue["attention"] == ["alice"]


def test_comment_shifts_attention_to_owner():
    issue = make_issue(status="review", attention=["bob"])
    transition(issue, "comment", u="bob", text="looks good")
    assert issue["attention"] == ["alice"]
    assert len(issue["comments"]) == 1


def test_comment_by_owner_shifts_to_reviewers():
    issue = make_issue(status="review", reviewers=["bob"], attention=["alice"])
    transition(issue, "comment", u="alice", text="updated")
    assert issue["attention"] == ["bob"]


def test_approve_requires_reviewer():
    issue = make_issue(status="review", reviewers=["bob"])
    with pytest.raises(SystemExit):
        transition(issue, "approve", u="charlie")


def test_approve_moves_to_approved():
    issue = make_issue(status="review", reviewers=["bob"])
    transition(issue, "approve", u="bob")
    assert issue["status"] == "approved"
    assert "bob" in issue["approved_by"]


def test_approve_partial():
    issue = make_issue(status="review", reviewers=["bob", "carol"])
    transition(issue, "approve", u="bob")
    assert issue["status"] == "review"  # not all approved yet
    assert issue["attention"] == ["carol"]


def test_complete_clears_attention():
    issue = make_issue(status="approved")
    transition(issue, "complete")
    assert issue["status"] == "completed"
    assert issue["attention"] == []


def test_abandon():
    issue = make_issue()
    transition(issue, "abandon")
    assert issue["status"] == "abandoned"


def test_invalid_transition():
    issue = make_issue(status="completed")
    with pytest.raises(SystemExit):
        transition(issue, "review")


def test_block():
    a = make_issue(id="a", attention=["alice"])
    b = make_issue(id="b", attention=["bob"])
    transition(a, "block", blocker=b)
    assert "b" in a["blocked_by"]
    assert "a" in b["blocks"]
    assert a["attention"] == []
    assert "alice" in b["attention"]


def test_unblock():
    a = make_issue(id="a", blocked_by=["b"], attention=[])
    b = make_issue(id="b", blocks=["a"])
    transition(a, "unblock", blocker=b)
    assert a["blocked_by"] == []
    assert b["blocks"] == []
    assert a["attention"] == ["alice"]


def test_pending():
    issue = make_issue(reviewers=["bob", "carol"], approved_by=["bob"])
    assert pending(issue) == ["carol"]
