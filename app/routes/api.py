"""JSON API for external clients (Android/desktop/scripts).

Auth: send `Authorization: Bearer <token>` on every request. Tokens are
minted via `scripts/api_token.py create <username>` and revoked via
`scripts/api_token.py revoke <token_id>`.

Response format:
    Success: 200 with JSON body
    Error:   non-2xx with {"error": "<code>", "message": "<human text>"}

Versioning: mounted at /api/v1. Breaking changes go under /api/v2.
"""
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request

from app.calculations import is_price_stale
from app.models import (
    fetch_account,
    fetch_all_accounts,
    fetch_all_goals,
    fetch_all_holdings,
    fetch_assumptions,
    fetch_budget_entries,
    fetch_budget_items,
    fetch_holdings_for_account,
    fetch_user_by_api_token,
)

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _err(code, message, status):
    return jsonify({"error": code, "message": message}), status


def api_auth_required(fn):
    """Decorator: require a valid Bearer token. Stashes the user on flask.g."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.lower().startswith("bearer "):
            return _err("missing_token", "Authorization: Bearer <token> required", 401)
        token = header.split(" ", 1)[1].strip()
        user = fetch_user_by_api_token(token)
        if user is None:
            return _err("invalid_token", "Token not recognised", 401)
        g.api_user = user
        return fn(*args, **kwargs)

    return wrapper


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _account_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "provider": row["provider"],
        "wrapper_type": row["wrapper_type"],
        "category": row["category"],
        "tags": (row["tags"] or "").split(",") if row["tags"] else [],
        "current_value": float(row["current_value"] or 0),
        "monthly_contribution": float(row["monthly_contribution"] or 0),
        "goal_value": float(row["goal_value"]) if row["goal_value"] is not None else None,
        "valuation_mode": row["valuation_mode"],
        "owner": row["owner"],
        "last_updated": row["last_updated"],
    }


def _holding_to_dict(row):
    keys = set(row.keys())
    price_updated_at = row["price_updated_at"] if "price_updated_at" in keys else None
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "holding_name": row["holding_name"],
        "ticker": row["ticker"],
        "asset_type": row["asset_type"],
        "bucket": row["bucket"],
        "value": float(row["value"] or 0),
        "units": float(row["units"]) if row["units"] is not None else None,
        "price": float(row["price"]) if row["price"] is not None else None,
        "price_updated_at": price_updated_at,
        "is_price_stale": is_price_stale(price_updated_at),
    }


def _goal_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "target_value": float(row["target_value"] or 0),
        "goal_type": row["goal_type"],
        "selected_tags": (row["selected_tags"] or "").split(",") if row["selected_tags"] else [],
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@api_bp.route("/me")
@api_auth_required
def me():
    u = g.api_user
    return jsonify({
        "id": u.id,
        "username": u.username,
        "is_admin": u.is_admin,
    })


@api_bp.route("/accounts")
@api_auth_required
def list_accounts():
    rows = fetch_all_accounts(g.api_user.id)
    return jsonify({"accounts": [_account_to_dict(r) for r in rows]})


@api_bp.route("/accounts/<int:account_id>")
@api_auth_required
def get_account(account_id):
    row = fetch_account(account_id, g.api_user.id)
    if row is None:
        return _err("not_found", "Account not found", 404)
    data = _account_to_dict(row)
    data["holdings"] = [_holding_to_dict(h) for h in fetch_holdings_for_account(account_id)]
    return jsonify(data)


@api_bp.route("/holdings")
@api_auth_required
def list_holdings():
    rows = fetch_all_holdings(g.api_user.id)
    return jsonify({"holdings": [_holding_to_dict(r) for r in rows]})


@api_bp.route("/goals")
@api_auth_required
def list_goals():
    rows = fetch_all_goals(g.api_user.id)
    return jsonify({"goals": [_goal_to_dict(r) for r in rows]})


@api_bp.route("/overview")
@api_auth_required
def overview():
    accounts = fetch_all_accounts(g.api_user.id)
    total = sum(float(a["current_value"] or 0) for a in accounts)
    monthly = sum(float(a["monthly_contribution"] or 0) for a in accounts)
    return jsonify({
        "total_value": total,
        "monthly_contribution": monthly,
        "account_count": len(accounts),
    })


@api_bp.route("/budget/<month_key>")
@api_auth_required
def get_budget(month_key):
    # month_key looks like "2026-04"
    if len(month_key) != 7 or month_key[4] != "-":
        return _err("bad_request", "month_key must be YYYY-MM", 400)
    items = fetch_budget_items(g.api_user.id)
    entries = fetch_budget_entries(month_key, g.api_user.id)
    entries_by_item = {e["budget_item_id"]: float(e["amount"] or 0) for e in entries}
    return jsonify({
        "month": month_key,
        "items": [
            {
                "id": it["id"],
                "name": it["name"],
                "section": it["section"],
                "default_amount": float(it["default_amount"] or 0),
                "amount": entries_by_item.get(it["id"], float(it["default_amount"] or 0)),
                "linked_account_id": it["linked_account_id"],
            }
            for it in items
        ],
    })


@api_bp.route("/assumptions")
@api_auth_required
def get_assumptions():
    row = fetch_assumptions(g.api_user.id)
    if row is None:
        return jsonify({})
    # Return as dict; Row → dict is fine since all columns are primitive.
    return jsonify({k: row[k] for k in row.keys()})


# ── Error handlers scoped to this blueprint ──────────────────────────────────

@api_bp.errorhandler(404)
def _404(e):
    return _err("not_found", "Route not found", 404)


@api_bp.errorhandler(405)
def _405(e):
    return _err("method_not_allowed", "Method not allowed", 405)


@api_bp.errorhandler(500)
def _500(e):
    current_app.logger.exception("API 500")
    return _err("server_error", "Internal server error", 500)
