"""Filesystem storage backend."""
import os
import yaml
from pathlib import Path
from ..utils import die, now

DIR = Path(os.environ.get("ISSUE_DIR", ".issues"))

def load(id):
    path = DIR / f"{id}.yaml"
    return yaml.safe_load(open(path)) if path.exists() else None

def save(issue):
    DIR.mkdir(exist_ok=True)
    issue["updated"] = now()
    yaml.dump(issue, open(DIR / f"{issue['id']}.yaml", "w"),
              default_flow_style=False, sort_keys=False)

def all_issues():
    if not DIR.exists():
        return []
    issues = [yaml.safe_load(open(p)) for p in sorted(DIR.glob("*.yaml"))]
    return sorted([i for i in issues if i], key=lambda i: i['id'])

def index():
    if not DIR.exists():
        return {}
    return {n+1: p.stem for n, p in enumerate(sorted(DIR.glob("*.yaml")))}

def num(id):
    return next((n for n, uid in index().items() if uid == id), 0)

def resolve(arg):
    if arg.isdigit():
        return index().get(int(arg))
    if len(arg) == 32 and (DIR / f"{arg}.yaml").exists():
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
    path = DIR / f"{id}.yaml"
    return path.read_text() if path.exists() else None

def write_raw(id, content):
    """Write raw YAML content from editor."""
    DIR.mkdir(exist_ok=True)
    (DIR / f"{id}.yaml").write_text(content)
