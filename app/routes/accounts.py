from datetime import date, datetime, timezone

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.calculations import contribution_breakdown, effective_account_value, to_float
from app.models import (
    CATEGORY_OPTIONS,
    DEFAULT_TAG_OPTIONS,
    WRAPPER_TYPE_OPTIONS,
    add_custom_tag,
    add_holding,
    add_holding_catalogue_item,
    create_account,
    create_contribution_override,
    delete_account,
    delete_contribution_override,
    delete_custom_tag,
    delete_holding,
    fetch_account,
    fetch_all_accounts,
    fetch_catalogue_with_prices,
    fetch_contribution_overrides,
    fetch_custom_tags,
    fetch_holding_catalogue,
    fetch_holding_totals_by_account,
    fetch_holdings_for_account,
    fetch_account_snapshot_history,
    fetch_user_tags,
    reconnect_holdings_to_catalogue,
    sync_holding_prices_from_catalogue,
    fetch_assumptions,
    fetch_latest_price_update,
    fetch_account_daily_snapshots,
    save_account_daily_snapshots,
    save_daily_snapshot,
    update_account,
    update_catalogue_price,
    update_holding,
)
from app.services.prices import fetch_price, lookup_instrument
from app.utils import optional_float, optional_int, split_tags, valid_month_key

ASSET_TYPE_OPTIONS = ["ETF", "Fund", "Share", "Pension Fund", "Cash", "Bond", "Other"]
BUCKET_OPTIONS = [
    "Global Equity",
    "Developed World Equity",
    "Emerging Markets Equity",
    "UK Equity",
    "Bonds",
    "Cash",
    "Property / REIT",
    "Other",
]


accounts_bp = Blueprint("accounts", __name__)


def _account_payload_from_form(form):
    return {
        "name": form.get("name", ""),
        "provider": form.get("provider", ""),
        "wrapper_type": form.get("wrapper_type", ""),
        "category": form.get("category", ""),
        "tags": ", ".join(t.strip() for t in form.getlist("tags") if t.strip()),
        "current_value": optional_float(form.get("current_value"), 0.0, min_val=0.0),
        "monthly_contribution": optional_float(form.get("monthly_contribution"), 0.0, min_val=0.0),
        "pension_contribution_day": max(0, min(31, int(form.get("pension_contribution_day", 0) or 0))),
        "goal_value": optional_float(form.get("goal_value"), None, min_val=0.0),
        "valuation_mode": form.get("valuation_mode", "manual"),
        "growth_mode": form.get("growth_mode", "default"),
        "growth_rate_override": optional_float(form.get("growth_rate_override"), None, divide_by_100=True),
        "owner": form.get("owner", ""),
        "notes": form.get("notes", ""),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "employer_contribution": optional_float(form.get("employer_contribution"), 0.0, min_val=0.0),
        "contribution_method": form.get("contribution_method", "standard"),
        "annual_fee_pct": optional_float(form.get("annual_fee_pct"), 0.0, min_val=0.0),
        "platform_fee_pct": optional_float(form.get("platform_fee_pct"), 0.0, min_val=0.0),
        "platform_fee_flat": optional_float(form.get("platform_fee_flat"), 0.0, min_val=0.0),
        "platform_fee_cap": optional_float(form.get("platform_fee_cap"), 0.0, min_val=0.0),
        "fund_fee_pct": optional_float(form.get("fund_fee_pct"), 0.0, min_val=0.0),
        "cash_interest_rate": optional_float(form.get("cash_interest_rate"), None, divide_by_100=True),
        "interest_payment_day": max(0, min(31, int(form.get("interest_payment_day", 0) or 0))),
    }


