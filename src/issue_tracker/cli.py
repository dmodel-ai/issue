"""CLI: argument parsing and main entry point."""
import argparse
import sys

from .utils import die
from .views import cmd_show, cmd_list, cmd_inbox, cmd_outbox, cmd_default
from .commands import cmd_create, cmd_do, cmd_comment, cmd_update, cmd_link, cmd_pick
from .tui import cmd_tui

CMDS = ["new", "show", "list", "edit", "comment", "review", "approve", "block", "unblock", "inbox", "outbox", "pick", "tui"]

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

    c = s.add_parser("new", help="create new issue")
    c.add_argument("title", nargs="?", help="omit to open $EDITOR")
    c.add_argument("-d", "--description")
    c.add_argument("--owner", help="default: you")
    c.add_argument("-p", "--priority", type=int, help="higher = more important")
    c.add_argument("-r", "--reviewers", nargs="+")
    c.add_argument("--cc", nargs="+")
    c.add_argument("-l", "--labels", nargs="+")

    s.add_parser("show", help="show issue details").add_argument("id")
    s.add_parser("review", help="request review (draft→review)").add_argument("id")
    s.add_parser("approve", help="approve issue (review→approved)").add_argument("id")

    c = s.add_parser("comment", help="add comment")
    c.add_argument("id", nargs="?", help="default: first inbox issue")
    c.add_argument("text", nargs="?", help="omit to open $EDITOR")

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
    c.add_argument("-s", "--status", choices=["draft", "review", "approved", "completed", "abandoned"])
    c.add_argument("-o", "--owner")
    c.add_argument("-t", "--title")
    c.add_argument("-p", "--priority", type=int)
    c.add_argument("-r", "--add-reviewer", nargs="+")
    c.add_argument("-l", "--add-label", nargs="+")
    c.add_argument("-D", "--done", action="store_true", help="mark completed")
    c.add_argument("-X", "--abandon", action="store_true", help="mark abandoned")

    c = s.add_parser("block", help="mark issue as blocked by another")
    c.add_argument("id")
    c.add_argument("blocker_id")
    c = s.add_parser("unblock", help="remove blocking relationship")
    c.add_argument("id")
    c.add_argument("blocker_id")

    s.add_parser("inbox", help="issues needing your action")
    s.add_parser("outbox", help="your issues waiting on others")

    c = s.add_parser("pick", help="fzf picker, outputs issue number")
    c.add_argument("-i", "--inbox", action="store_true", help="pick from inbox")
    c.add_argument("-o", "--outbox", action="store_true", help="pick from outbox")

    s.add_parser("tui", help="interactive terminal UI")

    args = p.parse_args()

    cmds = {
        "new": cmd_create,
        "show": cmd_show,
        "list": cmd_list,
        "edit": cmd_update,
        "comment": cmd_comment,
        "review": lambda a: cmd_do("submit", a),
        "approve": lambda a: cmd_do("approve", a),
        "block": lambda a: cmd_link(a, add=True),
        "unblock": lambda a: cmd_link(a, add=False),
        "inbox": cmd_inbox,
        "outbox": cmd_outbox,
        "pick": cmd_pick,
        "tui": cmd_tui,
    }
    cmds.get(args.cmd, cmd_default)(args)
