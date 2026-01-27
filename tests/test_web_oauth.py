"""Integration tests for OAuth routes."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def auth_enabled(monkeypatch):
    """Enable auth for a test."""
    monkeypatch.setenv("ISSUE_AUTH_GOOGLE", "1")
    monkeypatch.setenv("ISSUE_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("ISSUE_GOOGLE_CLIENT_SECRET", "test-secret")


def _reload_modules():
    """Reload modules to pick up env var changes."""
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)
    from issue_tracker.web import routes
    importlib.reload(routes)
    import issue_tracker.web as web_mod
    importlib.reload(web_mod)
    return web_mod.create_app()


@pytest.fixture
def client_no_auth(monkeypatch):
    """Client with auth disabled."""
    monkeypatch.delenv("ISSUE_AUTH_GOOGLE", raising=False)
    app = _reload_modules()
    return TestClient(app)


@pytest.fixture
def client_with_auth(monkeypatch, auth_enabled):
    """Client with auth enabled."""
    app = _reload_modules()
    return TestClient(app, follow_redirects=False)


def test_login_redirects_to_google_when_auth_enabled(client_with_auth):
    """GET /login redirects to Google OAuth when auth is enabled."""
    resp = client_with_auth.get("/login")
    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers.get("location", "")


def test_login_redirects_home_when_auth_disabled(client_no_auth):
    """GET /login redirects to / when auth is disabled."""
    resp = client_no_auth.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_auth_callback_stores_user_in_session(client_with_auth):
    """GET /auth/callback stores user in session and redirects."""
    with patch("issue_tracker.web.routes.oauth") as mock_oauth:
        mock_oauth.google.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": "testuser@example.com"}}
        )
        resp = client_with_auth.get("/auth/callback")
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"


def test_logout_clears_session_and_redirects_to_login(client_with_auth):
    """GET /logout clears session and redirects to /login when auth enabled."""
    resp = client_with_auth.get("/logout")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_logout_redirects_home_when_auth_disabled(client_no_auth):
    """GET /logout redirects to / when auth is disabled."""
    resp = client_no_auth.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_protected_routes_redirect_to_login(client_with_auth):
    """Protected routes redirect to /login when not authenticated."""
    resp = client_with_auth.get("/")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_protected_routes_work_when_auth_disabled(client_no_auth, tmp_path, monkeypatch):
    """Protected routes work normally when auth is disabled."""
    monkeypatch.setenv("ISSUE_DIR", str(tmp_path / "issues"))
    resp = client_no_auth.get("/")
    assert resp.status_code == 200
