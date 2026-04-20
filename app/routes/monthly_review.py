import calendar as _cal
from datetime import date, datetime, timezone

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.calculations import (
    effective_account_value,
    goal_current_value,
    progress_to_goal,
    review_ready_date as calc_review_ready_date,
    tag_totals,
    total_invested,
)
from app.models import (
    create_contribution_override,
    ensure_monthly_review_items,
    fetch_account,
    fetch_all_accounts,
    fetch_all_active_overrides,
    fetch_all_holdings,
    fetch_all_holdings_grouped,
    fetch_assumptions,
    fetch_budget_items,
    fetch_holding,
    fetch_holding_totals_by_account,
    fetch_monthly_review,
    fetch_monthly_review_items,
    fetch_or_create_monthly_review,
    fetch_primary_goal,
    mark_review_item_updated,
    remove_contribution_override_for_month,
    set_contribution_confirmed,
    update_account,
    update_holding,
    update_monthly_review,
    upsert_monthly_snapshot,
)
from app.utils import optional_float, optional_int
from app.services.csv_parsers import (
    count_csv_rows,
    detect_csv_headers,
    diagnose_parsed_holdings,
    match_parsed_to_holdings,
    parse_ajbell,
    parse_freetrade,
    parse_generic,
    parse_hl,
    parse_ii,
    parse_investengine,
    parse_trading212,
    parse_vanguard,
)

monthly_review_bp = Blueprint("monthly_review", __name__)


_optional_float = optional_float


def default_month_key(uid=None, salary_day=None):
    today = date.today()
    current_key = f"{today.year}-{today.month:02d}"
    if not uid or not salary_day:
        return current_key
    # Point to last month if its review is incomplete and we're past the ready date
    if today.month == 1:
        last_year, last_month = today.year - 1, 12
    else:
        last_year, last_month = today.year, today.month - 1
    last_key = f"{last_year}-{last_month:02d}"
    ready = calc_review_ready_date(last_year, last_month, salary_day)
    if today >= ready:
        review = fetch_monthly_review(last_key, uid)
        if review is None or review["status"] != "complete":
            return last_key
    return current_key


def month_label(month_key):
    return datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")


