from datetime import date, datetime, timedelta


def age_from_dob(dob_str, today=None):
    """Calculate current age in fractional years from a date-of-birth string (YYYY-MM-DD).

    Falls back to 0 if the DOB is missing or unparseable.
    """
    if not dob_str:
        return 0.0
    today = today or date.today()
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 0.0
    age_years = today.year - dob.year
    # Subtract 1 if birthday hasn't happened yet this year
    if (today.month, today.day) < (dob.month, dob.day):
        age_years -= 1
    # Add fractional part for months
    months_since_birthday = (today.month - dob.month) % 12
    if today.day < dob.day:
        months_since_birthday = max(months_since_birthday - 1, 0)
    return age_years + months_since_birthday / 12.0


def current_age_from_assumptions(assumptions):
    """Get the user's current age, preferring date_of_birth over legacy current_age."""
    if not assumptions:
        return 0.0
    dob = assumptions.get("date_of_birth") if hasattr(assumptions, 'get') else (assumptions["date_of_birth"] if "date_of_birth" in assumptions.keys() else None)
    if dob:
        return age_from_dob(dob)
    # Legacy fallback
    return to_float(assumptions.get("current_age") if hasattr(assumptions, 'get') else assumptions["current_age"])


TAX_BAND_RATES = {"basic": 0.20, "higher": 0.40, "additional": 0.45}
LISA_ANNUAL_CAP = 4000  # Max personal contribution per tax year
LISA_BONUS_RATE = 0.25


def contribution_breakdown(account, assumptions=None):
    """Calculate the full contribution breakdown for an account.

    Returns a dict:
        personal        — what you pay each month (from your bank / salary)
        tax_relief      — basic-rate relief added by provider (SIPP / relief-at-source pension)
        government_bonus— LISA 25% bonus
        employer        — employer contribution (workplace pension)
        total_into_pot  — the amount actually going into the account each month
        self_assessment — additional relief reclaimable by higher/additional-rate taxpayers
        method_label    — human-readable description of the method
    """
    personal = to_float(account.get("monthly_contribution") if hasattr(account, 'get') else account["monthly_contribution"])
    employer = to_float(account.get("employer_contribution") if hasattr(account, 'get') else (account["employer_contribution"] if "employer_contribution" in account.keys() else 0))
    wrapper = (account.get("wrapper_type") if hasattr(account, 'get') else account["wrapper_type"]) or ""
    method = (account.get("contribution_method") if hasattr(account, 'get') else (account["contribution_method"] if "contribution_method" in account.keys() else "standard")) or "standard"

    tax_band = "basic"
    if assumptions:
        tax_band = (assumptions.get("tax_band") if hasattr(assumptions, 'get') else (assumptions["tax_band"] if "tax_band" in assumptions.keys() else "basic")) or "basic"

    tax_relief = 0.0
    government_bonus = 0.0
    self_assessment = 0.0
    method_label = ""

    is_sipp = "SIPP" in wrapper
    is_workplace = "Workplace" in wrapper or "workplace" in wrapper
    is_lisa = "Lifetime" in wrapper or "LISA" in wrapper
    is_pension = is_sipp or is_workplace

    if is_sipp:
        # SIPP: always relief at source. You pay net, provider claims basic rate.
        # Gross = personal / 0.80 = personal * 1.25
        tax_relief = personal * 0.25  # 25% of your net payment
        method_label = "Relief at source"
        # Higher/additional-rate taxpayers can reclaim the difference via self-assessment
        band_rate = TAX_BAND_RATES.get(tax_band, 0.20)
        if band_rate > 0.20:
            gross = personal + tax_relief  # what's in the pension
            self_assessment = gross * (band_rate - 0.20)  # goes to YOU, not the pension

    elif is_workplace:
        if method == "salary_sacrifice":
            # Salary sacrifice: contributions are pre-tax, no relief needed
            # personal = your gross contribution, employer = their contribution
            tax_relief = 0
            method_label = "Salary sacrifice"
        else:
            # Relief at source (NEST-style): you pay net, provider claims 20%
            tax_relief = personal * 0.25
            method_label = "Relief at source"
            band_rate = TAX_BAND_RATES.get(tax_band, 0.20)
            if band_rate > 0.20:
                gross = personal + tax_relief
                self_assessment = gross * (band_rate - 0.20)

    elif is_lisa:
        # 25% government bonus, capped at £4,000/year personal contributions
        annual_personal = personal * 12
        eligible = min(annual_personal, LISA_ANNUAL_CAP)
        government_bonus = (eligible * LISA_BONUS_RATE) / 12  # monthly equivalent
        method_label = "Government bonus (25%)"

    total_into_pot = personal + tax_relief + government_bonus + employer

    return {
        "personal": personal,
        "tax_relief": tax_relief,
        "government_bonus": government_bonus,
        "employer": employer,
        "total_into_pot": total_into_pot,
        "self_assessment": self_assessment,
        "method_label": method_label,
    }


