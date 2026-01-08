"""Views: list, show, inbox, outbox."""
from ..utils import ago, user
from ..store import all_issues, fetch, num, refs
from ..workflows import status_colors
from ..query import filter_issues

C = {
    'reset': '\033[0m', 'bold': '\033[1m', 'dim': '\033[2m',
    'red': '\033[31m', 'green': '\033[32m', 'yellow': '\033[33m',
    'blue': '\033[34m', 'magenta': '\033[35m', 'cyan': '\033[36m',
}


def cmd_show(args):
    _, i = fetch(args.id)
    print(f"#{num(i['id'])} {i['title']}")
    print(f"status: {i['status']}  owner: {i['owner']}")

    # Show reviewer approval status
    if reviewers := i.get('reviewers'):
        approved = i.get('approved_by', [])
        print(f"reviewers: {', '.join(reviewers)}")
        if approved:
            print(f"approved: {', '.join(approved)} ({len(approved)}/{len(reviewers)})")
        pending = [r for r in reviewers if r not in approved]
        if pending:
            print(f"pending: {', '.join(pending)}")

    for k in ['attention', 'blocked_by', 'blocks', 'labels']:
        if v := i.get(k):
            print(f"{k}: {refs(v) if k in ('blocked_by', 'blocks') else ', '.join(v)}")
    print(f"created: {i['created']}  updated: {i['updated']}")
    if i['description']:
        print("\n" + i['description'])
    if i['comments']:
        print("\ncomments:")
        for c in i['comments']:
            print(f"  {c['author']} ({ago(c['time'])}): {c['text']}")


def cmd_list(args):
    issues = all_issues()

    # Apply query DSL if provided
    if args.query:
        issues = filter_issues(issues, args.query)

    if args.me:
        u = user()
        issues = [i for i in issues if u == i['owner']
                  or u in i.get('reviewers', []) or u in i.get('cc', [])]

    # Translate flags to query terms for backwards compat
    filters = [
        (args.owner,    lambda i, v: i['owner'] == v.replace('@me', user())),
        (args.status,   lambda i, v: i['status'] in v.split(',')),
        (args.reviewer, lambda i, v: v.replace('@me', user()) in i.get('reviewers', [])),
        (args.cc,       lambda i, v: v.replace('@me', user()) in i.get('cc', [])),
        (args.label,    lambda i, v: v in i.get('labels', [])),
        (args.blocked,  lambda i, _: i.get('blocked_by')),
        (args.blocking, lambda i, _: i.get('blocks')),
    ]
    for val, pred in filters:
        if val:
            issues = [i for i in issues if pred(i, val)]

    if not issues:
        print("No issues found")
        return

    for i in issues:
        marks = ""
        if i.get('attention'): marks += f" {C['yellow']}⚠️{C['reset']}"
        # Show approval progress for issues with reviewers
        reviewers = i.get('reviewers', [])
        approved = i.get('approved_by', [])
        if reviewers and len(approved) < len(reviewers):
            marks += f" [{len(approved)}/{len(reviewers)}]"
        if i['blocks']: marks += f" {C['green']}→ {refs(i['blocks'])}{C['reset']}"
        if i['blocked_by']: marks += f" {C['red']}← {refs(i['blocked_by'])}{C['reset']}"
        sc = C.get(status_colors.get(i['status'], ''), '')
        owner = f"{C['bold']}YOU{C['reset']}" if i['owner'] == user() else f"{C['cyan']}{i['owner']}{C['reset']}"
        print(f"{C['bold']}#{num(i['id']):<3}{C['reset']} {sc}{i['status']:10}{C['reset']} {owner:24} {i['title']}{marks}")


def inbox_issues():
    u = user()
    items = [i for i in all_issues()
             if u in i.get('attention', []) and not i.get('blocked_by')]
    return sorted(items, key=lambda i: (not i.get('blocks'), -i.get('priority', 0), i['id']))


def outbox_issues():
    u = user()
    items = [i for i in all_issues()
             if i['owner'] == u and u not in i.get('attention', [])
             and i.get('attention') and not i.get('blocked_by')]
    return sorted(items, key=lambda i: (-i.get('priority', 0), i['id']))


def line(i, arrow_to=None):
    u = user()
    owner = f"{C['bold']}YOU{C['reset']}" if i['owner'] == u else f"{C['cyan']}{i['owner']}{C['reset']}"
    arrow = arrow_to or owner
    pri = f"{C['magenta']}P{i['priority']}{C['reset']}" if i.get('priority') else f"{C['dim']}-{C['reset']}"
    deps = f"{C['green']}→{refs(i['blocks'])}{C['reset']}" if i.get('blocks') else \
           f"{C['red']}←{refs(i['blocked_by'])}{C['reset']}" if i.get('blocked_by') else f"{C['dim']}-{C['reset']}"
    comment = f'{C["dim"]}"{i["comments"][-1]["text"][:20]}"{C["reset"]}' if i.get('comments') else f'{C["dim"]}-{C["reset"]}'
    sc = C.get(status_colors.get(i['status'], ''), '')
    print(f"  {C['bold']}#{num(i['id']):<2}{C['reset']} {pri:14} {sc}{i['status']:8}{C['reset']} {arrow:21} [{i['title'][:25]:25}] {deps:20} {comment}")


def cmd_inbox(_):
    items = inbox_issues()
    if not items:
        print(f"{C['dim']}Inbox empty!{C['reset']}")
        return False
    print(f"{C['bold']}{C['green']}INBOX{C['reset']} ({len(items)})")
    for i in items:
        line(i)
    return True


def cmd_outbox(_):
    items = outbox_issues()
    if not items:
        print(f"{C['dim']}Outbox empty!{C['reset']}")
        return False
    print(f"{C['bold']}{C['yellow']}OUTBOX{C['reset']} ({len(items)})")
    for i in items:
        line(i, ', '.join(i.get('attention', ['?']))[:12])
    return True


def cmd_default(_):
    has = cmd_inbox(None)
    if has: print()
    has2 = cmd_outbox(None)
    if has2: print()
    if not has and not has2:
        print("No active issues.")
