from datetime import datetime, timezone

from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.calculations import (
    SCHEDULER_STALE_AFTER_HOURS,
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
    last_price_update_display = None
    next_update_display = None
    import pytz
    uk = pytz.timezone("Europe/London")
    now_uk = datetime.now(timezone.utc).astimezone(uk)
    lpu_dt_uk = None
    if last_price_update:
        try:
            if isinstance(last_price_update, str) and last_price_update.endswith(" UTC"):
                dt = datetime.strptime(last_price_update, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(last_price_update))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            lpu_dt_uk = dt.astimezone(uk)
            last_price_update_display = lpu_dt_uk.strftime("%d %b %H:%M")
        except (ValueError, TypeError):
            last_price_update_display = str(last_price_update)[:16]

    # Compute next expected auto-update time
    if assumptions and bool(assumptions.get("auto_update_prices", 1)):
        try:
            def _hhmm(val, default_h):
                try:
                    p = str(val).strip().split(":")
                    return int(p[0]), int(p[1])
                except (ValueError, IndexError):
                    return default_h, 0
            mh, mm = _hhmm(assumptions.get("update_time_morning", "08:30"), 8)
            eh, em = _hhmm(assumptions.get("update_time_evening", "22:00"), 22)
            win_start = now_uk.replace(hour=mh, minute=mm, second=0, microsecond=0)
            win_end   = now_uk.replace(hour=eh, minute=em, second=0, microsecond=0)

            if lpu_dt_uk:
                from datetime import timedelta
                candidate = lpu_dt_uk + timedelta(hours=1)
            else:
                candidate = win_start

            if candidate < win_start:
                candidate = win_start
            if candidate > win_end:
                # Next window is tomorrow morning
                tomorrow_start = (now_uk + timedelta(days=1)).replace(hour=mh, minute=mm, second=0, microsecond=0)
                next_update_display = "Tomorrow " + tomorrow_start.strftime("%H:%M")
            elif candidate <= now_uk:
                next_update_display = "Soon"
            else:
                next_update_display = candidate.strftime("%H:%M")
        except (ValueError, TypeError):
            next_update_display = None

    # ── Alerts ────────────────────────────────────────────────────────────────
    alerts = []

    # Price stale: only nag if auto-update is on and prices haven't refreshed in 24h
    if assumptions and assumptions["auto_update_prices"]:
        price_stale = True
        if last_price_update:
            try:
                if isinstance(last_price_update, str) and last_price_update.endswith(" UTC"):
                    lpu_dt = datetime.strptime(last_price_update, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                else:
                    lpu_dt = datetime.fromisoformat(str(last_price_update))
                    if lpu_dt.tzinfo is None:
                        lpu_dt = lpu_dt.replace(tzinfo=timezone.utc)
                price_stale = (datetime.now(timezone.utc) - lpu_dt).total_seconds() > SCHEDULER_STALE_AFTER_HOURS * 3600
            except (ValueError, TypeError):
                price_stale = True
        if price_stale:
            alerts.append({
                "kind": "warning",
                "message": "Prices haven't updated in over 24 hours — the scheduler may have missed a window.",
                "cta_text": "↻ Refresh now",
                "cta_href": None,
                "cta_form_action": "/holdings/trigger-price-update",
            })

    # ISA projected to exceed allowance
    isa_allowance_val = float(assumptions["isa_allowance"]) if assumptions and assumptions["isa_allowance"] else 0
    if isa_allowance_val > 0 and metrics["projected_isa"] > isa_allowance_val:
        over = metrics["projected_isa"] - isa_allowance_val
        alerts.append({
            "kind": "danger",
            "message": f"You're on track to exceed your ISA allowance by £{over:,.0f} this tax year.",
            "cta_text": "View allowance",
            "cta_href": "/allowance/",
        })

    # Pension projected to exceed allowance
    if pension_allowance > 0 and metrics["projected_pension"] > pension_allowance:
        over = metrics["projected_pension"] - pension_allowance
        alerts.append({
            "kind": "danger",
            "message": f"You're on track to exceed your pension annual allowance by £{over:,.0f} this tax year.",
            "cta_text": "View allowance",
            "cta_href": "/allowance/#pension",
        })

    # Tax year ending soon with unused ISA allowance
    days_left = metrics["tax_year_days_left"]
    isa_remaining = isa_allowance_val - metrics["isa_used"]
    if 0 < days_left <= 30 and isa_remaining > 500:
        alerts.append({
            "kind": "info",
            "message": f"{days_left} days left in the tax year — £{isa_remaining:,.0f} of your ISA allowance is still unused.",
            "cta_text": "Record top-up",
            "cta_href": "/allowance/#topup",
        })

    # Nudge to set investment day if accounts exist but salary_day is not configured
    if not salary_day and raw_accounts:
        alerts.append({
            "kind": "info",
            "message": "Set your investment day in Settings — it tells Shelly when to remind you to do your Monthly Update.",
            "cta_text": "Go to Settings",
            "cta_href": "/settings/?mode=edit",
            "cta_form_action": None,
        })

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
        last_price_update_display=last_price_update_display,
        next_update_display=next_update_display,
        review_nudge=review_nudge,
        review_ready=review_ready,
        alerts=alerts,
        active_page="overview",
    )
