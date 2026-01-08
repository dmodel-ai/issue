"""Issue review workflow: draft → review → approved → completed."""
from ..utils import die, now

terminal = {"completed", "abandoned"}
active = {"draft", "review", "approved"}


def pending(issue):
    return [r for r in issue.get("reviewers", [])
            if r not in issue.get("approved_by", [])]


def on_submit(issue, **_):
    issue["attention"] = issue["reviewers"].copy() if issue["reviewers"] else [issue["owner"]]


def on_comment(issue, u, text, **_):
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


def on_block(a, b):
    if b["id"] not in a.setdefault("blocked_by", []):
        a["blocked_by"].append(b["id"])
    if a["id"] not in b.setdefault("blocks", []):
        b["blocks"].append(a["id"])
    for u in a.get("attention", []):
        if u not in b.setdefault("cc", []):
            b["cc"].append(u)
        if u not in b.setdefault("attention", []):
            b["attention"].append(u)
    a["attention"] = []


def on_unblock(a, b):
    if b["id"] in a.get("blocked_by", []):
        a["blocked_by"].remove(b["id"])
    if a["id"] in b.get("blocks", []):
        b["blocks"].remove(a["id"])
    if not a.get("blocked_by") and not a.get("attention"):
        a["attention"] = [a["owner"]]


transitions = {
    "submit":   ({"draft"},  "review",    on_submit),
    "comment":  (active | terminal, None, on_comment),
    "approve":  ({"review"}, "approved",  on_approve, all_approved),
    "complete": (active,     "completed", clear_attention),
    "abandon":  (active,     "abandoned", clear_attention),
}
