"""Holdings blueprint — API-only routes (page removed; see accounts for add-holding flow)."""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.models import fetch_holding_catalogue, update_holding
from app.services.prices import fetch_price, lookup_instrument

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
    price_gbp = data["price"] / 100.0 if data["currency"] == "GBp" else data["price"]
    return jsonify({
        "price": round(price_gbp, 4),
        "currency": "GBP",
        "change_pct": data.get("change_pct"),
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

    update_holding({
        "id": holding_id,
        "account_id": int(data.get("account_id", 0)),
        "holding_catalogue_id": data.get("holding_catalogue_id"),
        "holding_name": data.get("holding_name", ""),
        "ticker": data.get("ticker", ""),
        "asset_type": data.get("asset_type", ""),
        "bucket": data.get("bucket", ""),
        "value": units * price,
        "units": units,
        "price": price,
        "notes": data.get("notes", ""),
    })

    return jsonify({"ok": True, "value": round(units * price, 2)})
