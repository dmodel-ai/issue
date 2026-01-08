"""Git orphan branch storage backend with YAML-aware 3-way sync."""
import os
import subprocess
import sys
import threading
import yaml
from ..utils import die, now

BRANCH = os.environ.get("ISSUE_BRANCH", "issues")
REMOTE = os.environ.get("ISSUE_REMOTE", "origin")
AUTO_SYNC = os.environ.get("ISSUE_SYNC", "1") != "0"

# Background fetch state
_fetch_thread = None
_fetch_lock = threading.Lock()

# Fields that are immutable (keep base)
IMMUTABLE = {'id', 'created'}
# Fields where we take the latest timestamp
TIMESTAMP = {'updated'}
# Scalar fields that conflict if both changed differently
SCALAR = {'title', 'owner', 'status', 'priority', 'alias'}
# List fields merged via union
UNION = {'reviewers', 'cc', 'labels', 'approved_by', 'attention', 'blocked_by', 'blocks'}
# Comments: append, sort by time, dedupe


def _has_remote():
    """Check if remote exists."""
    result = subprocess.run(["git", "remote"], capture_output=True, text=True)
    return REMOTE in result.stdout.split()


def _ensure_branch():
    """Create orphan branch if it doesn't exist."""
    try:
        subprocess.run(["git", "rev-parse", "--verify", BRANCH],
                       capture_output=True, check=True)
    except subprocess.CalledProcessError:
        tree = subprocess.run(
            ["git", "hash-object", "-t", "tree", "/dev/null"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "commit-tree", tree, "-m", "Initialize issues"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        subprocess.run(["git", "update-ref", f"refs/heads/{BRANCH}", commit], check=True)


def _try_fetch():
    """Try to fetch remote (blocking). Returns True if online/successful."""
    if not AUTO_SYNC or not _has_remote():
        return False
    result = subprocess.run(
        ["git", "fetch", REMOTE, f"{BRANCH}:refs/remotes/{REMOTE}/{BRANCH}"],
        capture_output=True
    )
    return result.returncode == 0


def _fetch_background():
    """Start a background fetch. Returns immediately."""
    global _fetch_thread
    if not AUTO_SYNC or not _has_remote():
        return
    with _fetch_lock:
        # Don't start another fetch if one is running
        if _fetch_thread is not None and _fetch_thread.is_alive():
            return
        _fetch_thread = threading.Thread(target=_try_fetch, daemon=True)
        _fetch_thread.start()


def _get_merge_base():
    """Get merge-base commit between local and remote. Returns None if not available."""
    result = subprocess.run(
        ["git", "merge-base", BRANCH, f"refs/remotes/{REMOTE}/{BRANCH}"],
        capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _read_from_commit(commit, filename):
    """Read file from a specific commit. Returns None if not found."""
    if not commit:
        return None
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{filename}"],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def _read_local(filename):
    """Read file from local issues branch."""
    try:
        result = subprocess.run(
            ["git", "show", f"{BRANCH}:{filename}"],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def _read_remote(filename):
    """Read file from origin/issues."""
    try:
        result = subprocess.run(
            ["git", "show", f"{REMOTE}/{BRANCH}:{filename}"],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def _write_local(filename, content, message):
    """Write to local issues branch using git plumbing."""
    _ensure_branch()

    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=content, capture_output=True, text=True, check=True
    ).stdout.strip()

    try:
        tree_content = subprocess.run(
            ["git", "ls-tree", BRANCH],
            capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        tree_content = ""

    lines = [l for l in tree_content.strip().split('\n')
             if l and not l.endswith(f'\t{filename}')]
    lines.append(f"100644 blob {blob}\t{filename}")

    new_tree = subprocess.run(
        ["git", "mktree"],
        input='\n'.join(lines), capture_output=True, text=True, check=True
    ).stdout.strip()

    parent = subprocess.run(
        ["git", "rev-parse", BRANCH],
        capture_output=True, text=True
    )
    parent_args = ["-p", parent.stdout.strip()] if parent.returncode == 0 else []

    commit = subprocess.run(
        ["git", "commit-tree", new_tree, *parent_args, "-m", message],
        capture_output=True, text=True, check=True
    ).stdout.strip()

    subprocess.run(["git", "update-ref", f"refs/heads/{BRANCH}", commit], check=True)


def _try_push():
    """Try to push local to remote. Returns True on success."""
    if not AUTO_SYNC or not _has_remote():
        return True  # No remote, consider it "success"
    result = subprocess.run(
        ["git", "push", REMOTE, BRANCH],
        capture_output=True, text=True
    )
    return result.returncode == 0


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


def _yaml_merge_3way(base: dict, remote: dict, local: dict) -> dict:
    """3-way merge with field-by-field rules.

    For each field:
    - If neither changed from base: use base
    - If only local changed: use local
    - If only remote changed: use remote
    - If both changed to same value: use that value
    - If both changed differently: apply field-specific strategy
    """
    base = base or {}
    remote = remote or {}
    local = local or {}

    # If no base, fall back to 2-way merge preferring local
    if not base:
        return _yaml_merge_2way(remote, local)

    merged = {}
    all_keys = set(base.keys()) | set(remote.keys()) | set(local.keys())

    for key in all_keys:
        b_val = base.get(key)
        r_val = remote.get(key)
        l_val = local.get(key)

        # Determine what changed
        local_changed = l_val != b_val
        remote_changed = r_val != b_val

        if not local_changed and not remote_changed:
            # Neither changed
            merged[key] = b_val
        elif local_changed and not remote_changed:
            # Only local changed
            merged[key] = l_val
        elif not local_changed and remote_changed:
            # Only remote changed
            merged[key] = r_val
        elif l_val == r_val:
            # Both changed to same value
            merged[key] = l_val
        else:
            # Both changed differently - apply field-specific strategy
            merged[key] = _merge_conflict(key, b_val, r_val, l_val)

    return merged


def _merge_conflict(key, base_val, remote_val, local_val):
    """Handle a field where both sides changed differently."""
    if key in IMMUTABLE:
        # Keep base
        return base_val

    elif key in TIMESTAMP:
        # Take latest
        vals = [v for v in [remote_val, local_val] if v]
        return max(vals) if vals else base_val

    elif key in SCALAR:
        # Conflict - prompt user
        return _prompt_conflict(key, remote_val, local_val)

    elif key in UNION:
        # Union of both changes (relative to base)
        base_set = set(base_val or [])
        remote_set = set(remote_val or [])
        local_set = set(local_val or [])
        # Items added by either side
        added_by_remote = remote_set - base_set
        added_by_local = local_set - base_set
        # Items removed by either side
        removed_by_remote = base_set - remote_set
        removed_by_local = base_set - local_set
        # Result: base + additions - removals
        result_set = (base_set | added_by_remote | added_by_local) - removed_by_remote - removed_by_local
        # Preserve order: base first, then remote additions, then local additions
        result = [x for x in (base_val or []) if x in result_set]
        for x in (remote_val or []):
            if x in added_by_remote and x not in result:
                result.append(x)
        for x in (local_val or []):
            if x in added_by_local and x not in result:
                result.append(x)
        return result

    elif key == 'comments':
        # Append all, sort by time, dedupe
        all_comments = (base_val or []) + (remote_val or []) + (local_val or [])
        seen = set()
        unique = []
        for c in all_comments:
            key_tuple = (c.get('author'), c.get('time'))
            if key_tuple not in seen:
                seen.add(key_tuple)
                unique.append(c)
        return sorted(unique, key=lambda c: c.get('time', ''))

    else:
        # Unknown field: prefer local
        return local_val


def _yaml_merge_2way(remote: dict, local: dict) -> dict:
    """2-way merge fallback when no base available."""
    if not remote:
        return local.copy() if local else {}

    merged = {}
    all_keys = set(remote.keys()) | set(local.keys())

    for key in all_keys:
        r_val = remote.get(key)
        l_val = local.get(key)

        if key in IMMUTABLE:
            merged[key] = r_val if r_val is not None else l_val
        elif key in TIMESTAMP:
            if r_val and l_val:
                merged[key] = max(r_val, l_val)
            else:
                merged[key] = l_val or r_val
        elif key in SCALAR:
            if r_val == l_val:
                merged[key] = l_val
            elif r_val is None:
                merged[key] = l_val
            elif l_val is None:
                merged[key] = r_val
            else:
                merged[key] = _prompt_conflict(key, r_val, l_val)
        elif key in UNION:
            r_list = r_val or []
            l_list = l_val or []
            merged[key] = list(r_list) + [x for x in l_list if x not in r_list]
        elif key == 'comments':
            r_comments = r_val or []
            l_comments = l_val or []
            seen = set()
            all_comments = []
            for c in r_comments + l_comments:
                key_tuple = (c.get('author'), c.get('time'))
                if key_tuple not in seen:
                    seen.add(key_tuple)
                    all_comments.append(c)
            merged['comments'] = sorted(all_comments, key=lambda c: c.get('time', ''))
        else:
            merged[key] = l_val if l_val is not None else r_val

    return merged


def _try_sync(filename):
    """Try to sync a file with remote. No-op if offline."""
    if not _try_fetch():
        return  # Offline or no remote

    base_commit = _get_merge_base()
    base_content = _read_from_commit(base_commit, filename)
    remote_content = _read_remote(filename)
    local_content = _read_local(filename)

    base = yaml.safe_load(base_content) if base_content else {}
    remote = yaml.safe_load(remote_content) if remote_content else {}
    local = yaml.safe_load(local_content) if local_content else {}

    # 3-way merge
    merged = _yaml_merge_3way(base, remote, local)
    merged["updated"] = now()

    content = yaml.dump(merged, default_flow_style=False, sort_keys=False)
    _write_local(filename, content, f"Sync issue {filename[:-5][:8]}")

    if not _try_push():
        print(f"Warning: Saved locally, push failed. Re-run to sync.", file=sys.stderr)


# Git helpers for listing/existence

def _git_list():
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", BRANCH],
            capture_output=True, text=True, check=True
        )
        return sorted(result.stdout.strip().split('\n')) if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        return []


def _git_exists(filename):
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{BRANCH}:{filename}"],
        capture_output=True
    )
    return result.returncode == 0


# Public API

def load(id):
    _fetch_background()  # Non-blocking fetch for next read
    content = _read_local(f"{id}.yaml")
    return yaml.safe_load(content) if content else None


def save(issue):
    filename = f"{issue['id']}.yaml"
    issue["updated"] = now()

    # Write locally first (works offline)
    content = yaml.dump(issue, default_flow_style=False, sort_keys=False)
    _write_local(filename, content, f"Update issue {issue['id'][:8]}")

    # Try to sync with remote
    _try_sync(filename)


def all_issues():
    _fetch_background()  # Non-blocking fetch for next read
    files = [f for f in _git_list() if f.endswith('.yaml')]
    issues = [yaml.safe_load(_read_local(f)) for f in files]
    return sorted([i for i in issues if i], key=lambda i: i['id'])


def index():
    files = [f for f in _git_list() if f.endswith('.yaml')]
    return {n+1: f[:-5] for n, f in enumerate(files)}


def num(id):
    return next((n for n, uid in index().items() if uid == id), 0)


def resolve(arg):
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
    id = resolve(arg)
    issue = load(id) if id else None
    if not issue:
        die(f"Issue #{arg} not found")
    return id, issue


def refs(ids):
    return ', '.join(f'#{num(i)}' for i in ids)


def read_raw(id):
    """Read raw YAML content for editor."""
    _fetch_background()  # Non-blocking fetch for next read
    return _read_local(f"{id}.yaml")


def write_raw(id, content):
    """Write raw YAML content from editor."""
    filename = f"{id}.yaml"

    # Write locally first
    _write_local(filename, content, f"Edit issue {id[:8]}")

    # Try to sync with remote
    _try_sync(filename)
