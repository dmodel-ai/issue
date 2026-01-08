import pytest
import issue_tracker.utils as utils
from issue_tracker.store import save
from issue_tracker.cli.views import inbox_issues, outbox_issues

@pytest.fixture
def sample_issues(mock_user):
    utils.DIR.mkdir(exist_ok=True)
    # In inbox: owned by testuser, in attention
    save({
        "id": "inbox1",
        "title": "Inbox Issue",
        "status": "draft",
        "owner": "testuser",
        "attention": ["testuser"],
        "priority": 1,
        "comments": [],
        "blocked_by": [],
        "blocks": [],
    })
    # In outbox: owned by testuser, not in attention
    save({
        "id": "outbox1",
        "title": "Outbox Issue",
        "status": "review",
        "owner": "testuser",
        "attention": ["reviewer"],
        "priority": 0,
        "comments": [],
        "blocked_by": [],
        "blocks": [],
    })
    # Blocked: should not appear in inbox
    save({
        "id": "blocked1",
        "title": "Blocked Issue",
        "status": "draft",
        "owner": "testuser",
        "attention": ["testuser"],
        "priority": 0,
        "comments": [],
        "blocked_by": ["other"],
        "blocks": [],
    })
    # Completed: should not appear
    save({
        "id": "done1",
        "title": "Done Issue",
        "status": "completed",
        "owner": "testuser",
        "attention": [],
        "priority": 0,
        "comments": [],
        "blocked_by": [],
        "blocks": [],
    })

def test_inbox_issues(sample_issues):
    inbox = inbox_issues()
    assert len(inbox) == 1
    assert inbox[0]["id"] == "inbox1"

def test_outbox_issues(sample_issues):
    outbox = outbox_issues()
    assert len(outbox) == 1
    assert outbox[0]["id"] == "outbox1"

def test_inbox_excludes_blocked(sample_issues):
    inbox = inbox_issues()
    ids = [i["id"] for i in inbox]
    assert "blocked1" not in ids

def test_inbox_excludes_completed(sample_issues):
    inbox = inbox_issues()
    ids = [i["id"] for i in inbox]
    assert "done1" not in ids
