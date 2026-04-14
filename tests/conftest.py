"""Shared pytest fixtures.

Creates a fresh Flask app backed by an ephemeral SQLite DB for each test, with
CSRF disabled and the background scheduler skipped. Also provides an
authenticated client.
"""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def app(monkeypatch):
    tmpdir = tempfile.mkdtemp(prefix="shelly-test-")
    db_path = Path(tmpdir) / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("WTF_CSRF_ENABLED", "0")
    monkeypatch.setenv("FLASK_TESTING", "1")

    # Force config re-read since Config class caches at import time.
    import importlib
    import app as app_pkg
    import app.config as cfg
    importlib.reload(cfg)
    importlib.reload(app_pkg)

    flask_app = app_pkg.create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    """Create a user and return (user_id, username, password)."""
    def _make(username="alice", password="testpass123", is_admin=True):
        from app.models import create_user, get_user_by_username
        with app.app_context():
            existing = get_user_by_username(username)
            if existing:
                return existing.id, username, password
            uid = create_user(username, password, is_admin=is_admin)
            return uid, username, password
    return _make


@pytest.fixture
def auth_client(app, client, make_user):
    uid, username, password = make_user()
    client.post("/login", data={"username": username, "password": password},
                follow_redirects=False)
    return client
