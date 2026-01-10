"""Git orphan branch storage backend with YAML-aware 3-way sync."""
import os
import subprocess
import sys
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
    """Run git command, return stdout or None on failure."""
    r = subprocess.run(["git", *args], capture_output=True, text=True, input=input)
    if check and r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, args)
    if r.returncode != 0:
        return None
    return r.stdout.strip() if strip else r.stdout


def _git_list():
    """List all files in issues branch."""
    out = _git("ls-tree", "-r", "--name-only", BRANCH)
    return sorted(out.split('\n')) if out else []


def _git_exists(filename):
    """Check if file exists in issues branch."""
    return _git("cat-file", "-e", f"{BRANCH}:{filename}") is not None


def _read_from_commit(commit, filename):
    """Read file from a specific commit. Returns None if not found."""
    return _git("show", f"{commit}:{filename}", strip=False) if commit else None


def _read_local(filename):
    """Read file from local issues branch."""
    return _git("show", f"{BRANCH}:{filename}", strip=False)


def _read_remote(filename):
    """Read file from origin/issues."""
    return _git("show", f"{REMOTE}/{BRANCH}:{filename}", strip=False)


def _write_local(filename, content, message):
    """Write to local issues branch using git plumbing."""
    _ensure_branch()
    blob = _git("hash-object", "-w", "--stdin", input=content, check=True)
    tree_content = _git("ls-tree", BRANCH) or ""
    entries = []
    for line in tree_content.split('\n'):
        if not line:
            continue
        meta, name = line.split('\t', 1)
        if name == filename:
            continue
        entries.append((meta, name))
    entries.append((f"100644 blob {blob}", filename))

    def sort_key(entry):
        meta, name = entry
        kind = meta.split()[1] if meta else ""
        suffix = "/" if kind == "tree" else ""
        return f"{name}{suffix}"

    entries.sort(key=sort_key)
    new_tree = _git(
        "mktree",
        input='\n'.join(f"{meta}\t{name}" for meta, name in entries),
        check=True,
    )
    parent = _git("rev-parse", BRANCH)
    parent_args = ["-p", parent] if parent else []
    commit = _git("commit-tree", new_tree, *parent_args, "-m", message, check=True)
    _git("update-ref", LOCAL_REF, commit, check=True)


# =============================================================================
# Branch & remote management
# =============================================================================

# Background fetch state
_fetch_thread = None
_fetch_lock = threading.Lock()


def _has_remote():
    """Check if remote exists."""
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
    tree = _git("hash-object", "-t", "tree", "/dev/null", check=True)
    commit = _git("commit-tree", tree, "-m", "Initialize issues", check=True)
    _git("update-ref", LOCAL_REF, commit, check=True)


def _ensure_branch_exists():
    """Ensure the issues branch exists locally, fetching remote if needed.

    Unlike _ensure_read_setup(), this does NOT merge from remote.
    Used by index()/exists() which are called during writes.
    """
    if _git("rev-parse", "--verify", BRANCH):
        return
    _try_fetch()
    _ensure_branch()


def _try_fetch():
    """Try to fetch remote (blocking). Returns True if online/successful."""
    if not AUTO_SYNC or not _has_remote():
        return False
    return _git("fetch", REMOTE, f"{BRANCH}:{REMOTE_REF}") is not None


def _fetch_background():
    """Start a background fetch. Returns immediately."""
    global _fetch_thread
    if not AUTO_SYNC or not _has_remote():
        return
    with _fetch_lock:
        if _fetch_thread is not None and _fetch_thread.is_alive():
            return
        _fetch_thread = threading.Thread(target=_try_fetch, daemon=True)
        _fetch_thread.start()


def _try_push():
    """Try to push local to remote. Returns True on success."""
    if not AUTO_SYNC or not _has_remote():
        return True  # No remote, consider it "success"
    return _git("push", "-u", REMOTE, BRANCH) is not None


def _get_merge_base():
    """Get merge-base commit between local and remote. Returns None if not available."""
    return _git("merge-base", BRANCH, REMOTE_REF)


# =============================================================================
# YAML merge logic
# =============================================================================

def _yaml_load(content):
    """Safe YAML load, returning empty dict for None/empty content."""
    return yaml.safe_load(content) if content else {}


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
    """Keep base value (or remote if no base)."""
    return b if b is not None else r


def _merge_timestamp(key, b, r, l):
    """Take the latest timestamp."""
    vals = [v for v in [r, l] if v]
    return max(vals) if vals else b


def _merge_scalar(key, b, r, l):
    """Prompt user on conflict, else take non-None value."""
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


def _merge_local(key, b, r, l):
    """Prefer local, fall back to remote."""
    return l if l is not None else r


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
        strategy = MERGE_STRATEGY.get(key, 'scalar')
        merge_fn = MERGE_FN.get(strategy, _merge_scalar)
        merged[key] = _pick_3way(b, r, l, lambda b, r, l: merge_fn(key, b, r, l))

    return merged


