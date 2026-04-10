from datetime import datetime

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.calculations import current_age_from_assumptions
from app.models import fetch_assumptions, reset_all_user_data, update_assumptions

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/", methods=["GET", "POST"])
@login_required
def settings():
    uid = current_user.id
    assumptions = fetch_assumptions(uid)

    if request.method == "POST":
        # Remember whether this is the first time DOB is being set (for redirect)
        had_no_dob = not (assumptions and assumptions["date_of_birth"])

        salary_day = int(request.form.get("salary_day", 0))
        update_day = int(request.form.get("update_day", 0))

        # Auto-calculate update day: salary day + 5 calendar days (settlement buffer)
        if salary_day and not update_day:
            update_day = salary_day + 5
            if update_day > 28:
                update_day = update_day - 28  # wrap into next month (early days)

        new_dob = request.form.get("date_of_birth", "").strip()

        payload = {
            "annual_growth_rate": float(request.form.get("annual_growth_rate", 7)) / 100.0,
            "retirement_age": int(request.form.get("retirement_age", 60)),
            "date_of_birth": new_dob,
            "retirement_goal_value": assumptions["retirement_goal_value"] if assumptions else 1000000,
            "isa_allowance": float(request.form.get("isa_allowance", 20000)),
            "lisa_allowance": float(request.form.get("lisa_allowance", 4000)),
            "annual_income": float(request.form.get("annual_income", 0) or 0),
            "pension_annual_allowance": float(request.form.get("pension_annual_allowance", 60000) or 60000),
            "mpaa_enabled": 1 if request.form.get("mpaa_enabled") else 0,
            "mpaa_allowance": float(request.form.get("mpaa_allowance", 10000) or 10000),
            "target_dev_pct": assumptions["target_dev_pct"] if assumptions else 0.90,
            "target_em_pct": assumptions["target_em_pct"] if assumptions else 0.10,
            "emergency_fund_target": assumptions["emergency_fund_target"] if assumptions else 3000,
            "dashboard_name": request.form.get("dashboard_name", "Shelly").strip() or "Shelly",
            "salary_day": salary_day,
            "update_day": update_day,
            "retirement_date_mode": request.form.get("retirement_date_mode", "birthday"),
            "tax_band": request.form.get("tax_band", "basic"),
            "auto_update_prices": 1 if request.form.get("auto_update_prices") else 0,
            "update_time_morning": request.form.get("update_time_morning", "08:30").strip() or "08:30",
            "update_time_evening": request.form.get("update_time_evening", "18:00").strip() or "18:00",
            "updated_at": datetime.now().isoformat(),
        }
        update_assumptions(payload, uid)

        # First-time profile setup: bounce back to overview so the user
        # sees their onboarding progress tick forward
        if had_no_dob and new_dob:
            return redirect(url_for("overview.overview"))

        return redirect(url_for("settings.settings"))

    computed_age = int(current_age_from_assumptions(assumptions)) if assumptions else 0
    return render_template("settings.html", assumptions=assumptions, computed_age=computed_age, active_page="settings")


@settings_bp.route("/reset", methods=["POST"])
@login_required
def reset_account():
    """Wipe all user data and return to a fresh-login state."""
    confirmation = request.form.get("confirm_reset", "").strip()
    if confirmation != "RESET":
        return redirect(url_for("settings.settings"))
    reset_all_user_data(current_user.id)
    return redirect(url_for("overview.overview"))
