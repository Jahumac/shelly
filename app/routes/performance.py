from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.calculations import compute_performance_series, to_float
from app.models import fetch_all_accounts, fetch_assumptions, fetch_monthly_performance_data

performance_bp = Blueprint("performance", __name__)


@performance_bp.route("/")
@login_required
def performance():
    uid = current_user.id
    assumptions   = fetch_assumptions(uid)
    accounts      = fetch_all_accounts(uid)
    monthly_data  = fetch_monthly_performance_data(uid)

    assumed_rate    = to_float(assumptions["annual_growth_rate"]) if assumptions else 0.07
    assumed_monthly = sum(to_float(a["monthly_contribution"]) for a in accounts)

    perf = compute_performance_series(monthly_data, assumed_rate, assumed_monthly)

    return render_template(
        "performance.html",
        perf=perf,
        assumed_rate_pct=round(assumed_rate * 100, 1),
        active_page="performance",
    )
