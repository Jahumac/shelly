from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user, login_required

from app.calculations import (
    allowance_progress,
    calculate_isa_usage,
    calculate_pension_usage,
    current_age_from_assumptions,
    is_pension_account,
    pension_allowance_limits,
    uk_tax_year_label,
    uk_tax_year_start,
    uk_tax_year_end,
    ISA_WRAPPER_TYPES,
)
from app.models import (
    add_cgt_disposal,
    add_isa_contribution,
    add_pension_contribution,
    add_dividend_record,
    delete_cgt_disposal,
    delete_isa_contribution,
    delete_pension_contribution,
    delete_dividend_record,
    delete_pension_carry_forward,
    fetch_all_accounts,
    fetch_account,
    fetch_assumptions,
    fetch_cgt_disposals,
    fetch_isa_contributions,
    fetch_pension_carry_forward,
    fetch_pension_contributions,
    fetch_dividend_records,
    upsert_pension_carry_forward,
)

CGT_ANNUAL_EXEMPTION = 3000.0  # 2025-26 tax year

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

    has_lisa = any("Lifetime" in (a.get("wrapper_type") or "") or "LISA" in (a.get("wrapper_type") or "") for a in accounts)

    # LISA age warning — contributions stop at 50; warn at 49+
    current_age = current_age_from_assumptions(assumptions) if assumptions else 0
    lisa_age_warning = current_age >= 49 if current_age else False
    lisa_months_remaining = max(0, round((50 - current_age) * 12)) if lisa_age_warning else 0

    # ISA accounts for the dropdown
    isa_accounts = [a for a in accounts if (a["wrapper_type"] or "") in ISA_WRAPPER_TYPES]

    pension_contribs = fetch_pension_contributions(uid, ty_start, ty_end)
    pension_usage = calculate_pension_usage(accounts, pension_contribs, assumptions, now_date, salary_day)
    pension_limits = pension_allowance_limits(dict(assumptions) if assumptions else {})
    pension_accounts = [a for a in accounts if is_pension_account(dict(a))]

    # Carry-forward: sum unused allowances from up to 3 prior years
    carry_forward_entries = fetch_pension_carry_forward(uid)
    carry_forward_total = sum(float(e["unused_allowance"]) for e in carry_forward_entries[:3])
    pension_limits_with_carry = dict(pension_limits)
    pension_limits_with_carry["effective_allowance"] = pension_limits["effective_allowance"] + carry_forward_total
    pension_limits_with_carry["carry_forward_total"] = carry_forward_total

    _dividend_raw = assumptions["dividend_allowance"] if (assumptions is not None and "dividend_allowance" in assumptions) else None
    dividend_allowance = float(_dividend_raw) if _dividend_raw is not None else 500
    dividend_records = fetch_dividend_records(uid, ty_start, ty_end)
    dividend_used = sum(float(r["amount"] or 0) for r in dividend_records) if dividend_records else 0.0
    dividend_progress = allowance_progress(dividend_used, dividend_allowance) if dividend_allowance else 0
    taxable_accounts = [a for a in accounts if (a["wrapper_type"] or "") not in ISA_WRAPPER_TYPES and not is_pension_account(dict(a))]

    # ── Pension tax relief estimate ──────────────────────────────────────────
    tax_band = (assumptions["tax_band"] if assumptions and assumptions["tax_band"] else "basic") or "basic"
    personal_pension_total = sum(
        float(c["amount"] or 0) for c in pension_contribs
        if (c["kind"] or "personal") == "personal"
    )
    # Gross contribution entered by user; basic rate relief = 20% of gross
    basic_relief = personal_pension_total * 0.20
    extra_relief = personal_pension_total * 0.20 if tax_band == "higher" else (
        personal_pension_total * 0.25 if tax_band == "additional" else 0.0
    )

    # ── CGT disposals ────────────────────────────────────────────────────────
    cgt_disposals = fetch_cgt_disposals(uid, ty_start, ty_end)
    cgt_gains = sum(max(float(d["proceeds"]) - float(d["cost_basis"]), 0) for d in cgt_disposals)
    cgt_losses = sum(max(float(d["cost_basis"]) - float(d["proceeds"]), 0) for d in cgt_disposals)
    cgt_net = cgt_gains - cgt_losses
    cgt_remaining = max(CGT_ANNUAL_EXEMPTION - cgt_net, 0)
    cgt_over_exemption = max(cgt_net - CGT_ANNUAL_EXEMPTION, 0)

    return render_template(
        "allowance.html",
        tax_year=uk_tax_year_label(now_date),
        usage=usage,
        pension_usage=pension_usage,
        pension_limits=pension_limits_with_carry,
        isa_allowance=isa_allowance,
        lisa_allowance=lisa_allowance,
        isa_progress=allowance_progress(usage["isa_used"], isa_allowance),
        lisa_progress=allowance_progress(usage["lisa_used"], lisa_allowance),
        pension_progress=allowance_progress(pension_usage["pension_used"], pension_limits_with_carry["effective_allowance"]),
        carry_forward_entries=carry_forward_entries,
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
        active_page="budget",
        tax_band=tax_band,
        personal_pension_total=personal_pension_total,
        basic_relief=basic_relief,
        extra_relief=extra_relief,
        cgt_disposals=cgt_disposals,
        cgt_gains=cgt_gains,
        cgt_losses=cgt_losses,
        cgt_net=cgt_net,
        cgt_remaining=cgt_remaining,
        cgt_over_exemption=cgt_over_exemption,
        cgt_annual_exemption=CGT_ANNUAL_EXEMPTION,
        lisa_age_warning=lisa_age_warning,
        lisa_months_remaining=lisa_months_remaining,
        has_lisa=has_lisa,
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

    if not fetch_account(account_id, uid):
        flash("Please select one of your ISA accounts.", "error")
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

    if not fetch_account(account_id, uid):
        flash("Please select one of your pension accounts.", "error")
        return redirect(url_for("allowance.allowance_overview"))

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

    if not fetch_account(account_id, uid):
        flash("Please select one of your taxable accounts.", "error")
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


@allowance_bp.route("/cgt/add", methods=["POST"])
@login_required
def add_cgt():
    uid = current_user.id
    asset_name = request.form.get("asset_name", "").strip()
    proceeds = request.form.get("proceeds", type=float)
    cost_basis = request.form.get("cost_basis", type=float)
    disposal_date = request.form.get("disposal_date") or datetime.now().date().isoformat()
    note = request.form.get("note", "").strip() or None
    account_id = request.form.get("account_id", type=int) or None

    if not asset_name or proceeds is None or cost_basis is None or proceeds < 0 or cost_basis < 0:
        flash("Please fill in all required fields.", "error")
        return redirect(url_for("allowance.allowance_overview") + "#cgt")

    if account_id is not None and not fetch_account(account_id, uid):
        flash("Please select one of your accounts.", "error")
        return redirect(url_for("allowance.allowance_overview") + "#cgt")

    add_cgt_disposal(uid, disposal_date, asset_name, proceeds, cost_basis, note, account_id)
    gain = proceeds - cost_basis
    flash(f"Recorded disposal of {asset_name} — {'gain' if gain >= 0 else 'loss'} of £{abs(gain):,.2f}.", "success")
    return redirect(url_for("allowance.allowance_overview") + "#cgt")


@allowance_bp.route("/cgt/delete/<int:disposal_id>", methods=["POST"])
@login_required
def remove_cgt(disposal_id):
    delete_cgt_disposal(disposal_id, current_user.id)
    flash("Disposal removed.", "success")
    return redirect(url_for("allowance.allowance_overview") + "#cgt")


@allowance_bp.route("/pension/carry-forward/add", methods=["POST"])
@login_required
def add_carry_forward():
    tax_year = request.form.get("tax_year", "").strip()
    unused = request.form.get("unused_allowance", type=float)
    if not tax_year or unused is None or unused < 0:
        flash("Please enter a valid tax year and unused amount.", "error")
        return redirect(url_for("allowance.allowance_overview") + "#pension")
    upsert_pension_carry_forward(current_user.id, tax_year, unused)
    flash(f"Recorded £{unused:,.0f} carry-forward from {tax_year}.", "success")
    return redirect(url_for("allowance.allowance_overview") + "#pension")


@allowance_bp.route("/pension/carry-forward/delete/<int:entry_id>", methods=["POST"])
@login_required
def remove_carry_forward(entry_id):
    delete_pension_carry_forward(entry_id, current_user.id)
    flash("Carry-forward entry removed.", "success")
    return redirect(url_for("allowance.allowance_overview") + "#pension")
