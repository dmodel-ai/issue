"""Git orphan branch storage backend with YAML-aware 3-way sync."""
import os
import subprocess
import sys
import tempfile
import threading
import yaml
from ..utils import die, now


# =============================================================================
# Configuration & Constants
# =============================================================================

BRANCH = os.environ.get("ISSUE_BRANCH", "issues")
REMOTE = os.environ.get("ISSUE_REMOTE", "origin")
AUTO_SYNC = os.environ.get("ISSUE_SYNC", "1") != "0"

LOCAL_REF = f"refs/heads/{BRANCH}"
REMOTE_REF = f"refs/remotes/{REMOTE}/{BRANCH}"

MERGE_STRATEGY = {
    'id': 'immutable', 'created': 'immutable',
    'updated': 'timestamp',
    'title': 'scalar', 'owner': 'scalar', 'status': 'scalar',
    'priority': 'scalar', 'alias': 'scalar',
    'reviewers': 'union', 'cc': 'union', 'labels': 'union',
    'approved_by': 'union', 'attention': 'union',
    'blocked_by': 'union', 'blocks': 'union',
    'comments': 'comments',
    'due': 'dict',
}


# =============================================================================
# Low-level git plumbing
# =============================================================================

def _git(*args, input=None, check=False, strip=True):
    cmd = ["git", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, input=input)
    if check and r.returncode != 0:
        print("STDOUT:\n", r.stdout)
        print("STDERR:\n", r.stderr)
        raise subprocess.CalledProcessError(r.returncode, cmd)
    return (r.stdout.strip() if strip else r.stdout) if r.returncode == 0 else None

def _git_list():
    out = _git("ls-tree", "-r", "--name-only", BRANCH)
    return out.split('\n') if out else []

def _git_exists(filename):
    return _git("cat-file", "-e", f"{BRANCH}:{filename}") is not None

def _read_from_commit(commit, filename):
    return _git("show", f"{commit}:{filename}", strip=False) if commit else None

def _read_local(filename):
    return _git("show", f"{BRANCH}:{filename}", strip=False)

def _read_remote(filename):
    return _git("show", f"{REMOTE}/{BRANCH}:{filename}", strip=False)

def _git_with_index(index_file, *args, input=None, check=False, strip=True):
    """Run git with a custom index file."""
    env = {**os.environ, "GIT_INDEX_FILE": index_file}
    r = subprocess.run(["git", *args], capture_output=True, text=True, input=input, env=env)
    if check and r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, args)
    return (r.stdout.strip() if strip else r.stdout) if r.returncode == 0 else None


def _write_local(filename, content, message):
    _ensure_branch()
    blob = _git("hash-object", "-w", "--stdin", input=content, check=True)
    with tempfile.NamedTemporaryFile(suffix=".git-index", delete=True) as tmp:
        _git_with_index(tmp.name, "read-tree", BRANCH, check=True)
        _git_with_index(tmp.name, "update-index", "--add", "--cacheinfo", f"100644,{blob},{filename}", check=True)
        new_tree = _git_with_index(tmp.name, "write-tree", check=True)
    parent = _git("rev-parse", BRANCH)
    commit = _git("commit-tree", new_tree, *(["-p", parent] if parent else []), "-m", message, check=True)
    _git("update-ref", LOCAL_REF, commit, check=True)


# =============================================================================
# Branch & remote management
# =============================================================================

# Background fetch state
_fetch_thread = None
_fetch_lock = threading.Lock()


def _has_remote():
    return REMOTE in (_git("remote") or "").split()

def _ensure_branch():
    """Create local branch if it doesn't exist, tracking remote if available."""
    if _git("rev-parse", "--verify", BRANCH):
        return
    # Check if remote branch exists (may have been fetched earlier)
    if _git("rev-parse", "--verify", REMOTE_REF):
        _git("branch", "--track", BRANCH, f"{REMOTE}/{BRANCH}", check=True)
        return
    # No remote branch, create orphan
    tree = _git("mktree", input="", check=True)
    commit = _git("commit-tree", tree, "-m", "Initialize issues", check=True)
    _git("update-ref", LOCAL_REF, commit, check=True)


