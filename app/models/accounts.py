"""Accounts, holdings, and the holding catalogue.

These three concepts are tightly coupled (an account contains holdings;
a holding usually points to a catalogue entry that carries the live price)
so they live together. fetch_latest_price_update lives here too because
it joins the catalogue.
"""
from ._conn import get_connection


# ── Accounts list ─────────────────────────────────────────────────────────────

def fetch_all_accounts(user_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM accounts WHERE is_active = 1 AND user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()



# ── Catalogue price freshness ─────────────────────────────────────────────────

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

# ── Account CRUD ──────────────────────────────────────────────────────────────

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


def update_account(payload, user_id=None):
    where = "WHERE id = ? AND user_id = ?" if user_id is not None else "WHERE id = ?"
    params_tail = (payload["id"], user_id) if user_id is not None else (payload["id"],)
    with get_connection() as conn:
        conn.execute(
            f"""
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
            {where}
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
                *params_tail,
            ),
        )
        conn.commit()


def delete_account(account_id, user_id=None):
    with get_connection() as conn:
        if user_id is not None:
            conn.execute(
                "UPDATE accounts SET is_active = 0 WHERE id = ? AND user_id = ?",
                (account_id, user_id),
            )
        else:
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



# ── Catalogue prices ──────────────────────────────────────────────────────────

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


# ── Holdings + catalogue items ────────────────────────────────────────────────

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