def _render_accounts_page(user_id, selected=None, detail_mode="view", position_error=None, position_added=False, edit_holding_id=None):
    rows = fetch_all_accounts(user_id)
    assumptions = fetch_assumptions(user_id)
    holdings_totals = fetch_holding_totals_by_account(user_id)
    effective_values = {row["id"]: effective_account_value(row, holdings_totals) for row in rows}
    contrib_breakdowns = {row["id"]: contribution_breakdown(row, assumptions) for row in rows}

    # Staleness: flag holdings-based accounts if prices > 7 days old
    prices_stale = False
    last_price_update = fetch_latest_price_update(user_id)
    if last_price_update:
        try:
            lpu = datetime.fromisoformat(str(last_price_update).replace(" UTC", "+00:00"))
            if lpu.tzinfo is None:
                lpu = lpu.replace(tzinfo=timezone.utc)
            prices_stale = (datetime.now(timezone.utc) - lpu).days >= 7
        except (ValueError, TypeError):
            prices_stale = True
    else:
        prices_stale = any(r["valuation_mode"] == "holdings" for r in rows)
    positions = fetch_holdings_for_account(selected["id"]) if selected else []
    catalogue_rows = fetch_catalogue_with_prices(user_id)
    catalogue_prices = {row["id"]: {"price": row["last_price"], "currency": row["price_currency"]} for row in catalogue_rows if row["last_price"]}
    overrides = fetch_contribution_overrides(selected["id"]) if selected else []
    account_monthly_labels = []
    account_monthly_values = []
    account_daily_labels = []
    account_daily_values = []
    if selected:
        history = fetch_account_snapshot_history(selected["id"], limit=36)
        account_monthly_labels = [m for (m, _) in history]
        account_monthly_values = [round(float(v or 0), 2) for (_, v) in history]
        daily_history = fetch_account_daily_snapshots(selected["id"], limit=365)
        account_daily_labels = [d for (d, _) in daily_history]
        account_daily_values = [round(v, 2) for (_, v) in daily_history]

    edit_holding = None
    if edit_holding_id and positions:
        for p in positions:
            if p["id"] == edit_holding_id:
                edit_holding = p
                break

    allocation_rows = []
    allocation_total = 0.0
    if selected and positions:
        for position in positions:
            allocation_total += float(position["value"] or 0)
        if allocation_total > 0:
            allocation_rows = sorted(
                [
                    {
                        "bucket": position["holding_name"],
                        "value": float(position["value"] or 0),
                        "percentage": (float(position["value"] or 0) / allocation_total) * 100,
                    }
                    for position in positions
                    if float(position["value"] or 0) > 0
                ],
                key=lambda r: r["value"],
                reverse=True,
            )

    return render_template(
        "accounts.html",
        accounts=rows,
        selected=selected,
        detail_mode=detail_mode,
        holdings_totals=holdings_totals,
        effective_values=effective_values,
        total_value=sum(effective_values.values()),
        total_monthly=sum(float(r["monthly_contribution"] or 0) for r in rows),
        contrib_breakdowns=contrib_breakdowns,
        active_page="accounts",
        wrapper_type_options=WRAPPER_TYPE_OPTIONS,
        category_options=CATEGORY_OPTIONS,
        tag_options=fetch_user_tags(user_id),
        custom_tags=fetch_custom_tags(user_id),
        default_tags=DEFAULT_TAG_OPTIONS,
        selected_tags=split_tags(selected['tags']) if selected and 'tags' in selected else [],
        positions=positions,
        catalogue_rows=catalogue_rows,
        asset_type_options=ASSET_TYPE_OPTIONS,
        bucket_options=BUCKET_OPTIONS,
        position_error=position_error,
        position_added=position_added,
        allocation_rows=allocation_rows,
        allocation_total=allocation_total,
        overrides=overrides,
        current_month_key=date.today().strftime("%Y-%m"),
        catalogue_prices=catalogue_prices,
        edit_holding=edit_holding,
        tax_band=assumptions["tax_band"] if assumptions and "tax_band" in assumptions else "basic",
        account_monthly_labels=account_monthly_labels,
        account_monthly_values=account_monthly_values,
        account_daily_labels=account_daily_labels,
        account_daily_values=account_daily_values,
        global_growth_rate=float(assumptions["annual_growth_rate"]) if assumptions and assumptions["annual_growth_rate"] else 0.05,
        prices_stale=prices_stale,
    )


@accounts_bp.route("/", methods=["GET", "POST"])
@login_required
def accounts():
    uid = current_user.id
    if request.method == "POST":
        payload = _account_payload_from_form(request.form)
        if not payload["name"].strip():
            flash("Account name is required.", "error")
            return redirect(url_for("accounts.accounts"))
        new_id = create_account(payload, uid)
        return redirect(url_for("accounts.accounts"))

    return _render_accounts_page(uid, detail_mode="list")


