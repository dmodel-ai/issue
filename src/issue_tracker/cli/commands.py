"""Commands: create, comment, update, link, pick."""
import os
import subprocess
import tempfile
import uuid_utils as uuid
import yaml
from pathlib import Path

from ..utils import die, edit, now, user
from ..store import load, save, fetch, num, resolve, all_issues, read_raw, write_raw
from ..workflows import transition, workflow, INITIAL_STATE, DONE_STATE
from .views import inbox_issues, outbox_issues

def _str_representer(dumper, data):
    style = '|' if '\n' in data else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style=style)
yaml.SafeDumper.add_representer(str, _str_representer)


def validate_alias(alias):
    if alias and alias.isdigit():
        die("Alias cannot be a number")
    return alias

def cmd_create(args):
    ts = now()
    owner = args.owner or user()

    title = args.title
    alias = validate_alias(args.alias)
    priority = args.priority or 0
    reviewers = args.reviewers or []
    cc = args.cc or []
    labels = args.labels or []
    blocked_by = []
    blocks = []
    comment = None

    if not title:
        text = edit(f"""\
Owner: {owner}
Alias: {alias or ''}
Priority: {priority}
Reviewers: {', '.join(reviewers)}
CC: {', '.join(cc)}
Labels: {', '.join(labels)}
Blocked-by:
Blocks:

# Title on next blank line, then comment body
# Lines starting with # are stripped
""")
        meta = {}
        lines = []
        for ln in text.split('\n'):
            if ln.startswith('#'):
                continue
            if ':' in ln and not lines and not meta.get('_done'):
                key, val = ln.split(':', 1)
                meta[key.strip().lower().replace('-', '_')] = val.strip()
                continue
            meta['_done'] = True
            lines.append(ln)

        def parse_list(s):
            return [x.strip() for x in s.split(',') if x.strip()]

        def parse_refs(s):
            ids = []
            for r in parse_list(s):
                id = resolve(r.lstrip('#'))
                if id:
                    ids.append(id)
            return ids

        if meta.get('owner'):
            owner = meta['owner']
        if meta.get('alias'):
            alias = validate_alias(meta['alias'])
        if meta.get('priority'):
            priority = int(meta['priority'])
        if meta.get('reviewers'):
            reviewers = parse_list(meta['reviewers'])
        if meta.get('cc'):
            cc = parse_list(meta['cc'])
        if meta.get('labels'):
            labels = parse_list(meta['labels'])
        if meta.get('blocked_by'):
            blocked_by = parse_refs(meta['blocked_by'])
        if meta.get('blocks'):
            blocks = parse_refs(meta['blocks'])

        while lines and not lines[0].strip():
            lines.pop(0)
        title = lines[0].strip() if lines else ""
        if not title:
            die("Aborted: no title")
        body = '\n'.join(lines[1:]).strip()
        if body:
            comment = body

    issue = {
        "id": uuid.uuid7().hex,
        "title": title,
        "status": INITIAL_STATE,
        "owner": owner,
        "priority": priority,
        "reviewers": reviewers,
        "cc": cc,
        "created": ts,
        "updated": ts,
        "blocked_by": blocked_by,
        "blocks": blocks,
        "labels": labels,
        "comments": [],
        "attention": [owner],
    }
    if alias:
        issue["alias"] = alias
    if comment:
        issue["comments"].append({"author": owner, "time": ts, "text": comment})
    for bid in blocked_by:
        blocker = load(bid)
        if blocker and issue["id"] not in blocker.get("blocks", []):
            blocker.setdefault("blocks", []).append(issue["id"])
            save(blocker)
    for bid in blocks:
        blocked = load(bid)
        if blocked and issue["id"] not in blocked.get("blocked_by", []):
            blocked.setdefault("blocked_by", []).append(issue["id"])
            save(blocked)
    save(issue)
    print(f"Created #{num(issue['id'])}: {title}")
    print(f"Attention: {owner}")


