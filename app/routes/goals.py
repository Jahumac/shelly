from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.calculations import (
    effective_account_value,
    effective_monthly_contribution,
    projected_account_value_at_month,
    progress_to_goal,
    remaining_to_goal,
    to_float,
)
from app.utils import optional_float, optional_int, split_tags as _split_tags
from app.models import (
    fetch_assumptions,
    fetch_user_tags,
    create_goal,
    delete_goal,
    fetch_all_accounts,
    fetch_all_goals,
    fetch_goal,
    fetch_holding_totals_by_account,
    update_goal,
)

goals_bp = Blueprint("goals", __name__)


def _goal_payload_from_form(form):
    # getlist handles multiple checkboxes named "selected_tags" (direct submit approach).
    # Falls back to a single hidden input value if only one value is present.
    tag_values = [t.strip() for t in form.getlist("selected_tags") if t.strip()]
    return {
        "name": form.get("name", "").strip(),
        "target_value": max(0.0, optional_float(form.get("target_value"), default=0.0)),
        "goal_type": form.get("goal_type", "Tagged Goal").strip(),
        "selected_tags": ", ".join(tag_values),
        "notes": form.get("notes", "").strip(),
    }


def _project_goal(included_accounts, target, assumptions):
    """Estimate how many months until the included accounts reach `target`.

    Uses the same engine as the Projections page — effective_monthly_contribution
    (which includes tax relief, employer match, LISA bonus) and per-account growth
    rates net of fees. Each account is projected independently then summed, so
    different rates and LISA caps are all handled correctly.
    """
    target_f = float(target)
    current_total = sum(to_float(a["current_value"]) for a in included_accounts)

    if current_total >= target_f:
        return {"reached": True}

    total_monthly = sum(effective_monthly_contribution(a, assumptions) for a in included_accounts)
    if total_monthly <= 0:
        return None  # no contributions → can't project

    MAX_MONTHS = 50 * 12
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for month in range(1, MAX_MONTHS + 1):
        projected = sum(
            projected_account_value_at_month(a, assumptions, month)
            for a in included_accounts
        )
        if projected >= target_f:
            years, rem_months = divmod(month, 12)
            today = date.today()
            eta_month_num = today.month + month
            eta_year = today.year + (eta_month_num - 1) // 12
            eta_month_num = (eta_month_num - 1) % 12 + 1
            eta_label = f"{month_names[eta_month_num - 1]} {eta_year}"

            if years == 0:
                duration = f"{rem_months}m"
            elif rem_months == 0:
                duration = f"{years}y"
            else:
                duration = f"{years}y {rem_months}m"

            return {
                "reached": False,
                "total_months": month,
                "duration": duration,
                "eta_label": eta_label,
            }

    return {"reached": False, "total_months": None, "duration": ">50y", "eta_label": None}


def _build_goal_card(goal, accounts, holdings_totals, assumptions=None):
    selected_tags = _split_tags(goal["selected_tags"]) if "selected_tags" in goal else []
    included_accounts = []

    for account in accounts:
        account_tags = _split_tags(account["tags"]) if "tags" in account else []
        if selected_tags and any(tag in account_tags for tag in selected_tags):
            # Mirror what the Projections page does: override current_value with
            # the effective value (so holdings-based accounts use live holdings totals)
            row = dict(account)
            row["current_value"] = effective_account_value(account, holdings_totals)
            included_accounts.append(row)

    current_total = sum(a["current_value"] for a in included_accounts)
    target = float(goal["target_value"] or 0)

    monthly_contribution = sum(
        effective_monthly_contribution(a, assumptions) for a in included_accounts
    )
    projection = _project_goal(included_accounts, target, assumptions)

    return {
        "id": goal["id"],
        "name": goal["name"],
        "goal_type": goal["goal_type"] or "Tagged Goal",
        "selected_tags": selected_tags,
        "current": current_total,
        "target": target,
        "progress": progress_to_goal(current_total, target),
        "remaining": remaining_to_goal(current_total, target),
        "account_count": len(included_accounts),
        "notes": goal["notes"] or "",
        "monthly_contribution": monthly_contribution,
        "projection": projection,
    }


@goals_bp.route("/", methods=["GET", "POST"])
@login_required
def goals():
    uid = current_user.id
    if request.method == "POST":
        form_name = request.form.get("form_name", "create_goal")

        if form_name == "delete_goal":
            goal_id = optional_int(request.form.get("goal_id"))
            if goal_id:
                delete_goal(goal_id, uid)
            return redirect(url_for("goals.goals"))

        payload = _goal_payload_from_form(request.form)
        if not payload["name"]:
            flash("Goal name is required.", "error")
            return redirect(url_for("goals.goals"))
        goal_id = optional_int(request.form.get("goal_id"))
        if goal_id:
            payload["id"] = goal_id
            if not update_goal(payload, uid):
                flash("Goal not found.", "error")
        else:
            create_goal(payload, uid)
        return redirect(url_for("goals.goals"))

    accounts = fetch_all_accounts(uid)
    holdings_totals = fetch_holding_totals_by_account(uid)
    goal_rows = fetch_all_goals(uid)

    assumptions = fetch_assumptions(uid)

    goal_cards = [_build_goal_card(goal, accounts, holdings_totals, assumptions) for goal in goal_rows]

    # Deduplicated total saved: sum each account at most once across all goals
    included_ids = set()
    for goal_row in goal_rows:
        tags = _split_tags(goal_row["selected_tags"]) if goal_row["selected_tags"] else []
        for account in accounts:
            acct_tags = set(_split_tags(account["tags"]) if account["tags"] else [])
            if tags and acct_tags & set(tags):
                included_ids.add(account["id"])
    total_saved = sum(
        effective_account_value(a, holdings_totals)
        for a in accounts if a["id"] in included_ids
    )

    selected_goal = None
    selected_goal_tags = []
    page_mode = request.args.get("mode", "view")
    selected_goal_id = request.args.get("goal_id", type=int)
    if selected_goal_id:
        selected_goal = fetch_goal(selected_goal_id, uid)
        if selected_goal:
            selected_goal_tags = _split_tags(selected_goal["selected_tags"]) if "selected_tags" in selected_goal else []

    return render_template(
        "goals.html",
        goal_cards=goal_cards,
        total_saved=total_saved,
        selected_goal=selected_goal,
        selected_goal_tags=selected_goal_tags,
        tag_options=fetch_user_tags(current_user.id),
        page_mode=page_mode,
        active_page="goals",
    )
