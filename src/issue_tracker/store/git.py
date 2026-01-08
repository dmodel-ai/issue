"""Git orphan branch storage backend."""
import os
import subprocess
import yaml
from ..utils import die, now

BRANCH = os.environ.get("ISSUE_BRANCH", "issues")

def _ensure_branch():
    """Create orphan branch if it doesn't exist, without checkout."""
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

def _git_read(filename):
    try:
        result = subprocess.run(
            ["git", "show", f"{BRANCH}:{filename}"],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None

def _git_write(filename, content, message):
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
    content = _git_read(f"{id}.yaml")
    return yaml.safe_load(content) if content else None

def save(issue):
    _ensure_branch()
    issue["updated"] = now()
    content = yaml.dump(issue, default_flow_style=False, sort_keys=False)
    _git_write(f"{issue['id']}.yaml", content, f"Update issue {issue['id'][:8]}")

def all_issues():
    files = [f for f in _git_list() if f.endswith('.yaml')]
    issues = [yaml.safe_load(_git_read(f)) for f in files]
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
    return _git_read(f"{id}.yaml")

def write_raw(id, content):
    """Write raw YAML content from editor."""
    _ensure_branch()
    _git_write(f"{id}.yaml", content, f"Edit issue {id[:8]}")