def _ensure_branch_exists(sync=False):
    """Ensure branch exists. With sync=True, also merge from remote and background fetch."""
    if _git("rev-parse", "--verify", BRANCH):
        if sync:
            _try_merge()
            _fetch_background()
        return
    _try_fetch()
    _ensure_branch()


def _try_fetch(quiet=False):
    """Try to fetch remote (blocking). Returns True if online/successful."""
    if not AUTO_SYNC or not _has_remote():
        return False
    if not quiet:
        print("Fetching from remote...", file=sys.stderr, end="", flush=True)
    result = _git("fetch", REMOTE, f"{BRANCH}:{REMOTE_REF}", check=True) is not None
    if not quiet:
        print(" done" if result else " failed", file=sys.stderr)
    return result


def _fetch_background():
    global _fetch_thread
    if not AUTO_SYNC or not _has_remote():
        return
    with _fetch_lock:
        if _fetch_thread is not None and _fetch_thread.is_alive():
            return
        _fetch_thread = threading.Thread(target=lambda: _try_fetch(quiet=True), daemon=True)
        _fetch_thread.start()


def _try_push():
    if not AUTO_SYNC or not _has_remote():
        return True  # No remote, consider it "success"
    print("Pushing to remote...", file=sys.stderr, end="", flush=True)
    result = _git("push", "-u", REMOTE, BRANCH) is not None
    print(" done" if result else " failed", file=sys.stderr)
    return result


def _get_merge_base():
    return _git("merge-base", BRANCH, REMOTE_REF)


# =============================================================================
# YAML merge logic
# =============================================================================

def _pick_3way(b, r, l, on_conflict):
    """3-way merge decision: returns value or calls on_conflict if both changed differently."""
    local_changed, remote_changed = (l != b), (r != b)
    if not local_changed and not remote_changed:
        return b
    if local_changed and not remote_changed:
        return l
    if not local_changed and remote_changed:
        return r
    if l == r:
        return l
    return on_conflict(b, r, l)


def _prompt_conflict(field, remote_val, local_val):
    """Prompt user to resolve a conflict. Returns chosen value."""
    if not sys.stdin.isatty():
        die(f"Conflict on '{field}': remote={remote_val!r}, yours={local_val!r}. Run interactively to resolve.")

    print(f"\nConflict on '{field}':")
    print(f"  [1] remote: {remote_val!r}")
    print(f"  [2] yours:  {local_val!r}")

    while True:
        try:
            choice = input("Pick (1/2): ").strip()
            if choice == "1":
                return remote_val
            elif choice == "2":
                return local_val
        except (EOFError, KeyboardInterrupt):
            die("\nAborted")


# Merge strategy functions - each takes (key, base, remote, local) -> value

def _merge_immutable(key, b, r, l):
    return b if b is not None else r


def _merge_timestamp(key, b, r, l):
    return max(filter(None, [r, l]), default=b)


def _merge_scalar(key, b, r, l):
    if r == l:
        return l
    if r is None:
        return l
    if l is None:
        return r
    return _prompt_conflict(key, r, l)


def _merge_union(key, b, r, l):
    """Union of lists, respecting additions and removals from base."""
    base_set, remote_set, local_set = set(b or []), set(r or []), set(l or [])
    added_r, added_l = remote_set - base_set, local_set - base_set
    removed_r, removed_l = base_set - remote_set, base_set - local_set
    result_set = (base_set | added_r | added_l) - removed_r - removed_l
    # Preserve order: base items, then remote additions, then local additions
    result = [x for x in (b or []) if x in result_set]
    for x in (r or []):
        if x in added_r and x not in result:
            result.append(x)
    for x in (l or []):
        if x in added_l and x not in result:
            result.append(x)
    return result


