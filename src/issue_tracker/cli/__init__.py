"""CLI: argument parsing and main entry point."""
import argparse
import inspect
import sys

from ..utils import die
from ..tui import cmd_tui
from ..workflows import workflow
from .views import cmd_show, cmd_list, cmd_inbox, cmd_outbox, cmd_default
from .commands import cmd_create, cmd_do, cmd_comment, cmd_update, cmd_pick


def make_help(frm, to):
    """Generate help text from transition tuple."""
    frm_str = ",".join(sorted(frm))
    return f"{frm_str} → {to}" if to else f"({frm_str})"


def all_states():
    """Compute all states from transitions."""
    states = set()
    for frm, to, *_ in workflow.transitions.values():
        states |= frm
        if to:
            states.add(to)
    return states


# Non-transition commands
STATIC_CMDS = ["new", "show", "list", "edit", "inbox", "outbox", "pick", "tui"]

# Build full command list
CMDS = STATIC_CMDS + list(workflow.transitions.keys())


def main():
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        sys.argv.insert(1, "edit")

    if len(sys.argv) > 1 and sys.argv[1] not in CMDS and not sys.argv[1].startswith('-'):
        matches = [c for c in CMDS if c.startswith(sys.argv[1])]
        if len(matches) == 1:
            sys.argv[1] = matches[0]
        elif len(matches) > 1:
            die(f"Ambiguous: {', '.join(matches)}")

    p = argparse.ArgumentParser(description="Issue tracker. Run without args for inbox/outbox summary.")
    s = p.add_subparsers(dest="cmd", metavar="command")

    # Static commands
    c = s.add_parser("new", help="create new issue")
    c.add_argument("title", nargs="?", help="omit to open $EDITOR")
    c.add_argument("-d", "--description")
    c.add_argument("--owner", help="default: you")
    c.add_argument("-p", "--priority", type=int, help="higher = more important")
    c.add_argument("-r", "--reviewers", nargs="+")
    c.add_argument("--cc", nargs="+")
    c.add_argument("-l", "--labels", nargs="+")

    s.add_parser("show", help="show issue details").add_argument("id")

    c = s.add_parser("list", help="list issues with filters")
    c.add_argument("query", nargs="?", help="query DSL: field:value -negation text (e.g. 'owner:alice status:review')")
    c.add_argument("--me", action="store_true", help="owner, reviewer, or cc")
    c.add_argument("--owner")
    c.add_argument("--status", help="comma-separated")
    c.add_argument("--reviewer")
    c.add_argument("--cc")
    c.add_argument("--label")
    c.add_argument("--blocked", action="store_true")
    c.add_argument("--blocking", action="store_true")

    c = s.add_parser("edit", help="edit issue fields")
    c.add_argument("id", nargs="?", help="default: first inbox issue")
    c.add_argument("-s", "--status", choices=sorted(all_states()))
    c.add_argument("-o", "--owner")
    c.add_argument("-t", "--title")
    c.add_argument("-p", "--priority", type=int)
    c.add_argument("-r", "--add-reviewer", nargs="+")
    c.add_argument("-l", "--add-label", nargs="+")
    c.add_argument("-D", "--done", action="store_true", help="mark completed")
    c.add_argument("-X", "--abandon", action="store_true", help="mark abandoned")

    s.add_parser("inbox", help="issues needing your action")
    s.add_parser("outbox", help="your issues waiting on others")

    c = s.add_parser("pick", help="fzf picker, outputs issue number")
    c.add_argument("-i", "--inbox", action="store_true", help="pick from inbox")
    c.add_argument("-o", "--outbox", action="store_true", help="pick from outbox")

    s.add_parser("tui", help="interactive terminal UI")

    # Generate transition commands dynamically from handler signatures
    for name, t in workflow.transitions.items():
        frm, to, handler = t[0], t[1], t[2]

        if name == "comment":
            # comment has special handling (default id, editor fallback)
            c = s.add_parser(name, help=make_help(frm, to))
            c.add_argument("id", nargs="?", help="default: first inbox issue")
            c.add_argument("text", nargs="?", help="omit to open $EDITOR")
            continue

        c = s.add_parser(name, help=make_help(frm, to))
        c.add_argument("id")

        # Add args for handler params after 'issue', skip 'u' (from user())
        sig = inspect.signature(handler)
        for param, param_info in list(sig.parameters.items())[1:]:  # skip 'issue'
            if param.startswith('_') or param in ('kwargs', 'u'):
                continue
            # Optional if has default, required otherwise
            if param_info.default is inspect.Parameter.empty:
                c.add_argument(param)
            else:
                c.add_argument(param, nargs='?')

    args = p.parse_args()
    cmd = args.cmd

    # Static command handlers
    static_handlers = {
        "new": cmd_create,
        "show": cmd_show,
        "list": cmd_list,
        "edit": cmd_update,
        "inbox": cmd_inbox,
        "outbox": cmd_outbox,
        "pick": cmd_pick,
        "tui": cmd_tui,
    }

    if cmd in static_handlers:
        static_handlers[cmd](args)
    elif cmd == "comment":
        cmd_comment(args)
    elif cmd in workflow.transitions:
        cmd_do(cmd, args)
    else:
        cmd_default(args)
