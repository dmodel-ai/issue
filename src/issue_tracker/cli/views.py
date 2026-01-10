"""Views: list, show, inbox, outbox."""
from tabulate import tabulate
from ..utils import ago, user
from ..store import all_issues, fetch, num, refs
from ..workflows import status_colors
from ..query import filter_issues

C = {
    'reset': '\033[0m', 'bold': '\033[1m', 'dim': '\033[2m',
    'red': '\033[31m', 'green': '\033[32m', 'yellow': '\033[33m',
    'blue': '\033[34m', 'magenta': '\033[35m', 'cyan': '\033[36m',
    # Bright versions
    'bred': '\033[91m', 'bgreen': '\033[92m', 'byellow': '\033[93m',
    'bblue': '\033[94m', 'bmagenta': '\033[95m', 'bcyan': '\033[96m',
    # Background colors (with contrasting fg)
    'bg_red': '\033[97;41m', 'bg_green': '\033[30;42m', 'bg_yellow': '\033[30;43m',
    'bg_blue': '\033[97;44m', 'bg_magenta': '\033[97;45m', 'bg_cyan': '\033[30;46m',
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

    rows = []
    u = user()
    for i in issues:
        marks = ""
        if u in i.get('attention', []):
            marks += f" {C['yellow']}⚠️{C['reset']}"
        reviewers = i.get('reviewers', [])
        approved = i.get('approved_by', [])
        if reviewers and len(approved) < len(reviewers):
            marks += f" [{len(approved)}/{len(reviewers)}]"
        if i['blocks']:
            marks += f" {C['green']}→ {refs(i['blocks'])}{C['reset']}"
        if i['blocked_by']:
            marks += f" {C['red']}← {refs(i['blocked_by'])}{C['reset']}"

        sc = C.get(status_colors.get(i['status'], ''), '')
        owner_name = "YOU" if i['owner'] == u else i['owner']
        oc = C['bold'] if i['owner'] == u else C['cyan']
        alias = f" ({i['alias']})" if i.get('alias') else ""
        id_alias = f"#{num(i['id'])}{alias}"

        rev_list = ['YOU' if r == u else r for r in reviewers]
        rev_str = ', '.join(rev_list) if rev_list else '-'
        rows.append([
            f"{C['bold']}{id_alias}{C['reset']}",
            f"{sc}{i['status']}{C['reset']}",
            f"{oc}{owner_name}{C['reset']}",
            f"{C['cyan']}{rev_str}{C['reset']}",
            f"{i['title']}{marks}",
        ])
    headers = [f"{C['dim']}ID{C['reset']}", f"{C['dim']}STATUS{C['reset']}",
               f"{C['dim']}OWNER{C['reset']}", f"{C['dim']}REVIEWERS{C['reset']}",
               f"{C['dim']}TITLE{C['reset']}"]
    print(tabulate(rows, headers=headers, tablefmt="plain"))


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


def done_issues():
    u = user()
    items = [i for i in all_issues()
             if i['status'] == 'done'
             and (i['owner'] == u or u in i.get('reviewers', []))]
    return sorted(items, key=lambda i: i['updated'], reverse=True)


def _inbox_headers(who="OWNER"):
    d, r = C['dim'], C['reset']
    return [f"{d}ID{r}", f"{d}P{r}", f"{d}STATUS{r}", f"{d}{who}{r}",
            f"{d}TITLE{r}", f"{d}DEPS{r}", f"{d}COMMENT{r}"]


def _make_inbox_row(i, arrow_to=None):
    """Build a row for inbox/outbox tables."""
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
    r = C['reset']
    return [
        f"{C['bold']}{id_alias}{r}",
        f"{pri_color}{pri_str}{r}",
        f"{sc}{i['status']}{r}",
        f"{arrow_color}{arrow_name}{r}",
        f"[{i['title'][:25]}]",
        f"{dep_color}{dep_str}{r}",
        f"{C['dim']}{cmt}{r}",
    ]


def cmd_inbox(_):
    items = inbox_issues()
    if not items:
        return False
    print(f"{C['bold']}{C['green']}INBOX{C['reset']} ({len(items)})")
    rows = [_make_inbox_row(i) for i in items]
    print(tabulate(rows, headers=_inbox_headers(), tablefmt="plain"))
    return True


def cmd_cc(_):
    items = cc_issues()
    if not items:
        return False
    print(f"{C['bold']}{C['cyan']}CC{C['reset']} ({len(items)})")
    rows = [_make_inbox_row(i) for i in items]
    print(tabulate(rows, headers=_inbox_headers(), tablefmt="plain"))
    return True


def cmd_outbox(_):
    items = outbox_issues()
    if not items:
        return False
    print(f"{C['bold']}{C['yellow']}OUTBOX{C['reset']} ({len(items)})")
    rows = [_make_inbox_row(i, ', '.join(i.get('attention', ['?']))[:12]) for i in items]
    print(tabulate(rows, headers=_inbox_headers("WAITING"), tablefmt="plain"))
    return True


def cmd_done(_):
    items = done_issues()
    if not items:
        return False
    print(f"{C['bold']}{C['dim']}DONE{C['reset']} ({len(items)})")
    rows = [_make_inbox_row(i) for i in items]
    print(tabulate(rows, headers=_inbox_headers(), tablefmt="plain"))
    return True


def cmd_gantt(args):
    from datetime import datetime, timedelta
    issues = all_issues()
    if args.query:
        issues = filter_issues(issues, args.query)
    issues = [i for i in issues if i.get('due')]
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

    # Owner -> color mapping (background colors)
    owner_colors = {
        'alex': 'bg_red', 'anish': 'bg_magenta', 'adam': 'bg_green',
        'dmoon': 'bg_cyan', 'curry': 'bg_yellow',
    }

    def render_bar(label, start, end, owner, behind=False, done=False):
        # Color by owner background, '-' for done, '*' for behind, space otherwise
        # Fallback to blue background for unmapped owners
        sc = C.get(owner_colors.get(owner, 'bg_blue'), '')
        fill = '-' if done else '*' if behind else ' '
        print(f"{label:<20}", end="")
        for day in range(total_days):
            d = start_date + timedelta(days=day)
            char = " "
            if start and end and start <= d <= end:
                char = f"{sc}{fill}{C['reset']}"
            if d == today and char == " ":
                char = f"{C['dim']}:{C['reset']}"
            print(char, end="")
        print()

    # Color legend in verbose mode
    if args.verbose:
        legend = ' '.join(f"{C.get(c, '')}{name}{C['reset']}" for name, c in owner_colors.items())
        print(f"Legend: {legend}  [-]=done [*]=behind")

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
        owner = i.get('owner', '')
        phase_order = ['draft', 'pqa', 'augmenting', 'iqa', 'done']
        current_idx = phase_order.index(i['status']) if i['status'] in phase_order else 0

        if args.verbose:
            # Show each state as sub-bar (due date = start of that phase), skip 'done'
            phases = [(s, parse_date(due[s])) for s in phase_order if s in due and s != 'done']
            done_date = parse_date(due.get('done', ''))
            if not phases:
                continue
            # Header bar: behind if any phase should have started but hasn't
            any_behind = any(today > start and phase_order.index(s) > current_idx
                            for s, start in phases)
            is_done = i['status'] == 'done'
            header_end = done_date or phases[-1][1]
            render_bar(alias, phases[0][1], header_end, owner, any_behind, is_done)
            # Each phase bar (reviewer phases use reviewer color)
            reviewers = i.get('reviewers', [])
            reviewer = reviewers[0] if reviewers else owner
            for idx, (state, start) in enumerate(phases):
                if idx + 1 < len(phases):
                    end = phases[idx + 1][1]
                else:
                    end = done_date or start
                phase_idx = phase_order.index(state)
                phase_done = current_idx > phase_idx
                # Behind if phase should have started but we haven't reached it
                behind = today > start and current_idx < phase_idx
                phase_owner = reviewer if state in ('pqa', 'iqa') else owner
                render_bar(f"  {state}", start, end, phase_owner, behind, phase_done)
        else:
            # Single bar from earliest due to latest due
            first_due = parse_date(min(due.values())) if due else None
            last_due = parse_date(max(due.values())) if due else None
            is_done = i['status'] == 'done'
            behind = last_due and today > last_due and not is_done
            render_bar(alias, first_due, last_due, owner, behind, is_done)


def cmd_default(_):
    has_inbox = cmd_inbox(None)
    if has_inbox: print()
    has_cc = cmd_cc(None)
    if has_cc: print()
    has_outbox = cmd_outbox(None)
    if has_outbox: print()
    has_done = cmd_done(None)
    if has_done: print()
    if not has_inbox and not has_cc and not has_outbox and not has_done:
        print("No active issues.")
