"""Allowance tracking: ISA, pension, dividend, CGT, carry-forward, overrides."""
from datetime import datetime, timezone
from ._conn import get_connection


# ── Allowance tracking row ────────────────────────────────────────────────────

def fetch_allowance_tracking(user_id=None):
    """Return the most recent allowance_tracking row.

    user_id is accepted for API consistency but allowance_tracking is a
    global table (one row per tax year).
    """
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM allowance_tracking ORDER BY id DESC LIMIT 1"
        ).fetchone()


# ── ISA contributions ─────────────────────────────────────────────────────────

def _account_belongs_to_user(conn, account_id, user_id):
    return conn.execute(
        "SELECT 1 FROM accounts WHERE id = ? AND user_id = ?",
        (account_id, user_id),
    ).fetchone() is not None


def add_isa_contribution(user_id, account_id, amount, contribution_date, note=None):
    with get_connection() as conn:
        if not _account_belongs_to_user(conn, account_id, user_id):
            return False
        conn.execute(
            """
            INSERT INTO isa_contributions (user_id, account_id, amount, contribution_date, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, account_id, amount, contribution_date, note),
        )
        conn.commit()
        return True


def fetch_isa_contributions(user_id, tax_year_start, tax_year_end):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.*, a.name AS account_name, a.wrapper_type
            FROM isa_contributions c
            JOIN accounts a ON a.id = c.account_id
            WHERE c.user_id = ?
              AND a.user_id = c.user_id
              AND c.contribution_date >= ?
              AND c.contribution_date <= ?
            ORDER BY c.contribution_date DESC
            """,
            (user_id, tax_year_start, tax_year_end),
        ).fetchall()


def delete_isa_contribution(contribution_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM isa_contributions WHERE id = ? AND user_id = ?",
            (contribution_id, user_id),
        )
        conn.commit()


# ── Pension contributions ─────────────────────────────────────────────────────

def add_pension_contribution(user_id, account_id, amount, kind, contribution_date, note=None):
    with get_connection() as conn:
        if not _account_belongs_to_user(conn, account_id, user_id):
            return False
        conn.execute(
            """
            INSERT INTO pension_contributions (user_id, account_id, amount, kind, contribution_date, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, account_id, amount, kind, contribution_date, note),
        )
        conn.commit()
        return True


def fetch_pension_contributions(user_id, tax_year_start, tax_year_end):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.*, a.name AS account_name, a.wrapper_type
            FROM pension_contributions c
            JOIN accounts a ON a.id = c.account_id
            WHERE c.user_id = ?
              AND a.user_id = c.user_id
              AND c.contribution_date >= ?
              AND c.contribution_date <= ?
            ORDER BY c.contribution_date DESC
            """,
            (user_id, tax_year_start, tax_year_end),
        ).fetchall()


def delete_pension_contribution(contribution_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM pension_contributions WHERE id = ? AND user_id = ?",
            (contribution_id, user_id),
        )
        conn.commit()


# ── Dividend records ──────────────────────────────────────────────────────────

def add_dividend_record(user_id, account_id, amount, dividend_date, note=None):
    with get_connection() as conn:
        if not _account_belongs_to_user(conn, account_id, user_id):
            return False
        conn.execute(
            """
            INSERT INTO dividend_records (user_id, account_id, amount, dividend_date, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, account_id, amount, dividend_date, note),
        )
        conn.commit()
        return True


def fetch_dividend_records(user_id, tax_year_start, tax_year_end):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT d.*, a.name AS account_name, a.wrapper_type
            FROM dividend_records d
            JOIN accounts a ON a.id = d.account_id
            WHERE d.user_id = ?
              AND a.user_id = d.user_id
              AND d.dividend_date >= ?
              AND d.dividend_date <= ?
            ORDER BY d.dividend_date DESC
            """,
            (user_id, tax_year_start, tax_year_end),
        ).fetchall()


def delete_dividend_record(record_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM dividend_records WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        )
        conn.commit()


# ── CGT disposals ─────────────────────────────────────────────────────────────