@monthly_review_bp.route("/", methods=["GET", "POST"])
@login_required
def monthly_review():
    uid = current_user.id
    assumptions = fetch_assumptions(uid)
    try:
        salary_day = int(assumptions["salary_day"]) if assumptions and assumptions.get("salary_day") else 0
    except (ValueError, TypeError):
        salary_day = 0
    month_key = request.values.get("month") or default_month_key(uid, salary_day)

    if request.method == "POST":
        form_name = request.form.get("form_name")
        if form_name == "update_holding":
            account_id = optional_int(request.form.get("account_id"))
            holding_id = optional_int(request.form.get("holding_id"))
            catalogue_id = optional_int(request.form.get("holding_catalogue_id"))
            if not account_id or not holding_id:
                flash("Invalid holding data.", "error")
                return redirect(url_for("monthly_review.monthly_review", month=month_key))
            units = _optional_float(request.form.get("units"), 0.0)
            price = _optional_float(request.form.get("price"), 0.0)
            update_holding(
                {
                    "id": holding_id,
                    "account_id": account_id,
                    "holding_catalogue_id": catalogue_id,
                    "holding_name": request.form.get("holding_name", ""),
                    "ticker": request.form.get("ticker", ""),
                    "asset_type": request.form.get("asset_type", ""),
                    "bucket": request.form.get("bucket", ""),
                    "value": units * price,
                    "units": units,
                    "price": price,
                    "notes": request.form.get("notes", ""),
                },
                uid,
            )
            review = fetch_or_create_monthly_review(month_key, uid)
            mark_review_item_updated(review["id"], account_id, "holdings_updated")
        elif form_name == "update_account_balance":
            account_id = optional_int(request.form.get("account_id"))
            account = fetch_account(account_id, uid) if account_id else None
            if account:
                new_balance = _optional_float(request.form.get("current_value"), account["current_value"])
                payload = {**account, "current_value": new_balance, "last_updated": datetime.now(timezone.utc).isoformat()}
                update_account(payload, uid)
                upsert_monthly_snapshot(account["id"], month_key, new_balance)
                review = fetch_or_create_monthly_review(month_key, uid)
                mark_review_item_updated(review["id"], account["id"], "balance_updated")
                flash(f"{account['name']} balance updated to £{new_balance:,.2f}.", "success")
        elif form_name == "mark_complete":
            review = fetch_or_create_monthly_review(month_key, uid)
            all_accounts = fetch_all_accounts(uid)
            holdings_totals = fetch_holding_totals_by_account(uid)
            for acc in all_accounts:
                balance = effective_account_value(acc, holdings_totals)
                upsert_monthly_snapshot(acc["id"], month_key, balance)
            update_monthly_review(review["id"], "complete", request.form.get("notes", ""), uid)
        elif form_name == "reopen":
            review = fetch_monthly_review(month_key, uid)
            if review:
                update_monthly_review(review["id"], "not_started", review.get("notes") or "", uid)
        return redirect(url_for("monthly_review.monthly_review", month=month_key))

    review = fetch_or_create_monthly_review(month_key, uid)
    ensure_monthly_review_items(review["id"], uid)
    items = fetch_monthly_review_items(review["id"])

    holdings_items = [item for item in items if item["valuation_mode"] == "holdings"]
    manual_items = [item for item in items if item["valuation_mode"] != "holdings"]
    contribution_items = [item for item in items if (item["expected_contribution"] or 0) > 0]

    holdings_by_account = {}
    for row in fetch_all_holdings_grouped(uid):
        holdings_by_account.setdefault(row["account_id"], []).append(row)

    # Calculate the smart review-ready date for this month
    mk_year, mk_month = [int(x) for x in month_key.split("-")]
    ready_date = calc_review_ready_date(mk_year, mk_month, salary_day) if salary_day else None

    # Salary date for this review (day salary_day of this review's month)
    salary_date = None
    if salary_day:
        max_day = _cal.monthrange(mk_year, mk_month)[1]
        salary_date = date(mk_year, mk_month, min(salary_day, max_day))

    # Active overrides for this month (account_id → override row)
    active_overrides = fetch_all_active_overrides(month_key, uid)
    skipped_account_ids = {
        aid for aid, ov in active_overrides.items()
        if float(ov.get("override_amount") or 0) == 0
    }

    # Progress tracking stats — skipped contributions don't count as unconfirmed
    accounts_updated = sum(1 for item in items if item.get("holdings_updated") or item.get("balance_updated"))
    # Manual accounts whose balance hasn't been touched this review — snapshotting them
    # without an update will record a stale value and corrupt performance history.
    unupdated_manual_names = [
        item["account_name"] for item in manual_items
        if not item.get("balance_updated")
    ]
    unconfirmed_count = sum(
        1 for item in contribution_items
        if not item.get("contribution_confirmed")
        and (item.get("expected_contribution") or 0) > 0
        and item["account_id"] not in skipped_account_ids
    )

    # Build manual_holdings: flat list of individual holdings from holdings-based accounts
    # with field names matching the template expectations
    manual_holdings = []
    for item in holdings_items:
        for h in holdings_by_account.get(item['account_id'], []):
            manual_holdings.append({
                'id': h['id'],
                'account_id': h['account_id'],
                'name': h['holding_name'],
                'account_name': h['account_name'],
                'ticker': h['ticker'] or '',
                'units': float(h['units'] or 0),
                'price': float(h['price'] or 0),
            })

    # Goal progress
    goal = fetch_primary_goal(uid)
    goal_data = None
    if goal:
        all_accounts = fetch_all_accounts(uid)
        holdings_totals = fetch_holding_totals_by_account(uid)
        tag_totals_map = tag_totals(all_accounts, holdings_totals)
        selected_tags = [t.strip() for t in (goal["selected_tags"] or "").split(",") if t.strip()]
        current = (
            goal_current_value(selected_tags, all_accounts, holdings_totals)
            if selected_tags
            else total_invested(all_accounts, holdings_totals)
        )
        target = float(goal["target_value"] or 0)
        goal_data = {
            "name": goal["name"],
            "target": target,
            "current": current,
            "pct": progress_to_goal(current, target) * 100,
        }

    # Budget vs contributions comparison
    budget_comparison = []
    if contribution_items:
        budget_items_all = fetch_budget_items(uid)
        linked = {b["linked_account_id"]: b for b in budget_items_all if b.get("linked_account_id")}
        for item in contribution_items:
            budget_item = linked.get(item["account_id"])
            expected = float(item["expected_contribution"] or 0)
            budgeted = float(budget_item["default_amount"] or 0) if budget_item else None
            if budgeted is not None:
                budget_comparison.append({
                    "account_name": item["account_name"],
                    "budgeted": budgeted,
                    "expected": expected,
                    "diff": expected - budgeted,
                })

    return render_template(
        "monthly_review.html",
        review=review,
        month_key=month_key,
        month_label=month_label(month_key),
        current_month_num=mk_month,
        holdings_items=holdings_items,
        manual_items=manual_items,
        manual_holdings=manual_holdings,
        contribution_items=contribution_items,
        holdings_by_account=holdings_by_account,
        assumptions=assumptions,
        review_ready_date=ready_date,
        salary_date=salary_date,
        skipped_account_ids=skipped_account_ids,
        accounts_updated=accounts_updated,
        total_accounts=len(items),
        unconfirmed_count=unconfirmed_count,
        unupdated_manual_names=unupdated_manual_names,
        goal_data=goal_data,
        budget_comparison=budget_comparison,
        active_page="monthly_review",
    )