@accounts_bp.route("/api/tags", methods=["POST"])
@login_required
def api_add_tag():
    """JSON API: add a custom tag for the current user."""
    tag = (request.form.get("tag") or "").strip()
    if not tag:
        return jsonify({"ok": False, "error": "Tag cannot be empty"}), 400
    if len(tag) > 50:
        return jsonify({"ok": False, "error": "Tag too long (max 50 chars)"}), 400
    added = add_custom_tag(current_user.id, tag)
    return jsonify({"ok": True, "added": added, "tag": tag})


@accounts_bp.route("/api/tags/delete", methods=["POST"])
@login_required
def api_delete_tag():
    """JSON API: delete a custom tag for the current user."""
    tag = (request.form.get("tag") or "").strip()
    if not tag:
        return jsonify({"ok": False, "error": "Tag cannot be empty"}), 400
    if tag in DEFAULT_TAG_OPTIONS:
        return jsonify({"ok": False, "error": "Cannot delete default tags"}), 400
    deleted = delete_custom_tag(current_user.id, tag)
    return jsonify({"ok": True, "deleted": deleted, "tag": tag})


@accounts_bp.route("/api/create", methods=["POST"])
@login_required
def api_create_account():
    """JSON API: create account and return its ID (used by the wizard JS)."""
    uid = current_user.id
    payload = _account_payload_from_form(request.form)
    if not payload["name"].strip():
        return jsonify({"ok": False, "error": "Account name is required"}), 400
    new_id = create_account(payload, uid)
    return jsonify({"ok": True, "account_id": new_id})


@accounts_bp.route("/api/ticker-lookup", methods=["POST"])
@login_required
def api_ticker_lookup():
    """JSON API: look up a ticker via Yahoo Finance and return name + price.

    Used by the wizard to validate tickers and show a live price preview
    before the account is created.
    """
    ticker = (request.form.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"ok": False, "error": "Enter a ticker symbol"}), 400

    instrument = None
    try:
        instrument = lookup_instrument(ticker)
    except Exception as e:
        current_app.logger.warning("lookup_instrument(%s) failed: %s", ticker, e)

    if not instrument:
        return jsonify({"ok": False, "error": f"Shelly couldn't find '{ticker}' on Yahoo Finance. Double-check the symbol or add manually instead."}), 404

    price_gbp = instrument["price_gbp"]
    return jsonify({
        "ok": True,
        "ticker": instrument["ticker"],
        "yf_symbol": instrument.get("yf_symbol", ticker),
        "name": instrument["name"],
        "asset_type": instrument["asset_type"],
        "price": round(price_gbp, 4),
        "currency": instrument["currency"],
    })


