from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.calculations import current_age_from_assumptions, effective_account_value, projected_account_value, projected_account_value_at_year, projected_account_value_no_fees, projected_accounts, projected_total_retirement_value, to_float, years_to_retirement
from app.models import fetch_all_accounts, fetch_assumptions, fetch_holding_totals_by_account

projections_bp = Blueprint("projections", __name__)


def _year_by_year_chart(accounts, assumptions):
    """Return (labels, values) for projected total, year by year to retirement.

    Uses whole-year steps up to the last full year, then adds a final point at
    the exact fractional retirement date so the chart endpoint matches the
    summary card and breakdown figures.
    """
    if not assumptions:
        return [], []
    current_age = current_age_from_assumptions(assumptions)
    retirement_age = to_float(assumptions["retirement_age"])
    exact_years = years_to_retirement(current_age, retirement_age, assumptions)
    whole_years = int(exact_years)

    labels, values = [], []
    for yr in range(0, whole_years + 1):
        total = sum(
            projected_account_value_at_year(a, assumptions, yr)
            for a in accounts
        )
        label = "Today" if yr == 0 else f"Age {int(current_age + yr)}"
        labels.append(label)
        values.append(round(total, 0))

    # Add final fractional-year point so the chart endpoint matches the card
    if exact_years > whole_years:
        total = sum(
            projected_account_value(a, assumptions)
            for a in accounts
        )
        labels.append(f"Age {int(retirement_age)}")
        values.append(round(total, 0))

    return labels, values


@projections_bp.route("/")
@login_required
def projections():
    uid = current_user.id
    raw_accounts = fetch_all_accounts(uid)
    assumptions = fetch_assumptions(uid)
    holdings_totals = fetch_holding_totals_by_account(uid)

    accounts = []
    for account in raw_accounts:
        row = dict(account)
        row["current_value"] = effective_account_value(account, holdings_totals)
        accounts.append(row)

    account_rows = projected_accounts(accounts, assumptions)
    total_projected = projected_total_retirement_value(accounts, assumptions)
    total_no_fees = sum(projected_account_value_no_fees(a, assumptions) for a in accounts) if assumptions else 0
    total_fee_impact = total_no_fees - total_projected
    computed_age = current_age_from_assumptions(assumptions) if assumptions else 0
    years_remaining = years_to_retirement(computed_age, assumptions["retirement_age"], assumptions) if assumptions else 0
    chart_labels, chart_values = _year_by_year_chart(accounts, assumptions)

    metrics = {
        "growth_rate": float(assumptions["annual_growth_rate"]) if assumptions else 0,
        "retirement_age": assumptions["retirement_age"] if assumptions else 0,
        "current_age": int(computed_age),
        "current_age_frac": computed_age,
        "years_remaining": years_remaining,
        "total_projected": total_projected,
        "total_current": sum(to_float(a["current_value"]) for a in accounts),
        "total_monthly": sum(to_float(a["monthly_contribution"]) for a in accounts),
        "total_fee_impact": total_fee_impact,
    }

    return render_template(
        "projections.html",
        metrics=metrics,
        account_rows=account_rows,
        chart_labels=chart_labels,
        chart_values=chart_values,
        active_page="projections",
    )
