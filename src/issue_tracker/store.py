"""Persistence: load, save, query issues."""
import yaml
from .utils import DIR, die, now

def load(id):
    path = DIR / f"{id}.yaml"
    return yaml.safe_load(open(path)) if path.exists() else None

def save(issue):
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
    return None

def fetch(arg):
    id = resolve(arg)
    issue = load(id) if id else None
    if not issue:
        die(f"Issue #{arg} not found")
    return id, issue

def refs(ids):
    return ', '.join(f'#{num(i)}' for i in ids)