def effective_monthly_contribution(account, assumptions=None):
    """Return the total amount going into the account pot each month,
    including tax relief, government bonuses, and employer contributions."""
    return contribution_breakdown(account, assumptions)["total_into_pot"]


def future_value(current_value, monthly_contribution, annual_growth_rate, years):
    monthly_rate = annual_growth_rate / 12
    months = int(years * 12)

    future_current = current_value * ((1 + monthly_rate) ** months)

    if monthly_rate == 0:
        future_contrib = monthly_contribution * months
    else:
        future_contrib = monthly_contribution * (((1 + monthly_rate) ** months - 1) / monthly_rate)

    return future_current + future_contrib


def to_float(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def effective_account_value(account, holdings_totals=None):
    """Return the value of the account based on its valuation mode and uninvested cash."""
    holdings_totals = holdings_totals or {}
    uninvested = to_float(account.get("uninvested_cash", 0) if hasattr(account, 'get') else (account["uninvested_cash"] if "uninvested_cash" in account.keys() else 0))
    if account["valuation_mode"] == "holdings":
        return to_float(holdings_totals.get(account["id"], 0)) + uninvested
    return to_float(account["current_value"]) + uninvested


def total_invested(accounts, holdings_totals=None):
    return sum(effective_account_value(a, holdings_totals) for a in accounts)



def tag_totals(accounts, holdings_totals=None):
    totals = {}
    for account in accounts:
        tags = [t.strip() for t in (account["tags"] or "").split(",") if t.strip()]
        value = effective_account_value(account, holdings_totals)
        for tag in tags:
            totals[tag] = totals.get(tag, 0.0) + value
    return totals


def total_monthly_contributions(accounts):
    return sum(to_float(a["monthly_contribution"]) for a in accounts)


def retirement_target_date(dob_str, retirement_age, mode="birthday"):
    """Calculate the exact retirement date based on the chosen mode.

    Modes:
        birthday       — retire on the day you turn retirement_age
        end_of_year    — retire on 31 Dec of the year you turn retirement_age
        end_of_tax_year — retire on 5 Apr following the tax year you turn retirement_age
    """
    if not dob_str:
        return None
    try:
        dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    retire_year = dob.year + int(retirement_age)
    if mode == "end_of_year":
        return date(retire_year, 12, 31)
    elif mode == "end_of_tax_year":
        # UK tax year ends 5 April. If birthday is before 6 April,
        # you turn retirement_age in the current tax year (ending 5 Apr that year).
        # Otherwise you turn retirement_age in the *next* tax year (ending 5 Apr next year).
        if (dob.month, dob.day) < (4, 6):
            return date(retire_year, 4, 5)
        else:
            return date(retire_year + 1, 4, 5)
    else:  # birthday
        return date(retire_year, dob.month, dob.day)


def years_to_retirement(current_age, retirement_age, assumptions=None):
    """Return years remaining to retirement.

    If assumptions with DOB and retirement_date_mode are available, uses
    an exact date calculation. Otherwise falls back to simple subtraction.
    """
    if assumptions:
        dob = assumptions.get("date_of_birth") if hasattr(assumptions, 'get') else None
        mode = assumptions.get("retirement_date_mode", "birthday") if hasattr(assumptions, 'get') else "birthday"
        if dob:
            target = retirement_target_date(dob, retirement_age, mode)
            if target:
                today = date.today()
                delta = target - today
                return max(delta.days / 365.25, 0)
    return max(retirement_age - current_age, 0)


def _safe_get(account, key, default=0):
    """Safely get a value from a dict-like account row."""
    if hasattr(account, 'get'):
        return account.get(key, default)
    try:
        return account[key] if key in account.keys() else default
    except Exception:
        return default


def effective_fee_pct(account):
    """Compute the total effective annual fee as a percentage.

    Combines platform fee and fund fee into a single figure.
    Platform fees can be a percentage (e.g. 0.15 for 0.15%), a flat annual £
    amount (converted to an approximate % based on current value), or both.
    If a platform fee cap is set, the percentage-based platform fee is capped
    at that £ amount relative to the current value.

    Returns fee as a percentage value (e.g. 0.37 means 0.37%).
    """
    platform_pct = to_float(_safe_get(account, "platform_fee_pct", 0))
    platform_flat = to_float(_safe_get(account, "platform_fee_flat", 0))
    platform_cap = to_float(_safe_get(account, "platform_fee_cap", 0))
    fund_pct = to_float(_safe_get(account, "fund_fee_pct", 0))

    # If no granular fees are set, fall back to legacy annual_fee_pct
    if platform_pct == 0 and platform_flat == 0 and fund_pct == 0:
        return to_float(_safe_get(account, "annual_fee_pct", 0))

    current_value = to_float(_safe_get(account, "current_value", 0))

    # Platform fee: percentage-based, possibly capped
    if platform_pct > 0 and platform_cap > 0 and current_value > 0:
        # The cap limits the £ amount charged; convert cap to equivalent %
        pct_cost = current_value * (platform_pct / 100.0)
        actual_cost = min(pct_cost, platform_cap)
        effective_platform_pct = (actual_cost / current_value) * 100.0
    else:
        effective_platform_pct = platform_pct

    # Platform fee: flat annual amount converted to approximate %
    # When current_value is 0, flat fees can't be expressed as a %; they're
    # ignored until the account has a balance (avoids division by zero).
    if platform_flat > 0 and current_value > 0:
        effective_platform_pct += (platform_flat / current_value) * 100.0

    # Cap at a reasonable maximum to avoid nonsensical projections
    total = min(effective_platform_pct + fund_pct, 25.0)
    return total


def account_growth_rate(account, assumptions):
    """Return the effective annual growth rate for an account, net of fees.

    Uses the granular fee fields (platform_fee_pct, platform_fee_flat,
    platform_fee_cap, fund_fee_pct) when available, falling back to the
    legacy annual_fee_pct column.
    """
    if account["growth_mode"] == "custom" and account["growth_rate_override"] is not None:
        gross = to_float(account["growth_rate_override"])
    else:
        gross = to_float(assumptions["annual_growth_rate"]) if assumptions else 0.0
    fee = effective_fee_pct(account)
    return max(gross - fee / 100.0, 0.0)


def account_gross_growth_rate(account, assumptions):
    """Return the gross annual growth rate (before fees) for display purposes."""
    if account["growth_mode"] == "custom" and account["growth_rate_override"] is not None:
        return to_float(account["growth_rate_override"])
    return to_float(assumptions["annual_growth_rate"]) if assumptions else 0.0


def projected_account_value_at_year(account, assumptions, yr):
    """Project account value at `yr` years from now, respecting LISA contribution cap at 50."""
    current = to_float(account["current_value"])
    monthly = effective_monthly_contribution(account, assumptions)
    growth = account_growth_rate(account, assumptions)
    current_age = current_age_from_assumptions(assumptions)

    if account["wrapper_type"] == "Lifetime ISA":
        contrib_years = max(min(yr, 50 - current_age), 0)
        frozen_years = yr - contrib_years
        value_at_cap = future_value(current, monthly, growth, contrib_years)
        return future_value(value_at_cap, 0, growth, frozen_years)

    return future_value(current, monthly, growth, yr)


def projected_account_value_at_month(account, assumptions, month_count):
    """Project account value at `month_count` months from now.

    Like projected_account_value_at_year but with month precision.
    Respects LISA contribution cap at age 50.
    """
    years = month_count / 12.0
    current = to_float(account["current_value"])
    monthly = effective_monthly_contribution(account, assumptions)
    growth = account_growth_rate(account, assumptions)
    current_age = current_age_from_assumptions(assumptions)

    if account["wrapper_type"] == "Lifetime ISA":
        contrib_years = max(min(years, 50 - current_age), 0)
        frozen_years = years - contrib_years
        value_at_cap = future_value(current, monthly, growth, contrib_years)
        return future_value(value_at_cap, 0, growth, frozen_years)

    return future_value(current, monthly, growth, years)


def projected_account_value_at_month_no_fees(account, assumptions, month_count):
    """Same as projected_account_value_at_month but using gross growth rate."""
    years = month_count / 12.0
    current = to_float(account["current_value"])
    monthly = effective_monthly_contribution(account, assumptions)
    gross = account_gross_growth_rate(account, assumptions)
    current_age = current_age_from_assumptions(assumptions)

    if account["wrapper_type"] == "Lifetime ISA":
        contrib_years = max(min(years, 50 - current_age), 0)
        frozen_years = years - contrib_years
        value_at_cap = future_value(current, monthly, gross, contrib_years)
        return future_value(value_at_cap, 0, gross, frozen_years)

    return future_value(current, monthly, gross, years)


def projected_account_value(account, assumptions):
    if not assumptions:
        return 0.0

    current = to_float(account["current_value"])
    monthly = effective_monthly_contribution(account, assumptions)
    growth = account_growth_rate(account, assumptions)
    current_age = current_age_from_assumptions(assumptions)
    retirement_age = to_float(assumptions["retirement_age"])
    total_years = years_to_retirement(current_age, retirement_age, assumptions)

    if account["wrapper_type"] == "Lifetime ISA":
        contribution_end_age = min(50, retirement_age)
        contribution_years = max(contribution_end_age - current_age, 0)
        frozen_years = max(retirement_age - contribution_end_age, 0)

        value_at_contribution_end = future_value(current, monthly, growth, contribution_years)
        return future_value(value_at_contribution_end, 0, growth, frozen_years)

    return future_value(current, monthly, growth, total_years)


def projected_account_value_no_fees(account, assumptions):
    """Same as projected_account_value but using the gross growth rate (ignoring fees).

    The difference between this and projected_account_value is the lifetime cost of fees.
    """
    if not assumptions:
        return 0.0

    current = to_float(account["current_value"])
    monthly = effective_monthly_contribution(account, assumptions)
    gross = account_gross_growth_rate(account, assumptions)
    current_age = current_age_from_assumptions(assumptions)
    retirement_age = to_float(assumptions["retirement_age"])
    total_years = years_to_retirement(current_age, retirement_age, assumptions)

    if account["wrapper_type"] == "Lifetime ISA":
        contribution_end_age = min(50, retirement_age)
        contribution_years = max(contribution_end_age - current_age, 0)
        frozen_years = max(retirement_age - contribution_end_age, 0)
        value_at_contribution_end = future_value(current, monthly, gross, contribution_years)
        return future_value(value_at_contribution_end, 0, gross, frozen_years)

    return future_value(current, monthly, gross, total_years)


def projected_account_value_at_year_no_fees(account, assumptions, yr):
    """Same as projected_account_value_at_year but using gross growth rate."""
    current = to_float(account["current_value"])
    monthly = effective_monthly_contribution(account, assumptions)
    gross = account_gross_growth_rate(account, assumptions)
    current_age = current_age_from_assumptions(assumptions)

    if account["wrapper_type"] == "Lifetime ISA":
        contrib_years = max(min(yr, 50 - current_age), 0)
        frozen_years = yr - contrib_years
        value_at_cap = future_value(current, monthly, gross, contrib_years)
        return future_value(value_at_cap, 0, gross, frozen_years)

    return future_value(current, monthly, gross, yr)


def projected_total_retirement_value(accounts, assumptions):
    if not assumptions:
        return 0.0
    return sum(projected_account_value(account, assumptions) for account in accounts)


def projected_accounts(accounts, assumptions):
    if not assumptions:
        return []
    rows = []
    for account in accounts:
        current = to_float(account["current_value"])
        personal = to_float(account["monthly_contribution"])
        growth = account_growth_rate(account, assumptions)
        projected = projected_account_value(account, assumptions)
        proj_no_fees = projected_account_value_no_fees(account, assumptions)
        breakdown = contribution_breakdown(account, assumptions)
        rows.append({
            "name": account["name"],
            "provider": account["provider"],
            "wrapper_type": account["wrapper_type"],
            "current_value": current,
            "monthly_contribution": personal,
            "effective_contribution": breakdown["total_into_pot"],
            "tax_relief": breakdown["tax_relief"],
            "government_bonus": breakdown["government_bonus"],
            "employer": breakdown["employer"],
            "self_assessment": breakdown["self_assessment"],
            "method_label": breakdown["method_label"],
            "projected_value": projected,
            "growth_rate": growth,
            "gross_growth_rate": account_gross_growth_rate(account, assumptions),
            "annual_fee_pct": effective_fee_pct(account),
            "platform_fee_pct": to_float(_safe_get(account, "platform_fee_pct", 0)),
            "platform_fee_flat": to_float(_safe_get(account, "platform_fee_flat", 0)),
            "platform_fee_cap": to_float(_safe_get(account, "platform_fee_cap", 0)),
            "fund_fee_pct": to_float(_safe_get(account, "fund_fee_pct", 0)),
            "growth_mode": account["growth_mode"],
            "projected_no_fees": proj_no_fees,
            "fee_impact": proj_no_fees - projected,
        })
    return rows


def compute_performance_series(monthly_data, assumed_rate, assumed_monthly):
    """Compute actual vs projected performance from monthly snapshot data.

    Args:
        monthly_data: list of (month_key, total_balance, total_contribution)
        assumed_rate: annual growth rate assumption (e.g. 0.07)
        assumed_monthly: current total monthly contribution

    Returns a dict ready to pass to the performance template, or None if no data.

    The benchmark_values key is intentionally None — it exists as a slot for a
    future benchmark data source (API or manual entry) without template changes.
    """
    if not monthly_data:
        return None

    month_keys   = [m[0] for m in monthly_data]
    balances     = [m[1] for m in monthly_data]
    contribs     = [m[2] for m in monthly_data]

    # ── Modified Dietz monthly returns ────────────────────────────────────
    # Assumes contributions arrive mid-month (weight = 0.5)
    monthly_returns = []
    for i in range(1, len(monthly_data)):
        start = balances[i - 1]
        end   = balances[i]
        cf    = contribs[i]
        denom = start + 0.5 * cf
        monthly_returns.append((end - start - cf) / denom if denom > 0 else 0.0)

    # ── Chain-linked cumulative & annualised return ────────────────────────
    cum = 1.0
    for r in monthly_returns:
        cum *= (1 + r)
    total_return = cum - 1.0
    n = len(monthly_returns)
    annualised_return = ((cum ** (12.0 / n)) - 1) if n > 0 else None

    # ── Projected "on plan" series from first recorded balance ────────────
    # Shows what the portfolio would be worth at the assumed rate + assumed
    # monthly contribution, starting from the same base as the first snapshot.
    start_balance = balances[0]
    projected_values = [
        round(future_value(start_balance, assumed_monthly, assumed_rate, i / 12.0), 0)
        for i in range(len(monthly_data))
    ]

    # ── Month-by-month breakdown table ────────────────────────────────────
    rows = []
    for i in range(1, len(monthly_data)):
        opening = balances[i - 1]
        closing = balances[i]
        cf      = contribs[i]
        gain    = closing - opening - cf
        r       = monthly_returns[i - 1]
        rows.append({
            "month_key":    month_keys[i],
            "opening":      round(opening, 2),
            "contribution": round(cf, 2),
            "market_gain":  round(gain, 2),
            "closing":      round(closing, 2),
            "return_pct":   round(r * 100, 2),
        })
    rows.reverse()   # most recent first

    # ── Totals for summary cards ──────────────────────────────────────────
    total_contributed = sum(contribs[1:])   # exclude opening balance month
    total_market_gain = balances[-1] - balances[0] - total_contributed
    vs_plan = balances[-1] - projected_values[-1] if projected_values else 0

    return {
        "labels":            month_keys,
        "actual_values":     [round(b, 0) for b in balances],
        "projected_values":  projected_values,
        "benchmark_values":  None,       # slot for future benchmark data
        "monthly_returns":   monthly_returns,
        "table_rows":        rows,
        "n_months":          n,
        "total_return":      round(total_return * 100, 2),
        "annualised_return": round(annualised_return * 100, 2) if annualised_return is not None else None,
        "total_contributed": round(total_contributed, 2),
        "total_market_gain": round(total_market_gain, 2),
        "vs_plan":           round(vs_plan, 2),
        "current_value":     round(balances[-1], 2) if balances else 0,
    }


def progress_to_goal(current, target):
    if not target:
        return 0.0
    return current / target


def remaining_to_goal(current, target):
    return max(target - current, 0)


def allowance_progress(used, allowance):
    if not allowance:
        return 0.0
    return used / allowance


def uk_tax_year_label(today=None):
    today = today or date.today()
    start_year = today.year if (today.month > 4 or (today.month == 4 and today.day >= 6)) else today.year - 1
    end_year = start_year + 1
    return f"{start_year}/{str(end_year)[-2:]}"


def uk_tax_year_end(today=None):
    today = today or date.today()
    end_year = today.year + 1 if (today.month > 4 or (today.month == 4 and today.day >= 6)) else today.year
    return date(end_year, 4, 5)


def days_until_tax_year_end(today=None):
    today = today or date.today()
    return max((uk_tax_year_end(today) - today).days, 0)


def uk_tax_year_start(today=None):
    """Return the start date (April 6) of the current UK tax year."""
    today = today or date.today()
    start_year = today.year if (today.month > 4 or (today.month == 4 and today.day >= 6)) else today.year - 1
    return date(start_year, 4, 6)


def months_in_tax_year(today=None, salary_day=0):
    """Return the number of monthly ISA contributions that have gone through
    in the current UK tax year.

    salary_day: day of month when salary/contributions go in (1-28).
        If >= 6: April's contribution falls in the new tax year.
        If < 6 (or 0/unset): April's contribution is in the OLD tax year,
        so the first new-year contribution is May.
        Also, the current month only counts if salary_day has passed.

    E.g. salary_day=15, today=9 Apr 2026 → 0 (April contribution hasn't
    gone through yet).
    salary_day=1, today=9 Apr 2026 → 0 (April 1 was still old tax year).
    salary_day=10, today=15 Apr 2026 → 1 (April 10 is new tax year & has passed).
    """
    today = today or date.today()
    start = uk_tax_year_start(today)
    contribution_day = salary_day if salary_day >= 1 else 1

    # Determine the first month whose contribution belongs to this tax year
    if contribution_day >= 6:
        first_year, first_month = start.year, start.month  # April
    else:
        # Contribution on 1st-5th April belongs to OLD tax year → starts May
        first_year = start.year
        first_month = start.month + 1
        if first_month > 12:
            first_month = 1
            first_year += 1

    count = 0
    y, m = first_year, first_month
    while (y < today.year) or (y == today.year and m <= today.month):
        if y < today.year or (y == today.year and m < today.month):
            # Past month — contribution definitely happened
            count += 1
        elif y == today.year and m == today.month:
            # Current month — only count if contribution day has passed
            if today.day >= contribution_day:
                count += 1
        # Advance to next month
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1

    return count


def full_year_contribution_months(salary_day=0):
    """Return the number of monthly contributions in a full tax year (11 or 12).

    If salary_day < 6: April's contribution belongs to the old tax year,
    so only 11 contribution months fall in the new year (May-March).
    Otherwise 12 (April-March).
    """
    contribution_day = salary_day if salary_day >= 1 else 1
    return 12 if contribution_day >= 6 else 11


def review_ready_date(year, month, salary_day=0):
    """Calculate the date when investments should be settled and the monthly
    review is ready to do, for a given month.

    Logic:
    1. Start with the salary/investment day for that month.
    2. If it falls on a weekend, shift to the preceding Friday
       (banks pay early, standing orders move earlier).
    3. Add 2 business days for settlement.

    Returns a date object.
    """
    import calendar

    contribution_day = salary_day if salary_day >= 1 else 1
    # Clamp to actual days in the month (e.g. Feb 28)
    max_day = calendar.monthrange(year, month)[1]
    contribution_day = min(contribution_day, max_day)

    d = date(year, month, contribution_day)

    # If salary day is on a weekend, shift to the preceding Friday
    wd = d.weekday()  # 0=Mon .. 6=Sun
    if wd == 5:       # Saturday → Friday
        d = d - timedelta(days=1)
    elif wd == 6:     # Sunday → Friday
        d = d - timedelta(days=2)

    # Add 2 business days for settlement
    days_added = 0
    while days_added < 2:
        d = d + timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            days_added += 1

    return d


def is_review_due(today, salary_day=0):
    """Check whether the monthly review is due for the current month.

    Returns True if today is on or after the review-ready date.
    """
    ready = review_ready_date(today.year, today.month, salary_day)
    return today >= ready


ISA_WRAPPER_TYPES = {"Stocks & Shares ISA", "Cash ISA", "Lifetime ISA"}
LISA_WRAPPER_TYPES = {"Lifetime ISA"}


def calculate_isa_usage(accounts, ad_hoc_contributions, today=None, salary_day=0):
    """Auto-calculate ISA and LISA usage for the current tax year.

    accounts: list of account dicts (need wrapper_type, monthly_contribution)
    ad_hoc_contributions: list of isa_contributions rows (need wrapper_type, amount)
    salary_day: day of month when contributions go in (affects April handling)

    Returns dict with keys: isa_used, lisa_used, monthly_isa, monthly_lisa,
    adhoc_isa, adhoc_lisa, projected_isa, projected_lisa, breakdown.
    """
    today = today or date.today()
    months = months_in_tax_year(today, salary_day)
    total_months = full_year_contribution_months(salary_day)

    monthly_isa = 0.0
    monthly_lisa = 0.0
    projected_monthly_isa = 0.0
    projected_monthly_lisa = 0.0
    breakdown = []

    for acc in accounts:
        try:
            wt = acc["wrapper_type"] or ""
        except (KeyError, TypeError):
            wt = ""
        if wt not in ISA_WRAPPER_TYPES:
            continue
        try:
            monthly = float(acc["monthly_contribution"] or 0)
        except (KeyError, TypeError):
            monthly = 0.0
        total = monthly * months
        projected = monthly * total_months
        entry = {
            "account_id": acc["id"],
            "account_name": acc["name"],
            "wrapper_type": wt,
            "monthly_contribution": monthly,
            "months": months,
            "monthly_total": total,
            "adhoc_total": 0.0,
            "projected_total": projected,
        }
        monthly_isa += total
        projected_monthly_isa += projected
        if wt in LISA_WRAPPER_TYPES:
            monthly_lisa += total
            projected_monthly_lisa += projected
        breakdown.append(entry)

    # Sum ad-hoc contributions
    adhoc_isa = 0.0
    adhoc_lisa = 0.0
    for c in ad_hoc_contributions:
        amt = float(c["amount"])
        try:
            wt = c["wrapper_type"] or ""
        except (KeyError, TypeError):
            wt = ""
        adhoc_isa += amt
        if wt in LISA_WRAPPER_TYPES:
            adhoc_lisa += amt
        # Add to breakdown
        for entry in breakdown:
            if entry["account_id"] == c["account_id"]:
                entry["adhoc_total"] += amt
                break

    return {
        "isa_used": monthly_isa + adhoc_isa,
        "lisa_used": monthly_lisa + adhoc_lisa,
        "monthly_isa": monthly_isa,
        "monthly_lisa": monthly_lisa,
        "adhoc_isa": adhoc_isa,
        "adhoc_lisa": adhoc_lisa,
        "projected_isa": projected_monthly_isa + adhoc_isa,
        "projected_lisa": projected_monthly_lisa + adhoc_lisa,
        "months": months,
        "total_months": total_months,
        "breakdown": breakdown,
    }


def pension_allowance_limits(assumptions=None):
    assumptions = assumptions or {}
    try:
        annual_allowance = float(assumptions.get("pension_annual_allowance") or 60000)
    except (TypeError, ValueError):
        annual_allowance = 60000.0

    try:
        mpaa_enabled = int(assumptions.get("mpaa_enabled") or 0) == 1
    except (TypeError, ValueError):
        mpaa_enabled = False

    try:
        mpaa_allowance = float(assumptions.get("mpaa_allowance") or 10000)
    except (TypeError, ValueError):
        mpaa_allowance = 10000.0

    effective_allowance = min(annual_allowance, mpaa_allowance) if mpaa_enabled else annual_allowance

    try:
        income = float(assumptions.get("annual_income") or 0)
    except (TypeError, ValueError):
        income = 0.0

    if income > 0:
        personal_relief_limit = min(income, effective_allowance)
    else:
        personal_relief_limit = min(3600.0, effective_allowance)

    return {
        "annual_allowance": annual_allowance,
        "effective_allowance": effective_allowance,
        "personal_relief_limit": personal_relief_limit,
        "annual_income": income,
        "mpaa_enabled": mpaa_enabled,
        "mpaa_allowance": mpaa_allowance,
    }


def is_pension_account(account):
    if not account:
        return False
    try:
        cat_raw = account.get("category")
    except AttributeError:
        try:
            cat_raw = account["category"]
        except Exception:
            cat_raw = None
    try:
        wt_raw = account.get("wrapper_type")
    except AttributeError:
        try:
            wt_raw = account["wrapper_type"]
        except Exception:
            wt_raw = None

    cat = (cat_raw or "").strip().lower()
    wt = (wt_raw or "").strip().lower()
    return (cat == "pension") or ("pension" in wt) or ("sipp" in wt)


def calculate_pension_usage(accounts, ad_hoc_contributions, assumptions=None, today=None, salary_day=0):
    today = today or date.today()
    months = months_in_tax_year(today, salary_day)
    total_months = full_year_contribution_months(salary_day)

    used_total = 0.0
    used_personal = 0.0
    used_employer = 0.0
    projected_total = 0.0
    breakdown = []

    assumptions = assumptions or {}

    for acc in accounts:
        if not is_pension_account(acc):
            continue

        try:
            acc_day = int(acc.get("pension_contribution_day") or 0)
        except Exception:
            acc_day = 0
        if not acc_day:
            acc_day = salary_day
        acc_months = months_in_tax_year(today, acc_day)
        acc_total_months = full_year_contribution_months(acc_day)

        b = contribution_breakdown(acc, assumptions)

        monthly_total = float(b.get("total_into_pot") or 0)
        monthly_employer = float(b.get("employer") or 0)
        monthly_personal_net = float(b.get("personal") or 0)
        monthly_tax_relief = float(b.get("tax_relief") or 0)

        try:
            method = (acc.get("contribution_method") or "")
        except AttributeError:
            try:
                method = (acc["contribution_method"] or "")
            except Exception:
                method = ""

        if method == "salary_sacrifice":
            monthly_personal_gross = 0.0
            monthly_employer_gross = monthly_total
        else:
            monthly_personal_gross = max(0.0, (monthly_personal_net + monthly_tax_relief))
            monthly_employer_gross = max(0.0, monthly_employer)

        total = monthly_total * acc_months
        projected = monthly_total * acc_total_months

        used_total += total
        used_personal += monthly_personal_gross * acc_months
        used_employer += monthly_employer_gross * acc_months
        projected_total += projected

        breakdown.append({
            "account_id": (acc["id"] if "id" in acc.keys() else acc.get("id")),
            "account_name": (acc["name"] if "name" in acc.keys() else acc.get("name")),
            "wrapper_type": (
                (acc.get("wrapper_type") if hasattr(acc, "get") else acc["wrapper_type"])
                if ("wrapper_type" in acc.keys() or hasattr(acc, "get"))
                else ""
            ) or "",
            "monthly_total": monthly_total,
            "monthly_personal": monthly_personal_gross,
            "monthly_employer": monthly_employer_gross,
            "months": acc_months,
            "total_months": acc_total_months,
            "monthly_sum": total,
            "adhoc_total": 0.0,
            "adhoc_personal": 0.0,
            "adhoc_employer": 0.0,
        })

    adhoc_total = 0.0
    adhoc_personal = 0.0
    adhoc_employer = 0.0

    for c in ad_hoc_contributions:
        amt = float(c["amount"])
        kind = (c.get("kind") or "personal").strip().lower()
        adhoc_total += amt
        if kind == "employer":
            adhoc_employer += amt
        else:
            adhoc_personal += amt

        for entry in breakdown:
            if entry["account_id"] == c["account_id"]:
                entry["adhoc_total"] += amt
                if kind == "employer":
                    entry["adhoc_employer"] += amt
                else:
                    entry["adhoc_personal"] += amt
                break

    used_total += adhoc_total
    used_personal += adhoc_personal
    used_employer += adhoc_employer
    projected_total += adhoc_total

    return {
        "pension_used": used_total,
        "pension_personal_used": used_personal,
        "pension_employer_used": used_employer,
        "adhoc_total": adhoc_total,
        "adhoc_personal": adhoc_personal,
        "adhoc_employer": adhoc_employer,
        "projected_total": projected_total,
        "months": months,
        "total_months": total_months,
        "breakdown": breakdown,
    }


def build_month_strip(today=None):
    """Build the 12-month tax-year strip (Apr → Mar) for the current date.

    Returns a list of dicts: key, label, month_num, is_current, is_today.
    This is a display-only strip (no budget data), so has_data is always False.
    """
    today = today or date.today()
    current_month_key = today.strftime("%Y-%m")
    current_month_num = today.month

    # Determine the tax year start (April)
    if today.month > 4 or (today.month == 4 and today.day >= 6):
        ty_start_year = today.year
    else:
        ty_start_year = today.year - 1

    strip = []
    for i in range(12):
        m = 4 + i  # Apr=4 … Mar=15→3
        y = ty_start_year if m <= 12 else ty_start_year + 1
        if m > 12:
            m -= 12
        mk = f"{y}-{m:02d}"
        label_short = datetime.strptime(mk, "%Y-%m").strftime("%b")
        strip.append({
            "key": mk,
            "label": label_short,
            "month_num": m,
            "is_current": (m == current_month_num),
            "is_today": (mk == current_month_key),
            "has_data": False,
        })
    return strip