def _merge_comments(key, b, r, l):
    """Dedupe by (author, time), sort chronologically."""
    seen, unique = set(), []
    for c in (b or []) + (r or []) + (l or []):
        k = (c.get('author'), c.get('time'))
        if k not in seen:
            seen.add(k)
            unique.append(c)
    return sorted(unique, key=lambda c: c.get('time', ''))


def _merge_dict(key, b, r, l):
    """3-way merge for dicts: merge keys, conflict if same key changed differently."""
    b, r, l = b or {}, r or {}, l or {}
    merged = {}
    for k in set(b) | set(r) | set(l):
        bv, rv, lv = b.get(k), r.get(k), l.get(k)
        merged[k] = _pick_3way(bv, rv, lv, lambda b, r, l: _prompt_conflict(f"{key}.{k}", r, l))
    return merged if merged else None


MERGE_FN = {
    'immutable': _merge_immutable,
    'timestamp': _merge_timestamp,
    'scalar': _merge_scalar,
    'union': _merge_union,
    'comments': _merge_comments,
    'dict': _merge_dict,
}


def _yaml_merge_3way(base: dict, remote: dict, local: dict) -> dict:
    """3-way merge: only conflict if both sides changed same field differently."""
    base, remote, local = base or {}, remote or {}, local or {}
    merged = {}

    for key in set(base) | set(remote) | set(local):
        b, r, l = base.get(key), remote.get(key), local.get(key)
        merge_fn = MERGE_FN.get(MERGE_STRATEGY.get(key, 'scalar'), _merge_scalar)
        merged[key] = _pick_3way(b, r, l, lambda b, r, l: merge_fn(key, b, r, l))

    return merged


# =============================================================================
# Sync operations
# =============================================================================

def _yaml_load(content):
    return yaml.safe_load(content) if content else {}

def _merge_from_remote(filename, base_commit, action="Merge", update_time=False):
    """3-way merge remote into local for a file and write it."""
    base = _yaml_load(_read_from_commit(base_commit, filename))
    remote = _yaml_load(_read_remote(filename))
    local = _yaml_load(_read_local(filename))

    merged = _yaml_merge_3way(base, remote, local)
    if update_time:
        merged["updated"] = now()
    content = yaml.dump(merged, default_flow_style=False, sort_keys=False)
    _write_local(filename, content, _commit_msg(merged, action))


def _try_merge():
    """Merge remote into local if needed (ff or 3-way)."""
    if not _has_remote():
        return
    if not _git("rev-parse", "--verify", REMOTE_REF):
        return
    # Already in sync
    if _git("rev-parse", BRANCH) == _git("rev-parse", REMOTE_REF):
        return
    # Fast-forward if local is ancestor of remote
    if _git("merge-base", "--is-ancestor", BRANCH, REMOTE_REF) is not None:
        _git("update-ref", LOCAL_REF, REMOTE_REF)
        return
    # We're ahead - nothing to merge
    if _git("merge-base", "--is-ancestor", REMOTE_REF, BRANCH) is not None:
        return
    # Diverged - 3-way merge each changed file
    base_commit = _get_merge_base()
    if not base_commit:
        _git("update-ref", LOCAL_REF, REMOTE_REF)
        return
    remote_diff = _git("diff", "--name-only", base_commit, REMOTE_REF) or ""
    for filename in [f for f in remote_diff.split('\n') if f.endswith('.yaml')]:
        _merge_from_remote(filename, base_commit)


