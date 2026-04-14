import sqlite3
from pathlib import Path
from flask import current_app, g
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash


# DB schema, init_db, and connection handling live in submodules.
from ._conn import get_connection, close_db
from .schema import SCHEMA, init_db


# ── User model ────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, username, password_hash, is_admin):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.is_admin = bool(is_admin)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


def get_user_by_id(user_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return User(row["id"], row["username"], row["password_hash"], row["is_admin"])


def get_user_by_username(username):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return None
    return User(row["id"], row["username"], row["password_hash"], row["is_admin"])


def create_user(username, password, is_admin=False):
    from datetime import datetime
    pw_hash = generate_password_hash(password)
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, pw_hash, 1 if is_admin else 0, datetime.now().isoformat()),
        )
        conn.commit()
        return cursor.lastrowid


def count_users():
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def fetch_all_users():
    with get_connection() as conn:
        return conn.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()


def update_user(user_id, username=None, password=None, is_admin=None):
    """Update user fields. Pass None to leave a field unchanged.
    Returns (ok, error_message).
    """
    with get_connection() as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            return False, "User not found."
        # Check username uniqueness if changing
        if username and username != target["username"]:
            clash = conn.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?", (username, user_id)
            ).fetchone()
            if clash:
                return False, f"Username '{username}' is already taken."
        # Safety: can't remove admin from the last admin
        if is_admin is False and target["is_admin"]:
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_admin = 1"
            ).fetchone()[0]
            if admin_count <= 1:
                return False, "Cannot remove admin rights from the only admin account."
        # Build update
        if username:
            conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
        if password:
            pw_hash = generate_password_hash(password)
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id))
        if is_admin is not None:
            conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id))
        conn.commit()
    return True, None


