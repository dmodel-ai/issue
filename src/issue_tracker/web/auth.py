"""Google OAuth authentication for web UI."""
import os
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request

AUTH_ENABLED = os.environ.get("ISSUE_AUTH_GOOGLE") == "1"

oauth = OAuth()
if AUTH_ENABLED:
    oauth.register(
        name="google",
        client_id=os.environ.get("ISSUE_GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("ISSUE_GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "prompt": "select_account"},
    )


def get_user(request: Request) -> str:
    """Get username from session (if auth enabled) or fall back to env/git."""
    from ..utils import user as default_user
    if AUTH_ENABLED:
        return request.session.get("user") or ""
    return default_user()


def is_authenticated(request: Request) -> bool:
    """Check if user is authenticated (always True if auth disabled)."""
    if not AUTH_ENABLED:
        return True
    return bool(request.session.get("user"))
