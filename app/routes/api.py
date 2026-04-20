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
from datetime import datetime, timezone
from pathlib import Path

from app.extensions import limiter
from app.calculations import effective_account_value, is_price_stale
from app.utils import valid_month_key
from app.models import (
    add_dividend_record,
    add_isa_contribution,
    add_pension_contribution,
    fetch_account,
    fetch_all_accounts,
    fetch_all_goals,
    fetch_all_holdings,
    fetch_assumptions,
    fetch_budget_entries,
    fetch_budget_items,
    fetch_holding_totals_by_account,
    fetch_holdings_for_account,
    fetch_latest_price_update,
    fetch_or_create_monthly_review,
    fetch_user_by_api_token,
    get_connection,
    update_account,
    update_monthly_review,
    upsert_monthly_snapshot,
)

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


# Rate limit helper — no-op if Flask-Limiter isn't installed
def _limit(limit_string, **kwargs):
    if limiter:
        return limiter.limit(limit_string, **kwargs)
    return lambda f: f


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
@_limit("60 per minute")
def me():
    u = g.api_user
    return jsonify({
        "id": u.id,
        "username": u.username,
        "is_admin": u.is_admin,
    })


@api_bp.route("/accounts")
@api_auth_required
@_limit("60 per minute")
def list_accounts():
    rows = fetch_all_accounts(g.api_user.id)
    return jsonify({"accounts": [_account_to_dict(r) for r in rows]})


@api_bp.route("/accounts/<int:account_id>")
@api_auth_required
@_limit("60 per minute")
def get_account(account_id):
    row = fetch_account(account_id, g.api_user.id)
    if row is None:
        return _err("not_found", "Account not found", 404)
    data = _account_to_dict(row)
    data["holdings"] = [_holding_to_dict(h) for h in fetch_holdings_for_account(account_id)]
    return jsonify(data)


@api_bp.route("/holdings")
@api_auth_required
@_limit("60 per minute")
def list_holdings():
    rows = fetch_all_holdings(g.api_user.id)
    return jsonify({"holdings": [_holding_to_dict(r) for r in rows]})


@api_bp.route("/goals")
@api_auth_required
@_limit("60 per minute")
def list_goals():
    rows = fetch_all_goals(g.api_user.id)
    return jsonify({"goals": [_goal_to_dict(r) for r in rows]})


@api_bp.route("/overview")
@api_auth_required
@_limit("60 per minute")
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
@_limit("60 per minute")
def get_budget(month_key):
    if not valid_month_key(month_key):
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
    return jsonify(dict(row))


# ── Write endpoints ──────────────────────────────────────────────────────────
# Kept small and deliberate. Each write is scoped to the token's user and
# validated at the model layer (ownership checks apply the same as the web UI).

