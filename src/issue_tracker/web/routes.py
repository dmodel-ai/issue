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
from .auth import AUTH_ENABLED, oauth, get_user as auth_get_user
from uuid_utils import uuid7
import time
import threading
import sys

router = APIRouter()

# Web-only cache for all_issues() - CLI bypasses this
_cache = {"issues": None, "ts": 0}
_CACHE_TTL = 30


def _get_issues():
    if _cache["issues"] and time.time() - _cache["ts"] < _CACHE_TTL:
        return list(_cache["issues"])
    issues = all_issues()
    _cache["issues"], _cache["ts"] = issues, time.time()
    return issues


def _invalidate_cache():
    _cache["issues"] = None


def _save_background(issue):
    """Non-blocking save for web - optimistically updates cache, saves in background."""
    # Ensure cache is populated so we can add the new issue
    if _cache["issues"] is None:
        _get_issues()

    found = False
    for i, cached in enumerate(_cache["issues"]):
        if cached['id'] == issue['id']:
            _cache["issues"][i] = issue
            found = True
            break
    if not found:
        _cache["issues"].append(issue)

    def do_save():
        try:
            save(issue)
        except Exception as e:
            print(f"Background save error: {e}", file=sys.stderr)
            _invalidate_cache()

    threading.Thread(target=do_save, daemon=True).start()


def _num_cached(issue_id):
    """Get issue number from cache instead of hitting git."""
    issues = _get_issues()
    sorted_ids = sorted(iss['id'] for iss in issues)
    try:
        return sorted_ids.index(issue_id) + 1
    except ValueError:
        return 0


def _fetch_cached(ref):
    """Fetch issue using cache instead of hitting git."""
    issues = _get_issues()
    # Build index from cache
    idx = {n+1: iss['id'] for n, iss in enumerate(sorted(issues, key=lambda i: i['id']))}

    # Resolve ref to id
    if ref.isdigit():
        issue_id = idx.get(int(ref))
    elif len(ref) == 32:
        issue_id = ref
    else:
        # Alias lookup
        issue_id = None
        for iss in issues:
            if iss.get('alias') == ref:
                issue_id = iss['id']
                break
        if not issue_id:
            matches = [i for i in issues if (i.get('alias') or '').startswith(ref)]
            if len(matches) == 1:
                issue_id = matches[0]['id']

    if not issue_id:
        from ..utils import die
        die(f"Issue #{ref} not found")

    # Find issue in cache
    for iss in issues:
        if iss['id'] == issue_id:
            return issue_id, iss

    from ..utils import die
    die(f"Issue #{ref} not found")


templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _ctx(request: Request, **kwargs):
    """Build template context with common data."""
    return {"request": request, "user": auth_get_user(request),
            "auth_enabled": AUTH_ENABLED, "status_colors": status_colors,
            "ago": ago, "num": num, **kwargs}


@router.get("/", response_class=HTMLResponse)
async def list_issues(request: Request, q: str = ""):
    issues = _get_issues()
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
    _save_background(issue)
    return RedirectResponse(f"/issue/{_num_cached(issue['id'])}", status_code=303)


@router.get("/issue/{ref}", response_class=HTMLResponse)
async def show_issue(request: Request, ref: str):
    _, issue = _fetch_cached(ref)
    # Get available transitions for current status
    actions = []
    for name, t in workflow.transitions.items():
        frm, to, *_ = t
        if issue["status"] in frm and to:
            actions.append(name)
    return templates.TemplateResponse("detail.html", _ctx(request, issue=issue, actions=actions))


@router.post("/issue/{ref}/comment")
async def add_comment(request: Request, ref: str, text: str = Form(...)):
    id, issue = _fetch_cached(ref)
    transition(issue, "comment", u=user(), text=text)
    issue["updated"] = now()
    _save_background(issue)
    # Return just comments partial for htmx
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/comments.html",
                                          _ctx(request, issue=issue))
    return RedirectResponse(f"/issue/{ref}", status_code=303)


@router.post("/issue/{ref}/transition/{action}")
async def do_transition(ref: str, action: str):
    id, issue = _fetch_cached(ref)
    transition(issue, action, u=user())
    issue["updated"] = now()
    _save_background(issue)
    return RedirectResponse(f"/issue/{num(id)}", status_code=303)


def _parse_date(s):
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


@router.get("/gantt", response_class=HTMLResponse)
async def gantt_view(request: Request, q: str = "-status:done", start: str = "", end: str = ""):
    all_iss = _get_issues()
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
    id, issue = _fetch_cached(ref)
    due = issue.get('due', {})
    return templates.TemplateResponse("partials/due_form.html", _ctx(
        request, issue=issue, phases=phase_order, due=due
    ))


@router.post("/issue/{ref}/due")
async def update_due(request: Request, ref: str):
    id, issue = _fetch_cached(ref)
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
    _save_background(issue)
    if request.headers.get("HX-Request"):
        return HTMLResponse('<div hx-swap-oob="true" id="due-editor"></div>')
    return RedirectResponse(f"/gantt", status_code=303)


@router.post("/gantt/drag/{ref}")
async def drag_due(request: Request, ref: str):
    id, issue = _fetch_cached(ref)
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
        _save_background(issue)
    return HTMLResponse('ok')


@router.get("/login")
async def login(request: Request):
    """Redirect to Google OAuth."""
    if not AUTH_ENABLED:
        return RedirectResponse("/", status_code=302)
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle OAuth callback from Google."""
    if not AUTH_ENABLED:
        return RedirectResponse("/", status_code=302)
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo", {})
    email = userinfo.get("email", "")
    request.session["user"] = email.split("@")[0] if email else ""
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    if AUTH_ENABLED:
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/", status_code=302)
