"""Route handlers for web UI."""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from ..store import all_issues, fetch, save, num, resolve
from ..workflows import workflow, transition, status_colors, INITIAL_STATE
from ..query import filter_issues
from ..utils import user, now, ago
from uuid_utils import uuid7

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _ctx(request: Request, **kwargs):
    """Build template context with common data."""
    return {"request": request, "user": user(), "status_colors": status_colors,
            "ago": ago, "num": num, **kwargs}


@router.get("/", response_class=HTMLResponse)
async def list_issues(request: Request, q: str = ""):
    issues = all_issues()
    if q:
        issues = filter_issues(issues, q)
    issues = sorted(issues, key=lambda i: (-i.get('priority', 0), i['updated']), reverse=True)
    return templates.TemplateResponse("list.html", _ctx(request, issues=issues, query=q))


@router.get("/new", response_class=HTMLResponse)
async def new_issue_form(request: Request):
    return templates.TemplateResponse("new.html", _ctx(request))


@router.post("/new")
async def create_issue(title: str = Form(...), owner: str = Form(None),
                       reviewers: str = Form(""), labels: str = Form("")):
    u = user()
    issue = {
        "id": uuid7().hex,
        "title": title,
        "owner": owner or u,
        "status": INITIAL_STATE,
        "created": now(),
        "updated": now(),
        "comments": [],
        "attention": [owner or u],
        "blocks": [],
        "blocked_by": [],
    }
    if reviewers.strip():
        issue["reviewers"] = [r.strip() for r in reviewers.split(",") if r.strip()]
    if labels.strip():
        issue["labels"] = [l.strip() for l in labels.split(",") if l.strip()]
    save(issue["id"], issue)
    return RedirectResponse(f"/issue/{num(issue['id'])}", status_code=303)


@router.get("/issue/{ref}", response_class=HTMLResponse)
async def show_issue(request: Request, ref: str):
    _, issue = fetch(ref)
    # Get available transitions for current status
    actions = []
    for name, t in workflow.transitions.items():
        frm, to, *_ = t
        if issue["status"] in frm and to:
            actions.append(name)
    return templates.TemplateResponse("detail.html", _ctx(request, issue=issue, actions=actions))


@router.post("/issue/{ref}/comment")
async def add_comment(request: Request, ref: str, text: str = Form(...)):
    id, issue = fetch(ref)
    transition(issue, "comment", u=user(), text=text)
    issue["updated"] = now()
    save(id, issue)
    # Return just comments partial for htmx
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/comments.html",
                                          _ctx(request, issue=issue))
    return RedirectResponse(f"/issue/{ref}", status_code=303)


@router.post("/issue/{ref}/transition/{action}")
async def do_transition(ref: str, action: str):
    id, issue = fetch(ref)
    transition(issue, action, u=user())
    issue["updated"] = now()
    save(id, issue)
    return RedirectResponse(f"/issue/{num(id)}", status_code=303)
