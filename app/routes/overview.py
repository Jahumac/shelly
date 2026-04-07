from datetime import datetime

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.calculations import (
    allowance_progress,
    effective_account_value,
    progress_to_goal,
    projected_total_retirement_value,
    tag_totals,
    total_invested,
    total_monthly_contributions,
    uk_tax_year_label,
    days_until_tax_year_end,
)
from app.models import fetch_all_accounts, fetch_allowance_tracking, fetch_assumptions, fetch_holding_totals_by_account, fetch_net_worth_history, fetch_primary_goal

overview_bp = Blueprint("overview", __name__)


@overview_bp.route("/")
@login_required
def overview():
    uid = current_user.id
    raw_accounts = fetch_all_accounts(uid)
    assumptions = fetch_assumptions(uid)
    goal = fetch_primary_goal(uid)
    allowance = fetch_allowance_tracking(uid)
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
    if allowance and allowance["tax_year"] == current_tax_year:
        base_isa_used = float(allowance["isa_used"])
        lisa_used = float(allowance["lisa_used"])
        isa_used = base_isa_used + lisa_used
    else:
        isa_used = 0
        lisa_used = 0

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
        "isa_used": isa_used,
        "lisa_used": lisa_used,
        "isa_progress": allowance_progress(isa_used, float(assumptions["isa_allowance"]) if assumptions else 0),
        "lisa_progress": allowance_progress(lisa_used, float(assumptions["lisa_allowance"]) if assumptions else 0),
        "effective_values": {account["id"]: effective_account_value(account, holdings_totals) for account in accounts},
    }

    history = fetch_net_worth_history(uid)
    history_labels = [h[0] for h in history]
    history_values = [round(h[1], 2) for h in history]

    return render_template(
        "overview.html",
        metrics=metrics,
        accounts=accounts,
        assumptions=assumptions,
        history_labels=history_labels,
        history_values=history_values,
        active_page="overview",
    )
