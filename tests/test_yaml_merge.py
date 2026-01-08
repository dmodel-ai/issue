"""Tests for YAML-aware merge logic."""
import pytest
import sys
import io
from issue_tracker.store.git import _yaml_merge


def test_empty_remote():
    """New issue, no remote version."""
    local = {'id': 'abc', 'title': 'New', 'status': 'draft'}
    merged = _yaml_merge({}, local)
    assert merged == local


def test_same_values():
    """No changes, same values."""
    remote = {'id': 'abc', 'title': 'Same', 'status': 'draft'}
    local = {'id': 'abc', 'title': 'Same', 'status': 'draft'}
    merged = _yaml_merge(remote, local)
    assert merged['title'] == 'Same'


def test_local_adds_field():
    """Local adds a new field."""
    remote = {'id': 'abc', 'title': 'T'}
    local = {'id': 'abc', 'title': 'T', 'priority': 1}
    merged = _yaml_merge(remote, local)
    assert merged['priority'] == 1


def test_remote_adds_field():
    """Remote has a field local doesn't."""
    remote = {'id': 'abc', 'title': 'T', 'priority': 2}
    local = {'id': 'abc', 'title': 'T'}
    merged = _yaml_merge(remote, local)
    assert merged['priority'] == 2


def test_list_union():
    """Lists are merged via union."""
    remote = {'id': 'abc', 'reviewers': ['alice', 'bob']}
    local = {'id': 'abc', 'reviewers': ['bob', 'carol']}
    merged = _yaml_merge(remote, local)
    assert set(merged['reviewers']) == {'alice', 'bob', 'carol'}


def test_list_order_preserved():
    """Remote items first, then new local items."""
    remote = {'id': 'abc', 'reviewers': ['alice', 'bob']}
    local = {'id': 'abc', 'reviewers': ['carol', 'bob', 'dave']}
    merged = _yaml_merge(remote, local)
    assert merged['reviewers'] == ['alice', 'bob', 'carol', 'dave']


def test_comments_dedupe():
    """Comments are deduped by (author, time)."""
    remote = {'id': 'abc', 'comments': [
        {'author': 'a', 'time': '2024-01-01', 'text': 'hi'}
    ]}
    local = {'id': 'abc', 'comments': [
        {'author': 'a', 'time': '2024-01-01', 'text': 'hi'},
        {'author': 'b', 'time': '2024-01-02', 'text': 'yo'}
    ]}
    merged = _yaml_merge(remote, local)
    assert len(merged['comments']) == 2


def test_comments_sorted_by_time():
    """Comments are sorted by time."""
    remote = {'id': 'abc', 'comments': [
        {'author': 'a', 'time': '2024-01-03', 'text': 'late'}
    ]}
    local = {'id': 'abc', 'comments': [
        {'author': 'b', 'time': '2024-01-01', 'text': 'early'}
    ]}
    merged = _yaml_merge(remote, local)
    assert merged['comments'][0]['text'] == 'early'
    assert merged['comments'][1]['text'] == 'late'


def test_immutable_id():
    """ID is immutable, kept from remote."""
    remote = {'id': 'original'}
    local = {'id': 'changed'}
    merged = _yaml_merge(remote, local)
    assert merged['id'] == 'original'


def test_immutable_created():
    """Created timestamp is immutable."""
    remote = {'id': 'abc', 'created': '2024-01-01'}
    local = {'id': 'abc', 'created': '2024-01-02'}
    merged = _yaml_merge(remote, local)
    assert merged['created'] == '2024-01-01'


def test_timestamp_takes_latest():
    """Updated timestamp takes the latest."""
    remote = {'id': 'abc', 'updated': '2024-01-01'}
    local = {'id': 'abc', 'updated': '2024-01-05'}
    merged = _yaml_merge(remote, local)
    assert merged['updated'] == '2024-01-05'


def test_scalar_conflict_non_tty():
    """Scalar conflict in non-tty mode exits."""
    remote = {'id': 'abc', 'title': 'Remote Title'}
    local = {'id': 'abc', 'title': 'Local Title'}

    # Simulate non-tty
    old_stdin = sys.stdin
    sys.stdin = io.StringIO('')

    try:
        with pytest.raises(SystemExit):
            _yaml_merge(remote, local)
    finally:
        sys.stdin = old_stdin


def test_scalar_no_conflict_if_one_none():
    """No conflict if one side is None."""
    remote = {'id': 'abc', 'title': 'Remote'}
    local = {'id': 'abc'}
    merged = _yaml_merge(remote, local)
    assert merged['title'] == 'Remote'

    remote2 = {'id': 'abc'}
    local2 = {'id': 'abc', 'title': 'Local'}
    merged2 = _yaml_merge(remote2, local2)
    assert merged2['title'] == 'Local'


def test_unknown_field_prefers_local():
    """Unknown fields prefer local value."""
    remote = {'id': 'abc', 'custom': 'remote'}
    local = {'id': 'abc', 'custom': 'local'}
    merged = _yaml_merge(remote, local)
    assert merged['custom'] == 'local'


class FakeTTY(io.StringIO):
    """StringIO that pretends to be a TTY."""
    def isatty(self):
        return True


def test_scalar_conflict_pick_remote():
    """Interactive conflict resolution - pick remote."""
    remote = {'id': 'abc', 'title': 'Remote Title'}
    local = {'id': 'abc', 'title': 'Local Title'}

    old_stdin = sys.stdin
    sys.stdin = FakeTTY('1\n')  # Pick remote

    try:
        merged = _yaml_merge(remote, local)
        assert merged['title'] == 'Remote Title'
    finally:
        sys.stdin = old_stdin


def test_scalar_conflict_pick_local():
    """Interactive conflict resolution - pick local."""
    remote = {'id': 'abc', 'title': 'Remote Title'}
    local = {'id': 'abc', 'title': 'Local Title'}

    old_stdin = sys.stdin
    sys.stdin = FakeTTY('2\n')  # Pick local

    try:
        merged = _yaml_merge(remote, local)
        assert merged['title'] == 'Local Title'
    finally:
        sys.stdin = old_stdin
