"""Smoke tests — one GET per blueprint, plus the core write/auth paths.

These don't test business logic; they catch the class of bug where a route
crashes because of a template rename, missing import, or broken query.
"""


def test_setup_required_without_users(client):
    # First visit with no users should redirect to /setup
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/setup" in resp.headers.get("Location", "")


def test_setup_creates_admin_and_logs_in(client):
    resp = client.post("/setup", data={
        "username": "admin",
        "password": "testpass123",
        "confirm_password": "testpass123",
    }, follow_redirects=False)
    assert resp.status_code in (301, 302)
    # After setup, user should be logged in and see overview
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200


def test_login_rejects_bad_password(app, client, make_user):
    make_user(username="bob", password="rightpass123")
    resp = client.post("/login", data={"username": "bob", "password": "wrong"},
                       follow_redirects=False)
    # Stays on login page (renders 200) rather than redirecting to overview
    assert resp.status_code == 200
    assert b"Invalid" in resp.data or b"invalid" in resp.data


def test_unauthenticated_redirects_to_login(app, client, make_user):
    # Need at least one user so the app doesn't redirect to /setup
    make_user()
    resp = client.get("/accounts/", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers.get("Location", "")


def test_api_ping(client):
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


# ── One GET per blueprint's landing page (authenticated) ──────────────────────

import pytest

# Blueprints that expose a landing page. Holdings has no index route —
# it's detail-only (/holdings/<id>) and an API. That's worth knowing.
BLUEPRINT_PAGES = [
    "/",
    "/accounts/",
    "/goals/",
    "/projections/",
    "/settings/",
    "/monthly-review/",
    "/budget/",
    "/performance/",
    "/allowance/",
]


@pytest.mark.parametrize("path", BLUEPRINT_PAGES)
def test_authenticated_page_loads(auth_client, path):
    resp = auth_client.get(path, follow_redirects=True)
    # Accept 200 (renders) or 404 only if route is genuinely optional.
    # The whole point of a smoke test: a crash (500) fails loudly.
    assert resp.status_code in (200, 302), (
        f"GET {path} returned {resp.status_code}"
    )