def cmd_do(action, args):
    import inspect
    _, issue = fetch(args.id)

    # Build ctx from handler params
    handler = workflow.transitions[action][2]
    sig = inspect.signature(handler)
    params = list(sig.parameters.keys())

    ctx = {"u": user()}
    extra_issues = []

    for param in params[1:]:  # skip 'issue'
        if param.startswith('_') or param == 'kwargs':
            continue
        val = getattr(args, param, None)
        if val is None:
            continue
        # Try to resolve as issue reference
        resolved = resolve(val)
        if resolved:
            _, loaded = fetch(val)
            ctx[param] = loaded
            extra_issues.append(loaded)
        else:
            ctx[param] = val

    transition(issue, action, **ctx)
    save(issue)
    for extra in extra_issues:
        save(extra)

    past = {"review": "Submitted for review", "comment": "Commented on", "approve": "Approved", "done": "Done"}
    print(f"{past.get(action, action.title() + 'ed')} #{args.id}")
    print(f"Attention: {', '.join(issue['attention'])}")


def cmd_comment(args, note: bool = False):
    if not args.id:
        inbox = inbox_issues()
        if not inbox:
            die("No issues in inbox")
        id = inbox[0]['id']
    else:
        id = resolve(args.id)
        if not id:
            die(f"Issue #{args.id} not found")

    issue = load(id)
    text = args.text
    if not text:
        issue_yaml = yaml.dump(issue, Dumper=yaml.SafeDumper, default_flow_style=False, sort_keys=False)
        commented = '\n'.join(f'# {l}' for l in issue_yaml.split('\n'))
        text = edit(f"{commented}\n\n").strip()
        text = '\n'.join(l for l in text.split('\n') if not l.startswith('#')).strip()
        if not text:
            die("Aborted: no note" if note else "Aborted: no comment")

    transition(issue, "note" if note else "comment", u=user(), text=text)
    save(issue)
    print(f"{"Noted" if note else "Commented"} on #{num(id)}")
    print(f"Attention: {', '.join(issue['attention'])}")


def cmd_update(args):
    if not args.id:
        inbox = inbox_issues()
        if not inbox:
            die("No issues in inbox")
        id = inbox[0]['id']
    else:
        id = resolve(args.id)
        if not id:
            die(f"Issue #{args.id} not found")

    has_flags = args.status or args.owner or args.title or args.priority is not None \
                or args.add_reviewer or args.add_cc or len(args.due) or args.add_label or args.done or args.abandon or args.alias

    if not has_flags:
        content = read_raw(id)
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(content)
            tmp_path = f.name
        editor = os.environ.get("EDITOR", "vi")
        subprocess.run(f'{editor} "{tmp_path}"', shell=True)
        new_content = Path(tmp_path).read_text()
        write_raw(id, new_content)
        Path(tmp_path).unlink()
        print(f"Updated #{num(id)}")
        return

    issue = load(id)
    status = args.status or (DONE_STATE if args.done else "abandoned" if args.abandon else None)
    if status:
        if status in workflow.terminal:
            action = "done" if status == DONE_STATE else "abandon"
            if action in workflow.transitions:
                transition(issue, action)
            else:
                issue["status"] = status
        else:
            issue["status"] = status

    if args.owner:
        issue["owner"] = args.owner
    if args.title:
        issue["title"] = args.title
    if args.alias:
        issue["alias"] = validate_alias(args.alias)
    if args.priority is not None:
        issue["priority"] = args.priority

    for r in (args.add_reviewer or []):
        if r not in issue.setdefault("reviewers", []):
            issue["reviewers"].append(r)
    for c in (args.add_cc or []):
        if issue.get("cc") is None:
            issue["cc"] = []
        if c not in issue["cc"]:
            issue["cc"].append(c)
    for d in args.due:
        if ':' not in d:
            die(f"Invalid due format: {d} (expected state:date)")
        state, date = d.split(':', 1)
        if issue.get("due") is None:
            issue["due"] = {}
        issue["due"][state] = date
    for label in (args.add_label or []):
        if label not in issue.setdefault("labels", []):
            issue["labels"].append(label)

    save(issue)
    print(f"Updated #{num(id)}")


def cmd_pick(args):
    issues = all_issues()
    if args.inbox:
        issues = inbox_issues()
    elif args.outbox:
        issues = outbox_issues()
    if not issues:
        die("No issues")

    lines = []
    for i in issues:
        n = num(i['id'])
        status = i['status'][:8]
        owner = i['owner'][:12]
        title = i['title'][:40]
        lines.append(f"{n}\t{status}\t{owner}\t{title}")

    try:
        result = subprocess.run(
            ["fzf", "--with-nth=2..", "--delimiter=\t", "--preview", "issue show {{1}}"],
            input='\n'.join(lines), capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            print(result.stdout.strip().split('\t')[0])
    except FileNotFoundError:
        die("fzf not found")
