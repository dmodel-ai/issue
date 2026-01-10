"""Storage: dynamic backend selection based on git availability."""
import subprocess
from ..utils import die


def _in_git_repo():
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True
    )
    return result.returncode == 0


# Import backend primitives
if _in_git_repo():
    from .git import exists, load, save, all_issues, index, read_raw, write_raw
else:
    from .file import exists, load, save, all_issues, index, read_raw, write_raw


# Shared functions built on primitives

def num(id):
    """Get issue number for an ID."""
    return next((n for n, uid in index().items() if uid == id), 0)


def resolve(arg):
    """Resolve issue number, ID, or alias to full ID."""
    if arg.isdigit():
        return index().get(int(arg))
    if len(arg) == 32 and exists(arg):
        return arg
    # Check alias (exact match first, then prefix match)
    issues = all_issues()
    for issue in issues:
        if issue.get('alias') == arg:
            return issue['id']
    # Prefix match: find unique alias starting with arg
    matches = [i for i in issues if (i.get('alias') or '').startswith(arg)]
    if len(matches) == 1:
        return matches[0]['id']
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