def delete_user(user_id):
    """Delete a user and all their data. Returns (ok, error_message)."""
    with get_connection() as conn:
        # Safety: must not be the last admin
        admin_count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin = 1"
        ).fetchone()[0]
        target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            return False, "User not found."
        if target["is_admin"] and admin_count <= 1:
            return False, "Cannot delete the only admin account."
        # Delete user data across all tables
        conn.execute("DELETE FROM assumptions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM goals WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM holding_catalogue WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM budget_items WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM budget_sections WHERE user_id = ?", (user_id,))
        # Monthly reviews cascade — delete items first
        review_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM monthly_reviews WHERE user_id = ?", (user_id,)
        ).fetchall()]
        for rid in review_ids:
            conn.execute("DELETE FROM monthly_review_items WHERE review_id = ?", (rid,))
        conn.execute("DELETE FROM monthly_reviews WHERE user_id = ?", (user_id,))
        # Accounts — clean up holdings first, then soft-delete the accounts
        account_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM accounts WHERE user_id = ?", (user_id,)
        ).fetchall()]
        for aid in account_ids:
            conn.execute("DELETE FROM holdings WHERE account_id = ?", (aid,))
            conn.execute("DELETE FROM monthly_snapshots WHERE account_id = ?", (aid,))
            conn.execute("DELETE FROM monthly_review_items WHERE account_id = ?", (aid,))
            conn.execute("DELETE FROM contribution_overrides WHERE account_id = ?", (aid,))
        conn.execute("UPDATE accounts SET is_active = 0 WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return True, None



def fetch_all_accounts(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM accounts WHERE is_active = 1 AND user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()


def fetch_assumptions(user_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM assumptions WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            # Create default assumptions row for this user on first access
            conn.execute(
                """INSERT OR IGNORE INTO assumptions (user_id) VALUES (?)""",
                (user_id,),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM assumptions WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row


def fetch_primary_goal(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM goals WHERE user_id = ? ORDER BY id ASC LIMIT 1",
            (user_id,),
        ).fetchone()


def fetch_all_goals(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM goals WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()


def fetch_goal(goal_id, user_id=None):
    """Return a goal by id. If user_id is given, only returns the row
    when it belongs to that user — otherwise returns None."""
    with get_connection() as conn:
        if user_id is not None:
            return conn.execute(
                "SELECT * FROM goals WHERE id = ? AND user_id = ?",
                (goal_id, user_id),
            ).fetchone()
        return conn.execute(
            "SELECT * FROM goals WHERE id = ?",
            (goal_id,),
        ).fetchone()


def create_goal(payload, user_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO goals (user_id, name, target_value, goal_type, selected_tags, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload["name"],
                payload["target_value"],
                payload.get("goal_type", ""),
                payload.get("selected_tags", ""),
                payload.get("notes", ""),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_goal(payload, user_id):
    """Update a goal. Scoped to user_id — attempting to update another
    user's goal is a silent no-op (rowcount will be 0)."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE goals
            SET name = ?,
                target_value = ?,
                goal_type = ?,
                selected_tags = ?,
                notes = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                payload["name"],
                payload["target_value"],
                payload.get("goal_type", ""),
                payload.get("selected_tags", ""),
                payload.get("notes", ""),
                payload["id"],
                user_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_goal(goal_id, user_id):
    """Delete a goal scoped to user_id. Returns True if a row was deleted."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM goals WHERE id = ? AND user_id = ?",
            (goal_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def fetch_allowance_tracking(user_id=None):
    """Return the most recent allowance_tracking row.

    user_id is accepted for API consistency but allowance_tracking is a
    global table (one row per tax year). It will be made per-user in a
    future migration.
    """
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM allowance_tracking ORDER BY id DESC LIMIT 1"
        ).fetchone()


def fetch_latest_price_update(user_id):
    """Return the most recent price_updated_at timestamp across catalogue items that are actually held."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT MAX(hc.price_updated_at) AS latest
            FROM holding_catalogue hc
            JOIN holdings h ON h.holding_catalogue_id = hc.id
            JOIN accounts a ON a.id = h.account_id
            WHERE a.user_id = ?
              AND a.is_active = 1
              AND hc.is_active = 1
              AND hc.price_updated_at IS NOT NULL
            """,
            (user_id,),
        ).fetchone()
        return row["latest"] if row else None


# ── ISA ad-hoc contributions ─────────────────────────────────────────────────

def add_isa_contribution(user_id, account_id, amount, contribution_date, note=None):
    """Record an ad-hoc contribution to an ISA account."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO isa_contributions (user_id, account_id, amount, contribution_date, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, account_id, amount, contribution_date, note),
        )
        conn.commit()


def fetch_isa_contributions(user_id, tax_year_start, tax_year_end):
    """Return all ad-hoc ISA contributions for a user within a tax year window.

    tax_year_start / tax_year_end are ISO date strings (YYYY-MM-DD),
    e.g. '2026-04-06' / '2027-04-05'.
    """
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.*, a.name AS account_name, a.wrapper_type
            FROM isa_contributions c
            JOIN accounts a ON a.id = c.account_id
            WHERE c.user_id = ?
              AND c.contribution_date >= ?
              AND c.contribution_date <= ?
            ORDER BY c.contribution_date DESC
            """,
            (user_id, tax_year_start, tax_year_end),
        ).fetchall()


def delete_isa_contribution(contribution_id, user_id):
    """Delete an ad-hoc ISA contribution (only if it belongs to the user)."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM isa_contributions WHERE id = ? AND user_id = ?",
            (contribution_id, user_id),
        )
        conn.commit()


def add_pension_contribution(user_id, account_id, amount, kind, contribution_date, note=None):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pension_contributions (user_id, account_id, amount, kind, contribution_date, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, account_id, amount, kind, contribution_date, note),
        )
        conn.commit()


def fetch_pension_contributions(user_id, tax_year_start, tax_year_end):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT c.*, a.name AS account_name, a.wrapper_type
            FROM pension_contributions c
            JOIN accounts a ON a.id = c.account_id
            WHERE c.user_id = ?
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


def add_dividend_record(user_id, account_id, amount, dividend_date, note=None):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO dividend_records (user_id, account_id, amount, dividend_date, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, account_id, amount, dividend_date, note),
        )
        conn.commit()


def fetch_dividend_records(user_id, tax_year_start, tax_year_end):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT d.*, a.name AS account_name, a.wrapper_type
            FROM dividend_records d
            JOIN accounts a ON a.id = d.account_id
            WHERE d.user_id = ?
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

def fetch_or_create_monthly_review(month_key, user_id):
    with get_connection() as conn:
        review = conn.execute(
            "SELECT * FROM monthly_reviews WHERE month_key = ? AND user_id = ?",
            (month_key, user_id),
        ).fetchone()

        if review is None:
            conn.execute(
                """
                INSERT INTO monthly_reviews (user_id, month_key, status, created_at, updated_at)
                VALUES (?, ?, 'not_started', datetime('now'), datetime('now'))
                """,
                (user_id, month_key),
            )
            conn.commit()
            review = conn.execute(
                "SELECT * FROM monthly_reviews WHERE month_key = ? AND user_id = ?",
                (month_key, user_id),
            ).fetchone()

        return review


def fetch_monthly_review_items(review_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT mri.*, a.name AS account_name, a.provider, a.wrapper_type, a.valuation_mode,
                   a.monthly_contribution AS account_monthly_contribution
            FROM monthly_review_items mri
            JOIN accounts a ON a.id = mri.account_id
            WHERE mri.review_id = ?
            ORDER BY a.id ASC
            """,
            (review_id,),
        ).fetchall()


def ensure_monthly_review_items(review_id, user_id):
    accounts = fetch_all_accounts(user_id)
    with get_connection() as conn:
        existing_rows = conn.execute(
            "SELECT account_id FROM monthly_review_items WHERE review_id = ?",
            (review_id,),
        ).fetchall()
        existing_ids = {row["account_id"] for row in existing_rows}

        for account in accounts:
            if account["id"] not in existing_ids:
                conn.execute(
                    """
                    INSERT INTO monthly_review_items (
                        review_id, account_id, expected_contribution,
                        contribution_confirmed, holdings_updated, balance_updated, notes
                    )
                    VALUES (?, ?, ?, 0, 0, 0, '')
                    """,
                    (review_id, account["id"], account["monthly_contribution"] or 0),
                )
        conn.commit()


def update_monthly_review(review_id, status, notes):
    completed_at = "datetime('now')" if status == "complete" else "NULL"
    with get_connection() as conn:
        if status == "complete":
            conn.execute(
                """
                UPDATE monthly_reviews
                SET status = ?, notes = ?, completed_at = datetime('now'), updated_at = datetime('now')
                WHERE id = ?
                """,
                (status, notes, review_id),
            )
        else:
            conn.execute(
                """
                UPDATE monthly_reviews
                SET status = ?, notes = ?, completed_at = NULL, updated_at = datetime('now')
                WHERE id = ?
                """,
                (status, notes, review_id),
            )
        conn.commit()


def update_monthly_review_item(payload):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE monthly_review_items
            SET expected_contribution = ?,
                contribution_confirmed = ?,
                holdings_updated = ?,
                balance_updated = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                payload["expected_contribution"],
                payload["contribution_confirmed"],
                payload["holdings_updated"],
                payload["balance_updated"],
                payload["notes"],
                payload["id"],
            ),
        )
        conn.commit()


def update_assumptions(payload, user_id):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE assumptions
            SET annual_growth_rate = ?,
                retirement_age = ?,
                date_of_birth = ?,
                retirement_goal_value = ?,
                isa_allowance = ?,
                lisa_allowance = ?,
                dividend_allowance = ?,
                annual_income = ?,
                pension_annual_allowance = ?,
                mpaa_enabled = ?,
                mpaa_allowance = ?,
                target_dev_pct = ?,
                target_em_pct = ?,
                emergency_fund_target = ?,
                dashboard_name = ?,
                salary_day = ?,
                update_day = ?,
                retirement_date_mode = ?,
                tax_band = ?,
                auto_update_prices = ?,
                update_time_morning = ?,
                update_time_evening = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                payload["annual_growth_rate"],
                payload["retirement_age"],
                payload.get("date_of_birth", ""),
                payload["retirement_goal_value"],
                payload["isa_allowance"],
                payload["lisa_allowance"],
                payload.get("dividend_allowance", 500),
                payload.get("annual_income", 0),
                payload.get("pension_annual_allowance", 60000),
                payload.get("mpaa_enabled", 0),
                payload.get("mpaa_allowance", 10000),
                payload["target_dev_pct"],
                payload["target_em_pct"],
                payload["emergency_fund_target"],
                payload["dashboard_name"],
                payload.get("salary_day", 0),
                payload.get("update_day", 0),
                payload.get("retirement_date_mode", "birthday"),
                payload.get("tax_band", "basic"),
                payload.get("auto_update_prices", 1),
                payload.get("update_time_morning", "08:30"),
                payload.get("update_time_evening", "18:00"),
                payload["updated_at"],
                user_id,
            ),
        )
        conn.commit()


