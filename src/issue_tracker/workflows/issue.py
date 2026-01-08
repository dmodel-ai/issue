"""Issue review workflow: draft → review → approved → completed."""
from ..utils import die, now

terminal = {"completed", "abandoned"}
active = {"draft", "review", "approved"}

status_colors = {
    "draft": "dim",
    "review": "yellow",
    "approved": "green",
    "completed": "dim",
    "abandoned": "red",
}


def pending(issue):
    return [r for r in issue.get("reviewers", [])
            if r not in issue.get("approved_by", [])]


def on_submit(issue, **_):
    issue["attention"] = issue["reviewers"].copy() if issue["reviewers"] else [issue["owner"]]


def on_comment(issue, u, text=None, **_):
    issue["comments"].append({"author": u, "time": now(), "text": text})
    if issue["status"] in terminal:
        return
    if u == issue["owner"]:
        issue["attention"] = pending(issue) or [issue["owner"]]
    else:
        issue["attention"] = [issue["owner"]]


def on_approve(issue, u, **_):
    if u not in issue.get("reviewers", []):
        die("Not a reviewer")
    if u not in issue.get("approved_by", []):
        issue.setdefault("approved_by", []).append(u)
    issue["attention"] = pending(issue) or [issue["owner"]]


def all_approved(issue, **_):
    return set(issue.get("reviewers", [])) == set(issue.get("approved_by", []))


def clear_attention(issue, **_):
    issue["attention"] = []


def on_block(issue, blocker, **_):
    """Block issue on blocker."""
    if blocker["id"] not in issue.setdefault("blocked_by", []):
        issue["blocked_by"].append(blocker["id"])
    if issue["id"] not in blocker.setdefault("blocks", []):
        blocker["blocks"].append(issue["id"])
    for u in issue.get("attention", []):
        if u not in blocker.setdefault("cc", []):
            blocker["cc"].append(u)
        if u not in blocker.setdefault("attention", []):
            blocker["attention"].append(u)
    issue["attention"] = []


def on_unblock(issue, blocker, **_):
    """Unblock issue from blocker."""
    if blocker["id"] in issue.get("blocked_by", []):
        issue["blocked_by"].remove(blocker["id"])
    if issue["id"] in blocker.get("blocks", []):
        blocker["blocks"].remove(issue["id"])
    if not issue.get("blocked_by") and not issue.get("attention"):
        issue["attention"] = [issue["owner"]]


transitions = {
    "review":   ({"draft"},         "review",    on_submit),
    "comment":  (active | terminal, None,        on_comment),
    "approve":  ({"review"},        "approved",  on_approve, all_approved),
    "done":     (active,            "completed", clear_attention),
    "abandon":  (active,            "abandoned", clear_attention),
    "block":    (active,            None,        on_block),
    "unblock":  (active,            None,        on_unblock),
}
