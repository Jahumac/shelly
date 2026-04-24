"""Debt tracker model — CRUD and calculations for the debts table."""
import calendar
import math
from datetime import date, datetime

from ._conn import get_connection


# ── CRUD ─────────────────────────────────────────────────────────────────────

def fetch_all_debts(user_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM debts WHERE user_id = ? AND is_active = 1 ORDER BY created_at",
            (user_id,),
        ).fetchall()
    return rows


def fetch_debt(debt_id, user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM debts WHERE id = ? AND user_id = ?",
            (debt_id, user_id),
        ).fetchone()


def create_debt(payload, user_id):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO debts (user_id, name, original_amount, current_balance,
                               monthly_payment, apr, notes, start_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload["name"],
                payload.get("original_amount", 0),
                payload.get("current_balance", 0),
                payload["monthly_payment"],
                payload.get("apr", 0),
                payload.get("notes", ""),
                payload.get("start_date") or None,
            ),
        )
        conn.commit()


def update_debt(debt_id, payload, user_id):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE debts
            SET name = ?, original_amount = ?, current_balance = ?,
                monthly_payment = ?, apr = ?, notes = ?, start_date = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                payload["name"],
                payload.get("original_amount", 0),
                payload.get("current_balance", 0),
                payload["monthly_payment"],
                payload.get("apr", 0),
                payload.get("notes", ""),
                payload.get("start_date") or None,
                debt_id,
                user_id,
            ),
        )
        conn.commit()


def delete_debt(debt_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE debts SET is_active = 0 WHERE id = ? AND user_id = ?",
            (debt_id, user_id),
        )
        conn.commit()


# ── Calculations ─────────────────────────────────────────────────────────────

def debt_months_remaining(balance, monthly_payment, apr):
    """Number of months to pay off the debt. Returns None if payment can't cover interest."""
    if balance <= 0:
        return 0
    if monthly_payment <= 0:
        return None
    r = apr / 100.0 / 12.0
    if r == 0:
        return math.ceil(balance / monthly_payment)
    monthly_interest = balance * r
    if monthly_payment <= monthly_interest:
        return None  # payment too low to ever pay off
    return math.ceil(-math.log(1 - balance * r / monthly_payment) / math.log(1 + r))


def debt_total_interest(balance, monthly_payment, apr, months=None):
    """Total interest paid over the life of the debt."""
    if apr == 0:
        return 0.0
    if months is None:
        months = debt_months_remaining(balance, monthly_payment, apr)
    if months is None:
        return None
    total_paid = monthly_payment * months
    return max(total_paid - balance, 0)


def debt_payoff_date(months):
    """Calendar date when the debt will be cleared (from today)."""
    if months is None:
        return None
    today = date.today()
    total_months = today.month - 1 + months
    year = today.year + total_months // 12
    month = total_months % 12 + 1
    return date(year, month, 1)


def _add_months(d, n):
    """Add n months to a date, clamping to the last day of the target month."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def schedule_anchor(start_date_str, offset_months=0):
    """Calendar date for the first row of an amortisation schedule.

    Parses an ISO start_date and optionally shifts forward by N months (used to
    skip past payments already made). Returns None if start_date_str is missing
    or malformed.
    """
    if not start_date_str:
        return None
    try:
        start = date.fromisoformat(start_date_str)
    except (ValueError, TypeError):
        return None
    return _add_months(start, offset_months) if offset_months else start


def amortisation_schedule(balance, apr, monthly_payment, max_months=360, start_date=None):
    """Return a list of monthly rows: month, payment, interest, principal, balance.

    If start_date (a date object) is provided, each row also gets a 'date' field
    with the actual calendar date of that payment.
    """
    r = apr / 100.0 / 12.0
    rows = []
    for i in range(1, max_months + 1):
        if balance <= 0:
            break
        interest = round(balance * r, 2)
        # Final payment may be smaller
        payment = min(monthly_payment, balance + interest)
        principal = round(payment - interest, 2)
        balance = max(round(balance - principal, 2), 0)
        row = {
            "month": i,
            "payment": payment,
            "interest": interest,
            "principal": principal,
            "balance": balance,
        }
        if start_date:
            row["date"] = _add_months(start_date, i - 1)
        rows.append(row)
        if monthly_payment <= interest and i > 1:
            break  # can't pay off
    return rows


def _auto_balance_from_schedule(original_amount, apr, monthly_payment, start_date_str):
    """Calculate current balance from amortisation schedule based on first payment date.
    Returns (balance, payments_made) or (None, 0) if start_date not set.

    Payment count logic: a payment is counted for a given month only if today's
    date has reached or passed the payment day of that month. This prevents
    counting next month's payment as already made when it hasn't gone out yet.
    For example, start_date=2026-03-31, today=2026-04-19 → 1 payment made
    (April's payment is due on the 30th, not yet reached).
    """
    if not start_date_str or not original_amount:
        return None, 0
    try:
        start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        today = date.today()
        if today < start:
            return float(original_amount), 0
        # Whole months elapsed since start
        months_elapsed = (today.year - start.year) * 12 + (today.month - start.month)
        # Check whether today has reached the payment day in the current month.
        # Handle end-of-month: if start_date is the 31st and current month only
        # has 30 days, the payment falls on the last day of that month.
        days_in_current_month = calendar.monthrange(today.year, today.month)[1]
        payment_day_this_month = min(start.day, days_in_current_month)
        if today.day >= payment_day_this_month:
            n = months_elapsed + 1
        else:
            n = months_elapsed
        if n <= 0:
            return float(original_amount), 0
        r = apr / 100.0 / 12.0
        balance = float(original_amount)
        for _ in range(n):
            if balance <= 0:
                break
            interest = balance * r
            principal = monthly_payment - interest
            if principal <= 0:
                break
            balance = max(balance - principal, 0)
        return round(balance, 2), n
    except (ValueError, TypeError):
        return None, 0


def build_debt_card(debt):
    """Attach calculated fields to a debt row dict."""
    original = float(debt["original_amount"] or 0)
    payment = float(debt["monthly_payment"] or 0)
    apr = float(debt["apr"] or 0)
    start_date = debt["start_date"] if "start_date" in debt.keys() else None

    # Auto-calculate balance from schedule if start_date is set
    auto_balance, payments_made = _auto_balance_from_schedule(original, apr, payment, start_date)
    if auto_balance is not None:
        balance = auto_balance
        auto_tracked = True
    else:
        balance = float(debt["current_balance"] or 0)
        payments_made = 0
        auto_tracked = False

    months = debt_months_remaining(balance, payment, apr)
    interest = debt_total_interest(balance, payment, apr, months)
    payoff = debt_payoff_date(months)
    paid_off_pct = ((original - balance) / original * 100) if original > 0 else 0

    return {
        "id": debt["id"],
        "name": debt["name"],
        "original_amount": original,
        "current_balance": balance,
        "stored_balance": float(debt["current_balance"] or 0),
        "monthly_payment": payment,
        "apr": apr,
        "notes": debt["notes"] or "",
        "start_date": start_date,
        "auto_tracked": auto_tracked,
        "payments_made": payments_made,
        "months_remaining": months,
        "total_interest": interest,
        "payoff_date": payoff,
        "paid_off_pct": max(0, min(100, paid_off_pct)),
        "total_cost": (balance + interest) if interest is not None else None,
        "monthly_interest": balance * (apr / 100 / 12) if apr > 0 else 0,
    }