def fetch_account(account_id, user_id=None):
    """Fetch a single account by id.
    If user_id is provided, also checks ownership (returns None if mismatch).
    """
    with get_connection() as conn:
        if user_id is not None:
            return conn.execute(
                "SELECT * FROM accounts WHERE id = ? AND user_id = ?",
                (account_id, user_id),
            ).fetchone()
        return conn.execute(
            "SELECT * FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()


def update_account(payload):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE accounts
            SET name = ?,
                provider = ?,
                wrapper_type = ?,
                category = ?,
                tags = ?,
                current_value = ?,
                monthly_contribution = ?,
                pension_contribution_day = ?,
                goal_value = ?,
                valuation_mode = ?,
                growth_mode = ?,
                growth_rate_override = ?,
                owner = ?,
                notes = ?,
                last_updated = ?,
                employer_contribution = ?,
                contribution_method = ?,
                annual_fee_pct = ?,
                platform_fee_pct = ?,
                platform_fee_flat = ?,
                platform_fee_cap = ?,
                fund_fee_pct = ?,
                uninvested_cash = ?,
                cash_interest_rate = ?
            WHERE id = ?
            """,
            (
                payload["name"],
                payload["provider"],
                payload["wrapper_type"],
                payload["category"],
                payload["tags"],
                payload["current_value"],
                payload["monthly_contribution"],
                payload.get("pension_contribution_day", 0),
                payload["goal_value"],
                payload["valuation_mode"],
                payload["growth_mode"],
                payload["growth_rate_override"],
                payload["owner"],
                payload["notes"],
                payload["last_updated"],
                payload.get("employer_contribution", 0),
                payload.get("contribution_method", "standard"),
                payload.get("annual_fee_pct", 0),
                payload.get("platform_fee_pct", 0),
                payload.get("platform_fee_flat", 0),
                payload.get("platform_fee_cap", 0),
                payload.get("fund_fee_pct", 0),
                payload.get("uninvested_cash", 0),
                payload.get("cash_interest_rate", 0),
                payload["id"],
            ),
        )
        conn.commit()


def delete_account(account_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE accounts SET is_active = 0 WHERE id = ?",
            (account_id,),
        )
        conn.execute(
            "DELETE FROM holdings WHERE account_id = ?",
            (account_id,),
        )
        conn.commit()


def create_account(payload, user_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO accounts (
                user_id, name, provider, wrapper_type, category, tags, current_value,
                monthly_contribution, pension_contribution_day, goal_value, valuation_mode, growth_mode,
                growth_rate_override, owner, is_active, notes, last_updated,
                employer_contribution, contribution_method, annual_fee_pct,
                platform_fee_pct, platform_fee_flat, platform_fee_cap, fund_fee_pct,
                uninvested_cash, cash_interest_rate
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                payload["name"],
                payload["provider"],
                payload["wrapper_type"],
                payload["category"],
                payload["tags"],
                payload["current_value"],
                payload["monthly_contribution"],
                payload.get("pension_contribution_day", 0),
                payload["goal_value"],
                payload["valuation_mode"],
                payload["growth_mode"],
                payload["growth_rate_override"],
                payload["owner"],
                payload.get("is_active", 1),
                payload["notes"],
                payload["last_updated"],
                payload.get("employer_contribution", 0),
                payload.get("contribution_method", "standard"),
                payload.get("annual_fee_pct", 0),
                payload.get("platform_fee_pct", 0),
                payload.get("platform_fee_flat", 0),
                payload.get("platform_fee_cap", 0),
                payload.get("fund_fee_pct", 0),
                payload.get("uninvested_cash", 0),
                payload.get("cash_interest_rate", 0),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_catalogue_price(catalogue_id, price, currency, change_pct, updated_at):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE holding_catalogue
            SET last_price = ?, price_currency = ?, price_change_pct = ?, price_updated_at = ?
            WHERE id = ?
            """,
            (price, currency, change_pct, updated_at, catalogue_id),
        )
        conn.commit()


def sync_holding_prices_from_catalogue(catalogue_id, price, currency):
    """Propagate a refreshed catalogue price to all account holdings linked to it.

    Converts GBp → GBP automatically (Yahoo Finance returns pence for LSE funds).
    Updates both the per-unit price and the total value (units × price) on every
    holdings row that has holding_catalogue_id = catalogue_id.
    """
    # Always store GBP in the holdings table
    price_gbp = price / 100.0 if currency == "GBp" else price

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, units FROM holdings WHERE holding_catalogue_id = ?",
            (catalogue_id,),
        ).fetchall()
        for row in rows:
            units = float(row["units"] or 0)
            conn.execute(
                "UPDATE holdings SET price = ?, value = ? WHERE id = ?",
                (round(price_gbp, 4), round(units * price_gbp, 2), row["id"]),
            )
        conn.commit()
        return len(rows)  # how many holdings were updated


def fetch_catalogue_with_prices(user_id):
    """Return all active catalogue items for the user, including price data."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM holding_catalogue
            WHERE is_active = 1 AND user_id = ?
            ORDER BY holding_name ASC
            """,
            (user_id,),
        ).fetchall()


