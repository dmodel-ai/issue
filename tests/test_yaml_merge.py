"""Tests for YAML-aware merge logic."""
import pytest
import sys
import io
from issue_tracker.store.git import _yaml_merge_2way, _yaml_merge_3way


class FakeTTY(io.StringIO):
    """StringIO that pretends to be a TTY."""
    def isatty(self):
        return True


# ============ 2-way merge tests (backward compat) ============

def test_2way_empty_remote():
    """New issue, no remote version."""
    local = {'id': 'abc', 'title': 'New', 'status': 'draft'}
    merged = _yaml_merge_2way({}, local)
    assert merged == local


def test_2way_same_values():
    """No changes, same values."""
    remote = {'id': 'abc', 'title': 'Same', 'status': 'draft'}
    local = {'id': 'abc', 'title': 'Same', 'status': 'draft'}
    merged = _yaml_merge_2way(remote, local)
    assert merged['title'] == 'Same'


def test_2way_local_adds_field():
    """Local adds a new field."""
    remote = {'id': 'abc', 'title': 'T'}
    local = {'id': 'abc', 'title': 'T', 'priority': 1}
    merged = _yaml_merge_2way(remote, local)
    assert merged['priority'] == 1


def test_2way_remote_adds_field():
    """Remote has a field local doesn't."""
    remote = {'id': 'abc', 'title': 'T', 'priority': 2}
    local = {'id': 'abc', 'title': 'T'}
    merged = _yaml_merge_2way(remote, local)
    assert merged['priority'] == 2


def test_2way_list_union():
    """Lists are merged via union."""
    remote = {'id': 'abc', 'reviewers': ['alice', 'bob']}
    local = {'id': 'abc', 'reviewers': ['bob', 'carol']}
    merged = _yaml_merge_2way(remote, local)
    assert set(merged['reviewers']) == {'alice', 'bob', 'carol'}


def test_2way_list_order_preserved():
    """Remote items first, then new local items."""
    remote = {'id': 'abc', 'reviewers': ['alice', 'bob']}
    local = {'id': 'abc', 'reviewers': ['carol', 'bob', 'dave']}
    merged = _yaml_merge_2way(remote, local)
    assert merged['reviewers'] == ['alice', 'bob', 'carol', 'dave']


def test_2way_comments_dedupe():
    """Comments are deduped by (author, time)."""
    remote = {'id': 'abc', 'comments': [
        {'author': 'a', 'time': '2024-01-01', 'text': 'hi'}
    ]}
    local = {'id': 'abc', 'comments': [
        {'author': 'a', 'time': '2024-01-01', 'text': 'hi'},
        {'author': 'b', 'time': '2024-01-02', 'text': 'yo'}
    ]}
    merged = _yaml_merge_2way(remote, local)
    assert len(merged['comments']) == 2


def test_2way_comments_sorted_by_time():
    """Comments are sorted by time."""
    remote = {'id': 'abc', 'comments': [
        {'author': 'a', 'time': '2024-01-03', 'text': 'late'}
    ]}
    local = {'id': 'abc', 'comments': [
        {'author': 'b', 'time': '2024-01-01', 'text': 'early'}
    ]}
    merged = _yaml_merge_2way(remote, local)
    assert merged['comments'][0]['text'] == 'early'
    assert merged['comments'][1]['text'] == 'late'


def test_2way_immutable_id():
    """ID is immutable, kept from remote."""
    remote = {'id': 'original'}
    local = {'id': 'changed'}
    merged = _yaml_merge_2way(remote, local)
    assert merged['id'] == 'original'


def test_2way_immutable_created():
    """Created timestamp is immutable."""
    remote = {'id': 'abc', 'created': '2024-01-01'}
    local = {'id': 'abc', 'created': '2024-01-02'}
    merged = _yaml_merge_2way(remote, local)
    assert merged['created'] == '2024-01-01'


def test_2way_timestamp_takes_latest():
    """Updated timestamp takes the latest."""
    remote = {'id': 'abc', 'updated': '2024-01-01'}
    local = {'id': 'abc', 'updated': '2024-01-05'}
    merged = _yaml_merge_2way(remote, local)
    assert merged['updated'] == '2024-01-05'


