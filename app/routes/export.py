"""
Export routes — generates .xlsx downloads for Projections and Budget.

Clean, professional styling with Shelly-themed headers and plain UK-formatted data.
"""
from datetime import date, datetime
from io import BytesIO

from flask import Blueprint, send_file, request
from flask_login import current_user, login_required
from openpyxl import Workbook
from openpyxl.styles import Border, Font, PatternFill, Alignment, Side, numbers
from openpyxl.utils import get_column_letter

from app.calculations import (
    _safe_get,
    account_gross_growth_rate,
    account_growth_rate,
    compute_performance_series,
    contribution_breakdown,
    current_age_from_assumptions,
    effective_account_value,
    effective_fee_pct,
    effective_monthly_contribution,
    future_value,
    projected_account_value,
    projected_account_value_at_year,
    projected_account_value_at_month,
    projected_account_value_at_month_no_fees,
    projected_account_value_at_year_no_fees,
    projected_account_value_no_fees,
    projected_total_retirement_value,
    to_float,
    years_to_retirement,
)
from app.models import (
    fetch_all_accounts,
    fetch_assumptions,
    fetch_budget_entries,
    fetch_budget_items,
    fetch_budget_sections,
    fetch_holding_totals_by_account,
    fetch_monthly_performance_data,
    fetch_monthly_performance_data_by_account,
    fetch_prior_month_budget_entries,
)

export_bp = Blueprint("export", __name__)

# ── Clean Shelly colour palette ──────────────────────────────────────────────
_SHELLY_TEAL   = "0F766E"   # Shelly's signature teal (header bg)
_SHELLY_LIGHT  = "CCFBF1"   # Pale teal tint for alternating rows
_BORDER_COLOUR = "D1D5DB"   # Light grey border

_TITLE_FONT    = Font(name="Aptos", bold=True, color="0F766E", size=14)
_SUBTITLE_FONT = Font(name="Aptos", color="6B7280", size=10)
_HEADER_FONT   = Font(name="Aptos", bold=True, color="FFFFFF", size=11)
_DATA_FONT     = Font(name="Aptos", color="1F2937", size=10)
_DATA_BOLD     = Font(name="Aptos", bold=True, color="1F2937", size=10)
_ACCENT_FONT   = Font(name="Aptos", bold=True, color="0F766E", size=11)

_HEADER_FILL   = PatternFill("solid", fgColor=_SHELLY_TEAL)
_ALT_FILL      = PatternFill("solid", fgColor=_SHELLY_LIGHT)
_NO_FILL       = PatternFill(fill_type=None)

_THIN_BORDER   = Border(
    bottom=Side(style="thin", color=_BORDER_COLOUR),
)


def _set_col_width(ws, col, width):
    ws.column_dimensions[get_column_letter(col)].width = width


def _header_row(ws, row_num, values):
    for col, val in enumerate(values, 1):
        cell = ws.cell(row=row_num, column=col, value=val)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(vertical="center", horizontal="left")
    ws.row_dimensions[row_num].height = 24


def _data_row(ws, row_num, values, bold=False, num_formats=None):
    num_formats = num_formats or {}
    font = _DATA_BOLD if bold else _DATA_FONT
    fill = _ALT_FILL if row_num % 2 == 0 else _NO_FILL
    for col, val in enumerate(values, 1):
        cell = ws.cell(row=row_num, column=col, value=val)
        cell.font = font
        cell.fill = fill
        cell.alignment = Alignment(vertical="center")
        cell.border = _THIN_BORDER
        if col in num_formats:
            cell.number_format = num_formats[col]


def _title_cell(ws, row_num, text, col_span=1):
    cell = ws.cell(row=row_num, column=1, value=text)
    cell.font = _TITLE_FONT
    if col_span > 1:
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=col_span)


# ── Projections export ────────────────────────────────────────────────────────

