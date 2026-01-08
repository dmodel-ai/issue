"""Kanban workflow: backlog → ready → in_progress → done."""
from ..utils import now

terminal = {"done", "wontfix"}
active = {"backlog", "ready", "in_progress", "blocked"}


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


def on_block(a, b):
    """Block issue a on issue b."""
    if b["id"] not in a.setdefault("blocked_by", []):
        a["blocked_by"].append(b["id"])
    if a["id"] not in b.setdefault("blocks", []):
        b["blocks"].append(a["id"])
    for u in a.get("attention", []):
        if u not in b.setdefault("attention", []):
            b["attention"].append(u)
    a["attention"] = []


def on_unblock(a, b):
    """Unblock issue a from issue b."""
    if b["id"] in a.get("blocked_by", []):
        a["blocked_by"].remove(b["id"])
    if a["id"] in b.get("blocks", []):
        b["blocks"].remove(a["id"])
    if not a.get("blocked_by") and not a.get("attention"):
        a["attention"] = [a.get("assignee", a["owner"])]


transitions = {
    "groom":   ({"backlog"},     "ready",       on_ready),
    "start":   ({"ready"},       "in_progress", on_start),
    "block":   ({"in_progress"}, "blocked",     on_block_ext),
    "unblock": ({"blocked"},     "in_progress", on_unblock_ext),
    "finish":  ({"in_progress"}, "done",        on_done),
    "wontfix": (active,          "wontfix",     on_done),
    "reopen":  (terminal,        "backlog",     on_ready),
}
