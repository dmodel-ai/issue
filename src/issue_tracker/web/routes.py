"""Route handlers for web UI."""
from datetime import date, timedelta, datetime
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from ..store import all_issues, fetch, save, num, resolve
from ..workflows import workflow, transition, status_colors, INITIAL_STATE, phase_order, DONE_STATE
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
    save(issue)
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
    save(issue)
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
    save(issue)
    return RedirectResponse(f"/issue/{num(id)}", status_code=303)


def _parse_date(s):
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


@router.get("/gantt", response_class=HTMLResponse)
async def gantt_view(request: Request, q: str = "-status:done", start: str = "", end: str = ""):
    all_iss = all_issues()
    if q:
        all_iss = filter_issues(all_iss, q)
    issues = [i for i in all_iss if i.get('due')]
    no_due = [{'num': num(i['id']), 'label': i.get('alias') or f"#{num(i['id'])}", 'title': i['title']}
              for i in all_iss if not i.get('due')]

    today = date.today()

    # Parse start/end or use smart defaults based on issue dates
    if start:
        start_date = _parse_date(start) or today
    else:
        # Default: earliest issue date or start of current week
        all_dates = []
        for i in issues:
            all_dates.extend(_parse_date(d) for d in i.get('due', {}).values() if _parse_date(d))
        start_date = min(all_dates) if all_dates else today
        start_date = start_date - timedelta(days=start_date.weekday())  # Align to Monday

    if end:
        end_date = _parse_date(end) or (start_date + timedelta(weeks=4))
    else:
        # Default: 4 weeks after start or latest issue date + 1 week
        all_dates = []
        for i in issues:
            all_dates.extend(_parse_date(d) for d in i.get('due', {}).values() if _parse_date(d))
        if all_dates:
            end_date = max(all_dates) + timedelta(weeks=1)
        else:
            end_date = start_date + timedelta(weeks=4)

    total_days = (end_date - start_date).days
    if total_days <= 0:
        total_days = 28
        end_date = start_date + timedelta(days=total_days)

    week_headers = []
    d = start_date
    while d < end_date:
        week_headers.append(d.strftime('%m/%d'))
        d += timedelta(weeks=1)
    num_weeks = len(week_headers) or 1

    today_pct = ((today - start_date).days / total_days) * 100 if total_days else 0

    def pct(dt):
        if not dt:
            return None
        return max(0, min(100, (dt - start_date).days / total_days * 100))

    bars = []
    for i in issues:
        due = i.get('due', {})
        alias = i.get('alias') or f"#{num(i['id'])}"
        current_idx = phase_order.index(i['status']) if i['status'] in phase_order else 0

        # Build phase list (excluding done state)
        phases = [(s, _parse_date(due[s])) for s in phase_order if s in due and s != DONE_STATE]
        done_date = _parse_date(due.get(DONE_STATE, ''))
        if not phases:
            continue

        # Header bar spans first phase to done (or last phase)
        first_date = phases[0][1]
        last_date = done_date or phases[-1][1]
        is_done = i['status'] == DONE_STATE
        any_behind = any(today > start and phase_order.index(s) > current_idx
                        for s, start in phases if start)

        bar_left = pct(first_date) or 0
        bar_right = pct(last_date) or bar_left
        owner = i.get('owner', '')
        bars.append({
            'num': num(i['id']),
            'label': alias,
            'status': 'done' if is_done else 'behind' if any_behind else i['status'],
            'owner': owner,
            'left': bar_left,
            'width': max(2, bar_right - bar_left),
            'phases': [],
        })

        # Add phase sub-bars
        reviewers = i.get('reviewers', [])
        reviewer = reviewers[0] if reviewers else owner
        for idx, (state, start) in enumerate(phases):
            if idx + 1 < len(phases):
                end = phases[idx + 1][1]
            else:
                end = done_date or start
            phase_idx = phase_order.index(state) if state in phase_order else 0
            phase_done = current_idx > phase_idx
            behind = start and today > start and current_idx < phase_idx
            phase_left = pct(start) or 0
            phase_right = pct(end) or phase_left
            is_review = state in ('pqa', 'iqa')
            bars[-1]['phases'].append({
                'state': state,
                'status': 'done' if phase_done else 'behind' if behind else state,
                'owner': owner,
                'reviewer': reviewer if is_review else None,
                'left': phase_left,
                'width': max(2, phase_right - phase_left),
            })

    return templates.TemplateResponse("gantt.html", _ctx(
        request, bars=bars, weeks=week_headers, today_pct=today_pct, query=q,
        start_str=start_date.isoformat(), end_str=end_date.isoformat(), num_weeks=num_weeks,
        phases=phase_order, start_date=start_date.isoformat(), total_days=total_days, no_due=no_due
    ))


@router.get("/issue/{ref}/due", response_class=HTMLResponse)
async def edit_due_form(request: Request, ref: str):
    id, issue = fetch(ref)
    due = issue.get('due', {})
    return templates.TemplateResponse("partials/due_form.html", _ctx(
        request, issue=issue, phases=phase_order, due=due
    ))


@router.post("/issue/{ref}/due")
async def update_due(request: Request, ref: str):
    id, issue = fetch(ref)
    form = await request.form()
    due = issue.get('due', {})
    for phase in phase_order:
        val = form.get(f"due_{phase}", "").strip()
        if val:
            due[phase] = val
        elif phase in due:
            del due[phase]
    issue['due'] = due
    issue['updated'] = now()
    save(issue)
    if request.headers.get("HX-Request"):
        return HTMLResponse('<div hx-swap-oob="true" id="due-editor"></div>')
    return RedirectResponse(f"/gantt", status_code=303)


@router.post("/gantt/drag/{ref}")
async def drag_due(request: Request, ref: str):
    id, issue = fetch(ref)
    form = await request.form()
    due = issue.get('due', {})

    changed = False
    if form.get('phase'):
        # Single phase drag
        phase = form.get('phase')
        mode = form.get('mode')
        start = form.get('start')
        end = form.get('end')

        if mode == 'left' and start:
            due[phase] = start
            changed = True
        elif mode == 'right' and end:
            phases_in_due = [p for p in phase_order if p in due]
            try:
                idx = phases_in_due.index(phase)
                if idx + 1 < len(phases_in_due):
                    due[phases_in_due[idx + 1]] = end
                else:
                    due[DONE_STATE] = end
                changed = True
            except ValueError:
                pass
        elif mode == 'move' and start:
            old_start = _parse_date(due.get(phase, ''))
            new_start = _parse_date(start)
            if old_start and new_start:
                delta = (new_start - old_start).days
                if delta != 0:
                    due[phase] = start
                    changed = True
    else:
        # Whole bar drag - shift all dates
        shift_start = form.get('shift_start')
        shift_end = form.get('shift_end')
        if shift_start and shift_end and due:
            old_dates = [_parse_date(v) for v in due.values() if _parse_date(v)]
            if old_dates:
                old_first = min(old_dates)
                new_first = _parse_date(shift_start)
                if old_first and new_first:
                    delta = (new_first - old_first).days
                    if delta != 0:
                        for p in due:
                            d = _parse_date(due[p])
                            if d:
                                new_d = d + timedelta(days=delta)
                                due[p] = new_d.isoformat()
                        changed = True

    if changed:
        issue['due'] = due
        issue['updated'] = now()
        save(issue)
    return HTMLResponse('ok')
