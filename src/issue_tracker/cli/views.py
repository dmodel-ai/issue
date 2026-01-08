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
    alias_str = f" ({i['alias']})" if i.get('alias') else ""
    print(f"#{num(i['id'])}{alias_str} {i['title']}")
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
    if cc := i.get('cc'):
        print(f"cc: {', '.join(cc)}")

    for k in ['attention', 'blocked_by', 'blocks', 'labels']:
        if v := i.get(k):
            print(f"{k}: {refs(v) if k in ('blocked_by', 'blocks') else ', '.join(v)}")
    if due := i.get('due'):
        print(f"due: {', '.join(f'{k}:{v}' for k, v in due.items())}")
    print(f"created: {i['created']}  updated: {i['updated']}")
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

    print(f"{C['dim']}{'ID':<14} {'STATUS':10} {'OWNER':<16} TITLE{C['reset']}")
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
        u = user()
        owner_name = "YOU" if i['owner'] == u else i['owner']
        oc = C['bold'] if i['owner'] == u else C['cyan']
        alias = f" ({i['alias']})" if i.get('alias') else ""
        id_alias = f"#{num(i['id'])}{alias}"
        print(f"{C['bold']}{id_alias:<14}{C['reset']} {sc}{i['status']:10}{C['reset']} {oc}{owner_name:<16}{C['reset']} {i['title']}{marks}")


def inbox_issues():
    u = user()
    items = [i for i in all_issues()
             if u in i.get('attention', []) and not i.get('blocked_by')]
    return sorted(items, key=lambda i: (not i.get('blocks'), -i.get('priority', 0), i['id']))


def cc_issues():
    u = user()
    items = [i for i in all_issues()
             if u in (i.get('cc') or []) and i['owner'] != u
             and u not in (i.get('attention') or [])]
    return sorted(items, key=lambda i: (-i.get('priority', 0), i['id']))


def outbox_issues():
    u = user()
    items = [i for i in all_issues()
             if i['owner'] == u and u not in i.get('attention', [])
             and i.get('attention') and not i.get('blocked_by')]
    return sorted(items, key=lambda i: (-i.get('priority', 0), i['id']))


def line(i, arrow_to=None):
    u = user()
    owner_name = "YOU" if i['owner'] == u else i['owner']
    arrow_name = arrow_to or owner_name
    arrow_color = C['bold'] if not arrow_to and i['owner'] == u else C['cyan']
    pri_str = f"P{i['priority']}" if i.get('priority') else "-"
    pri_color = C['magenta'] if i.get('priority') else C['dim']
    dep_str = f"→{refs(i['blocks'])}" if i.get('blocks') else f"←{refs(i['blocked_by'])}" if i.get('blocked_by') else "-"
    dep_color = C['green'] if i.get('blocks') else C['red'] if i.get('blocked_by') else C['dim']
    cmt = f'"{i["comments"][-1]["text"][:20]}"' if i.get('comments') else "-"
    sc = C.get(status_colors.get(i['status'], ''), '')
    alias = f" ({i['alias']})" if i.get('alias') else ""
    id_alias = f"#{num(i['id'])}{alias}"
    print(f"  {C['bold']}{id_alias:<14}{C['reset']} {pri_color}{pri_str:<2}{C['reset']} {sc}{i['status']:8}{C['reset']} {arrow_color}{arrow_name:<12}{C['reset']} [{i['title'][:25]:25}] {dep_color}{dep_str:<8}{C['reset']} {C['dim']}{cmt}{C['reset']}")


def header(who="OWNER"):
    print(f"  {C['dim']}{'ID':<14} {'P':<2} {'STATUS':8} {who:<12} {'TITLE':25}   {'DEPS':<8} COMMENT{C['reset']}")

def cmd_inbox(_):
    items = inbox_issues()
    if not items:
        print(f"{C['dim']}Inbox empty!{C['reset']}")
        return False
    print(f"{C['bold']}{C['green']}INBOX{C['reset']} ({len(items)})")
    header()
    for i in items:
        line(i)
    return True


def cmd_cc(_):
    items = cc_issues()
    if not items:
        return False
    print(f"{C['bold']}{C['cyan']}CC{C['reset']} ({len(items)})")
    header()
    for i in items:
        line(i)
    return True


def cmd_outbox(_):
    items = outbox_issues()
    if not items:
        print(f"{C['dim']}Outbox empty!{C['reset']}")
        return False
    print(f"{C['bold']}{C['yellow']}OUTBOX{C['reset']} ({len(items)})")
    header("WAITING")
    for i in items:
        line(i, ', '.join(i.get('attention', ['?']))[:12])
    return True


def cmd_gantt(args):
    from datetime import datetime, timedelta
    issues = [i for i in all_issues() if i.get('due')]
    if not issues:
        print(f"{C['dim']}No issues with due dates{C['reset']}")
        return

    weeks = args.weeks
    today = datetime.now().date()
    start_date = today - timedelta(days=today.weekday())  # Start of current week
    end_date = start_date + timedelta(weeks=weeks)
    total_days = (end_date - start_date).days

    def parse_date(s):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    def render_bar(label, start, end, status, is_current=False):
        sc = C.get(status_colors.get(status, ''), '')
        marker = C['bold'] + '*' + C['reset'] if is_current else ''
        print(f"{C['bold'] if is_current else ''}{label:<20}{C['reset']}", end="")
        for day in range(total_days):
            d = start_date + timedelta(days=day)
            char = " "
            if start and end and start <= d <= end:
                if d == end:
                    char = f"{sc}]{C['reset']}"
                elif d == start:
                    char = f"{sc}[{C['reset']}"
                else:
                    char = f"{sc}={C['reset']}"
            if d == today and char == " ":
                char = f"{C['dim']}:{C['reset']}"
            print(char, end="")
        print()

    # Header: week labels
    print(f"{' ' * 20}", end="")
    d = start_date
    while d < end_date:
        print(f"{d.strftime('%m/%d'):<7}", end="")
        d += timedelta(weeks=1)
    print()

    # Header: day ticks
    print(f"{' ' * 20}", end="")
    for day in range(total_days):
        d = start_date + timedelta(days=day)
        if d == today:
            print(f"{C['bold']}|{C['reset']}", end="")
        elif d.weekday() == 0:
            print("|", end="")
        else:
            print(".", end="")
    print()

    for i in issues:
        alias = i.get('alias') or f"#{num(i['id'])}"
        due = i.get('due', {})

        if args.verbose:
            # Show each state as sub-bar (due date = start of that phase)
            phase_order = ['draft', 'pqa', 'augmenting', 'iqa', 'done']
            phases = [(s, parse_date(due[s])) for s in phase_order if s in due]
            if not phases:
                continue
            # Render task name header showing full span
            render_bar(alias, phases[0][1], phases[-1][1], i['status'], True)
            # Each phase bar: from this phase start to next phase start (or same if last)
            for idx, (state, start) in enumerate(phases):
                end = phases[idx + 1][1] if idx + 1 < len(phases) else start
                is_current = (state == i['status'])
                render_bar(f"  {state}", start, end, state, is_current)
        else:
            # Single bar from earliest due to latest due
            first_due = parse_date(min(due.values())) if due else None
            last_due = parse_date(max(due.values())) if due else None
            render_bar(alias, first_due, last_due, i['status'], True)


def cmd_default(_):
    has_inbox = cmd_inbox(None)
    if has_inbox: print()
    has_cc = cmd_cc(None)
    if has_cc: print()
    has_outbox = cmd_outbox(None)
    if has_outbox: print()
    if not has_inbox and not has_cc and not has_outbox:
        print("No active issues.")
