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

def _git(*args, input=None, check=False):
    """Run git command, return stdout or None on failure."""
    r = subprocess.run(["git", *args], capture_output=True, text=True, input=input)
    if check and r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, args)
    return r.stdout.strip() if r.returncode == 0 else None


def _git_list():
    """List all files in issues branch."""
    out = _git("ls-tree", "-r", "--name-only", BRANCH)
    return sorted(out.split('\n')) if out else []


def _git_exists(filename):
    """Check if file exists in issues branch."""
    return _git("cat-file", "-e", f"{BRANCH}:{filename}") is not None


def _read_from_commit(commit, filename):
    """Read file from a specific commit. Returns None if not found."""
    return _git("show", f"{commit}:{filename}") if commit else None


def _read_local(filename):
    """Read file from local issues branch."""
    return _git("show", f"{BRANCH}:{filename}")


def _read_remote(filename):
    """Read file from origin/issues."""
    return _git("show", f"{REMOTE}/{BRANCH}:{filename}")


def _write_local(filename, content, message):
    """Write to local issues branch using git plumbing."""
    _ensure_branch()
    blob = _git("hash-object", "-w", "--stdin", input=content, check=True)
    tree_content = _git("ls-tree", BRANCH) or ""
    lines = [l for l in tree_content.split('\n') if l and not l.endswith(f'\t{filename}')]
    lines.append(f"100644 blob {blob}\t{filename}")
    new_tree = _git("mktree", input='\n'.join(lines), check=True)
    parent = _git("rev-parse", BRANCH)
    parent_args = ["-p", parent] if parent else []
    commit = _git("commit-tree", new_tree, *parent_args, "-m", message, check=True)
    _git("update-ref", f"refs/heads/{BRANCH}", commit, check=True)


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
    if _git("rev-parse", "--verify", f"refs/remotes/{REMOTE}/{BRANCH}"):
        _git("branch", "--track", BRANCH, f"{REMOTE}/{BRANCH}", check=True)
        return
    # No remote branch, create orphan
    tree = _git("hash-object", "-t", "tree", "/dev/null", check=True)
    commit = _git("commit-tree", tree, "-m", "Initialize issues", check=True)
    _git("update-ref", f"refs/heads/{BRANCH}", commit, check=True)


def _try_fetch():
    """Try to fetch remote (blocking). Returns True if online/successful."""
    if not AUTO_SYNC or not _has_remote():
        return False
    return _git("fetch", REMOTE, f"{BRANCH}:refs/remotes/{REMOTE}/{BRANCH}") is not None


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
    return _git("merge-base", BRANCH, f"refs/remotes/{REMOTE}/{BRANCH}")


# =============================================================================
# YAML merge logic
# =============================================================================

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
        local_changed, remote_changed = (lv != bv), (rv != bv)
        if not local_changed and not remote_changed:
            merged[k] = bv
        elif local_changed and not remote_changed:
            merged[k] = lv
        elif not local_changed and remote_changed:
            merged[k] = rv
        elif lv == rv:
            merged[k] = lv
        else:
            merged[k] = _prompt_conflict(f"{key}.{k}", rv, lv)
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
        local_changed, remote_changed = (l != b), (r != b)

        if not local_changed and not remote_changed:
            merged[key] = b
        elif local_changed and not remote_changed:
            merged[key] = l
        elif not local_changed and remote_changed:
            merged[key] = r
        elif l == r:
            merged[key] = l
        else:
            strategy = MERGE_STRATEGY.get(key, 'scalar')
            merged[key] = MERGE_FN.get(strategy, _merge_scalar)(key, b, r, l)

    return merged


def _yaml_merge_2way(remote: dict, local: dict) -> dict:
    """2-way merge (no base). Just calls 3-way with empty base."""
    return _yaml_merge_3way({}, remote, local)


# =============================================================================
# Sync operations
# =============================================================================

def _merge_from_remote(filename, base_commit, action="Merge", update_time=False):
    """3-way merge remote into local for a file and write it."""
    base_content = _read_from_commit(base_commit, filename)
    remote_content = _read_remote(filename)
    local_content = _read_local(filename)

    base = yaml.safe_load(base_content) if base_content else {}
    remote = yaml.safe_load(remote_content) if remote_content else {}
    local = yaml.safe_load(local_content) if local_content else {}

    merged = _yaml_merge_3way(base, remote, local)
    if update_time:
        merged["updated"] = now()
    content = yaml.dump(merged, default_flow_style=False, sort_keys=False)
    _write_local(filename, content, _commit_msg(merged, action))


def _try_merge():
    """Merge remote into local if needed (ff or 3-way)."""
    if not _has_remote():
        return
    remote_ref = f"refs/remotes/{REMOTE}/{BRANCH}"
    if not _git("rev-parse", "--verify", remote_ref):
        return
    # Already in sync
    if _git("rev-parse", BRANCH) == _git("rev-parse", remote_ref):
        return
    # Fast-forward if local is ancestor of remote
    if _git("merge-base", "--is-ancestor", BRANCH, remote_ref) is not None:
        _git("update-ref", f"refs/heads/{BRANCH}", remote_ref)
        return
    # We're ahead - nothing to merge
    if _git("merge-base", "--is-ancestor", remote_ref, BRANCH) is not None:
        return
    # Diverged - 3-way merge each changed file
    base_commit = _get_merge_base()
    remote_diff = _git("diff", "--name-only", base_commit, remote_ref) or ""
    for filename in [f for f in remote_diff.split('\n') if f.endswith('.yaml')]:
        _merge_from_remote(filename, base_commit)


def _try_sync(filename):
    """Try to sync a file with remote. No-op if offline."""
    if not _try_fetch():
        return  # Offline or no remote

    _merge_from_remote(filename, _get_merge_base(), "Sync", update_time=True)

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
    title = issue.get('title', '')[:50]
    ref = issue.get('alias') or f"#{num(issue['id']) or issue['id'][:8]}"
    msg = f"{action}: {title} ({ref})"

    # Add status transition if changed
    old_status = old_issue.get('status') if old_issue else None
    new_status = issue.get('status')
    if old_status and new_status and old_status != new_status:
        msg += f" [{old_status} → {new_status}]"

    return msg


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
    files = [f for f in _git_list() if f.endswith('.yaml')]
    return {n+1: f[:-5] for n, f in enumerate(files)}


def num(id):
    """Get issue number for an ID."""
    return next((n for n, uid in index().items() if uid == id), 0)


def resolve(arg):
    """Resolve issue number, ID, or alias to full ID."""
    if arg.isdigit():
        return index().get(int(arg))
    if len(arg) == 32 and _git_exists(f"{arg}.yaml"):
        return arg
    # Check alias
    for issue in all_issues():
        if issue.get('alias') == arg:
            return issue['id']
    return None


def fetch(arg):
    """Fetch issue by number, ID, or alias. Dies if not found."""
    id = resolve(arg)
    issue = load(id) if id else None
    if not issue:
        die(f"Issue #{arg} not found")
    return id, issue


def refs(ids):
    """Format list of IDs as #num references."""
    return ', '.join(f'#{num(i)}' for i in ids)


def read_raw(id):
    """Read raw YAML content for editor."""
    _ensure_read_setup()
    return _read_local(f"{id}.yaml")


def write_raw(id, content):
    """Write raw YAML content from editor."""
    filename = f"{id}.yaml"
    issue = yaml.safe_load(content) or {}

    # Write locally first
    _write_local(filename, content, _commit_msg(issue, "Edit"))

    # Try to sync with remote
    _try_sync(filename)
