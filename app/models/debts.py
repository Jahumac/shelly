"""Debt tracker model — CRUD for the debts table."""
import math
from datetime import date

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
                               monthly_payment, apr, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload["name"],
                payload.get("original_amount", 0),
                payload["current_balance"],
                payload["monthly_payment"],
                payload.get("apr", 0),
                payload.get("notes", ""),
            ),
        )
        conn.commit()


def update_debt(debt_id, payload, user_id):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE debts
            SET name = ?, original_amount = ?, current_balance = ?,
                monthly_payment = ?, apr = ?, notes = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                payload["name"],
                payload.get("original_amount", 0),
                payload["current_balance"],
                payload["monthly_payment"],
                payload.get("apr", 0),
                payload.get("notes", ""),
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
    if months is None:
        months = debt_months_remaining(balance, monthly_payment, apr)
    if months is None:
        return None
    # Last payment is usually less than monthly_payment, so approximate:
    total_paid = monthly_payment * months
    return max(total_paid - balance, 0)


def debt_payoff_date(months):
    """Calendar date when the debt will be cleared."""
    if months is None:
        return None
    today = date.today()
    total_months = today.month - 1 + months
    year = today.year + total_months // 12
    month = total_months % 12 + 1
    return date(year, month, 1)


def build_debt_card(debt):
    """Attach calculated fields to a debt row dict."""
    balance = float(debt["current_balance"] or 0)
    payment = float(debt["monthly_payment"] or 0)
    apr = float(debt["apr"] or 0)
    original = float(debt["original_amount"] or 0)

    months = debt_months_remaining(balance, payment, apr)
    interest = debt_total_interest(balance, payment, apr, months)
    payoff = debt_payoff_date(months)
    paid_off_pct = ((original - balance) / original * 100) if original > 0 else 0

    return {
        "id": debt["id"],
        "name": debt["name"],
        "original_amount": original,
        "current_balance": balance,
        "monthly_payment": payment,
        "apr": apr,
        "notes": debt["notes"] or "",
        "months_remaining": months,
        "total_interest": interest,
        "payoff_date": payoff,
        "paid_off_pct": max(0, min(100, paid_off_pct)),
        "total_cost": (balance + interest) if interest is not None else None,
        "monthly_interest": balance * (apr / 100 / 12) if apr > 0 else 0,
    }
