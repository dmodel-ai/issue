"""Storage: dynamic backend selection based on git availability."""
import subprocess

def _in_git_repo():
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True
    )
    return result.returncode == 0

if _in_git_repo():
    from .git import load, save, all_issues, index, num, resolve, fetch, refs, read_raw, write_raw
else:
    from .file import load, save, all_issues, index, num, resolve, fetch, refs, read_raw, write_raw