@export_bp.route("/projections/export.xlsx")
@login_required
def export_projections():
    uid = current_user.id
    raw_accounts = fetch_all_accounts(uid)
    assumptions  = fetch_assumptions(uid)
    holdings_totals = fetch_holding_totals_by_account(uid)

    accounts = []
    for a in raw_accounts:
        row = dict(a)
        row["current_value"] = effective_account_value(a, holdings_totals)
        accounts.append(row)

    current_age    = current_age_from_assumptions(assumptions) if assumptions else 43
    retirement_age = to_float(assumptions["retirement_age"]) if assumptions else 60
    growth_rate    = to_float(assumptions["annual_growth_rate"]) if assumptions else 0.07
    exact_years    = years_to_retirement(current_age, retirement_age, assumptions) if assumptions else max(retirement_age - current_age, 0)
    whole_years    = int(exact_years)
    total_projected = projected_total_retirement_value(accounts, assumptions)

    wb = Workbook()

    # ── Sheet 1: Summary ──────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Summary"
    _set_col_width(ws, 1, 34)
    _set_col_width(ws, 2, 18)
    _set_col_width(ws, 3, 18)
    _set_col_width(ws, 4, 24)

    _title_cell(ws, 1, "Shelly Finance — Retirement Projections", 4)
    cell = ws.cell(row=2, column=1, value=f"Generated {datetime.now().strftime('%d %b %Y at %H:%M')}")
    cell.font = _SUBTITLE_FONT

    _header_row(ws, 4, ["Account", "Current Value", "Monthly into Pot", "Projected at Retirement"])

    # UK pound formats
    GBP  = '£#,##0.00'
    GBP0 = '£#,##0'

    for i, acc in enumerate(accounts, 5):
        proj = projected_account_value(acc, assumptions)
        effective = effective_monthly_contribution(acc, assumptions)
        _data_row(ws, i, [
            acc["name"],
            to_float(acc["current_value"]),
            effective,
            proj,
        ], num_formats={2: GBP, 3: GBP, 4: GBP0})

    total_row = len(accounts) + 5
    _data_row(ws, total_row, [
        "Total",
        sum(to_float(a["current_value"]) for a in accounts),
        sum(effective_monthly_contribution(a, assumptions) for a in accounts),
        total_projected,
    ], bold=True, num_formats={2: GBP, 3: GBP, 4: GBP0})

    # Fee impact summary (only if any account has fees)
    total_no_fees = sum(projected_account_value_no_fees(a, assumptions) for a in accounts)
    total_fee_impact = total_no_fees - total_projected
    if total_fee_impact > 0:
        r_fee = total_row + 1
        _data_row(ws, r_fee, [
            "Lifetime cost of fees",
            "",
            "",
            total_fee_impact,
        ], bold=True, num_formats={4: GBP0})
        # Colour the fee impact value in a muted red
        ws.cell(row=r_fee, column=4).font = Font(name="Aptos", bold=True, color="DC2626", size=10)
        ws.cell(row=r_fee, column=1).font = Font(name="Aptos", bold=True, color="DC2626", size=10)

    # Assumptions block
    r = (total_row + 3) if total_fee_impact > 0 else (total_row + 2)
    ws.cell(row=r, column=1, value="Assumptions").font = _ACCENT_FONT
    for label, val in [
        ("Current age", int(current_age)),
        ("Retirement age", int(retirement_age)),
        ("Annual growth rate", f"{growth_rate*100:.1f}%"),
        ("Years to retirement", f"{exact_years:.1f}"),
    ]:
        r += 1
        ws.cell(row=r, column=1, value=label).font = _SUBTITLE_FONT
        ws.cell(row=r, column=2, value=val).font = _DATA_FONT

    # ── Sheet 2: Year by year ─────────────────────────────────────────────────
    ws2 = wb.create_sheet("Year by Year")
    _title_cell(ws2, 1, "Shelly Finance — Year-by-Year Projection", 3)
    _header_row(ws2, 3, ["Age", "Year", "Projected Total"])
    _set_col_width(ws2, 1, 10)
    _set_col_width(ws2, 2, 10)
    _set_col_width(ws2, 3, 22)

    curr_year = date.today().year
    for yr in range(0, whole_years + 1):
        age = int(current_age + yr)
        total = sum(
            projected_account_value_at_year(a, assumptions, yr)
            for a in accounts
        )
        yby_year_label = f"{curr_year + yr} (today)" if yr == 0 else curr_year + yr
        _data_row(ws2, yr + 4, [age, yby_year_label, total], num_formats={3: GBP0})

    # Final fractional-year point (matches summary card exactly)
    if exact_years > whole_years:
        final_row = whole_years + 4 + 1
        _data_row(ws2, final_row, [
            int(retirement_age),
            curr_year + whole_years + 1,
            total_projected,
        ], bold=True, num_formats={3: GBP0})

    # ── Sheet 3: Month by month (total portfolio) ────────────────────────────
    ws3 = wb.create_sheet("Month by Month")
    _title_cell(ws3, 1, "Shelly Finance — Monthly Projection", 3)
    _header_row(ws3, 3, ["Month", "Projected Total"])
    _set_col_width(ws3, 1, 16)
    _set_col_width(ws3, 2, 22)

    total_months = int(exact_years * 12)
    today = date.today()
    for m in range(0, total_months + 1):
        month_date = date(today.year + (today.month - 1 + m) // 12,
                          (today.month - 1 + m) % 12 + 1, 1)
        month_label = f"{month_date.strftime('%b %Y')}"
        if m == 0:
            month_label += " (today)"
        total = sum(
            projected_account_value_at_month(a, assumptions, m)
            for a in accounts
        )
        _data_row(ws3, m + 4, [month_label, total], num_formats={2: GBP0})

    # Final row at retirement
    _data_row(ws3, total_months + 5, ["Retirement", total_projected], bold=True, num_formats={2: GBP0})

    # ── Per-account sheets: year-by-year for each account ─────────────────
    for acc in accounts:
        # Sanitise name for Excel sheet title (max 31 chars, no special chars)
        safe_name = acc["name"][:28].replace("/", "-").replace("\\", "-").replace("*", "").replace("?", "").replace("[", "(").replace("]", ")")
        ws_acc = wb.create_sheet(safe_name)

        acc_growth = account_growth_rate(acc, assumptions)
        acc_gross = account_gross_growth_rate(acc, assumptions)
        acc_fee_pct = effective_fee_pct(acc)
        acc_platform_pct = to_float(_safe_get(acc, "platform_fee_pct", 0))
        acc_platform_flat = to_float(_safe_get(acc, "platform_fee_flat", 0))
        acc_platform_cap = to_float(_safe_get(acc, "platform_fee_cap", 0))
        acc_fund_pct = to_float(_safe_get(acc, "fund_fee_pct", 0))
        acc_monthly = effective_monthly_contribution(acc, assumptions)
        acc_current = to_float(acc["current_value"])
        acc_projected = projected_account_value(acc, assumptions)
        acc_projected_no_fees = projected_account_value_no_fees(acc, assumptions)
        acc_fee_impact = acc_projected_no_fees - acc_projected
        acc_breakdown = contribution_breakdown(acc, assumptions)
        has_fees = acc_fee_pct > 0

        _title_cell(ws_acc, 1, f"Shelly Finance — {acc['name']}", 7 if has_fees else 5)
        sub = ws_acc.cell(row=2, column=1, value=f"{acc['wrapper_type']} · {acc.get('provider') or ''}")
        sub.font = _SUBTITLE_FONT

        # Account summary
        _header_row(ws_acc, 4, ["", "Value"])
        _set_col_width(ws_acc, 1, 28)
        _set_col_width(ws_acc, 2, 18)
        summary_rows = [
            ("Current value", acc_current, GBP),
            ("You pay (monthly)", acc_breakdown["personal"], GBP),
            ("Total into pot (monthly)", acc_monthly, GBP),
            ("Growth rate (net of fees)", f"{acc_growth*100:.1f}%", None),
        ]
        if has_fees:
            summary_rows.append(("Growth rate (gross)", f"{acc_gross*100:.1f}%", None))
            # Show granular fee breakdown if available
            if acc_platform_pct > 0:
                cap_note = f" (capped £{acc_platform_cap:,.0f}/yr)" if acc_platform_cap > 0 else ""
                summary_rows.append(("Platform fee", f"{acc_platform_pct:.2f}%{cap_note}", None))
            if acc_platform_flat > 0:
                summary_rows.append(("Platform fee (flat)", f"£{acc_platform_flat:,.0f}/yr", None))
            if acc_fund_pct > 0:
                summary_rows.append(("Fund fee (OCF)", f"{acc_fund_pct:.2f}%", None))
            summary_rows.append(("Total effective fee", f"{acc_fee_pct:.2f}%", None))
        summary_rows.append(("Projected at retirement", acc_projected, GBP0))
        if has_fees:
            summary_rows.append(("Value without fees", acc_projected_no_fees, GBP0))
            summary_rows.append(("Lifetime cost of fees", acc_fee_impact, GBP0))

        for ri, (label, val, fmt) in enumerate(summary_rows, 5):
            _data_row(ws_acc, ri, [label, val], num_formats={2: fmt} if fmt else {})

        # Year-by-year table
        yby_start = 5 + len(summary_rows) + 1
        if has_fees:
            _header_row(ws_acc, yby_start, ["Age", "Year", "Projected Value", "Growth", "Contributions", "Value (no fees)", "Fee Impact"])
            _set_col_width(ws_acc, 6, 22)
            _set_col_width(ws_acc, 7, 18)
        else:
            _header_row(ws_acc, yby_start, ["Age", "Year", "Projected Value", "Growth", "Contributions"])
        _set_col_width(ws_acc, 3, 22)
        _set_col_width(ws_acc, 4, 18)
        _set_col_width(ws_acc, 5, 18)

        is_lisa = acc.get("wrapper_type") == "Lifetime ISA"
        prev_val = acc_current
        for yr in range(0, whole_years + 1):
            age = int(current_age + yr)
            val = projected_account_value_at_year(acc, assumptions, yr)
            # LISA contributions stop at age 50
            if yr == 0:
                contrib_this_year = 0
            elif is_lisa and (current_age + yr) > 50:
                contrib_this_year = 0
            else:
                contrib_this_year = acc_monthly * 12
            growth_this_year = (val - prev_val - contrib_this_year) if yr > 0 else 0
            year_label = f"{curr_year + yr} (today)" if yr == 0 else curr_year + yr
            if has_fees:
                val_no_fees = projected_account_value_at_year_no_fees(acc, assumptions, yr)
                fee_impact_yr = val_no_fees - val
                _data_row(ws_acc, yby_start + 1 + yr, [
                    age, year_label, val, growth_this_year, contrib_this_year, val_no_fees, fee_impact_yr,
                ], num_formats={3: GBP0, 4: GBP0, 5: GBP0, 6: GBP0, 7: GBP0})
            else:
                _data_row(ws_acc, yby_start + 1 + yr, [
                    age, year_label, val, growth_this_year, contrib_this_year,
                ], num_formats={3: GBP0, 4: GBP0, 5: GBP0})
            prev_val = val

        # Final fractional-year row
        if exact_years > whole_years:
            final_r = yby_start + 1 + whole_years + 1
            if has_fees:
                _data_row(ws_acc, final_r, [
                    int(retirement_age),
                    curr_year + whole_years + 1,
                    acc_projected,
                    "", "",
                    acc_projected_no_fees,
                    acc_fee_impact,
                ], bold=True, num_formats={3: GBP0, 6: GBP0, 7: GBP0})
            else:
                _data_row(ws_acc, final_r, [
                    int(retirement_age),
                    curr_year + whole_years + 1,
                    acc_projected,
                    "", "",
                ], bold=True, num_formats={3: GBP0})

        # ── Monthly breakdown table ──────────────────────────────────
        yearly_end = yby_start + 1 + whole_years + (2 if exact_years > whole_years else 1)
        mby_start = yearly_end + 2  # gap of 1 empty row

        if has_fees:
            _header_row(ws_acc, mby_start, ["Month", "Projected Value", "Value (no fees)", "Fee Impact"])
        else:
            _header_row(ws_acc, mby_start, ["Month", "Projected Value"])

        acc_total_months = int(exact_years * 12)
        for m in range(0, acc_total_months + 1):
            m_date = date(today.year + (today.month - 1 + m) // 12,
                          (today.month - 1 + m) % 12 + 1, 1)
            m_label = f"{m_date.strftime('%b %Y')}"
            if m == 0:
                m_label += " (today)"
            m_val = projected_account_value_at_month(acc, assumptions, m)
            if has_fees:
                m_val_nf = projected_account_value_at_month_no_fees(acc, assumptions, m)
                _data_row(ws_acc, mby_start + 1 + m, [
                    m_label, m_val, m_val_nf, m_val_nf - m_val,
                ], num_formats={2: GBP0, 3: GBP0, 4: GBP0})
            else:
                _data_row(ws_acc, mby_start + 1 + m, [
                    m_label, m_val,
                ], num_formats={2: GBP0})

        # Final retirement row
        m_final_r = mby_start + 1 + acc_total_months + 1
        if has_fees:
            _data_row(ws_acc, m_final_r, [
                "Retirement", acc_projected, acc_projected_no_fees, acc_fee_impact,
            ], bold=True, num_formats={2: GBP0, 3: GBP0, 4: GBP0})
        else:
            _data_row(ws_acc, m_final_r, [
                "Retirement", acc_projected,
            ], bold=True, num_formats={2: GBP0})

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"projections_{date.today().isoformat()}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Budget export ─────────────────────────────────────────────────────────────

