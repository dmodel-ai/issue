"""Unit tests for auth module."""
import pytest
from unittest.mock import MagicMock


def test_auth_disabled_by_default(monkeypatch):
    """AUTH_ENABLED is False when env var not set."""
    monkeypatch.delenv("ISSUE_AUTH_GOOGLE", raising=False)
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)
    assert auth.AUTH_ENABLED is False


def test_auth_enabled_when_env_set(monkeypatch):
    """AUTH_ENABLED is True when ISSUE_AUTH_GOOGLE=1."""
    monkeypatch.setenv("ISSUE_AUTH_GOOGLE", "1")
    monkeypatch.setenv("ISSUE_GOOGLE_CLIENT_ID", "test-id")
    monkeypatch.setenv("ISSUE_GOOGLE_CLIENT_SECRET", "test-secret")
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)
    assert auth.AUTH_ENABLED is True


def test_get_user_returns_session_user_when_auth_enabled(monkeypatch):
    """get_user returns session user when auth is enabled."""
    monkeypatch.setenv("ISSUE_AUTH_GOOGLE", "1")
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)

    request = MagicMock()
    request.session = {"user": "testuser@example.com"}
    assert auth.get_user(request) == "testuser@example.com"


def test_get_user_returns_empty_when_not_logged_in(monkeypatch):
    """get_user returns empty string when auth enabled but not logged in."""
    monkeypatch.setenv("ISSUE_AUTH_GOOGLE", "1")
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)

    request = MagicMock()
    request.session = {}
    assert auth.get_user(request) == ""


def test_get_user_falls_back_to_env_when_auth_disabled(monkeypatch):
    """get_user uses env/git user when auth is disabled."""
    monkeypatch.delenv("ISSUE_AUTH_GOOGLE", raising=False)
    monkeypatch.setenv("ISSUE_USER", "envuser")
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)

    request = MagicMock()
    request.session = {}
    assert auth.get_user(request) == "envuser"


def test_is_authenticated_true_when_auth_disabled(monkeypatch):
    """is_authenticated returns True when auth is disabled."""
    monkeypatch.delenv("ISSUE_AUTH_GOOGLE", raising=False)
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)

    request = MagicMock()
    request.session = {}
    assert auth.is_authenticated(request) is True


def test_is_authenticated_false_when_not_logged_in(monkeypatch):
    """is_authenticated returns False when auth enabled but no session."""
    monkeypatch.setenv("ISSUE_AUTH_GOOGLE", "1")
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)

    request = MagicMock()
    request.session = {}
    assert auth.is_authenticated(request) is False


def test_is_authenticated_true_when_logged_in(monkeypatch):
    """is_authenticated returns True when auth enabled and user in session."""
    monkeypatch.setenv("ISSUE_AUTH_GOOGLE", "1")
    import importlib
    from issue_tracker.web import auth
    importlib.reload(auth)

    request = MagicMock()
    request.session = {"user": "testuser"}
    assert auth.is_authenticated(request) is True
