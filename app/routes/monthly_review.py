from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.calculations import effective_account_value, review_ready_date as calc_review_ready_date
from app.models import (
    ensure_monthly_review_items,
    fetch_account,
    fetch_all_accounts,
    fetch_all_holdings,
    fetch_all_holdings_grouped,
    fetch_assumptions,
    fetch_holding,
    fetch_holding_totals_by_account,
    fetch_monthly_review_items,
    fetch_or_create_monthly_review,
    update_account,
    update_holding,
    update_monthly_review,
    upsert_monthly_snapshot,
)
from app.services.csv_parsers import (
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


def _optional_float(value, default=None):
    value = (value or "").strip()
    if value == "":
        return default
    return float(value)


def default_month_key():
    today = date.today()
    return f"{today.year}-{today.month:02d}"


def month_label(month_key):
    return datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")


@monthly_review_bp.route("/", methods=["GET", "POST"])
@login_required
def monthly_review():
    uid = current_user.id
    month_key = request.values.get("month") or default_month_key()

    if request.method == "POST":
        form_name = request.form.get("form_name")
        if form_name == "update_holding":
            units = _optional_float(request.form.get("units"), 0.0)
            price = _optional_float(request.form.get("price"), 0.0)
            update_holding(
                {
                    "id": int(request.form.get("holding_id")),
                    "account_id": int(request.form.get("account_id")),
                    "holding_catalogue_id": _optional_float(request.form.get("holding_catalogue_id"), None),
                    "holding_name": request.form.get("holding_name", ""),
                    "ticker": request.form.get("ticker", ""),
                    "asset_type": request.form.get("asset_type", ""),
                    "bucket": request.form.get("bucket", ""),
                    "value": units * price,
                    "units": units,
                    "price": price,
                    "notes": request.form.get("notes", ""),
                }
            )
        elif form_name == "update_account_balance":
            account = fetch_account(int(request.form.get("account_id")))
            if account:
                new_balance = _optional_float(request.form.get("current_value"), account["current_value"])
                update_account(
                    {
                        "id": account["id"],
                        "name": account["name"],
                        "provider": account["provider"],
                        "wrapper_type": account["wrapper_type"],
                        "category": account["category"],
                        "tags": account["tags"],
                        "current_value": new_balance,
                        "monthly_contribution": account["monthly_contribution"],
                        "goal_value": account["goal_value"],
                        "valuation_mode": account["valuation_mode"],
                        "growth_mode": account["growth_mode"],
                        "growth_rate_override": account["growth_rate_override"],
                        "owner": account["owner"],
                        "notes": account["notes"],
                        "last_updated": datetime.now().isoformat(),
                    }
                )
                upsert_monthly_snapshot(account["id"], month_key, new_balance)
        elif form_name == "mark_complete":
            review = fetch_or_create_monthly_review(month_key, uid)
            all_accounts = fetch_all_accounts(uid)
            holdings_totals = fetch_holding_totals_by_account(uid)
            for acc in all_accounts:
                balance = effective_account_value(acc, holdings_totals)
                upsert_monthly_snapshot(acc["id"], month_key, balance)
            update_monthly_review(review["id"], "complete", request.form.get("notes", ""))
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

    assumptions = fetch_assumptions(uid)

    # Calculate the smart review-ready date for this month
    try:
        salary_day = int(assumptions["salary_day"]) if assumptions and assumptions["salary_day"] else 0
    except (KeyError, TypeError):
        salary_day = 0
    mk_year, mk_month = [int(x) for x in month_key.split("-")]
    ready_date = calc_review_ready_date(mk_year, mk_month, salary_day) if salary_day else None

    return render_template(
        "monthly_review.html",
        review=review,
        month_key=month_key,
        month_label=month_label(month_key),
        holdings_items=holdings_items,
        manual_items=manual_items,
        contribution_items=contribution_items,
        holdings_by_account=holdings_by_account,
        assumptions=assumptions,
        review_ready_date=ready_date,
        active_page="monthly_review",
    )


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

    existing = fetch_all_holdings(current_user.id)
    matched, csv_only, db_only = match_parsed_to_holdings(parsed, existing)

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
        holding = fetch_holding(int(hid_str))
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
        })
        updated += 1

    # Clear session data after successful apply
    session.pop("csv_import", None)

    if updated:
        flash(f"Updated {updated} holding{'s' if updated != 1 else ''} from CSV import.", "success")
    if skipped:
        flash(f"{skipped} holding{'s' if skipped != 1 else ''} could not be applied.", "info")

    return redirect(url_for("monthly_review.monthly_review"))
