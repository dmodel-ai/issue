"""Git orphan branch storage backend with YAML-aware sync."""
import os
import subprocess
import sys
import yaml
from ..utils import die, now

BRANCH = os.environ.get("ISSUE_BRANCH", "issues")
REMOTE = os.environ.get("ISSUE_REMOTE", "origin")
AUTO_SYNC = os.environ.get("ISSUE_SYNC", "1") != "0"

# Fields that are immutable (keep original)
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


def _fetch_and_ff():
    """Fetch remote, fast-forward local if local is behind."""
    if not AUTO_SYNC or not _has_remote():
        return

    # Fetch remote
    subprocess.run(
        ["git", "fetch", REMOTE, f"{BRANCH}:refs/remotes/{REMOTE}/{BRANCH}"],
        capture_output=True
    )

    # Get local and remote refs
    local = subprocess.run(
        ["git", "rev-parse", "--verify", BRANCH],
        capture_output=True, text=True
    )
    remote = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/remotes/{REMOTE}/{BRANCH}"],
        capture_output=True, text=True
    )

    if local.returncode != 0 and remote.returncode == 0:
        # No local branch, create from remote
        subprocess.run(
            ["git", "update-ref", f"refs/heads/{BRANCH}", remote.stdout.strip()],
            capture_output=True
        )
    elif local.returncode == 0 and remote.returncode == 0:
        # Both exist, fast-forward if local is ancestor of remote
        merge_base = subprocess.run(
            ["git", "merge-base", BRANCH, f"refs/remotes/{REMOTE}/{BRANCH}"],
            capture_output=True, text=True
        )
        if merge_base.returncode == 0 and merge_base.stdout.strip() == local.stdout.strip():
            # Local is ancestor of remote, fast-forward
            subprocess.run(
                ["git", "update-ref", f"refs/heads/{BRANCH}", remote.stdout.strip()],
                capture_output=True
            )
        # If diverged or local ahead: leave local alone (preserve pending changes)


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


def _push():
    """Push local to remote. Returns True on success."""
    if not AUTO_SYNC or not _has_remote():
        return True
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


def _yaml_merge(remote: dict, local: dict) -> dict:
    """Merge local into remote with field-by-field rules.

    - Immutable fields: keep from remote (or local if new)
    - Timestamps: take latest
    - Scalars: conflict if both differ, prompt user
    - Lists: union
    - Comments: append, sort, dedupe
    """
    if not remote:
        return local.copy()

    merged = {}
    all_keys = set(remote.keys()) | set(local.keys())

    for key in all_keys:
        r_val = remote.get(key)
        l_val = local.get(key)

        if key in IMMUTABLE:
            # Keep original (from remote if exists, else local)
            merged[key] = r_val if r_val is not None else l_val

        elif key in TIMESTAMP:
            # Take latest
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
                # Both have different values - conflict!
                merged[key] = _prompt_conflict(key, r_val, l_val)

        elif key in UNION:
            # Union of lists
            r_list = r_val or []
            l_list = l_val or []
            # Preserve order: remote first, then new items from local
            merged[key] = list(r_list) + [x for x in l_list if x not in r_list]

        elif key == 'comments':
            # Append, sort by time, dedupe by (author, time)
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
            # Unknown field: prefer local
            merged[key] = l_val if l_val is not None else r_val

    return merged


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
    _fetch_and_ff()
    content = _read_local(f"{id}.yaml")
    return yaml.safe_load(content) if content else None


def save(issue):
    _fetch_and_ff()

    filename = f"{issue['id']}.yaml"
    remote_content = _read_remote(filename)
    remote_issue = yaml.safe_load(remote_content) if remote_content else {}

    merged = _yaml_merge(remote_issue, issue)
    merged["updated"] = now()

    content = yaml.dump(merged, default_flow_style=False, sort_keys=False)
    _write_local(filename, content, f"Update issue {issue['id'][:8]}")

    if not _push():
        print(f"Warning: Saved locally, push failed. Re-run to sync.", file=sys.stderr)


def all_issues():
    _fetch_and_ff()
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
    _fetch_and_ff()
    return _read_local(f"{id}.yaml")


def write_raw(id, content):
    """Write raw YAML content from editor."""
    _fetch_and_ff()

    remote_content = _read_remote(f"{id}.yaml")
    if remote_content:
        remote_issue = yaml.safe_load(remote_content)
        local_issue = yaml.safe_load(content)
        merged = _yaml_merge(remote_issue, local_issue)
        merged["updated"] = now()
        content = yaml.dump(merged, default_flow_style=False, sort_keys=False)

    _write_local(f"{id}.yaml", content, f"Edit issue {id[:8]}")

    if not _push():
        print(f"Warning: Saved locally, push failed. Re-run to sync.", file=sys.stderr)
