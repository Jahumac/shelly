from datetime import datetime

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.calculations import compute_performance_series, to_float, uk_tax_year_start, uk_tax_year_end, uk_tax_year_label
from app.models import fetch_all_accounts, fetch_assumptions, fetch_monthly_performance_data, fetch_monthly_performance_data_by_account, fetch_tax_year_contributions

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
    benchmark_rate  = to_float(assumptions["benchmark_rate"]) if assumptions and assumptions["benchmark_rate"] is not None else None

    perf = compute_performance_series(monthly_data, assumed_rate, assumed_monthly, benchmark_rate=benchmark_rate)

    benchmark_rate_pct = round(benchmark_rate * 100, 1) if benchmark_rate is not None else None

    # Per-account performance
    by_account_raw = fetch_monthly_performance_data_by_account(uid)
    account_perf = []
    for aid, info in by_account_raw.items():
        rows = info["rows"]
        if len(rows) < 2:
            continue
        acct_data = [(mk, bal, contrib) for mk, bal, contrib in rows]
        ap = compute_performance_series(acct_data, assumed_rate, 0, benchmark_rate=None)
        if ap:
            account_perf.append({
                "account_id":  aid,
                "account_name": info["account_name"],
                "total_return": ap["total_return"],
                "annualised_return": ap["annualised_return"],
                "current_value": ap["current_value"],
                "n_months": ap["n_months"],
            })
    account_perf.sort(key=lambda x: (x["annualised_return"] is None, -(x["annualised_return"] or 0)))

    plan_value      = perf["projected_values"][-1]  if perf and perf.get("projected_values") else None
    benchmark_value = perf["benchmark_values"][-1]  if perf and perf.get("benchmark_values") else None
    start_value     = perf["actual_values"][0]       if perf and perf.get("actual_values") else None
    current_value   = perf["actual_values"][-1]      if perf and perf.get("actual_values") else None

    return render_template(
        "performance.html",
        perf=perf,
        assumed_rate_pct=round(assumed_rate * 100, 1),
        benchmark_rate_pct=benchmark_rate_pct,
        account_perf=account_perf,
        plan_value=plan_value,
        benchmark_value=benchmark_value,
        start_value=start_value,
        current_value=current_value,
        active_page="performance",
    )


@performance_bp.route("/contributions/")
@login_required
def contribution_summary():
    uid = current_user.id
    today = datetime.now().date()
    ty_start = uk_tax_year_start(today)
    ty_end   = uk_tax_year_end(today)
    from_month = ty_start.strftime("%Y-%m")
    to_month   = ty_end.strftime("%Y-%m")

    rows = fetch_tax_year_contributions(uid, from_month, to_month)

    # Build month list for the tax year (Apr through Mar, only past/current months)
    months = []
    y, m = ty_start.year, ty_start.month
    current_ym = today.strftime("%Y-%m")
    while True:
        mk = f"{y:04d}-{m:02d}"
        if mk > current_ym:
            break
        months.append(mk)
        m += 1
        if m > 12:
            m = 1
            y += 1
        if mk > to_month:
            break

    # Index rows by (account_id, month_key)
    data = {}      # {account_id: {"name": str, "wrapper_type": str, "months": {mk: {expected, confirmed}}}}
    for r in rows:
        aid = r["account_id"]
        if aid not in data:
            data[aid] = {
                "name": r["account_name"],
                "wrapper_type": r["wrapper_type"],
                "months": {},
            }
        data[aid]["months"][r["month_key"]] = {
            "expected": float(r["expected_contribution"] or 0),
            "confirmed": bool(r["contribution_confirmed"]),
            "skipped": bool(r["is_skipped"]),
        }

    # Sort accounts by name
    accounts = sorted(data.values(), key=lambda a: a["name"])

    # Month display labels
    month_labels = []
    for mk in months:
        try:
            month_labels.append(datetime.strptime(mk, "%Y-%m").strftime("%b %Y"))
        except ValueError:
            month_labels.append(mk)

    # Column totals
    month_totals = {}
    for mk in months:
        month_totals[mk] = sum(
            a["months"].get(mk, {}).get("expected", 0) for a in accounts
        )

    return render_template(
        "contribution_summary.html",
        accounts=accounts,
        months=months,
        month_labels=month_labels,
        month_totals=month_totals,
        tax_year=uk_tax_year_label(today),
        active_page="performance",
    )
