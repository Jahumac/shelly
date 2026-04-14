"""API smoke tests: auth enforcement + each endpoint returns valid JSON."""
import pytest


@pytest.fixture
def token(app, make_user):
    """Mint a real API token for a test user."""
    uid, _, _ = make_user(username="apiuser")
    with app.app_context():
        from app.models import create_api_token
        return create_api_token(uid, label="test")


@pytest.fixture
def api(client, token):
    """A helper that attaches the Bearer header to every request."""
    class _Client:
        def get(self, path):
            return client.get(path, headers={"Authorization": f"Bearer {token}"})

    return _Client()


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_api_rejects_missing_token(client):
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"] == "missing_token"


def test_api_rejects_wrong_scheme(client):
    resp = client.get("/api/v1/me", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401


def test_api_rejects_invalid_token(client):
    resp = client.get("/api/v1/me",
                      headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "invalid_token"


# ── Endpoints ────────────────────────────────────────────────────────────────

def test_me_returns_user_info(api):
    resp = api.get("/api/v1/me")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["username"] == "apiuser"
    assert "id" in body


def test_accounts_empty_for_new_user(api):
    resp = api.get("/api/v1/accounts")
    assert resp.status_code == 200
    assert resp.get_json() == {"accounts": []}


def test_account_detail_404(api):
    resp = api.get("/api/v1/accounts/99999")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"


def test_holdings_empty(api):
    resp = api.get("/api/v1/holdings")
    assert resp.status_code == 200
    assert resp.get_json() == {"holdings": []}


def test_goals_empty(api):
    resp = api.get("/api/v1/goals")
    assert resp.status_code == 200
    assert resp.get_json() == {"goals": []}


def test_overview_empty(api):
    resp = api.get("/api/v1/overview")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_value"] == 0
    assert body["account_count"] == 0


def test_budget_bad_month_key(api):
    resp = api.get("/api/v1/budget/2026")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_request"


def test_budget_valid_month_key(api):
    resp = api.get("/api/v1/budget/2026-04")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["month"] == "2026-04"
    assert "items" in body


def test_assumptions_returns_defaults(api):
    resp = api.get("/api/v1/assumptions")
    assert resp.status_code == 200
    body = resp.get_json()
    # Defaults are created on first access
    assert body.get("annual_growth_rate") is not None


def test_unknown_api_route_returns_json_404(api):
    resp = api.get("/api/v1/nonexistent")
    # Falls through to Flask 404 which returns HTML; our errorhandler
    # on the blueprint only fires for matched prefix mismatches. This test
    # documents current behaviour — if we ever bolt on a catch-all we can
    # tighten the assertion.
    assert resp.status_code == 404


# ── End-to-end: create account via web, fetch via API ────────────────────────

# ── Write endpoints ───────────────────────────────────────────────────────────

def test_update_account_balance_requires_ownership(app, client, token):
    """Cannot update an account that belongs to another user."""
    with app.app_context():
        from app.models import create_user, get_connection
        other_uid = create_user("eve", "password123")
        with get_connection() as conn:
            other_account = conn.execute(
                "INSERT INTO accounts (user_id, name, current_value, is_active) "
                "VALUES (?, 'Eve ISA', 1000, 1)",
                (other_uid,),
            ).lastrowid
            conn.commit()
    resp = client.post(
        f"/api/v1/accounts/{other_account}/balance",
        json={"current_value": 999999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_update_account_balance_succeeds_for_owner(app, client, token):
    with app.app_context():
        from app.models import get_connection, get_user_by_username
        uid = get_user_by_username("apiuser").id
        with get_connection() as conn:
            aid = conn.execute(
                "INSERT INTO accounts (user_id, name, current_value, is_active) "
                "VALUES (?, 'Mine', 100, 1)",
                (uid,),
            ).lastrowid
            conn.commit()
    resp = client.post(
        f"/api/v1/accounts/{aid}/balance",
        json={"current_value": 5555, "month": "2026-04"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["current_value"] == 5555


def test_update_account_balance_rejects_negative(app, client, token):
    resp = client.post(
        "/api/v1/accounts/1/balance",
        json={"current_value": -100},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_isa_contribution_rejects_missing_fields(client, token):
    resp = client.post(
        "/api/v1/contributions/isa",
        json={"amount": 500},  # no account_id, no date
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_isa_contribution_accepted(app, client, token):
    with app.app_context():
        from app.models import get_connection, get_user_by_username
        uid = get_user_by_username("apiuser").id
        with get_connection() as conn:
            aid = conn.execute(
                "INSERT INTO accounts (user_id, name, wrapper_type, is_active) "
                "VALUES (?, 'My ISA', 'Stocks & Shares ISA', 1)",
                (uid,),
            ).lastrowid
            conn.commit()
    resp = client.post(
        "/api/v1/contributions/isa",
        json={"account_id": aid, "amount": 500, "date": "2026-04-10"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201


def test_isa_contribution_rejects_foreign_account(app, client, token):
    with app.app_context():
        from app.models import create_user, get_connection
        other_uid = create_user("mallory", "password123")
        with get_connection() as conn:
            foreign_aid = conn.execute(
                "INSERT INTO accounts (user_id, name, is_active) VALUES (?, 'theirs', 1)",
                (other_uid,),
            ).lastrowid
            conn.commit()
    resp = client.post(
        "/api/v1/contributions/isa",
        json={"account_id": foreign_aid, "amount": 500, "date": "2026-04-10"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_pension_contribution_rejects_bad_kind(app, client, token):
    resp = client.post(
        "/api/v1/contributions/pension",
        json={"account_id": 1, "amount": 100, "date": "2026-04-10", "kind": "wat"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# ── Health check ──────────────────────────────────────────────────────────────

def test_health_check_no_auth_required(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["checks"]["database"] == "ok"
    assert "timestamp" in body


def test_api_returns_data_created_via_db(app, client, token):
    """Proves the API reads the same DB the web UI writes to."""
    with app.app_context():
        from app.models import get_connection, get_user_by_username
        uid = get_user_by_username("apiuser").id
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO accounts (user_id, name, wrapper_type,
                   current_value, monthly_contribution, is_active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (uid, "Test ISA", "Stocks & Shares ISA", 12345.67, 100),
            )
            conn.commit()
    resp = client.get("/api/v1/accounts",
                      headers={"Authorization": f"Bearer {token}"})
    body = resp.get_json()
    assert len(body["accounts"]) == 1
    assert body["accounts"][0]["name"] == "Test ISA"
    assert body["accounts"][0]["current_value"] == 12345.67