def fetch_instruments_in_use(user_id):
    """Return all instruments held in account holdings for a user, with catalogue price data where available."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                hc.id,
                COALESCE(hc.holding_name, h.holding_name)     AS holding_name,
                COALESCE(hc.ticker,       h.ticker)           AS ticker,
                COALESCE(hc.asset_type,   h.asset_type)       AS asset_type,
                COALESCE(hc.bucket,       h.bucket)           AS bucket,
                hc.last_price,
                hc.price_currency,
                hc.price_change_pct,
                hc.price_updated_at,
                COUNT(h.id)                                    AS usage_count,
                SUM(h.units)                                   AS total_units,
                SUM(h.value)                                   AS total_value
            FROM holdings h
            JOIN accounts a ON a.id = h.account_id
            LEFT JOIN holding_catalogue hc ON hc.id = h.holding_catalogue_id
            WHERE a.user_id = ?
            GROUP BY COALESCE(
                CAST(h.holding_catalogue_id AS TEXT),
                h.ticker,
                h.holding_name
            )
            ORDER BY COALESCE(hc.holding_name, h.holding_name)
            """,
            (user_id,),
        ).fetchall()


def fetch_all_holdings(user_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT h.*, a.name AS account_name, hc.price_updated_at
            FROM holdings h
            JOIN accounts a ON a.id = h.account_id
            LEFT JOIN holding_catalogue hc ON hc.id = h.holding_catalogue_id
            WHERE a.user_id = ?
            ORDER BY a.name, h.id
            """,
            (user_id,),
        ).fetchall()


def fetch_holding_catalogue(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM holding_catalogue WHERE is_active = 1 AND user_id = ? ORDER BY holding_name ASC",
            (user_id,),
        ).fetchall()


def fetch_holding_catalogue_in_use(user_id):
    """Return active catalogue items that are linked to at least one holding in an active account."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT hc.*
            FROM holding_catalogue hc
            JOIN holdings h ON h.holding_catalogue_id = hc.id
            JOIN accounts a ON a.id = h.account_id
            WHERE hc.is_active = 1
              AND a.user_id = ?
              AND a.is_active = 1
            GROUP BY hc.id
            ORDER BY hc.holding_name ASC
            """,
            (user_id,),
        ).fetchall()


def add_holding_catalogue_item(payload, user_id):
    """Insert a new catalogue entry. If a ticker already exists for this user, return its id."""
    ticker = (payload.get("ticker") or "").strip() or None
    with get_connection() as conn:
        # Deduplication: return existing row for the same ticker+user
        if ticker:
            existing = conn.execute(
                "SELECT id FROM holding_catalogue WHERE UPPER(ticker) = UPPER(?) AND user_id = ?",
                (ticker, user_id),
            ).fetchone()
            if existing:
                return existing["id"]
        cursor = conn.execute(
            """
            INSERT INTO holding_catalogue (user_id, holding_name, ticker, asset_type, bucket, notes, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                user_id,
                payload["holding_name"],
                ticker,
                payload.get("asset_type", ""),
                payload.get("bucket", ""),
                payload.get("notes", ""),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def fetch_catalogue_holding(catalogue_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM holding_catalogue WHERE id = ?",
            (catalogue_id,),
        ).fetchone()


def fetch_first_position_for_catalogue_holding(catalogue_id, user_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT h.id AS holding_id, h.account_id, a.name AS account_name
            FROM holdings h
            JOIN accounts a ON a.id = h.account_id
            WHERE h.holding_catalogue_id = ?
              AND a.user_id = ?
              AND a.is_active = 1
            ORDER BY a.id ASC, h.id ASC
            LIMIT 1
            """,
            (catalogue_id, user_id),
        ).fetchone()


def update_holding_catalogue_item(payload):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE holding_catalogue
            SET holding_name = ?,
                ticker = ?,
                asset_type = ?,
                bucket = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                payload["holding_name"],
                payload["ticker"],
                payload["asset_type"],
                payload["bucket"],
                payload.get("notes", ""),
                payload["id"],
            ),
        )
        conn.commit()


def delete_holding_catalogue_item(catalogue_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE holding_catalogue SET is_active = 0 WHERE id = ?",
            (catalogue_id,),
        )
        conn.commit()


def fetch_holding_totals_by_account(user_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT h.account_id, COALESCE(SUM(h.value), 0) AS holdings_total
            FROM holdings h
            JOIN accounts a ON a.id = h.account_id
            WHERE a.user_id = ?
            GROUP BY h.account_id
            """,
            (user_id,),
        ).fetchall()
        return {row["account_id"]: row["holdings_total"] for row in rows}


def add_holding(payload):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO holdings (account_id, holding_catalogue_id, holding_name, ticker, asset_type, bucket, value, units, price, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["account_id"],
                payload.get("holding_catalogue_id"),
                payload["holding_name"],
                payload["ticker"],
                payload["asset_type"],
                payload["bucket"],
                payload["value"],
                payload["units"],
                payload["price"],
                payload["notes"],
            ),
        )
        conn.commit()


def fetch_holding(holding_id, user_id=None):
    """Return a holding by id. If user_id is given, the row is only
    returned when its account belongs to that user."""
    with get_connection() as conn:
        if user_id is not None:
            return conn.execute(
                """
                SELECT h.* FROM holdings h
                JOIN accounts a ON a.id = h.account_id
                WHERE h.id = ? AND a.user_id = ?
                """,
                (holding_id, user_id),
            ).fetchone()
        return conn.execute(
            "SELECT * FROM holdings WHERE id = ?",
            (holding_id,),
        ).fetchone()


def fetch_holdings_for_account(account_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT h.*, hc.price_updated_at, hc.price_change_pct AS catalogue_change_pct
            FROM holdings h
            LEFT JOIN holding_catalogue hc ON hc.id = h.holding_catalogue_id
            WHERE h.account_id = ?
            ORDER BY h.holding_name, h.id
            """,
            (account_id,),
        ).fetchall()


def fetch_all_holdings_grouped(user_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT h.*, a.name AS account_name, a.provider, a.wrapper_type, a.valuation_mode
            FROM holdings h
            JOIN accounts a ON a.id = h.account_id
            WHERE a.is_active = 1 AND a.user_id = ?
            ORDER BY a.id ASC, h.holding_name ASC, h.id ASC
            """,
            (user_id,),
        ).fetchall()


def update_holding(payload, user_id):
    """Update a holding, scoped so the mutation only applies if the
    holding belongs to an account owned by user_id. Returns True on
    a real update, False if the id didn't match that user."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE holdings
            SET account_id = ?,
                holding_catalogue_id = ?,
                holding_name = ?,
                ticker = ?,
                asset_type = ?,
                bucket = ?,
                value = ?,
                units = ?,
                price = ?,
                notes = ?
            WHERE id = ?
              AND account_id IN (SELECT id FROM accounts WHERE user_id = ?)
            """,
            (
                payload["account_id"],
                payload.get("holding_catalogue_id"),
                payload["holding_name"],
                payload["ticker"],
                payload["asset_type"],
                payload["bucket"],
                payload["value"],
                payload["units"],
                payload["price"],
                payload["notes"],
                payload["id"],
                user_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_holding(holding_id, user_id):
    """Delete a holding only if it belongs to an account owned by user_id."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM holdings
            WHERE id = ?
              AND account_id IN (SELECT id FROM accounts WHERE user_id = ?)
            """,
            (holding_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def reconnect_holdings_to_catalogue(ticker: str, catalogue_id: int) -> None:
    """Point any existing holdings whose ticker matches to the given catalogue entry.

    Run this after creating or re-creating a catalogue item so that previously
    disconnected holdings (e.g. after a catalogue wipe) get re-linked for price sync.
    """
    if not ticker:
        return
    with get_connection() as conn:
        conn.execute(
            """UPDATE holdings
               SET holding_catalogue_id = ?
               WHERE UPPER(ticker) = UPPER(?)
                 AND (holding_catalogue_id IS NULL OR holding_catalogue_id != ?)""",
            (catalogue_id, ticker, catalogue_id),
        )
        conn.commit()


def reset_catalogue(user_id):
    """Wipe all catalogue entries for a user. Holdings in accounts are not affected."""
    with get_connection() as conn:
        conn.execute("DELETE FROM holding_catalogue WHERE user_id = ?", (user_id,))
        conn.commit()


def reset_all_user_data(user_id):
    """Wipe every piece of user data back to a fresh-login state.

    Deletes: accounts (and their holdings), goals, assumptions,
    holding catalogue, monthly snapshots, allowance tracking,
    monthly reviews + items, budget items/entries/sections,
    and contribution overrides.

    The user row itself is kept so they can log straight back in.
    """
    with get_connection() as conn:
        # Holdings reference accounts, so delete them first
        conn.execute(
            "DELETE FROM holdings WHERE account_id IN "
            "(SELECT id FROM accounts WHERE user_id = ?)", (user_id,))
        conn.execute(
            "DELETE FROM contribution_overrides WHERE account_id IN "
            "(SELECT id FROM accounts WHERE user_id = ?)", (user_id,))
        # Snapshots FK to accounts, so delete before accounts
        conn.execute(
            "DELETE FROM monthly_snapshots WHERE account_id IN "
            "(SELECT id FROM accounts WHERE user_id = ?)", (user_id,))
        conn.execute("DELETE FROM accounts WHERE user_id = ?", (user_id,))

        conn.execute("DELETE FROM goals WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM assumptions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM holding_catalogue WHERE user_id = ?", (user_id,))

        # allowance_tracking has no user_id — wipe all rows (single-user table)
        conn.execute("DELETE FROM allowance_tracking")

        # Monthly reviews + their line items
        conn.execute(
            "DELETE FROM monthly_review_items WHERE review_id IN "
            "(SELECT id FROM monthly_reviews WHERE user_id = ?)", (user_id,))
        conn.execute("DELETE FROM monthly_reviews WHERE user_id = ?", (user_id,))

        # Budget (entries FK to items, so delete entries first)
        conn.execute(
            "DELETE FROM budget_entries WHERE budget_item_id IN "
            "(SELECT id FROM budget_items WHERE user_id = ?)", (user_id,))
        conn.execute("DELETE FROM budget_items WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM budget_sections WHERE user_id = ?", (user_id,))

        conn.commit()


WRAPPER_TYPE_OPTIONS = [
    "Stocks & Shares ISA",
    "Cash ISA",
    "Lifetime ISA",
    "SIPP",
    "Workplace Pension",
    "General Investment Account",
    "Other",
]

CATEGORY_OPTIONS = [
    "ISA",
    "Pension",
    "Taxable",
    "Other",
]

DEFAULT_TAG_OPTIONS = [
    "Retirement",
    "Emergency Fund",
    "Accessible Investing",
    "General Investing",
    "Short-Term Savings",
    "Bridge to Retirement",
    "Long-Term",
    "Other",
]

# Keep old name for backwards compat
TAG_OPTIONS = DEFAULT_TAG_OPTIONS


def fetch_user_tags(user_id):
    """Return merged list: default tags + user's custom tags (de-duped, ordered)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tag FROM custom_tags WHERE user_id = ? ORDER BY tag",
            (user_id,),
        ).fetchall()
    custom = [r["tag"] for r in rows]
    # Defaults first, then any custom ones not already in defaults
    merged = list(DEFAULT_TAG_OPTIONS)
    for tag in custom:
        if tag not in merged:
            merged.append(tag)
    return merged


def fetch_custom_tags(user_id):
    """Return just the user's custom tags."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tag FROM custom_tags WHERE user_id = ? ORDER BY tag",
            (user_id,),
        ).fetchall()
    return [r["tag"] for r in rows]


def add_custom_tag(user_id, tag):
    """Add a custom tag for a user. Returns True if added, False if duplicate."""
    tag = tag.strip()
    if not tag:
        return False
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO custom_tags (user_id, tag) VALUES (?, ?)",
                (user_id, tag),
            )
            conn.commit()
            return True
        except Exception:
            return False


def delete_custom_tag(user_id, tag):
    """Remove a custom tag. Returns True if deleted."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM custom_tags WHERE user_id = ? AND tag = ?",
            (user_id, tag),
        )
        conn.commit()
        return cur.rowcount > 0

DEFAULT_HOLDING_CATALOGUE = [  # kept for reference only — no longer auto-seeded
    # ── Global equity ETFs ─────────────────────────────────────────────────
    {"holding_name": "Vanguard FTSE Developed World UCITS ETF (Acc)", "ticker": "VHVG", "asset_type": "ETF", "bucket": "Developed World Equity", "notes": ""},
    {"holding_name": "Vanguard FTSE All-World UCITS ETF (Acc)", "ticker": "VWRP", "asset_type": "ETF", "bucket": "Global / All-World Equity", "notes": ""},
    {"holding_name": "Vanguard FTSE All-World UCITS ETF (Dist)", "ticker": "VWRL", "asset_type": "ETF", "bucket": "Global / All-World Equity", "notes": ""},
    {"holding_name": "Vanguard FTSE Global All Cap Index Fund", "ticker": "", "asset_type": "Fund", "bucket": "Global / All-World Equity", "notes": "Includes small cap"},
    {"holding_name": "Vanguard FTSE Emerging Markets UCITS ETF (Acc)", "ticker": "VFEG", "asset_type": "ETF", "bucket": "Emerging Markets Equity", "notes": ""},
    {"holding_name": "iShares Core MSCI World UCITS ETF (Acc)", "ticker": "SWDA", "asset_type": "ETF", "bucket": "Developed World Equity", "notes": "MSCI World, USD-based"},
    {"holding_name": "iShares MSCI All Country World UCITS ETF (Acc)", "ticker": "SSAC", "asset_type": "ETF", "bucket": "Global / All-World Equity", "notes": ""},
    {"holding_name": "iShares Core MSCI Emerging Markets IMI UCITS ETF", "ticker": "EMIM", "asset_type": "ETF", "bucket": "Emerging Markets Equity", "notes": ""},
    {"holding_name": "HSBC FTSE All-World Index C Acc", "ticker": "0P00013P6I.L", "asset_type": "Fund", "bucket": "Global / All-World Equity", "notes": ""},
    {"holding_name": "Fidelity Index World Fund P Accumulation", "ticker": "", "asset_type": "Fund", "bucket": "Developed World Equity", "notes": "MSCI World tracker"},
    {"holding_name": "Fidelity Index Emerging Markets Fund P Accumulation", "ticker": "", "asset_type": "Fund", "bucket": "Emerging Markets Equity", "notes": ""},
    {"holding_name": "L&G International Index Trust I Acc", "ticker": "", "asset_type": "Fund", "bucket": "Developed World Equity", "notes": ""},
    {"holding_name": "Invesco FTSE All-World UCITS ETF Acc", "ticker": "FWRG", "asset_type": "ETF", "bucket": "Global / All-World Equity", "notes": "Lower ongoing charges"},
    # ── UK equity ─────────────────────────────────────────────────────────
    {"holding_name": "Vanguard FTSE 100 UCITS ETF (Dist)", "ticker": "VUKE", "asset_type": "ETF", "bucket": "UK Equity", "notes": ""},
    {"holding_name": "Vanguard FTSE UK All Share Index Unit Trust Acc", "ticker": "", "asset_type": "Fund", "bucket": "UK Equity", "notes": ""},
    {"holding_name": "iShares Core FTSE 100 UCITS ETF (Dist)", "ticker": "ISF", "asset_type": "ETF", "bucket": "UK Equity", "notes": ""},
    {"holding_name": "Fidelity Index UK Fund P Accumulation", "ticker": "", "asset_type": "Fund", "bucket": "UK Equity", "notes": ""},
    # ── Vanguard LifeStrategy ──────────────────────────────────────────────
    {"holding_name": "Vanguard LifeStrategy 100% Equity Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "Global / All-World Equity", "notes": "100% equities, UK-biased"},
    {"holding_name": "Vanguard LifeStrategy 80% Equity Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "Mixed / Multi-Asset", "notes": "80% equity, 20% bonds"},
    {"holding_name": "Vanguard LifeStrategy 60% Equity Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "Mixed / Multi-Asset", "notes": "60% equity, 40% bonds"},
    {"holding_name": "Vanguard LifeStrategy 40% Equity Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "Mixed / Multi-Asset", "notes": "40% equity, 60% bonds"},
    # ── Bonds / Fixed income ───────────────────────────────────────────────
    {"holding_name": "Vanguard UK Government Bond Index Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "UK Bonds / Fixed Income", "notes": ""},
    {"holding_name": "Vanguard Global Bond Index Fund GBP Hedged Acc", "ticker": "", "asset_type": "Fund", "bucket": "Global Bonds", "notes": ""},
    {"holding_name": "iShares Core Global Aggregate Bond UCITS ETF GBP Hedged", "ticker": "AGBP", "asset_type": "ETF", "bucket": "Global Bonds", "notes": ""},
    {"holding_name": "Vanguard U.S. Government Bond Index Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "US Bonds", "notes": ""},
    # ── US equity ─────────────────────────────────────────────────────────
    {"holding_name": "Vanguard S&P 500 UCITS ETF (Acc)", "ticker": "VUAG", "asset_type": "ETF", "bucket": "US Equity", "notes": ""},
    {"holding_name": "Vanguard S&P 500 UCITS ETF (Dist)", "ticker": "VUSA", "asset_type": "ETF", "bucket": "US Equity", "notes": ""},
    {"holding_name": "iShares Core S&P 500 UCITS ETF (Acc)", "ticker": "CSP1", "asset_type": "ETF", "bucket": "US Equity", "notes": ""},
    {"holding_name": "Fidelity Index US Fund P Accumulation", "ticker": "", "asset_type": "Fund", "bucket": "US Equity", "notes": "S&P 500 tracker"},
    # ── Pension fund defaults ──────────────────────────────────────────────
    {"holding_name": "SL abrdn Evolve World Equity Index Pension Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "Standard Life workplace pension default"},
    {"holding_name": "Nest Higher Risk Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "Nest workplace pension"},
    {"holding_name": "Nest Sharia Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "Nest workplace pension"},
    {"holding_name": "Aviva My Future Focus Growth Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Mixed / Multi-Asset", "notes": "Aviva workplace pension default"},
    {"holding_name": "Legal & General PMC Global Equity Fixed Weights (50:50) Index", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "L&G workplace pension"},
    {"holding_name": "Legal & General PMC World Equity Index Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Developed World Equity", "notes": "L&G workplace pension"},
    {"holding_name": "Royal London Global Equity Select Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "Royal London workplace pension"},
    # ── Money market / cash ────────────────────────────────────────────────
    {"holding_name": "Royal London Short Term Money Market Fund", "ticker": "", "asset_type": "Fund", "bucket": "Cash / Money Market", "notes": ""},
    {"holding_name": "Vanguard Sterling Short-Term Money Market Fund", "ticker": "", "asset_type": "Fund", "bucket": "Cash / Money Market", "notes": ""},
    # ── InvestEngine / Dodl popular ───────────────────────────────────────
    {"holding_name": "iShares MSCI World Small Cap UCITS ETF", "ticker": "WLDS", "asset_type": "ETF", "bucket": "Developed World Equity", "notes": "Small cap global"},
    {"holding_name": "Xtrackers MSCI World Swap UCITS ETF 1C", "ticker": "XDWD", "asset_type": "ETF", "bucket": "Developed World Equity", "notes": "Synthetic replication"},
]


# ── Budget ──────────────────────────────────────────────────────────────────

def fetch_budget_items(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM budget_items WHERE is_active = 1 AND user_id = ? ORDER BY section, sort_order, id",
            (user_id,),
        ).fetchall()


def fetch_budget_item(item_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM budget_items WHERE id = ?", (item_id,)
        ).fetchone()


def create_budget_item(payload, user_id):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO budget_items (user_id, name, section, default_amount, linked_account_id, notes, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                user_id,
                payload["name"],
                payload["section"],
                payload["default_amount"],
                payload.get("linked_account_id"),
                payload.get("notes", ""),
                payload.get("sort_order", 0),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_budget_item(payload, user_id):
    """Update a budget item, scoped to user_id."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE budget_items
            SET name = ?, section = ?, default_amount = ?, linked_account_id = ?, notes = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                payload["name"],
                payload["section"],
                payload["default_amount"],
                payload.get("linked_account_id"),
                payload.get("notes", ""),
                payload["id"],
                user_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_budget_item(item_id, user_id):
    """Soft-delete a budget item, scoped to user_id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE budget_items SET is_active = 0 WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_budget_items_by_section(section_key, user_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE budget_items SET is_active = 0 WHERE section = ? AND user_id = ?",
            (section_key, user_id),
        )
        conn.commit()


_DEFAULT_SECTIONS = [
    ("income", "Income", 0),
    ("fixed", "Fixed Expenses", 1),
    ("debt", "Debt Repayment", 2),
    ("investment", "Investments & Savings", 3),
    ("discretionary", "Discretionary", 4),
]


def fetch_budget_sections(user_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM budget_sections WHERE user_id = ? ORDER BY sort_order, id",
            (user_id,),
        ).fetchall()
        # Always fill in any missing defaults (handles partial seeding from old migration bug)
        existing_keys = {r["key"] for r in rows}
        missing = [(k, l, o) for k, l, o in _DEFAULT_SECTIONS if k not in existing_keys]
        if missing:
            conn.executemany(
                "INSERT OR IGNORE INTO budget_sections (user_id, key, label, sort_order) VALUES (?, ?, ?, ?)",
                [(user_id, k, l, o) for k, l, o in missing],
            )
            conn.commit()
            rows = conn.execute(
                "SELECT * FROM budget_sections WHERE user_id = ? ORDER BY sort_order, id",
                (user_id,),
            ).fetchall()
        return rows


def create_budget_section(label, user_id):
    with get_connection() as conn:
        key = label.lower().replace(" ", "_").replace("&", "and")
        existing = conn.execute(
            "SELECT MAX(sort_order) as m FROM budget_sections WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        sort_order = (existing["m"] or 0) + 1
        conn.execute(
            "INSERT OR IGNORE INTO budget_sections (user_id, key, label, sort_order) VALUES (?, ?, ?, ?)",
            (user_id, key, label, sort_order),
        )
        conn.commit()
        return key


def update_budget_section(key, label, user_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE budget_sections SET label = ? WHERE key = ? AND user_id = ?",
            (label, key, user_id),
        )
        conn.commit()


def delete_budget_section(key, user_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE budget_items SET is_active = 0 WHERE section = ? AND user_id = ?",
            (key, user_id),
        )
        conn.execute(
            "DELETE FROM budget_sections WHERE key = ? AND user_id = ?",
            (key, user_id),
        )
        conn.commit()


def fetch_budget_entries(month_key, user_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT be.* FROM budget_entries be
            JOIN budget_items bi ON bi.id = be.budget_item_id
            WHERE be.month_key = ? AND bi.user_id = ?
            """,
            (month_key, user_id),
        ).fetchall()


