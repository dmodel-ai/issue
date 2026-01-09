"""Filesystem storage backend."""
import os
import yaml
from pathlib import Path
from ..utils import now

DIR = Path(os.environ.get("ISSUE_DIR", ".issues"))


def exists(id):
    """Check if issue exists."""
    return (DIR / f"{id}.yaml").exists()


def load(id):
    """Load an issue by ID."""
    path = DIR / f"{id}.yaml"
    return yaml.safe_load(open(path)) if path.exists() else None


def save(issue):
    """Save an issue (create or update)."""
    DIR.mkdir(exist_ok=True)
    issue["updated"] = now()
    yaml.dump(issue, open(DIR / f"{issue['id']}.yaml", "w"),
              default_flow_style=False, sort_keys=False)


def all_issues():
    """Get all issues, sorted by ID."""
    if not DIR.exists():
        return []
    issues = [yaml.safe_load(open(p)) for p in sorted(DIR.glob("*.yaml"))]
    return sorted([i for i in issues if i], key=lambda i: i['id'])


def index():
    """Get mapping of issue numbers to IDs."""
    if not DIR.exists():
        return {}
    return {n+1: p.stem for n, p in enumerate(sorted(DIR.glob("*.yaml")))}


def read_raw(id):
    """Read raw YAML content for editor."""
    path = DIR / f"{id}.yaml"
    return path.read_text() if path.exists() else None


def write_raw(id, content):
    """Write raw YAML content from editor."""
    DIR.mkdir(exist_ok=True)
    (DIR / f"{id}.yaml").write_text(content)