def _parse_amount(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


@api_bp.route("/accounts/<int:account_id>/balance", methods=["POST"])
@api_auth_required
def update_account_balance(account_id):
    """Update a manual-valuation account's current balance. Also records
    a monthly snapshot so performance history stays consistent with the
    web-based monthly review flow."""
    payload = request.get_json(silent=True) or {}
    balance = _parse_amount(payload.get("current_value"))
    if balance is None:
        return _err("bad_request", "current_value (number >= 0) required", 400)

    account = fetch_account(account_id, g.api_user.id)
    if account is None:
        return _err("not_found", "Account not found", 404)

    # Preserve all other fields — update_account needs a complete payload.
    update_payload = dict(account)
    update_payload["current_value"] = balance
    update_payload["last_updated"] = datetime.now(timezone.utc).isoformat()
    update_account(update_payload, g.api_user.id)

    month_key = payload.get("month") or datetime.now().strftime("%Y-%m")
    upsert_monthly_snapshot(account_id, month_key, balance)

    return jsonify({"ok": True, "account_id": account_id,
                    "current_value": balance, "month": month_key})


@api_bp.route("/contributions/isa", methods=["POST"])
@api_auth_required
def log_isa_contribution():
    payload = request.get_json(silent=True) or {}
    account_id = payload.get("account_id")
    amount = _parse_amount(payload.get("amount"))
    date = (payload.get("date") or "").strip()

    if amount is None or not account_id or not date:
        return _err("bad_request",
                    "account_id, amount (>= 0), and date (YYYY-MM-DD) required", 400)
    if fetch_account(int(account_id), g.api_user.id) is None:
        return _err("not_found", "Account not found", 404)

    add_isa_contribution(g.api_user.id, int(account_id), amount, date,
                         payload.get("note"))
    return jsonify({"ok": True}), 201


@api_bp.route("/contributions/pension", methods=["POST"])
@api_auth_required
def log_pension_contribution():
    payload = request.get_json(silent=True) or {}
    account_id = payload.get("account_id")
    amount = _parse_amount(payload.get("amount"))
    date = (payload.get("date") or "").strip()
    kind = (payload.get("kind") or "personal").strip()

    if amount is None or not account_id or not date:
        return _err("bad_request",
                    "account_id, amount (>= 0), and date (YYYY-MM-DD) required", 400)
    if kind not in ("personal", "employer", "salary_sacrifice"):
        return _err("bad_request",
                    "kind must be one of: personal, employer, salary_sacrifice", 400)
    if fetch_account(int(account_id), g.api_user.id) is None:
        return _err("not_found", "Account not found", 404)

    add_pension_contribution(g.api_user.id, int(account_id), amount, kind,
                             date, payload.get("note"))
    return jsonify({"ok": True}), 201


@api_bp.route("/dividends", methods=["POST"])
@api_auth_required
def log_dividend():
    payload = request.get_json(silent=True) or {}
    account_id = payload.get("account_id")
    amount = _parse_amount(payload.get("amount"))
    date = (payload.get("date") or "").strip()

    if amount is None or not account_id or not date:
        return _err("bad_request",
                    "account_id, amount (>= 0), and date (YYYY-MM-DD) required", 400)
    if fetch_account(int(account_id), g.api_user.id) is None:
        return _err("not_found", "Account not found", 404)

    add_dividend_record(g.api_user.id, int(account_id), amount, date,
                        payload.get("note"))
    return jsonify({"ok": True}), 201


@api_bp.route("/monthly-review/<month_key>/complete", methods=["POST"])
@api_auth_required
def complete_monthly_review(month_key):
    """Mark a monthly review as complete and snapshot every account's
    current effective value for that month. Mirrors the web UI's
    'mark complete' button exactly."""
    if not valid_month_key(month_key):
        return _err("bad_request", "month_key must be YYYY-MM", 400)

    payload = request.get_json(silent=True) or {}
    notes = (payload.get("notes") or "").strip()

    uid = g.api_user.id
    review = fetch_or_create_monthly_review(month_key, uid)
    accounts = fetch_all_accounts(uid)
    holdings_totals = fetch_holding_totals_by_account(uid)

    snapshots_taken = 0
    for acc in accounts:
        balance = effective_account_value(acc, holdings_totals)
        upsert_monthly_snapshot(acc["id"], month_key, balance)
        snapshots_taken += 1

    update_monthly_review(review["id"], "complete", notes, g.api_user.id)

    return jsonify({
        "ok": True,
        "month": month_key,
        "review_id": review["id"],
        "status": "complete",
        "snapshots_taken": snapshots_taken,
    })


# ── Health check (unauthenticated) ────────────────────────────────────────────
# Meant for uptime monitors and mobile clients to decide whether to retry.
# Purposefully returns no user-specific info so it's safe to expose.

@api_bp.route("/health")
def health():
    status = {"ok": True, "checks": {}}
    # DB connectivity
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        status["checks"]["database"] = "ok"
    except Exception as e:
        status["ok"] = False
        status["checks"]["database"] = f"error: {e.__class__.__name__}"

    # Most recent backup (file presence only — doesn't verify contents)
    try:
        data_dir = Path(current_app.config.get("DATA_DIR",
                        Path(current_app.config["DB_PATH"]).parent))
        backup_dir = data_dir / "backups"
        if backup_dir.exists():
            backups = sorted(backup_dir.glob("finance-*.db"))
            backups = [p for p in backups if not p.is_symlink()]
            if backups:
                newest = backups[-1]
                mtime = datetime.fromtimestamp(newest.stat().st_mtime).isoformat()
                status["checks"]["last_backup"] = mtime
            else:
                status["checks"]["last_backup"] = "none"
        else:
            status["checks"]["last_backup"] = "none"
    except Exception:
        status["checks"]["last_backup"] = "error"

    # Timestamp so clients can tell if the response itself is cached stale
    status["timestamp"] = datetime.now(timezone.utc).isoformat()
    return jsonify(status), (200 if status["ok"] else 503)


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