def test_2way_scalar_conflict_non_tty():
    """Scalar conflict in non-tty mode exits."""
    remote = {'id': 'abc', 'title': 'Remote Title'}
    local = {'id': 'abc', 'title': 'Local Title'}

    old_stdin = sys.stdin
    sys.stdin = io.StringIO('')

    try:
        with pytest.raises(SystemExit):
            _yaml_merge_2way(remote, local)
    finally:
        sys.stdin = old_stdin


def test_2way_scalar_no_conflict_if_one_none():
    """No conflict if one side is None."""
    remote = {'id': 'abc', 'title': 'Remote'}
    local = {'id': 'abc'}
    merged = _yaml_merge_2way(remote, local)
    assert merged['title'] == 'Remote'

    remote2 = {'id': 'abc'}
    local2 = {'id': 'abc', 'title': 'Local'}
    merged2 = _yaml_merge_2way(remote2, local2)
    assert merged2['title'] == 'Local'


def test_2way_unknown_field_prefers_local():
    """Unknown fields prefer local value."""
    remote = {'id': 'abc', 'custom': 'remote'}
    local = {'id': 'abc', 'custom': 'local'}
    merged = _yaml_merge_2way(remote, local)
    assert merged['custom'] == 'local'


def test_2way_scalar_conflict_pick_remote():
    """Interactive conflict resolution - pick remote."""
    remote = {'id': 'abc', 'title': 'Remote Title'}
    local = {'id': 'abc', 'title': 'Local Title'}

    old_stdin = sys.stdin
    sys.stdin = FakeTTY('1\n')

    try:
        merged = _yaml_merge_2way(remote, local)
        assert merged['title'] == 'Remote Title'
    finally:
        sys.stdin = old_stdin


def test_2way_scalar_conflict_pick_local():
    """Interactive conflict resolution - pick local."""
    remote = {'id': 'abc', 'title': 'Remote Title'}
    local = {'id': 'abc', 'title': 'Local Title'}

    old_stdin = sys.stdin
    sys.stdin = FakeTTY('2\n')

    try:
        merged = _yaml_merge_2way(remote, local)
        assert merged['title'] == 'Local Title'
    finally:
        sys.stdin = old_stdin


# ============ 3-way merge tests ============

def test_3way_no_base_falls_back_to_2way():
    """With no base, falls back to 2-way merge."""
    remote = {'id': 'abc', 'title': 'Remote'}
    local = {'id': 'abc', 'title': 'Remote', 'priority': 1}
    merged = _yaml_merge_3way({}, remote, local)
    assert merged['priority'] == 1


def test_3way_neither_changed():
    """Neither side changed from base."""
    base = {'id': 'abc', 'title': 'Original', 'priority': 1}
    remote = {'id': 'abc', 'title': 'Original', 'priority': 1}
    local = {'id': 'abc', 'title': 'Original', 'priority': 1}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['title'] == 'Original'
    assert merged['priority'] == 1


def test_3way_only_local_changed():
    """Only local changed from base - local wins."""
    base = {'id': 'abc', 'title': 'Original', 'priority': 1}
    remote = {'id': 'abc', 'title': 'Original', 'priority': 1}
    local = {'id': 'abc', 'title': 'My Title', 'priority': 1}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['title'] == 'My Title'


def test_3way_only_remote_changed():
    """Only remote changed from base - remote wins."""
    base = {'id': 'abc', 'title': 'Original', 'priority': 1}
    remote = {'id': 'abc', 'title': 'Original', 'priority': 2}
    local = {'id': 'abc', 'title': 'Original', 'priority': 1}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['priority'] == 2


def test_3way_both_changed_different_fields():
    """Both changed, but different fields - no conflict."""
    base = {'id': 'abc', 'title': 'Original', 'priority': 1}
    remote = {'id': 'abc', 'title': 'Original', 'priority': 2}
    local = {'id': 'abc', 'title': 'My Title', 'priority': 1}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['title'] == 'My Title'  # local's change
    assert merged['priority'] == 2  # remote's change


def test_3way_both_changed_same_value():
    """Both changed to same value - no conflict."""
    base = {'id': 'abc', 'title': 'Original'}
    remote = {'id': 'abc', 'title': 'Same New Title'}
    local = {'id': 'abc', 'title': 'Same New Title'}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['title'] == 'Same New Title'


