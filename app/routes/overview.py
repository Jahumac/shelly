import math
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
    to_float,
    total_invested,
    total_monthly_contributions,
    uk_tax_year_label,
    uk_tax_year_start,
    uk_tax_year_end,
    days_until_tax_year_end,
)
from app.models import (
    fetch_all_accounts,
    fetch_all_active_overrides,
    fetch_all_goals,
    fetch_all_holdings,
    fetch_all_holdings_grouped,
    fetch_assumptions,
    fetch_holding_totals_by_account,
    fetch_isa_contributions,
    fetch_monthly_review,
    fetch_monthly_review_items,
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

    # Keep a single primary goal for the hero stat + backward compat
    goal = fetch_primary_goal(uid)
    goal_target = float(goal["target_value"]) if goal else 0
    goal_progress = progress_to_goal(invested_total, goal_target)

    current_tax_year = uk_tax_year_label()
    now_date = datetime.now().date()

    # Build per-goal progress rows (used in the goals section)
    def _goal_year_estimate(target, current, monthly, assum):
        if target <= current or monthly <= 0 or not assum:
            return None
        try:
            rate = to_float(assum.get("annual_growth_rate", 0.07))
            mr = rate / 12
            rem = target - current
            months = math.log(1 + rem * mr / monthly) / math.log(1 + mr) if mr > 0 else rem / monthly
            return now_date.year + int(months // 12) if 0 < months < 600 else None
        except (ValueError, ZeroDivisionError):
            return None

    all_goals = fetch_all_goals(uid)
    goals_data = []
    for g in all_goals:
        gt = float(g["target_value"] or 0)
        gp = progress_to_goal(invested_total, gt)
        goals_data.append({
            "id": g["id"],
            "name": g["name"],
            "target": gt,
            "progress": gp,
            "remaining": max(gt - invested_total, 0),
            "goal_year": _goal_year_estimate(gt, invested_total, monthly_total, assumptions),
        })

    # Primary goal year for hero stat
    goal_year = goals_data[0]["goal_year"] if goals_data else None
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
        "goal_year": goal_year,
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

    # Unlinked holdings: held via "holdings" valuation but no catalogue link → won't auto-price
    if assumptions and assumptions.get("auto_update_prices"):
        all_holdings = fetch_all_holdings(uid)
        unlinked = [h for h in all_holdings if not h.get("holding_catalogue_id") and h.get("ticker")]
        if unlinked:
            count = len(unlinked)
            alerts.append({
                "kind": "info",
                "message": f"{count} holding{'s' if count != 1 else ''} {'have' if count != 1 else 'has'} a ticker but no price source linked — {'their' if count != 1 else 'its'} price won't update automatically.",
                "cta_text": "Review holdings",
                "cta_href": "/holdings/",
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

    # Missed last-month review: past the ready date and review not complete
    if salary_day:
        lm_year, lm_month = (now_date.year - 1, 12) if now_date.month == 1 else (now_date.year, now_date.month - 1)
        lm_key = f"{lm_year}-{lm_month:02d}"
        lm_ready = review_ready_date(lm_year, lm_month, salary_day)
        if now_date >= lm_ready:
            lm_review = fetch_monthly_review(lm_key, uid)
            if lm_review is None or lm_review["status"] != "complete":
                lm_label = datetime(lm_year, lm_month, 1).strftime("%B")
                alerts.append({
                    "kind": "warning",
                    "message": f"Your {lm_label} monthly update hasn't been completed yet.",
                    "cta_text": "Do it now",
                    "cta_href": f"/monthly-review/?month={lm_key}",
                    "cta_form_action": None,
                })

    # Unconfirmed contributions: review is complete but some contributions weren't ticked off
    current_review = fetch_monthly_review(current_month_key, uid)
    if current_review and current_review["status"] == "complete":
        review_items = fetch_monthly_review_items(current_review["id"])
        active_overrides = fetch_all_active_overrides(current_month_key, uid)
        skipped_ids = {
            aid for aid, ov in active_overrides.items()
            if float(ov.get("override_amount") or 0) == 0
        }
        unconfirmed = [
            item for item in review_items
            if (item.get("expected_contribution") or 0) > 0
            and not item.get("contribution_confirmed")
            and item["account_id"] not in skipped_ids
        ]
        if unconfirmed:
            names = ", ".join(item["account_name"] for item in unconfirmed[:3])
            if len(unconfirmed) > 3:
                names += f" and {len(unconfirmed) - 3} more"
            alerts.append({
                "kind": "info",
                "message": f"Your {now_date.strftime('%B')} update is done but {len(unconfirmed)} contribution{'s' if len(unconfirmed) != 1 else ''} weren't confirmed — did they all arrive? ({names})",
                "cta_text": "Check contributions",
                "cta_href": f"/monthly-review/?month={current_month_key}",
                "cta_form_action": None,
            })

    # LISA bonus reminder: April 6 – June 30, if LISA was used in the just-ended tax year
    has_lisa = any("Lifetime" in (a.get("wrapper_type") or "") or "LISA" in (a.get("wrapper_type") or "") for a in raw_accounts)
    if has_lisa:
        from datetime import date as _date
        last_ty_end = _date(now_date.year, 4, 5)
        last_ty_start = _date(now_date.year - 1, 4, 6)
        bonus_window_end = _date(now_date.year, 6, 30)
        if last_ty_end < now_date <= bonus_window_end:
            prev_ad_hoc = fetch_isa_contributions(uid, last_ty_start.isoformat(), last_ty_end.isoformat())
            prev_usage = calculate_isa_usage(raw_accounts, prev_ad_hoc, last_ty_end, salary_day)
            if prev_usage["lisa_used"] > 0:
                alerts.append({
                    "kind": "info",
                    "message": f"The {last_ty_start.year}/{str(last_ty_end.year)[2:]} LISA government bonus should arrive soon — check your account to make sure it's been credited.",
                    "cta_text": None,
                    "cta_href": None,
                })

    # ── Asset allocation by individual holding ────────────────────────────────
    all_holdings_grouped = fetch_all_holdings_grouped(uid)
    holding_totals: dict = {}
    for h in all_holdings_grouped:
        name = (h["holding_name"] or "Unknown").strip() or "Unknown"
        val = float(h["value"] or 0)
        if val > 0:
            holding_totals[name] = holding_totals.get(name, 0) + val
    # Sort by value descending
    allocation = sorted(
        holding_totals.items(),
        key=lambda x: -x[1],
    )
    allocation_labels = [a[0] for a in allocation]
    allocation_values = [round(a[1], 2) for a in allocation]

    return render_template(
        "overview.html",
        metrics=metrics,
        accounts=accounts,
        goals_data=goals_data,
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
        allocation_labels=allocation_labels,
        allocation_values=allocation_values,
        active_page="overview",
    )
