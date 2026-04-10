from datetime import datetime

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.calculations import (
    allowance_progress,
    calculate_isa_usage,
    calculate_pension_usage,
    effective_account_value,
    is_review_due,
    pension_allowance_limits,
    progress_to_goal,
    projected_total_retirement_value,
    review_ready_date,
    tag_totals,
    total_invested,
    total_monthly_contributions,
    uk_tax_year_label,
    uk_tax_year_start,
    uk_tax_year_end,
    days_until_tax_year_end,
)
from app.models import (
    fetch_all_accounts,
    fetch_assumptions,
    fetch_holding_totals_by_account,
    fetch_isa_contributions,
    fetch_pension_contributions,
    fetch_latest_price_update,
    fetch_net_worth_history,
    fetch_or_create_monthly_review,
    fetch_primary_goal,
    fetch_daily_snapshots,
)

overview_bp = Blueprint("overview", __name__)


@overview_bp.route("/")
@login_required
def overview():
    uid = current_user.id
    raw_accounts = fetch_all_accounts(uid)
    assumptions = fetch_assumptions(uid)
    goal = fetch_primary_goal(uid)
    holdings_totals = fetch_holding_totals_by_account(uid)

    accounts = []
    for account in raw_accounts:
        row = dict(account)
        row["current_value"] = effective_account_value(account, holdings_totals)
        accounts.append(row)

    invested_total = total_invested(accounts, holdings_totals)
    monthly_total = total_monthly_contributions(accounts)
    tag_totals_map = tag_totals(accounts, holdings_totals)
    projected_total = projected_total_retirement_value(accounts, assumptions)
    goal_target = float(goal["target_value"]) if goal else 0
    goal_progress = progress_to_goal(invested_total, goal_target)

    current_tax_year = uk_tax_year_label()
    now_date = datetime.now().date()
    try:
        salary_day = int(assumptions["salary_day"]) if assumptions and assumptions["salary_day"] else 0
    except (KeyError, TypeError):
        salary_day = 0
    ty_start = uk_tax_year_start(now_date).isoformat()
    ty_end = uk_tax_year_end(now_date).isoformat()
    ad_hoc = fetch_isa_contributions(uid, ty_start, ty_end)
    isa_usage = calculate_isa_usage(raw_accounts, ad_hoc, now_date, salary_day)
    isa_used = isa_usage["isa_used"]
    lisa_used = isa_usage["lisa_used"]

    pension_contribs = fetch_pension_contributions(uid, ty_start, ty_end)
    pension_usage = calculate_pension_usage(raw_accounts, pension_contribs, assumptions, now_date, salary_day)
    pension_limits = pension_allowance_limits(dict(assumptions) if assumptions else {})
    pension_allowance = pension_limits["effective_allowance"]

    now = datetime.now()

    metrics = {
        "invested_total": invested_total,
        "monthly_total": monthly_total,
        "tag_totals": tag_totals_map,
        "projected_total": projected_total,
        "goal_target": goal_target,
        "goal_progress": goal_progress,
        "tax_year": current_tax_year,
        "tax_year_days_left": days_until_tax_year_end(now.date()),
        "current_date": now.strftime("%A, %d %B %Y"),
        "current_time": now.strftime("%H:%M"),
        "isa_allowance": float(assumptions["isa_allowance"]) if assumptions else 0,
        "lisa_allowance": float(assumptions["lisa_allowance"]) if assumptions else 0,
        "pension_allowance": pension_allowance,
        "isa_used": isa_used,
        "lisa_used": lisa_used,
        "pension_used": pension_usage["pension_used"],
        "projected_isa": isa_usage["projected_isa"],
        "projected_lisa": isa_usage["projected_lisa"],
        "projected_pension": pension_usage["projected_total"],
        "isa_progress": allowance_progress(isa_used, float(assumptions["isa_allowance"]) if assumptions else 0),
        "lisa_progress": allowance_progress(lisa_used, float(assumptions["lisa_allowance"]) if assumptions else 0),
        "pension_progress": allowance_progress(pension_usage["pension_used"], pension_allowance),
        "pension_personal_limit": pension_limits["personal_relief_limit"],
        "effective_values": {account["id"]: effective_account_value(account, holdings_totals) for account in accounts},
    }

    # ── Monthly review nudge ──────────────────────────────────────────────────
    current_month_key = now_date.strftime("%Y-%m")
    review_nudge = False
    review_ready = None
    if salary_day:
        review_due = is_review_due(now_date, salary_day)
        if review_due:
            review = fetch_or_create_monthly_review(current_month_key, uid)
            if review["status"] != "complete":
                review_nudge = True
                review_ready = review_ready_date(now_date.year, now_date.month, salary_day)

    history = fetch_net_worth_history(uid)
    history_labels = [h[0] for h in history]
    history_values = [round(h[1], 2) for h in history]

    # Fetch daily snapshots (up to 365 days)
    daily_snapshots = fetch_daily_snapshots(uid, limit=365)
    daily_labels = [d[0] for d in daily_snapshots]
    daily_values = [round(d[1], 2) for d in daily_snapshots]
    last_snapshot_date = daily_labels[-1] if daily_labels else None
    last_price_update = fetch_latest_price_update(uid)

    return render_template(
        "overview.html",
        metrics=metrics,
        accounts=accounts,
        assumptions=assumptions,
        history_labels=history_labels,
        history_values=history_values,
        daily_labels=daily_labels,
        daily_values=daily_values,
        last_snapshot_date=last_snapshot_date,
        last_price_update=last_price_update,
        review_nudge=review_nudge,
        review_ready=review_ready,
        active_page="overview",
    )