def _add_holding_by_ticker(uid, account_id, ticker, units):
    """Shared logic: look up ticker price, create catalogue entry, and add holding.

    Returns a result dict on success. Raises ValueError with a user-facing message on failure.
    """
    price_data = fetch_price(ticker)
    if not price_data:
        raise ValueError(f"Couldn't fetch a price for '{ticker}'. Check the ticker and try again.")

    price_raw = price_data["price"]
    currency = price_data["currency"]
    price_gbp = price_raw / 100 if currency == "GBp" else price_raw

    instrument = None
    try:
        instrument = lookup_instrument(ticker)
    except Exception as e:
        current_app.logger.warning("lookup_instrument(%s) failed: %s", ticker, e)

    name = (instrument["name"] if instrument else None) or ticker
    asset_type = (instrument["asset_type"] if instrument else None) or "ETF"

    catalogue_id = add_holding_catalogue_item({
        "holding_name": name, "ticker": ticker,
        "asset_type": asset_type, "bucket": "Global Equity", "notes": "",
    }, uid)
    update_catalogue_price(
        catalogue_id, price_raw, currency,
        price_data.get("change_pct"),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    reconnect_holdings_to_catalogue(ticker, catalogue_id, uid)
    add_holding({
        "account_id": account_id, "holding_catalogue_id": catalogue_id,
        "holding_name": name, "ticker": ticker, "asset_type": asset_type,
        "bucket": "Global Equity", "value": round(units * price_gbp, 2),
        "units": units, "price": price_gbp, "notes": "",
    })
    return {"name": name, "ticker": ticker, "units": units, "price_gbp": price_gbp,
            "value": round(units * price_gbp, 2)}


def _add_holding_manual(uid, account_id, name, ticker, asset_type, units, price):
    """Shared logic: create catalogue entry and add a manual holding (no live price lookup).

    Returns a result dict. Raises ValueError with a user-facing message on failure.
    """
    catalogue_id = add_holding_catalogue_item({
        "holding_name": name, "ticker": ticker,
        "asset_type": asset_type, "bucket": "Other", "notes": "",
    }, uid)
    update_catalogue_price(
        catalogue_id, price, "GBP", None,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    if ticker:
        reconnect_holdings_to_catalogue(ticker, catalogue_id, uid)
    add_holding({
        "account_id": account_id, "holding_catalogue_id": catalogue_id,
        "holding_name": name, "ticker": ticker, "asset_type": asset_type,
        "bucket": "Other", "value": round(units * price, 2),
        "units": units, "price": price, "notes": "",
    })
    return {"name": name, "ticker": ticker, "units": units, "price_gbp": price,
            "value": round(units * price, 2)}


@accounts_bp.route("/api/<int:account_id>/holdings/add", methods=["POST"])
@login_required
def api_add_holding(account_id):
    """JSON API: add a holding by ticker and return the result (used by wizard JS)."""
    uid = current_user.id
    if not fetch_account(account_id, uid):
        return jsonify({"ok": False, "error": "Account not found"}), 404

    ticker = (request.form.get("ticker") or "").strip().upper()
    units = optional_float(request.form.get("units"), None)

    if not ticker or not units or units <= 0:
        return jsonify({"ok": False, "error": "Ticker and units are required"}), 400

    try:
        result = _add_holding_by_ticker(uid, account_id, ticker, units)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404

    return jsonify({
        "ok": True, "name": result["name"], "ticker": result["ticker"],
        "units": result["units"], "price": round(result["price_gbp"], 4),
        "value": result["value"],
    })


@accounts_bp.route("/api/<int:account_id>/holdings/add-manual", methods=["POST"])
@login_required
def api_add_holding_manual(account_id):
    """JSON API: add a manual holding and return the result (used by wizard JS)."""
    uid = current_user.id
    if not fetch_account(account_id, uid):
        return jsonify({"ok": False, "error": "Account not found"}), 404

    name = (request.form.get("name") or "").strip()
    ticker = (request.form.get("ticker") or "").strip().upper() or None
    asset_type = request.form.get("asset_type", "Fund")
    units = optional_float(request.form.get("units"), None)
    price = optional_float(request.form.get("price"), None)

    if not name or not units or not price or units <= 0 or price <= 0:
        return jsonify({"ok": False, "error": "Name, units and price are required"}), 400

    result = _add_holding_manual(uid, account_id, name, ticker, asset_type, units, price)
    return jsonify({
        "ok": True, "name": result["name"], "ticker": result["ticker"],
        "units": result["units"], "price": round(result["price_gbp"], 4),
        "value": result["value"],
    })


@accounts_bp.route("/<int:account_id>", methods=["GET", "POST"])
@login_required
def account_detail(account_id):
    uid = current_user.id
    selected = fetch_account(account_id, uid)
    if not selected:
        return redirect(url_for("accounts.accounts"))

    if request.method == "POST":
        form_name = request.form.get("form_name", "account")
        if form_name == "delete_account":
            delete_account(account_id, uid)
            return redirect(url_for("accounts.accounts"))

        if form_name == "add_override":
            from_raw = valid_month_key(request.form.get("from_month", ""))
            to_raw = valid_month_key(request.form.get("to_month", ""))
            if not from_raw or not to_raw:
                flash("Invalid month format.", "error")
            elif from_raw > to_raw:
                flash("'From' month must be before or equal to 'To' month.", "error")
            else:
                create_contribution_override({
                    "account_id": account_id,
                    "from_month": from_raw,
                    "to_month": to_raw,
                    "override_amount": optional_float(request.form.get("override_amount"), 0.0),
                    "reason": request.form.get("reason", "").strip(),
                })
            return redirect(url_for("accounts.account_detail", account_id=account_id))

        if form_name == "delete_override":
            override_id = optional_int(request.form.get("override_id"))
            if override_id:
                delete_contribution_override(override_id, uid)
            return redirect(url_for("accounts.account_detail", account_id=account_id))

        payload = _account_payload_from_form(request.form)
        payload["id"] = account_id
        if not payload["name"].strip():
            flash("Account name is required.", "error")
            return redirect(url_for("accounts.account_detail", account_id=account_id))
        # preserve fields managed by separate forms, not the main edit form
        if payload.get("cash_interest_rate") is None:
            payload["cash_interest_rate"] = (selected or {}).get("cash_interest_rate", 0) or 0
        if "uninvested_cash" not in payload:
            payload["uninvested_cash"] = (selected or {}).get("uninvested_cash") or 0
        update_account(payload, uid)
        return redirect(url_for("accounts.account_detail", account_id=account_id))

    detail_mode = request.args.get("mode", "view")
    edit_holding_id = request.args.get("holding_id", type=int)
    return _render_accounts_page(uid, selected=selected, detail_mode=detail_mode, edit_holding_id=edit_holding_id)


@accounts_bp.route("/<int:account_id>/positions/new", methods=["GET", "POST"])
@login_required
def account_add_position(account_id):
    """Legacy route — redirect to account detail which now has an inline add form."""
    return redirect(url_for("accounts.account_detail", account_id=account_id))


@accounts_bp.route("/<int:account_id>/holdings/add", methods=["POST"])
@login_required
def account_add_holding(account_id):
    """Add a holding by ticker. Looks up price live, auto-creates catalogue entry."""
    uid = current_user.id
    account = fetch_account(account_id, uid)
    if not account:
        return redirect(url_for("accounts.accounts"))

    ticker = (request.form.get("ticker") or "").strip().upper()
    units = optional_float(request.form.get("units"), None)

    if not ticker or not units or units <= 0:
        flash("Please enter a valid ticker and number of units.", "error")
        return redirect(url_for("accounts.account_detail", account_id=account_id))

    try:
        _add_holding_by_ticker(uid, account_id, ticker, units)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("accounts.account_detail", account_id=account_id))

    if account["valuation_mode"] != "holdings":
        update_account({**dict(account), "valuation_mode": "holdings",
                        "last_updated": datetime.now(timezone.utc).isoformat()}, uid)

    return redirect(url_for("accounts.account_detail", account_id=account_id))


@accounts_bp.route("/<int:account_id>/holdings/add-manual", methods=["POST"])
@login_required
def account_add_holding_manual(account_id):
    """Add a custom holding without a Yahoo Finance ticker (pensions, unlisted funds, etc.)."""
    uid = current_user.id
    account = fetch_account(account_id, uid)
    if not account:
        return redirect(url_for("accounts.accounts"))

    name = (request.form.get("name") or "").strip()
    ticker = (request.form.get("ticker") or "").strip().upper() or None
    asset_type = request.form.get("asset_type", "Fund")
    units = optional_float(request.form.get("units"), None)
    price = optional_float(request.form.get("price"), None)

    if not name or not units or not price or units <= 0 or price <= 0:
        flash("Please fill in the holding name, units, and price.", "error")
        return redirect(url_for("accounts.account_detail", account_id=account_id))

    _add_holding_manual(uid, account_id, name, ticker, asset_type, units, price)

    if account["valuation_mode"] != "holdings":
        update_account({**dict(account), "valuation_mode": "holdings",
                        "last_updated": datetime.now(timezone.utc).isoformat()}, uid)

    return redirect(url_for("accounts.account_detail", account_id=account_id))


@accounts_bp.route("/<int:account_id>/cash", methods=["POST"])
@login_required
def update_cash(account_id):
    uid = current_user.id
    account = fetch_account(account_id, uid)
    if not account:
        flash("Account not found.", "error")
        return redirect(url_for("accounts.accounts"))

    cash = request.form.get("uninvested_cash", "")
    rate = request.form.get("cash_interest_rate", "")
    payment_day = request.form.get("interest_payment_day", "")

    payload = dict(account)
    payload["uninvested_cash"] = to_float(cash) if cash else 0.0
    payload["cash_interest_rate"] = (to_float(rate) / 100.0) if rate else 0.0
    payload["interest_payment_day"] = max(0, min(31, int(payment_day) if payment_day else 0))
    payload["last_updated"] = datetime.now(timezone.utc).isoformat()

    # ensure missing fields are populated before update
    payload.setdefault("employer_contribution", 0)
    payload.setdefault("contribution_method", "standard")
    payload.setdefault("annual_fee_pct", 0)
    payload.setdefault("platform_fee_pct", 0)
    payload.setdefault("platform_fee_flat", 0)
    payload.setdefault("platform_fee_cap", 0)
    payload.setdefault("fund_fee_pct", 0)
    payload.setdefault("uninvested_cash", 0)
    payload.setdefault("cash_interest_rate", 0)
    payload.setdefault("interest_payment_day", 0)

    update_account(payload, uid)
    holdings_totals = fetch_holding_totals_by_account(uid)
    accounts = fetch_all_accounts(uid)
    acct_vals = [(a["id"], effective_account_value(a, holdings_totals)) for a in accounts]
    save_daily_snapshot(uid, sum(v for _, v in acct_vals))
    save_account_daily_snapshots(uid, acct_vals)
    flash("Cash balance updated.", "success")
    return redirect(url_for("accounts.account_detail", account_id=account_id))


@accounts_bp.route("/<int:account_id>/holdings/<int:holding_id>/delete", methods=["POST"])
@login_required
def account_delete_holding(account_id, holding_id):
    delete_holding(holding_id, current_user.id)
    return redirect(url_for("accounts.account_detail", account_id=account_id))


@accounts_bp.route("/<int:account_id>/holdings/<int:holding_id>/edit", methods=["POST"])
@login_required
def account_edit_holding(account_id, holding_id):
    # Verify the account belongs to the current user before doing anything.
    if fetch_account(account_id, current_user.id) is None:
        return redirect(url_for("accounts.accounts"))

    units = optional_float(request.form.get("units"), None)
    price = optional_float(request.form.get("price"), None)
    book_cost = optional_float(request.form.get("book_cost"), None)
    notes = request.form.get("notes", "").strip()

    if units is not None and price is not None:
        value = units * price
    else:
        value = optional_float(request.form.get("value"), None)

    existing_list = [h for h in fetch_holdings_for_account(account_id) if h["id"] == holding_id]
    if not existing_list:
        return redirect(url_for("accounts.account_detail", account_id=account_id))
    existing = existing_list[0]

    payload = {
        "id": holding_id,
        "account_id": account_id,
        "holding_catalogue_id": existing["holding_catalogue_id"],
        "holding_name": existing["holding_name"],
        "ticker": existing["ticker"],
        "asset_type": existing["asset_type"],
        "bucket": existing["bucket"],
        "value": value if value is not None else float(existing["value"] or 0),
        "units": units if units is not None else float(existing["units"] or 0),
        "price": price if price is not None else float(existing["price"] or 0),
        "book_cost": book_cost if book_cost is not None else (float(existing["book_cost"]) if existing["book_cost"] is not None else None),
        "notes": notes,
    }
    update_holding(payload, current_user.id)

    # Also update catalogue price if modified
    if price is not None and existing["holding_catalogue_id"]:
        update_catalogue_price(
            existing["holding_catalogue_id"],
            price,
            "GBP",
            None,
            datetime.now(timezone.utc).isoformat()
        )
        sync_holding_prices_from_catalogue(existing["holding_catalogue_id"], price, "GBP")

    uid = current_user.id
    holdings_totals = fetch_holding_totals_by_account(uid)
    accounts = fetch_all_accounts(uid)
    acct_vals = [(a["id"], effective_account_value(a, holdings_totals)) for a in accounts]
    save_daily_snapshot(uid, sum(v for _, v in acct_vals))
    save_account_daily_snapshots(uid, acct_vals)
    flash(f"Updated {existing['holding_name']}", "success")
    return redirect(url_for("accounts.account_detail", account_id=account_id))
