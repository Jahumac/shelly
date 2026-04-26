from datetime import datetime

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.calculations import compute_performance_series, to_float, uk_tax_year_start, uk_tax_year_end, uk_tax_year_label
from app.models import fetch_all_accounts, fetch_assumptions, fetch_daily_snapshots, fetch_monthly_performance_data, fetch_monthly_performance_data_by_account, fetch_tax_year_contributions

performance_bp = Blueprint("performance", __name__)


@performance_bp.route("/")
@login_required
def performance():
    uid = current_user.id
    assumptions   = fetch_assumptions(uid)
    accounts      = fetch_all_accounts(uid)

    assumed_rate   = to_float(assumptions["annual_growth_rate"]) if assumptions else 0.07
    benchmark_rate = to_float(assumptions["benchmark_rate"]) if assumptions and assumptions["benchmark_rate"] is not None else None
    benchmark_rate_pct = round(benchmark_rate * 100, 1) if benchmark_rate is not None else None

    # Daily snapshots for the chart (same as overview)
    daily_snapshots = fetch_daily_snapshots(uid, limit=730)
    has_data = len(daily_snapshots) >= 2

    daily_labels = []
    daily_actual = []
    daily_plan   = []
    daily_bench  = []
    plan_value      = None
    benchmark_value = None
    current_value   = None

    if has_data:
        start_val = daily_snapshots[0][1]
        daily_rate_plan  = (1 + assumed_rate) ** (1 / 365) - 1
        daily_rate_bench = (1 + benchmark_rate) ** (1 / 365) - 1 if benchmark_rate else None

        for i, (date_str, val) in enumerate(daily_snapshots):
            # Format date label same style as overview
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                label = dt.strftime("%-d %b %Y")
            except ValueError:
                label = date_str
            daily_labels.append(label)
            daily_actual.append(round(val, 2))
            daily_plan.append(round(start_val * ((1 + daily_rate_plan) ** i), 2))
            if daily_rate_bench is not None:
                daily_bench.append(round(start_val * ((1 + daily_rate_bench) ** i), 2))

        current_value   = daily_actual[-1]
        plan_value      = daily_plan[-1]
        benchmark_value = daily_bench[-1] if daily_bench else None

    # Per-account — use live account values + monthly snapshots for growth %
    live_accounts = {a["id"]: a for a in accounts if to_float(a.get("current_value")) > 0}
    by_account_raw = fetch_monthly_performance_data_by_account(uid)
    account_perf = []
    seen_ids = set()
    for aid, info in by_account_raw.items():
        rows = info["rows"]
        live = live_accounts.get(aid)
        current_val = to_float(live["current_value"]) if live else (rows[-1][1] if rows else 0)
        n_months = len(rows)
        total_return = None
        if len(rows) >= 2:
            acct_data = [(mk, bal, contrib) for mk, bal, contrib in rows]
            ap = compute_performance_series(acct_data, assumed_rate, 0, benchmark_rate=None)
            if ap:
                total_return = ap["total_return"]
        if current_val > 0 or n_months > 0:
            account_perf.append({
                "account_id":   aid,
                "account_name": info["account_name"],
                "total_return": total_return,
                "current_value": current_val,
                "n_months": n_months,
            })
            seen_ids.add(aid)
    # Include accounts with no snapshots at all (never had a monthly review)
    for a in accounts:
        if a["id"] not in seen_ids and to_float(a.get("current_value")) > 0:
            account_perf.append({
                "account_id":   a["id"],
                "account_name": a["name"],
                "total_return": None,
                "current_value": to_float(a["current_value"]),
                "n_months": 0,
            })
    account_perf.sort(key=lambda x: -(x["current_value"] or 0))

    return render_template(
        "performance.html",
        has_data=has_data,
        daily_labels=daily_labels,
        daily_actual=daily_actual,
        daily_plan=daily_plan,
        daily_bench=daily_bench,
        assumed_rate_pct=round(assumed_rate * 100, 1),
        benchmark_rate_pct=benchmark_rate_pct,
        account_perf=account_perf,
        plan_value=plan_value,
        benchmark_value=benchmark_value,
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
