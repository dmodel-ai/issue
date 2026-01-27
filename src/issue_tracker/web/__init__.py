"""Web UI: FastAPI app with Jinja2 templates."""
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path

from .routes import router
from ..utils import IssueError

SESSION_SECRET = os.environ.get("ISSUE_SESSION_SECRET", "dev-secret-change-me")
PUBLIC_PATHS = {"/login", "/auth/callback", "/logout"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        from .auth import AUTH_ENABLED, is_authenticated
        if AUTH_ENABLED and request.url.path not in PUBLIC_PATHS:
            if not is_authenticated(request):
                return RedirectResponse("/login", status_code=302)
        return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(title="Issue Tracker")
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
    app.include_router(router)

    @app.exception_handler(IssueError)
    async def issue_error_handler(request, exc):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc))

    return app


def main():
    import uvicorn
    uvicorn.run("issue_tracker.web:create_app", factory=True, host="0.0.0.0", port=8000, reload=True)
