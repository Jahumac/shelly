from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user, login_required

from app.calculations import (
    allowance_progress,
    calculate_isa_usage,
    calculate_pension_usage,
    is_pension_account,
    pension_allowance_limits,
    uk_tax_year_label,
    uk_tax_year_start,
    uk_tax_year_end,
    ISA_WRAPPER_TYPES,
)
from app.models import (
    add_isa_contribution,
    add_pension_contribution,
    add_dividend_record,
    delete_isa_contribution,
    delete_pension_contribution,
    delete_dividend_record,
    fetch_all_accounts,
    fetch_assumptions,
    fetch_isa_contributions,
    fetch_pension_contributions,
    fetch_dividend_records,
)

allowance_bp = Blueprint("allowance", __name__)


@allowance_bp.route("/")
@login_required
def allowance_overview():
    uid = current_user.id
    now_date = datetime.now().date()
    accounts = fetch_all_accounts(uid)
    assumptions = fetch_assumptions(uid)

    try:
        salary_day = int(assumptions["salary_day"]) if assumptions and assumptions["salary_day"] else 0
    except (KeyError, TypeError):
        salary_day = 0
    ty_start = uk_tax_year_start(now_date).isoformat()
    ty_end = uk_tax_year_end(now_date).isoformat()
    ad_hoc = fetch_isa_contributions(uid, ty_start, ty_end)
    usage = calculate_isa_usage(accounts, ad_hoc, now_date, salary_day)

    isa_allowance = float(assumptions["isa_allowance"]) if assumptions else 20000
    lisa_allowance = float(assumptions["lisa_allowance"]) if assumptions else 4000

    # ISA accounts for the dropdown
    isa_accounts = [a for a in accounts if (a["wrapper_type"] or "") in ISA_WRAPPER_TYPES]

    pension_contribs = fetch_pension_contributions(uid, ty_start, ty_end)
    pension_usage = calculate_pension_usage(accounts, pension_contribs, assumptions, now_date, salary_day)
    pension_limits = pension_allowance_limits(dict(assumptions) if assumptions else {})
    pension_accounts = [a for a in accounts if is_pension_account(dict(a))]

    dividend_allowance = float(assumptions["dividend_allowance"]) if assumptions and assumptions.get("dividend_allowance") is not None else 500
    dividend_records = fetch_dividend_records(uid, ty_start, ty_end)
    dividend_used = sum(float(r["amount"] or 0) for r in dividend_records) if dividend_records else 0.0
    dividend_progress = allowance_progress(dividend_used, dividend_allowance) if dividend_allowance else 0
    taxable_accounts = [a for a in accounts if (a["wrapper_type"] or "") not in ISA_WRAPPER_TYPES and not is_pension_account(dict(a))]

    return render_template(
        "allowance.html",
        tax_year=uk_tax_year_label(now_date),
        usage=usage,
        pension_usage=pension_usage,
        pension_limits=pension_limits,
        isa_allowance=isa_allowance,
        lisa_allowance=lisa_allowance,
        isa_progress=allowance_progress(usage["isa_used"], isa_allowance),
        lisa_progress=allowance_progress(usage["lisa_used"], lisa_allowance),
        pension_progress=allowance_progress(pension_usage["pension_used"], pension_limits["effective_allowance"]),
        contributions=ad_hoc,
        pension_contributions=pension_contribs,
        isa_accounts=isa_accounts,
        pension_accounts=pension_accounts,
        dividend_allowance=dividend_allowance,
        dividend_used=dividend_used,
        dividend_progress=dividend_progress,
        dividend_records=dividend_records,
        taxable_accounts=taxable_accounts,
        today=now_date.isoformat(),
        active_page="overview",
    )


@allowance_bp.route("/add", methods=["POST"])
@login_required
def add_contribution():
    uid = current_user.id
    account_id = request.form.get("account_id", type=int)
    amount = request.form.get("amount", type=float)
    contribution_date = request.form.get("contribution_date") or datetime.now().date().isoformat()
    note = request.form.get("note", "").strip() or None

    if not account_id or not amount or amount <= 0:
        flash("Please select an account and enter a valid amount.", "error")
        return redirect(url_for("allowance.allowance_overview"))

    add_isa_contribution(uid, account_id, amount, contribution_date, note)
    flash(f"Recorded £{amount:,.2f} top-up.", "success")
    return redirect(url_for("allowance.allowance_overview"))


@allowance_bp.route("/delete/<int:contribution_id>", methods=["POST"])
@login_required
def remove_contribution(contribution_id):
    delete_isa_contribution(contribution_id, current_user.id)
    flash("Contribution removed.", "success")
    return redirect(url_for("allowance.allowance_overview"))


@allowance_bp.route("/pension/add", methods=["POST"])
@login_required
def add_pension_topup():
    uid = current_user.id
    account_id = request.form.get("account_id", type=int)
    amount = request.form.get("amount", type=float)
    kind = (request.form.get("kind") or "personal").strip().lower()
    contribution_date = request.form.get("contribution_date") or datetime.now().date().isoformat()
    note = request.form.get("note", "").strip() or None

    if not account_id or not amount or amount <= 0:
        flash("Please select an account and enter a valid amount.", "error")
        return redirect(url_for("allowance.allowance_overview"))

    if kind not in ("personal", "employer"):
        kind = "personal"

    add_pension_contribution(uid, account_id, amount, kind, contribution_date, note)
    flash(f"Recorded £{amount:,.2f} pension contribution.", "success")
    return redirect(url_for("allowance.allowance_overview"))


@allowance_bp.route("/pension/delete/<int:contribution_id>", methods=["POST"])
@login_required
def remove_pension_topup(contribution_id):
    delete_pension_contribution(contribution_id, current_user.id)
    flash("Contribution removed.", "success")
    return redirect(url_for("allowance.allowance_overview"))


@allowance_bp.route("/dividend/add", methods=["POST"])
@login_required
def add_dividend():
    uid = current_user.id
    account_id = request.form.get("account_id", type=int)
    amount = request.form.get("amount", type=float)
    dividend_date = request.form.get("dividend_date") or datetime.now().date().isoformat()
    note = request.form.get("note", "").strip() or None

    if not account_id or not amount or amount <= 0:
        flash("Please select an account and enter a valid amount.", "error")
        return redirect(url_for("allowance.allowance_overview"))

    add_dividend_record(uid, account_id, amount, dividend_date, note)
    flash(f"Recorded £{amount:,.2f} dividend.", "success")
    return redirect(url_for("allowance.allowance_overview"))


@allowance_bp.route("/dividend/delete/<int:record_id>", methods=["POST"])
@login_required
def delete_dividend(record_id):
    delete_dividend_record(record_id, current_user.id)
    flash("Dividend removed.", "success")
    return redirect(url_for("allowance.allowance_overview"))
