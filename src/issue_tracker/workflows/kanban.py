"""Kanban workflow: backlog → ready → in_progress → done."""
from ..utils import now

terminal = {"done", "wontfix"}
active = {"backlog", "ready", "in_progress", "blocked"}

status_colors = {
    "backlog": "dim",
    "ready": "cyan",
    "in_progress": "yellow",
    "blocked": "red",
    "done": "green",
    "wontfix": "dim",
}


def on_ready(issue, **_):
    """Move from backlog to ready when groomed."""
    issue["attention"] = [issue["owner"]]


def on_start(issue, u, **_):
    """Assign to worker, begin work."""
    issue["assignee"] = u
    issue["attention"] = [u]


def on_block_ext(issue, reason=None, **_):
    """Blocked on external dependency."""
    if reason:
        issue["block_reason"] = reason
    issue["attention"] = [issue["owner"]]


def on_unblock_ext(issue, **_):
    """External blocker resolved."""
    issue.pop("block_reason", None)
    issue["attention"] = [issue.get("assignee", issue["owner"])]


def on_done(issue, **_):
    issue["attention"] = []


transitions = {
    "groom":   ({"backlog"},     "ready",       on_ready),
    "start":   ({"ready"},       "in_progress", on_start),
    "block":   ({"in_progress"}, "blocked",     on_block_ext),
    "unblock": ({"blocked"},     "in_progress", on_unblock_ext),
    "finish":  ({"in_progress"}, "done",        on_done),
    "wontfix": (active,          "wontfix",     on_done),
    "reopen":  (terminal,        "backlog",     on_ready),
}
