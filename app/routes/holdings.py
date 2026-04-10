"""Holdings blueprint — API-only routes (page removed; see accounts for add-holding flow)."""
from flask import Blueprint, jsonify, request, current_app, flash, redirect, url_for
from flask_login import current_user, login_required

from datetime import datetime, timezone

from app.calculations import effective_account_value
from app.models import (
    fetch_all_accounts,
    fetch_holding_catalogue,
    fetch_holding_totals_by_account,
    save_daily_snapshot,
    sync_holding_prices_from_catalogue,
    update_catalogue_price,
    update_holding,
)
from app.services.prices import fetch_price, lookup_instrument
from app.services.scheduler import trigger_manual_update

holdings_bp = Blueprint("holdings", __name__)


@holdings_bp.route("/api/lookup")
@login_required
def api_lookup():
    """Search for an instrument by ticker and return enriched metadata + price."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "no query"}), 400

    catalogue = fetch_holding_catalogue(current_user.id)
    existing = next((r for r in catalogue if (r["ticker"] or "").upper() == q.upper()), None)

    result = lookup_instrument(q)
    if not result:
        return jsonify({"error": f"Could not find '{q}' on Yahoo Finance"}), 404

    result["in_catalogue"] = existing is not None
    result["catalogue_id"] = existing["id"] if existing else None
    result["catalogue_name"] = existing["holding_name"] if existing else None
    return jsonify(result)


@holdings_bp.route("/api/price")
@login_required
def api_price():
    """Lightweight price lookup used by the monthly update and add-holding bar."""
    ticker = request.args.get("ticker", "").strip()
    if not ticker:
        return jsonify({"error": "no ticker"}), 400
    data = fetch_price(ticker)
    if not data:
        return jsonify({"error": "not found"}), 404
    price_raw = data["price"]
    currency_raw = data["currency"]
    price_gbp = price_raw / 100.0 if currency_raw == "GBp" else price_raw
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return jsonify({
        "price": round(price_gbp, 4),
        "currency": "GBP",
        "price_raw": round(float(price_raw), 4),
        "currency_raw": currency_raw,
        "change_pct": data.get("change_pct"),
        "updated_at": updated_at,
        "yf_symbol": data.get("yf_symbol", ticker),
    })


@holdings_bp.route("/api/save-price", methods=["POST"])
@login_required
def api_save_price():
    """Save an updated price (and recalculated value) for a single holding.

    Called automatically after a live price fetch so the user doesn't need
    a separate Save click.
    """
    data = request.get_json(silent=True)
    if not data or "holding_id" not in data:
        return jsonify({"error": "missing data"}), 400

    holding_id = int(data["holding_id"])
    price = float(data.get("price", 0))
    units = float(data.get("units", 0))
    holding_catalogue_id = data.get("holding_catalogue_id")

    update_holding({
        "id": holding_id,
        "account_id": int(data.get("account_id", 0)),
        "holding_catalogue_id": holding_catalogue_id,
        "holding_name": data.get("holding_name", ""),
        "ticker": data.get("ticker", ""),
        "asset_type": data.get("asset_type", ""),
        "bucket": data.get("bucket", ""),
        "value": units * price,
        "units": units,
        "price": price,
        "notes": data.get("notes", ""),
    })

    price_source = (data.get("price_source") or "").strip().lower()
    currency_raw = (data.get("currency_raw") or "").strip() or None
    price_raw = data.get("price_raw", None)
    change_pct = data.get("change_pct", None)
    updated_at = (data.get("updated_at") or "").strip() or None
    if not updated_at:
        updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if holding_catalogue_id and (price_source == "live" or currency_raw or price_raw is not None):
        try:
            catalogue_id_int = int(holding_catalogue_id)
            price_raw_f = float(price_raw) if price_raw is not None else float(price)
            currency_raw_s = currency_raw or "GBP"
            change_pct_f = float(change_pct) if change_pct is not None else None

            update_catalogue_price(catalogue_id_int, price_raw_f, currency_raw_s, change_pct_f, updated_at)
            sync_holding_prices_from_catalogue(catalogue_id_int, price_raw_f, currency_raw_s)

            accounts = fetch_all_accounts(current_user.id)
            holdings_totals = fetch_holding_totals_by_account(current_user.id)
            total_value = sum(
                effective_account_value(account, holdings_totals)
                for account in accounts
            )
            save_daily_snapshot(current_user.id, total_value)
        except Exception:
            pass

    return jsonify({"ok": True, "value": round(units * price, 2)})


@holdings_bp.route("/api/trigger-price-update", methods=["POST"])
@login_required
def api_trigger_price_update():
    """Manually trigger a price update for the current user.

    This fetches fresh prices for all holdings, updates the catalogue,
    and saves a daily snapshot.
    """
    result = trigger_manual_update(current_app, current_user.id)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@holdings_bp.route("/trigger-price-update", methods=["POST"])
@login_required
def trigger_price_update():
    result = trigger_manual_update(current_app, current_user.id)
    if result.get("ok"):
        flash(result.get("message") or "Prices updated.", "success")
    else:
        flash(result.get("message") or result.get("error") or "Price update failed.", "error")
    return redirect(request.referrer or url_for("overview.overview"))