def _yaml_merge_2way(remote: dict, local: dict) -> dict:
    """2-way merge (no base). Just calls 3-way with empty base."""
    return _yaml_merge_3way({}, remote, local)


# =============================================================================
# Sync operations
# =============================================================================

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

    # Fetch may fail if remote branch doesn't exist yet - that's OK
    if not _try_fetch():
        # No remote branch yet, just push
        if not _try_push():
            print(f"Warning: Saved locally, push failed. Re-run to sync.", file=sys.stderr)
        return

    # Check relationship with remote
    local_ref = _git("rev-parse", BRANCH)
    remote_ref = _git("rev-parse", REMOTE_REF)

    if local_ref == remote_ref:
        # Already in sync (shouldn't happen since we just wrote, but handle it)
        return

    if _git("merge-base", "--is-ancestor", remote_ref, local_ref) is not None:
        # Remote is ancestor of local - we can just push
        if not _try_push():
            print(f"Warning: Saved locally, push failed. Re-run to sync.", file=sys.stderr)
        return

    # Diverged - preserve every local YAML change, then replay them on top of remote
    base_commit = _get_merge_base()
    # Get files changed locally. If no common ancestor (orphan branches), use remote as diff base
    diff_base = base_commit if base_commit else remote_ref
    local_diff = _git("diff", "--name-only", diff_base, local_ref) or ""
    local_files = [f for f in local_diff.split('\n') if f.endswith('.yaml')]
    local_snapshots = {f: _read_local(f) for f in local_files}

    # Reset local to remote HEAD
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

    if not _try_push():
        print(f"Warning: Saved locally, push failed. Re-run to sync.", file=sys.stderr)


def _ensure_read_setup():
    """Ensure local branch exists for reading, fetching from remote if needed."""
    if _git("rev-parse", "--verify", BRANCH):
        _try_merge()  # Merge from previous fetch if needed
        _fetch_background()  # Kick off fetch for next time
        return
    # First time: blocking fetch + create tracking branch
    _try_fetch()
    _ensure_branch()


# =============================================================================
# Public API
# =============================================================================

def _commit_msg(issue, action="Update", old_issue=None):
    """Generate human-friendly commit message."""
    from . import num  # avoid circular import
    title = issue.get('title', '')[:50]
    issue_id = issue.get('id')
    if issue_id:
        ref = issue.get('alias') or f"#{num(issue_id) or issue_id[:8]}"
    else:
        ref = issue.get('alias') or "#?"
    msg = f"{action}: {title} ({ref})"

    # Add status transition if changed
    old_status = old_issue.get('status') if old_issue else None
    new_status = issue.get('status')
    if old_status and new_status and old_status != new_status:
        msg += f" [{old_status} → {new_status}]"

    return msg


def exists(id):
    """Check if issue exists."""
    _ensure_branch_exists()
    return _git_exists(f"{id}.yaml")


def load(id):
    """Load an issue by ID."""
    _ensure_read_setup()
    content = _read_local(f"{id}.yaml")
    return yaml.safe_load(content) if content else None


def save(issue):
    """Save an issue (create or update)."""
    filename = f"{issue['id']}.yaml"

    # Fetch first so _ensure_branch() can track remote if it exists
    _try_fetch()

    # Read previous version to detect changes
    old_content = _read_local(filename)
    old_issue = yaml.safe_load(old_content) if old_content else None

    issue["updated"] = now()

    # Write locally first (works offline)
    content = yaml.dump(issue, default_flow_style=False, sort_keys=False)
    _write_local(filename, content, _commit_msg(issue, old_issue=old_issue))

    # Try to sync with remote
    _try_sync(filename)


def all_issues():
    """Get all issues, sorted by ID."""
    _ensure_read_setup()
    files = [f for f in _git_list() if f.endswith('.yaml')]
    issues = [yaml.safe_load(_read_local(f)) for f in files]
    return sorted([i for i in issues if i], key=lambda i: i['id'])


def index():
    """Get mapping of issue numbers to IDs."""
    _ensure_branch_exists()
    files = [f for f in _git_list() if f.endswith('.yaml')]
    return {n+1: f[:-5] for n, f in enumerate(files)}


def read_raw(id):
    """Read raw YAML content for editor."""
    _ensure_read_setup()
    return _read_local(f"{id}.yaml")


def write_raw(id, content):
    """Write raw YAML content from editor.

    Caller must ensure `_ensure_read_setup()` or an equivalent fetch happened
    beforehand so the local branch reflects the remote state before editing.
    """
    filename = f"{id}.yaml"
    issue = yaml.safe_load(content) or {}
    commit_issue = issue if issue.get('id') else {**issue, 'id': id}

    # Write locally first
    _write_local(filename, content, _commit_msg(commit_issue, "Edit"))

    # Try to sync with remote
    _try_sync(filename)