def test_3way_both_changed_different_values_conflict():
    """Both changed to different values - conflict."""
    base = {'id': 'abc', 'title': 'Original'}
    remote = {'id': 'abc', 'title': 'Remote Title'}
    local = {'id': 'abc', 'title': 'Local Title'}

    old_stdin = sys.stdin
    sys.stdin = FakeTTY('2\n')  # Pick local

    try:
        merged = _yaml_merge_3way(base, remote, local)
        assert merged['title'] == 'Local Title'
    finally:
        sys.stdin = old_stdin


def test_3way_list_union_both_add():
    """Both sides add to list - union."""
    base = {'id': 'abc', 'reviewers': ['alice']}
    remote = {'id': 'abc', 'reviewers': ['alice', 'bob']}
    local = {'id': 'abc', 'reviewers': ['alice', 'carol']}
    merged = _yaml_merge_3way(base, remote, local)
    assert set(merged['reviewers']) == {'alice', 'bob', 'carol'}


def test_3way_list_one_removes():
    """One side removes from list."""
    base = {'id': 'abc', 'reviewers': ['alice', 'bob']}
    remote = {'id': 'abc', 'reviewers': ['alice']}  # removed bob
    local = {'id': 'abc', 'reviewers': ['alice', 'bob']}  # unchanged
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['reviewers'] == ['alice']  # bob removed


def test_3way_list_both_add_and_remove():
    """One adds, one removes."""
    base = {'id': 'abc', 'reviewers': ['alice', 'bob']}
    remote = {'id': 'abc', 'reviewers': ['alice', 'bob', 'carol']}  # added carol
    local = {'id': 'abc', 'reviewers': ['alice']}  # removed bob
    merged = _yaml_merge_3way(base, remote, local)
    # Should have alice, carol (bob removed by local, carol added by remote)
    assert set(merged['reviewers']) == {'alice', 'carol'}


def test_3way_immutable_preserved():
    """Immutable fields keep base value even if both change."""
    base = {'id': 'original', 'created': '2024-01-01'}
    remote = {'id': 'remote-id', 'created': '2024-01-02'}
    local = {'id': 'local-id', 'created': '2024-01-03'}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['id'] == 'original'
    assert merged['created'] == '2024-01-01'


def test_3way_timestamp_takes_latest():
    """Updated timestamp takes latest when both change."""
    base = {'id': 'abc', 'updated': '2024-01-01'}
    remote = {'id': 'abc', 'updated': '2024-01-05'}
    local = {'id': 'abc', 'updated': '2024-01-03'}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['updated'] == '2024-01-05'


# ============ dict merge tests (for due field) ============

def test_3way_dict_both_add_different_keys():
    """Both sides add different keys to dict - merge."""
    base = {'id': 'abc', 'due': {'draft': '2024-01-01'}}
    remote = {'id': 'abc', 'due': {'draft': '2024-01-01', 'pqa': '2024-01-10'}}
    local = {'id': 'abc', 'due': {'draft': '2024-01-01', 'done': '2024-01-20'}}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['due'] == {'draft': '2024-01-01', 'pqa': '2024-01-10', 'done': '2024-01-20'}


def test_3way_dict_one_changes_key():
    """One side changes a key - use changed value."""
    base = {'id': 'abc', 'due': {'draft': '2024-01-01'}}
    remote = {'id': 'abc', 'due': {'draft': '2024-01-01'}}
    local = {'id': 'abc', 'due': {'draft': '2024-01-05'}}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['due']['draft'] == '2024-01-05'


def test_3way_dict_both_change_same_key_same_value():
    """Both sides change same key to same value - no conflict."""
    base = {'id': 'abc', 'due': {'draft': '2024-01-01'}}
    remote = {'id': 'abc', 'due': {'draft': '2024-01-05'}}
    local = {'id': 'abc', 'due': {'draft': '2024-01-05'}}
    merged = _yaml_merge_3way(base, remote, local)
    assert merged['due']['draft'] == '2024-01-05'


def test_3way_dict_conflict_prompts():
    """Both sides change same key differently - prompts."""
    base = {'id': 'abc', 'due': {'draft': '2024-01-01'}}
    remote = {'id': 'abc', 'due': {'draft': '2024-01-05'}}
    local = {'id': 'abc', 'due': {'draft': '2024-01-10'}}

    old_stdin = sys.stdin
    sys.stdin = FakeTTY('2\n')  # Pick local

    try:
        merged = _yaml_merge_3way(base, remote, local)
        assert merged['due']['draft'] == '2024-01-10'
    finally:
        sys.stdin = old_stdin