# ---------------------------------------------------------------------------
# Contribution confirmation (AJAX)
# ---------------------------------------------------------------------------

@monthly_review_bp.route("/api/confirm-contribution", methods=["POST"])
@login_required
def api_confirm_contribution():
    uid = current_user.id
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    confirmed = bool(data.get("confirmed", False))
    month_key = data.get("month_key") or default_month_key()

    if not item_id:
        return jsonify({"ok": False, "error": "item_id required"}), 400

    # Verify ownership via the review
    review = fetch_or_create_monthly_review(month_key, uid)
    set_contribution_confirmed(item_id, review["id"], confirmed)
    return jsonify({"ok": True})


@monthly_review_bp.route("/api/skip-contribution", methods=["POST"])
@login_required
def api_skip_contribution():
    """Skip a contribution for this month only — creates a zero-amount override."""
    uid = current_user.id
    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")
    month_key = data.get("month_key") or default_month_key()
    reason = (data.get("reason") or "Skipped").strip() or "Skipped"

    if not account_id:
        return jsonify({"ok": False, "error": "account_id required"}), 400
    if not fetch_account(account_id, uid):
        return jsonify({"ok": False, "error": "Account not found"}), 404

    create_contribution_override({
        "account_id": account_id,
        "from_month": month_key,
        "to_month": month_key,
        "override_amount": 0,
        "reason": reason,
    })
    return jsonify({"ok": True})


@monthly_review_bp.route("/api/restore-contribution", methods=["POST"])
@login_required
def api_restore_contribution():
    """Remove a single-month skip override, restoring the expected contribution."""
    uid = current_user.id
    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")
    month_key = data.get("month_key") or default_month_key()

    if not account_id:
        return jsonify({"ok": False, "error": "account_id required"}), 400

    remove_contribution_override_for_month(account_id, month_key, uid)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# CSV Import
# ---------------------------------------------------------------------------

PARSERS = {
    "trading212": parse_trading212,
    "investengine": parse_investengine,
    "vanguard": parse_vanguard,
    "hl": parse_hl,
    "ajbell": parse_ajbell,
    "freetrade": parse_freetrade,
    "ii": parse_ii,
    "generic": parse_generic,
}

PLATFORM_LABELS = {
    "trading212": "Trading 212",
    "investengine": "InvestEngine",
    "vanguard": "Vanguard Investor",
    "hl": "Hargreaves Lansdown",
    "ajbell": "AJ Bell",
    "freetrade": "Freetrade",
    "ii": "Interactive Investor",
    "generic": "Generic CSV",
}