@export_bp.route("/budget/export.xlsx")
@login_required
def export_budget():
    uid = current_user.id
    month_key = request.args.get("month") or date.today().strftime("%Y-%m")
    month_label = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")

    db_sections = fetch_budget_sections(uid)
    items       = fetch_budget_items(uid)
    entries     = fetch_budget_entries(month_key, uid)
    entry_map   = {e["budget_item_id"]: e for e in entries}

    if not entry_map:
        prior = fetch_prior_month_budget_entries(month_key, uid)
        entry_map = {e["budget_item_id"]: e for e in prior}

    wb = Workbook()
    ws = wb.active
    ws.title = f"Budget {month_key}"
    _set_col_width(ws, 1, 30)
    _set_col_width(ws, 2, 20)
    _set_col_width(ws, 3, 16)

    _title_cell(ws, 1, f"Shelly Finance — Budget for {month_label}", 3)
    cell = ws.cell(row=2, column=1, value=f"Generated {datetime.now().strftime('%d %b %Y at %H:%M')}")
    cell.font = _SUBTITLE_FONT

    GBP = '£#,##0.00'
    row = 4
    income_key = db_sections[0]["key"] if db_sections else "income"
    section_totals = {}

    for sec in db_sections:
        section_items = [it for it in items if it["section"] == sec["key"]]
        if not section_items:
            continue

        # Section header
        _header_row(ws, row, [sec["label"], "", "Amount"])
        row += 1

        sec_total = 0.0
        for item in section_items:
            amount = float(entry_map[item["id"]]["amount"]) if item["id"] in entry_map else float(item["default_amount"] or 0)
            _data_row(ws, row, [item["name"], item["notes"] or "", amount], num_formats={3: GBP})
            sec_total += amount
            row += 1

        _data_row(ws, row, ["", "Section total", sec_total], bold=True, num_formats={3: GBP})
        section_totals[sec["key"]] = sec_total
        row += 2

    # Summary block
    total_income   = section_totals.get(income_key, 0)
    total_expenses = sum(v for k, v in section_totals.items() if k != income_key)
    surplus        = total_income - total_expenses

    for label, val in [("Total Income", total_income), ("Total Expenses", total_expenses), ("Surplus", surplus)]:
        _data_row(ws, row, [label, "", val], bold=(label == "Surplus"), num_formats={3: GBP})
        row += 1

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"budget_{month_key}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Performance export ────────────────────────────────────────────────────────

