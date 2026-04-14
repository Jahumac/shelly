"""IDOR regression tests — proves that user A cannot mutate user B's data.

If any of these fail, the site has an authorization-bypass hole.
"""
import pytest


@pytest.fixture
def two_users(app, make_user, client):
    """Create Alice and Bob, then seed one goal/account/holding/budget_item
    for each. Returns a dict with each user's ids."""
    alice_uid, _, _ = make_user(username="alice", password="password123")
    bob_uid, _, _ = make_user(username="bob", password="password123")

    with app.app_context():
        from app.models import get_connection
        with get_connection() as conn:
            # Goal
            alice_goal = conn.execute(
                "INSERT INTO goals (user_id, name, target_value) VALUES (?, 'Alice goal', 10000)",
                (alice_uid,),
            ).lastrowid
            bob_goal = conn.execute(
                "INSERT INTO goals (user_id, name, target_value) VALUES (?, 'Bob goal', 10000)",
                (bob_uid,),
            ).lastrowid
            # Account
            alice_account = conn.execute(
                "INSERT INTO accounts (user_id, name, current_value, is_active) VALUES (?, 'Alice ISA', 5000, 1)",
                (alice_uid,),
            ).lastrowid
            bob_account = conn.execute(
                "INSERT INTO accounts (user_id, name, current_value, is_active) VALUES (?, 'Bob ISA', 5000, 1)",
                (bob_uid,),
            ).lastrowid
            # Holding
            alice_holding = conn.execute(
                """INSERT INTO holdings (account_id, holding_name, ticker, value, units, price)
                   VALUES (?, 'VUSA', 'VUSA', 5000, 100, 50)""",
                (alice_account,),
            ).lastrowid
            bob_holding = conn.execute(
                """INSERT INTO holdings (account_id, holding_name, ticker, value, units, price)
                   VALUES (?, 'VUSA', 'VUSA', 5000, 100, 50)""",
                (bob_account,),
            ).lastrowid
            # Budget item
            alice_budget = conn.execute(
                "INSERT INTO budget_items (user_id, name, section, default_amount, is_active) VALUES (?, 'Rent', 'fixed', 1000, 1)",
                (alice_uid,),
            ).lastrowid
            bob_budget = conn.execute(
                "INSERT INTO budget_items (user_id, name, section, default_amount, is_active) VALUES (?, 'Rent', 'fixed', 1000, 1)",
                (bob_uid,),
            ).lastrowid
            conn.commit()

    return {
        "alice": {"uid": alice_uid, "goal": alice_goal, "account": alice_account,
                  "holding": alice_holding, "budget": alice_budget},
        "bob": {"uid": bob_uid, "goal": bob_goal, "account": bob_account,
                "holding": bob_holding, "budget": bob_budget},
    }


def _login_as(client, username, password="password123"):
    client.post("/login", data={"username": username, "password": password})


# ── Model-level checks (unit tests, catch the core mistake earliest) ─────────

def test_update_goal_scoped_to_user(app, two_users):
    from app.models import fetch_goal, update_goal
    with app.app_context():
        ok = update_goal(
            {"id": two_users["bob"]["goal"], "name": "HACKED",
             "target_value": 99, "goal_type": "", "selected_tags": "", "notes": ""},
            two_users["alice"]["uid"],  # Alice trying to mutate Bob's goal
        )
        assert ok is False
        bob_goal = fetch_goal(two_users["bob"]["goal"])
        assert bob_goal["name"] == "Bob goal"  # untouched


def test_delete_goal_scoped_to_user(app, two_users):
    from app.models import delete_goal, fetch_goal
    with app.app_context():
        ok = delete_goal(two_users["bob"]["goal"], two_users["alice"]["uid"])
        assert ok is False
        assert fetch_goal(two_users["bob"]["goal"]) is not None


