from datetime import date, datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import (
    create_budget_item,
    create_budget_section,
    delete_budget_item,
    delete_budget_items_by_section,
    delete_budget_section,
    fetch_all_accounts,
    fetch_budget_entries,
    fetch_budget_item,
    fetch_budget_items,
    fetch_budget_sections,
    fetch_months_with_budget_entries,
    fetch_prior_month_budget_entries,
    update_budget_item,
    update_budget_section,
    upsert_budget_entry,
)

budget_bp = Blueprint("budget", __name__)


def _default_month_key():
    today = date.today()
    return f"{today.year}-{today.month:02d}"


def _month_label(month_key):
    return datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")


def _optional_float(value, default=0.0):
    try:
        return float((value or "").strip())
    except ValueError:
        return default


def _build_monthly_data(month_key, user_id):
    db_sections = fetch_budget_sections(user_id)
    items = fetch_budget_items(user_id)
    entries = fetch_budget_entries(month_key, user_id)
    entry_map = {e["budget_item_id"]: e for e in entries}
    accounts = fetch_all_accounts(user_id)
    account_map = {a["id"]: a for a in accounts}

    # Always load prior-month entries so we can show per-item inheritance
    prior_entries = fetch_prior_month_budget_entries(month_key, user_id)
    prior_entry_map = {e["budget_item_id"]: e for e in prior_entries}

    income_key = db_sections[0]["key"] if db_sections else "income"

    sections = []
    section_totals = {}

    for sec in db_sections:
        section_key = sec["key"]
        section_items = []
        for item in items:
            if item["section"] != section_key:
                continue
            if item["id"] in entry_map:
                amount = float(entry_map[item["id"]]["amount"] or 0)
            elif item["id"] in prior_entry_map:
                amount = float(prior_entry_map[item["id"]]["amount"] or 0)
            elif item["linked_account_id"] and item["linked_account_id"] in account_map:
                amount = float(account_map[item["linked_account_id"]]["monthly_contribution"] or 0)
            else:
                amount = float(item["default_amount"] or 0)
            # Track whether amount came from the current month or was inherited
            source = "current"
            if item["id"] in entry_map:
                source = "current"
            elif item["id"] in prior_entry_map:
                source = "inherited"
            elif item["linked_account_id"] and item["linked_account_id"] in account_map:
                source = "linked"
            else:
                source = "default"

            section_items.append({
                "id": item["id"],
                "name": item["name"],
                "notes": item["notes"],
                "amount": amount,
                "linked": item["linked_account_id"] is not None,
                "source": source,
            })
        section_total = sum(i["amount"] for i in section_items)
        section_totals[section_key] = section_total
        sections.append({
            "key": section_key,
            "label": sec["label"],
            "rows": section_items,
            "total": section_total,
        })

    total_income = section_totals.get(income_key, 0)
    total_expenses = sum(v for k, v in section_totals.items() if k != income_key)
    surplus = total_income - total_expenses
    savings_total = 0.0
    for sec in db_sections:
        k = sec["key"]
        if k != income_key and ("invest" in k or "saving" in k):
            savings_total += section_totals.get(k, 0)
    savings_rate = (savings_total / total_income * 100) if total_income > 0 else 0.0

    summary = {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "surplus": surplus,
        "savings_rate": savings_rate,
    }

    return sections, summary


@budget_bp.route("/", methods=["GET", "POST"])
@login_required
def budget():
    uid = current_user.id
    month_key = request.values.get("month") or _default_month_key()

    if request.method == "POST":
        item_id = request.form.get("item_id", type=int)
        if item_id:
            upsert_budget_entry(month_key, item_id, _optional_float(request.form.get("amount"), 0.0))
        return redirect(url_for("budget.budget", month=month_key))

    sections, summary = _build_monthly_data(month_key, uid)
    db_sections = fetch_budget_sections(uid)
    income_key = db_sections[0]["key"] if db_sections else "income"

    # ── 12-month strip: build tax-year range (Apr → Mar) ─────────────────
    saved_months = fetch_months_with_budget_entries(uid)
    mk_parts = month_key.split("-")
    mk_year, mk_month = int(mk_parts[0]), int(mk_parts[1])

    # Determine the tax year the selected month falls in (Apr 6 → Apr 5)
    if mk_month >= 4:
        ty_start_year = mk_year
    else:
        ty_start_year = mk_year - 1

    month_strip = []
    for i in range(12):
        m = 4 + i  # Apr=4, May=5, ... Mar=15→3
        y = ty_start_year if m <= 12 else ty_start_year + 1
        if m > 12:
            m -= 12
        mk = f"{y}-{m:02d}"
        label_short = datetime.strptime(mk, "%Y-%m").strftime("%b")
        month_strip.append({
            "key": mk,
            "label": label_short,
            "has_data": mk in saved_months,
            "is_current": mk == month_key,
            "is_today": mk == _default_month_key(),
            "month_num": m,
        })

    # Is this month entirely inherited (no saved entries)?
    is_inherited = month_key not in saved_months

    return render_template(
        "budget.html",
        month_key=month_key,
        month_label=_month_label(month_key),
        sections=sections,
        summary=summary,
        income_key=income_key,
        month_strip=month_strip,
        is_inherited=is_inherited,
        active_page="budget",
    )