@export_bp.route("/performance/export.xlsx")
@login_required
def export_performance():
    uid = current_user.id
    assumptions = fetch_assumptions(uid)
    accounts = fetch_all_accounts(uid)
    account_id = request.args.get("account_id")

    assumed_rate = to_float(assumptions["annual_growth_rate"]) if assumptions else 0.07
    assumed_monthly_total = sum(to_float(a["monthly_contribution"]) for a in accounts)

    per_account_data = fetch_monthly_performance_data_by_account(uid)
    account_map = {int(a["id"]): a for a in accounts}

    selected_account_id = None
    if account_id:
        try:
            selected_account_id = int(account_id)
        except Exception:
            selected_account_id = None
        if selected_account_id not in account_map:
            selected_account_id = None

    perf_portfolio = None
    if selected_account_id is None:
        monthly_data = fetch_monthly_performance_data(uid)
        perf_portfolio = compute_performance_series(monthly_data, assumed_rate, assumed_monthly_total)

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    _set_col_width(ws, 1, 26)
    _set_col_width(ws, 2, 12)
    _set_col_width(ws, 3, 12)
    _set_col_width(ws, 4, 14)
    _set_col_width(ws, 5, 16)
    _set_col_width(ws, 6, 16)
    _set_col_width(ws, 7, 16)
    _set_col_width(ws, 8, 16)
    _set_col_width(ws, 9, 16)
    _set_col_width(ws, 10, 18)

    _title_cell(ws, 1, "Shelly Finance — Performance Report", 10)
    cell = ws.cell(row=2, column=1, value=f"Generated {datetime.now().strftime('%d %b %Y at %H:%M')}")
    cell.font = _SUBTITLE_FONT

    _header_row(ws, 4, [
        "Entity",
        "Start",
        "End",
        "Months",
        "Total Return",
        "Annualised",
        "Contributed",
        "Market Gain",
        "Vs Plan",
        "Current Value",
    ])

    GBP = '£#,##0.00'
    PCT = '0.00"%"'
    row = 5

    def _append_summary(entity_name, perf):
        nonlocal row
        if not perf:
            _data_row(ws, row, [entity_name, "", "", 0, "", "", "", "", "", ""], bold=True)
            row += 1
            return
        labels = perf.get("labels") or []
        start_m = labels[0] if labels else ""
        end_m = labels[-1] if labels else ""
        _data_row(ws, row, [
            entity_name,
            start_m,
            end_m,
            int(perf.get("n_months") or 0),
            float(perf.get("total_return") or 0),
            float(perf.get("annualised_return") or 0) if perf.get("annualised_return") is not None else None,
            float(perf.get("total_contributed") or 0),
            float(perf.get("total_market_gain") or 0),
            float(perf.get("vs_plan") or 0),
            float(perf.get("current_value") or 0),
        ], bold=True, num_formats={5: PCT, 6: PCT, 7: GBP, 8: GBP, 9: GBP, 10: GBP})
        row += 1

    if selected_account_id is None:
        _append_summary("Portfolio", perf_portfolio)

        for aid, payload in per_account_data.items():
            acc = account_map.get(aid)
            if not acc:
                continue
            assumed_monthly = to_float(acc.get("monthly_contribution", 0))
            perf_acc = compute_performance_series(payload["rows"], assumed_rate, assumed_monthly)
            _append_summary(payload["account_name"], perf_acc)
    else:
        payload = per_account_data.get(selected_account_id, {"account_name": account_map[selected_account_id]["name"], "rows": []})
        acc = account_map[selected_account_id]
        assumed_monthly = to_float(acc.get("monthly_contribution", 0))
        perf_acc = compute_performance_series(payload["rows"], assumed_rate, assumed_monthly)
        _append_summary(payload["account_name"], perf_acc)

    def _safe_sheet_title(base, used):
        s = (base or "Sheet").strip()
        s = "".join("-" if ch in (":", "\\", "/", "?", "*", "[", "]") else ch for ch in s)
        s = s.strip().strip("'")[:31]
        if not s:
            s = "Sheet"
        if s not in used:
            used.add(s)
            return s
        i = 2
        while True:
            suffix = f" {i}"
            candidate = (s[:31 - len(suffix)] + suffix)[:31]
            if candidate not in used:
                used.add(candidate)
                return candidate
            i += 1

    used_titles = {ws.title}

    def _add_detail_sheet(title, perf):
        ws_d = wb.create_sheet(_safe_sheet_title(title, used_titles))
        _set_col_width(ws_d, 1, 10)
        _set_col_width(ws_d, 2, 16)
        _set_col_width(ws_d, 3, 16)
        _set_col_width(ws_d, 4, 18)
        _set_col_width(ws_d, 5, 16)
        _set_col_width(ws_d, 6, 12)

        _title_cell(ws_d, 1, f"Shelly Finance — {title}", 6)
        sub = ws_d.cell(row=2, column=1, value=f"Assumed growth: {assumed_rate*100:.1f}%")
        sub.font = _SUBTITLE_FONT

        if not perf or not perf.get("table_rows"):
            ws_d.cell(row=4, column=1, value="Not enough data yet (need at least two monthly snapshots).").font = _DATA_FONT
            return

        _header_row(ws_d, 4, ["Month", "Opening", "Contributions", "Market Gain / Loss", "Closing", "Return"])
        rows_chrono = list(reversed(perf["table_rows"]))
        for i, r in enumerate(rows_chrono, 5):
            _data_row(ws_d, i, [
                r["month_key"],
                float(r["opening"]),
                float(r["contribution"]),
                float(r["market_gain"]),
                float(r["closing"]),
                float(r["return_pct"]),
            ], num_formats={2: GBP, 3: GBP, 4: GBP, 5: GBP, 6: PCT})

    if selected_account_id is None:
        _add_detail_sheet("Portfolio (Monthly)", perf_portfolio)

        for aid, payload in per_account_data.items():
            acc = account_map.get(aid)
            if not acc:
                continue
            assumed_monthly = to_float(acc.get("monthly_contribution", 0))
            perf_acc = compute_performance_series(payload["rows"], assumed_rate, assumed_monthly)
            _add_detail_sheet(f"{payload['account_name']} (Monthly)", perf_acc)
    else:
        payload = per_account_data.get(selected_account_id, {"account_name": account_map[selected_account_id]["name"], "rows": []})
        acc = account_map[selected_account_id]
        assumed_monthly = to_float(acc.get("monthly_contribution", 0))
        perf_acc = compute_performance_series(payload["rows"], assumed_rate, assumed_monthly)
        _add_detail_sheet(f"{payload['account_name']} (Monthly)", perf_acc)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    if selected_account_id is None:
        fname = f"performance_{date.today().isoformat()}.xlsx"
    else:
        safe = "".join(ch for ch in (account_map[selected_account_id]["name"] or "account") if ch.isalnum() or ch in (" ", "-", "_")).strip().replace(" ", "_")
        fname = f"performance_{safe}_{date.today().isoformat()}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