def test_update_holding_scoped_to_account_owner(app, two_users):
    from app.models import fetch_holding, update_holding
    with app.app_context():
        ok = update_holding({
            "id": two_users["bob"]["holding"],
            "account_id": two_users["bob"]["account"],
            "holding_catalogue_id": None,
            "holding_name": "HACKED", "ticker": "X",
            "asset_type": "", "bucket": "",
            "value": 0, "units": 0, "price": 0, "notes": "",
        }, two_users["alice"]["uid"])
        assert ok is False
        bob_h = fetch_holding(two_users["bob"]["holding"])
        assert bob_h["holding_name"] == "VUSA"


def test_delete_holding_scoped_to_account_owner(app, two_users):
    from app.models import delete_holding, fetch_holding
    with app.app_context():
        ok = delete_holding(two_users["bob"]["holding"], two_users["alice"]["uid"])
        assert ok is False
        assert fetch_holding(two_users["bob"]["holding"]) is not None


def test_update_budget_item_scoped_to_user(app, two_users):
    from app.models import get_connection, update_budget_item
    with app.app_context():
        ok = update_budget_item({
            "id": two_users["bob"]["budget"],
            "name": "HACKED", "section": "fixed",
            "default_amount": 0, "linked_account_id": None, "notes": "",
        }, two_users["alice"]["uid"])
        assert ok is False
        with get_connection() as conn:
            name = conn.execute("SELECT name FROM budget_items WHERE id = ?",
                                (two_users["bob"]["budget"],)).fetchone()["name"]
        assert name == "Rent"


def test_delete_budget_item_scoped_to_user(app, two_users):
    from app.models import delete_budget_item, get_connection
    with app.app_context():
        ok = delete_budget_item(two_users["bob"]["budget"], two_users["alice"]["uid"])
        assert ok is False
        with get_connection() as conn:
            is_active = conn.execute(
                "SELECT is_active FROM budget_items WHERE id = ?",
                (two_users["bob"]["budget"],)).fetchone()["is_active"]
        assert is_active == 1


def test_fetch_goal_scoped_to_user(app, two_users):
    from app.models import fetch_goal
    with app.app_context():
        # Alice asking for Bob's goal with her user_id should get nothing
        result = fetch_goal(two_users["bob"]["goal"], two_users["alice"]["uid"])
        assert result is None
        # Without user scoping the old behaviour still works (used by internal code)
        result = fetch_goal(two_users["bob"]["goal"])
        assert result is not None


def test_fetch_holding_scoped_to_account_owner(app, two_users):
    from app.models import fetch_holding
    with app.app_context():
        result = fetch_holding(two_users["bob"]["holding"], two_users["alice"]["uid"])
        assert result is None


# ── Route-level checks (proves the wiring is correct end-to-end) ─────────────

def test_alice_cannot_delete_bobs_goal_via_route(app, client, two_users):
    _login_as(client, "alice")
    resp = client.post("/goals/", data={
        "form_name": "delete_goal",
        "goal_id": two_users["bob"]["goal"],
    })
    assert resp.status_code in (200, 302)
    with app.app_context():
        from app.models import fetch_goal
        assert fetch_goal(two_users["bob"]["goal"]) is not None  # still there


def test_alice_cannot_delete_bobs_holding_via_route(app, client, two_users):
    _login_as(client, "alice")
    resp = client.post(
        f"/accounts/{two_users['bob']['account']}/holdings/{two_users['bob']['holding']}/delete"
    )
    assert resp.status_code in (200, 302)
    with app.app_context():
        from app.models import fetch_holding
        assert fetch_holding(two_users["bob"]["holding"]) is not None


def test_alice_cannot_delete_bobs_budget_item_via_route(app, client, two_users):
    _login_as(client, "alice")
    resp = client.post(
        f"/budget/items/{two_users['bob']['budget']}",
        data={"form_name": "delete"},
    )
    assert resp.status_code in (200, 302)
    with app.app_context():
        from app.models import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT is_active FROM budget_items WHERE id = ?",
                (two_users["bob"]["budget"],),
            ).fetchone()
        assert row["is_active"] == 1  # still active