@monthly_review_bp.route("/import-csv", methods=["POST"])
@login_required
def import_csv():
    """Parse an uploaded CSV and show a preview of changes."""
    platform = request.form.get("platform", "").strip()
    uploaded_file = request.files.get("csv_file")

    if not uploaded_file or uploaded_file.filename == "":
        flash("Please choose a CSV file to upload.", "error")
        return redirect(url_for("monthly_review.monthly_review"))

    if platform not in PARSERS:
        flash("Please select a supported platform from the dropdown.", "error")
        return redirect(url_for("monthly_review.monthly_review"))

    file_bytes = uploaded_file.read()
    if not file_bytes:
        flash("The uploaded file is empty.", "error")
        return redirect(url_for("monthly_review.monthly_review"))

    try:
        parsed = PARSERS[platform](file_bytes)
    except ValueError as exc:
        flash(f"Could not parse CSV: {exc}", "error")
        return redirect(url_for("monthly_review.monthly_review"))
    except Exception:
        flash("An unexpected error occurred while reading the CSV. Check the file format.", "error")
        return redirect(url_for("monthly_review.monthly_review"))

    if not parsed:
        flash("No holdings found in the CSV. Check you selected the right platform and file.", "error")
        return redirect(url_for("monthly_review.monthly_review"))

    # Surface per-row sanity warnings (parsers themselves raise only on
    # totally-wrong formats; this catches subtler issues like 0-unit rows).
    for warning in diagnose_parsed_holdings(parsed, count_csv_rows(file_bytes)):
        flash(warning, "warning")

    existing = fetch_all_holdings(current_user.id)
    matched, csv_only, db_only = match_parsed_to_holdings(parsed, existing)

    # If nothing matched, surface the raw CSV headers so users can self-debug
    csv_headers = detect_csv_headers(file_bytes) if not matched else []

    # Store parsed data in session so confirm step can re-validate
    session["csv_import"] = {
        "platform": platform,
        "matched": [
            {
                "holding_id": m["holding"]["id"],
                "new_units": m["csv"].get("units"),
                "new_price": m["csv"].get("price"),
            }
            for m in matched
        ],
    }

    return render_template(
        "csv_import_preview.html",
        platform=platform,
        platform_label=PLATFORM_LABELS[platform],
        matched=matched,
        csv_only=csv_only,
        db_only=db_only,
        csv_headers=csv_headers,
        active_page="monthly_review",
    )


@monthly_review_bp.route("/confirm-import", methods=["POST"])
@login_required
def confirm_import():
    """Apply the confirmed CSV import changes."""
    # Collect selected holding_ids from form checkboxes
    selected_ids = set(request.form.getlist("apply_holding_id"))

    if not selected_ids:
        flash("No holdings were selected — nothing was updated.", "info")
        return redirect(url_for("monthly_review.monthly_review"))

    # Pull the saved import data from session for cross-validation
    import_data = session.get("csv_import", {})
    allowed = {
        str(row["holding_id"]): row
        for row in import_data.get("matched", [])
    }

    updated = 0
    skipped = 0

    for hid_str in selected_ids:
        if hid_str not in allowed:
            skipped += 1
            continue

        session_row = allowed[hid_str]
        holding = fetch_holding(int(hid_str), current_user.id)
        if not holding:
            skipped += 1
            continue

        # Form may override values from session (user could have edited them)
        new_units = _optional_float(request.form.get(f"units_{hid_str}"), session_row.get("new_units"))
        new_price = _optional_float(request.form.get(f"price_{hid_str}"), session_row.get("new_price"))

        # Only update fields that are available; fall back to existing values
        final_units = new_units if new_units is not None else (holding["units"] or 0.0)
        final_price = new_price if new_price is not None else (holding["price"] or 0.0)

        update_holding({
            "id": holding["id"],
            "account_id": holding["account_id"],
            "holding_catalogue_id": holding["holding_catalogue_id"],
            "holding_name": holding["holding_name"],
            "ticker": holding["ticker"] or "",
            "asset_type": holding["asset_type"] or "",
            "bucket": holding["bucket"] or "",
            "value": final_units * final_price,
            "units": final_units,
            "price": final_price,
            "notes": holding["notes"] or "",
        }, current_user.id)
        updated += 1

    # Clear session data after successful apply
    session.pop("csv_import", None)

    if updated:
        flash(f"Updated {updated} holding{'s' if updated != 1 else ''} from CSV import.", "success")
    if skipped:
        flash(f"{skipped} holding{'s' if skipped != 1 else ''} could not be applied.", "info")

    return redirect(url_for("monthly_review.monthly_review"))