def add_cgt_disposal(user_id, disposal_date, asset_name, proceeds, cost_basis, note=None, account_id=None):
    with get_connection() as conn:
        if account_id is not None and not _account_belongs_to_user(conn, account_id, user_id):
            return False
        conn.execute(
            """
            INSERT INTO cgt_disposals (user_id, disposal_date, asset_name, proceeds, cost_basis, note, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, disposal_date, asset_name, proceeds, cost_basis, note, account_id),
        )
        conn.commit()
        return True


def fetch_cgt_disposals(user_id, tax_year_start, tax_year_end):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.*, a.name AS account_name
            FROM cgt_disposals c
            LEFT JOIN accounts a ON a.id = c.account_id AND a.user_id = c.user_id
            WHERE c.user_id = ?
              AND c.disposal_date >= ?
              AND c.disposal_date <= ?
            ORDER BY c.disposal_date DESC
            """,
            (user_id, tax_year_start, tax_year_end),
        ).fetchall()


def delete_cgt_disposal(disposal_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM cgt_disposals WHERE id = ? AND user_id = ?",
            (disposal_id, user_id),
        )
        conn.commit()


# ── Pension carry-forward ─────────────────────────────────────────────────────

def fetch_pension_carry_forward(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM pension_carry_forward WHERE user_id = ? ORDER BY tax_year DESC",
            (user_id,),
        ).fetchall()


def upsert_pension_carry_forward(user_id, tax_year, unused_allowance):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pension_carry_forward (user_id, tax_year, unused_allowance)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tax_year) DO UPDATE SET unused_allowance = excluded.unused_allowance
            """,
            (user_id, tax_year, unused_allowance),
        )
        conn.commit()


def delete_pension_carry_forward(entry_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM pension_carry_forward WHERE id = ? AND user_id = ?",
            (entry_id, user_id),
        )
        conn.commit()


# ── Contribution overrides ────────────────────────────────────────────────────

def fetch_contribution_overrides(account_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM contribution_overrides WHERE account_id = ? ORDER BY from_month ASC",
            (account_id,),
        ).fetchall()


def fetch_all_active_overrides(month_key, user_id):
    """Return overrides active for a given month, keyed by account_id."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT co.* FROM contribution_overrides co
            JOIN accounts a ON a.id = co.account_id
            WHERE co.from_month <= ? AND co.to_month >= ? AND a.user_id = ?
            """,
            (month_key, month_key, user_id),
        ).fetchall()
    return {r["account_id"]: r for r in rows}


def create_contribution_override(payload):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO contribution_overrides (account_id, from_month, to_month, override_amount, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload["account_id"],
                payload["from_month"],
                payload["to_month"],
                payload["override_amount"],
                payload.get("reason", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def remove_contribution_override_for_month(account_id, month_key, user_id):
    """Delete a single-month skip override (from_month == to_month == month_key)."""
    with get_connection() as conn:
        conn.execute(
            """DELETE FROM contribution_overrides
               WHERE account_id = ? AND from_month = ? AND to_month = ?
               AND account_id IN (SELECT id FROM accounts WHERE user_id = ?)""",
            (account_id, month_key, month_key, user_id),
        )
        conn.commit()


def upsert_single_month_contribution_override(account_id, month_key, amount, user_id, reason="from budget"):
    """Upsert a single-month contribution override for an account.

    Replaces any existing single-month override (from_month == to_month == month_key)
    for this account. Used by the budget page to reflect per-month edits on linked
    items straight through to projections without creating duplicates.

    Verifies the account belongs to user_id — silently no-ops if not.
    """
    with get_connection() as conn:
        owned = conn.execute(
            "SELECT 1 FROM accounts WHERE id = ? AND user_id = ?",
            (account_id, user_id),
        ).fetchone()
        if not owned:
            return
        conn.execute(
            """DELETE FROM contribution_overrides
               WHERE account_id = ? AND from_month = ? AND to_month = ?""",
            (account_id, month_key, month_key),
        )
        conn.execute(
            """INSERT INTO contribution_overrides
               (account_id, from_month, to_month, override_amount, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (account_id, month_key, month_key, amount, reason, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def delete_contribution_override(override_id, user_id=None):
    with get_connection() as conn:
        if user_id is not None:
            conn.execute(
                """DELETE FROM contribution_overrides
                   WHERE id = ? AND account_id IN (SELECT id FROM accounts WHERE user_id = ?)""",
                (override_id, user_id),
            )
        else:
            conn.execute("DELETE FROM contribution_overrides WHERE id = ?", (override_id,))
        conn.commit()
