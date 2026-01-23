"""Web UI: FastAPI app with Jinja2 templates."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from .routes import router
from ..utils import IssueError


def create_app() -> FastAPI:
    app = FastAPI(title="Issue Tracker")
    app.include_router(router)

    @app.exception_handler(IssueError)
    async def issue_error_handler(request, exc):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc))

    return app


def main():
    import uvicorn
    uvicorn.run("issue_tracker.web:create_app", factory=True, host="0.0.0.0", port=8000, reload=True)