def fetch_prior_month_budget_entries(month_key, user_id):
    """Return entries from the most recent month that has saved entries before month_key, for the given user."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT be.month_key FROM budget_entries be
            JOIN budget_items bi ON bi.id = be.budget_item_id
            WHERE be.month_key < ? AND bi.user_id = ?
            ORDER BY be.month_key DESC
            LIMIT 1
            """,
            (month_key, user_id),
        ).fetchone()
        if row is None:
            return []
        prior_key = row["month_key"]
        return conn.execute(
            """
            SELECT be.* FROM budget_entries be
            JOIN budget_items bi ON bi.id = be.budget_item_id
            WHERE be.month_key = ? AND bi.user_id = ?
            """,
            (prior_key, user_id),
        ).fetchall()


def fetch_months_with_budget_entries(user_id):
    """Return a set of month_key strings (e.g. '2026-04') that have saved budget entries."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT be.month_key
            FROM budget_entries be
            JOIN budget_items bi ON bi.id = be.budget_item_id
            WHERE bi.user_id = ?
            ORDER BY be.month_key
            """,
            (user_id,),
        ).fetchall()
        return {r["month_key"] for r in rows}


def upsert_budget_entry(month_key, item_id, amount):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO budget_entries (month_key, budget_item_id, amount)
            VALUES (?, ?, ?)
            ON CONFLICT(month_key, budget_item_id) DO UPDATE SET amount = excluded.amount
            """,
            (month_key, item_id, amount),
        )
        conn.commit()


# ── Monthly snapshots ─────────────────────────────────────────────────────────

def upsert_monthly_snapshot(account_id, month_key, balance):
    """Write or overwrite a snapshot for one account for a given month."""
    snapshot_date = month_key + "-01"
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM monthly_snapshots WHERE account_id = ? AND month_key = ?",
            (account_id, month_key),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE monthly_snapshots SET balance = ?, snapshot_date = ? WHERE id = ?",
                (balance, snapshot_date, existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO monthly_snapshots (snapshot_date, account_id, balance, month_key)
                VALUES (?, ?, ?, ?)
                """,
                (snapshot_date, account_id, balance, month_key),
            )
        conn.commit()


