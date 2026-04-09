from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.calculations import effective_account_value, progress_to_goal, remaining_to_goal
from app.models import (
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


def _split_tags(tags_value):
    return [tag.strip() for tag in (tags_value or "").split(",") if tag.strip()]


def _goal_payload_from_form(form):
    return {
        "name": form.get("name", "").strip(),
        "target_value": float(form.get("target_value", 0) or 0),
        "goal_type": form.get("goal_type", "Tagged Goal").strip(),
        "selected_tags": form.get("selected_tags", ""),
        "notes": form.get("notes", "").strip(),
    }


def _build_goal_card(goal, accounts, holdings_totals):
    selected_tags = _split_tags(goal["selected_tags"]) if "selected_tags" in goal.keys() else []
    included_accounts = []

    for account in accounts:
        account_tags = _split_tags(account["tags"]) if "tags" in account.keys() else []
        if selected_tags and any(tag in account_tags for tag in selected_tags):
            included_accounts.append(account)

    current_total = sum(effective_account_value(account, holdings_totals) for account in included_accounts)
    target = float(goal["target_value"] or 0)

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
    }


@goals_bp.route("/", methods=["GET", "POST"])
@login_required
def goals():
    uid = current_user.id
    if request.method == "POST":
        form_name = request.form.get("form_name", "create_goal")

        if form_name == "delete_goal":
            goal_id = int(request.form.get("goal_id", 0))
            if goal_id:
                delete_goal(goal_id)
            return redirect(url_for("goals.goals"))

        payload = _goal_payload_from_form(request.form)
        goal_id = request.form.get("goal_id")
        if goal_id:
            payload["id"] = int(goal_id)
            update_goal(payload)
        else:
            create_goal(payload, uid)
        return redirect(url_for("goals.goals"))

    accounts = fetch_all_accounts(uid)
    holdings_totals = fetch_holding_totals_by_account(uid)
    goal_rows = fetch_all_goals(uid)

    goal_cards = [_build_goal_card(goal, accounts, holdings_totals) for goal in goal_rows]

    selected_goal = None
    selected_goal_tags = []
    page_mode = request.args.get("mode", "view")
    selected_goal_id = request.args.get("goal_id", type=int)
    if selected_goal_id:
        selected_goal = fetch_goal(selected_goal_id)
        if selected_goal:
            selected_goal_tags = _split_tags(selected_goal["selected_tags"]) if "selected_tags" in selected_goal.keys() else []
            if page_mode == "view":
                page_mode = "edit"

    return render_template(
        "goals.html",
        goal_cards=goal_cards,
        selected_goal=selected_goal,
        selected_goal_tags=selected_goal_tags,
        tag_options=fetch_user_tags(current_user.id),
        page_mode=page_mode,
        active_page="goals",
    )