@budget_bp.route("/api/entry", methods=["POST"])
@login_required
def budget_save_entry():
    """AJAX endpoint — save a single budget entry, return JSON."""
    month_key = request.form.get("month") or _default_month_key()
    item_id = request.form.get("item_id", type=int)
    amount = _optional_float(request.form.get("amount"), 0.0)
    if item_id:
        upsert_budget_entry(month_key, item_id, amount)
    return jsonify({"ok": True})


@budget_bp.route("/api/quick-add", methods=["POST"])
@login_required
def budget_quick_add():
    """AJAX endpoint — add a new budget item from the budget view."""
    uid = current_user.id
    name = (request.form.get("name") or "").strip()
    section = (request.form.get("section") or "").strip()
    if not name or not section:
        return jsonify({"ok": False, "error": "Name and section required"}), 400

    existing = fetch_budget_items(uid)
    sort_order = max(
        (i["sort_order"] for i in existing if i["section"] == section), default=-1
    ) + 1
    item_id = create_budget_item({
        "name": name,
        "section": section,
        "default_amount": 0.0,
        "linked_account_id": None,
        "notes": "",
        "sort_order": sort_order,
    }, uid)
    return jsonify({"ok": True, "item_id": item_id, "name": name})


@budget_bp.route("/items/", methods=["GET", "POST"])
@login_required
def budget_items_view():
    uid = current_user.id
    if request.method == "POST":
        form_name = request.form.get("form_name", "")

        if form_name == "clear_section":
            delete_budget_items_by_section(request.form.get("section_key", ""), uid)
            return redirect(url_for("budget.budget_items_view"))

        if form_name == "add_section":
            label = request.form.get("section_label", "").strip()
            if label:
                create_budget_section(label, uid)
            return redirect(url_for("budget.budget_items_view"))

        if form_name == "edit_section":
            update_budget_section(
                request.form.get("section_key", ""),
                request.form.get("section_label", "").strip(),
                uid,
            )
            return redirect(url_for("budget.budget_items_view"))

        if form_name == "delete_section":
            delete_budget_section(request.form.get("section_key", ""), uid)
            return redirect(url_for("budget.budget_items_view"))

        # default: create item
        section = request.form.get("section", "")
        existing = fetch_budget_items(uid)
        sort_order = max(
            (i["sort_order"] for i in existing if i["section"] == section), default=-1
        ) + 1
        linked_raw = request.form.get("linked_account_id", "")
        create_budget_item({
            "name": request.form.get("name", "").strip(),
            "section": section,
            "default_amount": _optional_float(request.form.get("default_amount"), 0.0),
            "linked_account_id": int(linked_raw) if linked_raw else None,
            "notes": request.form.get("notes", "").strip(),
            "sort_order": sort_order,
        }, uid)
        return redirect(url_for("budget.budget_items_view"))

    db_sections = fetch_budget_sections(uid)
    all_items = fetch_budget_items(uid)
    accounts = fetch_all_accounts(uid)
    account_map = {a["id"]: dict(a) for a in accounts}

    grouped = []
    for sec in db_sections:
        section_key = sec["key"]
        section_items = []
        for item in all_items:
            if item["section"] != section_key:
                continue
            row = dict(item)
            row["linked_account_name"] = (
                account_map[item["linked_account_id"]]["name"]
                if item["linked_account_id"] and item["linked_account_id"] in account_map
                else None
            )
            section_items.append(row)
        grouped.append({"key": section_key, "label": sec["label"], "rows": section_items})

    selected_id = request.args.get("item_id", type=int)
    selected = fetch_budget_item(selected_id) if selected_id else None
    page_mode = request.args.get("mode", "view" if selected_id else "list")
    section_options = [(s["key"], s["label"]) for s in db_sections]

    return render_template(
        "budget_items.html",
        grouped=grouped,
        accounts=accounts,
        section_options=section_options,
        selected=selected,
        page_mode=page_mode,
        active_page="budget",
    )


@budget_bp.route("/items/<int:item_id>", methods=["POST"])
@login_required
def budget_item_action(item_id):
    if request.form.get("form_name") == "delete":
        delete_budget_item(item_id)
        return redirect(url_for("budget.budget_items_view"))

    linked_raw = request.form.get("linked_account_id", "")
    update_budget_item({
        "id": item_id,
        "name": request.form.get("name", "").strip(),
        "section": request.form.get("section", ""),
        "default_amount": _optional_float(request.form.get("default_amount"), 0.0),
        "linked_account_id": int(linked_raw) if linked_raw else None,
        "notes": request.form.get("notes", "").strip(),
    })
    return redirect(url_for("budget.budget_items_view"))