def fetch_net_worth_history(user_id, limit=24):
    """Return (month_key, total_balance) pairs for the last `limit` months that have snapshots."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ms.month_key, SUM(ms.balance) AS total
            FROM monthly_snapshots ms
            JOIN accounts a ON a.id = ms.account_id
            WHERE ms.month_key IS NOT NULL AND a.user_id = ?
            GROUP BY ms.month_key
            ORDER BY ms.month_key ASC
            """,
            (user_id,),
        ).fetchall()
    return [(r["month_key"], r["total"]) for r in rows[-limit:]]


def fetch_account_snapshot_history(account_id, limit=24):
    """Return (month_key, balance) pairs for one account for the last `limit` months that have snapshots."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT month_key, balance
            FROM monthly_snapshots
            WHERE account_id = ?
              AND month_key IS NOT NULL
            ORDER BY month_key ASC
            """,
            (account_id,),
        ).fetchall()
    return [(r["month_key"], r["balance"]) for r in rows[-limit:]]


def fetch_monthly_performance_data(user_id):
    """Return list of (month_key, total_balance, total_contribution) ordered by month."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                ms.month_key,
                SUM(ms.balance) AS total_balance,
                COALESCE(SUM(mri.expected_contribution), 0) AS total_contribution
            FROM monthly_snapshots ms
            JOIN accounts a ON a.id = ms.account_id
            LEFT JOIN monthly_reviews mr ON mr.month_key = ms.month_key AND mr.user_id = ?
            LEFT JOIN monthly_review_items mri
                   ON mri.review_id = mr.id AND mri.account_id = ms.account_id
            WHERE ms.month_key IS NOT NULL AND a.user_id = ?
            GROUP BY ms.month_key
            ORDER BY ms.month_key ASC
            """,
            (user_id, user_id),
        ).fetchall()
    return [(r["month_key"], r["total_balance"], r["total_contribution"]) for r in rows]