def _try_sync(filename):
    """Try to sync a file with remote. No-op if no remote configured."""
    if not _has_remote():
        return

    warn = lambda: print("Warning: Saved locally, push failed. Re-run to sync.", file=sys.stderr)

    # Fetch may fail if remote branch doesn't exist yet - just push
    if not _try_fetch():
        _try_push() or warn()
        return

    local_ref = _git("rev-parse", BRANCH)
    remote_ref = _git("rev-parse", REMOTE_REF)

    # Already in sync
    if local_ref == remote_ref:
        return

    # We're ahead - just push
    if _git("merge-base", "--is-ancestor", remote_ref, local_ref) is not None:
        _try_push() or warn()
        return

    # Diverged - snapshot local files, reset to remote, replay merges
    base_commit = _get_merge_base()
    diff_base = base_commit or remote_ref
    local_diff = _git("diff", "--name-only", diff_base, local_ref) or ""
    local_files = [f for f in local_diff.split('\n') if f.endswith('.yaml')]
    local_snapshots = {f: _read_local(f) for f in local_files}

    _git("update-ref", LOCAL_REF, REMOTE_REF)

    for changed in local_files:
        base = _yaml_load(_read_from_commit(base_commit, changed))
        remote = _yaml_load(_read_local(changed))  # Now at remote HEAD
        local = _yaml_load(local_snapshots.get(changed))
        merged = _yaml_merge_3way(base, remote, local)
        if changed == filename:
            merged["updated"] = now()
        content = yaml.dump(merged, default_flow_style=False, sort_keys=False)
        _write_local(changed, content, _commit_msg(merged, "Sync"))

    _try_push() or warn()


# =============================================================================
# Public API
# =============================================================================

def _commit_msg(issue, action="Update", old_issue=None):
    from . import num  # avoid circular import
    title = issue.get('title', '')[:50]
    issue_id = issue.get('id')
    ref = issue.get('alias') or (f"#{num(issue_id) or issue_id[:8]}" if issue_id else "#?")
    msg = f"{action}: {title} ({ref})"

    # Add status transition if changed
    old_status = old_issue.get('status') if old_issue else None
    new_status = issue.get('status')
    if old_status and new_status and old_status != new_status:
        msg += f" [{old_status} → {new_status}]"

    return msg


def exists(id):
    _ensure_branch_exists()
    return _git_exists(f"{id}.yaml")


def load(id):
    _ensure_branch_exists(sync=True)
    content = _read_local(f"{id}.yaml")
    return yaml.safe_load(content) if content else None


def save(issue):
    from ..discord import notify_issue_change
    filename = f"{issue['id']}.yaml"
    _try_fetch()

    # Read previous version to detect status changes for commit message
    old_content = _read_local(filename)
    old_issue = yaml.safe_load(old_content) if old_content else None

    issue["updated"] = now()
    content = yaml.dump(issue, default_flow_style=False, sort_keys=False)
    _write_local(filename, content, _commit_msg(issue, old_issue=old_issue))
    _try_sync(filename)
    old_attn = set(old_issue.get("attention", [])) if old_issue else set()
    new_attn = set(issue.get("attention", []))
    if new_attn != old_attn:
        notify_issue_change(issue, old_issue)


def all_issues():
    _ensure_branch_exists(sync=True)
    return [i for f in _git_list() if (i := yaml.safe_load(_read_local(f)))]


def index():
    _ensure_branch_exists()
    return {n+1: f[:-5] for n, f in enumerate(_git_list())}


def read_raw(id):
    _ensure_branch_exists(sync=True)
    return _read_local(f"{id}.yaml")


def write_raw(id, content):
    """Write raw YAML content from editor.

    Caller must ensure `_ensure_branch_exists(sync=True)` or an equivalent fetch happened
    beforehand so the local branch reflects the remote state before editing.
    """
    from ..discord import notify_issue_change
    filename = f"{id}.yaml"
    issue = yaml.safe_load(content) or {}
    commit_issue = issue if issue.get('id') else {**issue, 'id': id}

    # Read previous version for notification
    old_content = _read_local(filename)
    old_issue = yaml.safe_load(old_content) if old_content else None

    # Write locally first
    _write_local(filename, content, _commit_msg(commit_issue, "Edit"))

    # Try to sync with remote
    _try_sync(filename)
    old_attn = set(old_issue.get("attention", [])) if old_issue else set()
    new_attn = set(commit_issue.get("attention", []))
    if new_attn != old_attn:
        notify_issue_change(commit_issue, old_issue)