def fetch_monthly_performance_data_by_account(user_id):
    """Return per-account monthly performance data.

    Returns a dict keyed by account_id:
        {account_id: {"account_name": str, "rows": [(month_key, balance, contribution), ...]}}
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.id AS account_id,
                a.name AS account_name,
                ms.month_key,
                ms.balance AS balance,
                COALESCE(mri.expected_contribution, 0) AS contribution
            FROM monthly_snapshots ms
            JOIN accounts a ON a.id = ms.account_id
            LEFT JOIN monthly_reviews mr ON mr.month_key = ms.month_key AND mr.user_id = ?
            LEFT JOIN monthly_review_items mri
                   ON mri.review_id = mr.id AND mri.account_id = ms.account_id
            WHERE ms.month_key IS NOT NULL
              AND a.user_id = ?
            ORDER BY a.name ASC, ms.month_key ASC
            """,
            (user_id, user_id),
        ).fetchall()

    out = {}
    for r in rows:
        aid = int(r["account_id"])
        if aid not in out:
            out[aid] = {"account_name": r["account_name"], "rows": []}
        out[aid]["rows"].append((r["month_key"], float(r["balance"] or 0), float(r["contribution"] or 0)))
    return out


# ── Contribution overrides ────────────────────────────────────────────────────

def fetch_contribution_overrides(account_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM contribution_overrides WHERE account_id = ? ORDER BY from_month ASC",
            (account_id,),
        ).fetchall()


def fetch_all_active_overrides(month_key, user_id):
    """Return overrides that are active for a given month, keyed by account_id."""
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
    from datetime import datetime
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
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def delete_contribution_override(override_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM contribution_overrides WHERE id = ?", (override_id,))
        conn.commit()


# ── Portfolio daily snapshots ──────────────────────────────────────────────────

def save_daily_snapshot(user_id, total_value, snapshot_date=None):
    """Save or update a portfolio snapshot for a given user and date.

    Uses INSERT OR REPLACE to handle the UNIQUE(user_id, snapshot_date) constraint.
    If snapshot_date is None, uses today's date.
    """
    from datetime import datetime
    if snapshot_date is None:
        snapshot_date = datetime.now().strftime("%Y-%m-%d")

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO portfolio_daily_snapshots (user_id, snapshot_date, total_value, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (user_id, snapshot_date, total_value),
        )
        conn.commit()


def fetch_daily_snapshots(user_id, limit=365):
    """Fetch daily portfolio snapshots for a user, limited to the last N days.

    Returns a list of (snapshot_date, total_value) tuples ordered by date ASC.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT snapshot_date, total_value FROM portfolio_daily_snapshots
            WHERE user_id = ?
            ORDER BY snapshot_date ASC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [(r["snapshot_date"], float(r["total_value"])) for r in rows]


# ── API tokens ────────────────────────────────────────────────────────────────
# Bearer tokens for the JSON API. Tokens are random 32-byte hex strings
# generated with secrets.token_hex(32). Stored in plaintext: this is a
# self-hosted personal app where DB access already implies full compromise.
# If you want hashed tokens, swap to secrets.compare_digest against a hash.

def create_api_token(user_id, label=None):
    import secrets
    token = secrets.token_hex(32)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO api_tokens (user_id, token, label) VALUES (?, ?, ?)",
            (user_id, token, label),
        )
        conn.commit()
    return token


def fetch_user_by_api_token(token):
    if not token:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.* FROM users u
            JOIN api_tokens t ON t.user_id = u.id
            WHERE t.token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE api_tokens SET last_used_at = datetime('now') WHERE token = ?",
            (token,),
        )
        conn.commit()
    return User(row["id"], row["username"], row["password_hash"], row["is_admin"])


def fetch_api_tokens(user_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, label, created_at, last_used_at,
                   substr(token, 1, 8) AS token_preview
            FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()


def revoke_api_token(token_id, user_id):
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM api_tokens WHERE id = ? AND user_id = ?",
            (token_id, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0
