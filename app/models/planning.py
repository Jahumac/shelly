"""Long-term planning, snapshots, and tax-allowance tracking.

A grab-bag of everything that isn't account/holding/goal/budget CRUD:
- assumptions (growth rate, retirement age, allowances)
- monthly reviews + monthly snapshots
- ad-hoc ISA / pension / dividend contribution records
- contribution overrides (temporary plan changes)
- daily portfolio snapshots + performance history
- per-user tag management
- whole-account/data resets

Imports fetch_all_accounts from .accounts because ensure_monthly_review_items
needs it.
"""
from ._conn import get_connection
from .accounts import fetch_all_accounts


# ── Assumptions ───────────────────────────────────────────────────────────────

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



# ── Allowance tracking ────────────────────────────────────────────────────────

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



# ── ISA / pension / dividend ad-hoc records ───────────────────────────────────

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


# ── Monthly reviews ───────────────────────────────────────────────────────────

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



# ── Whole-account / data resets ───────────────────────────────────────────────

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



# ── Tags ──────────────────────────────────────────────────────────────────────

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


# ── Snapshots + performance ───────────────────────────────────────────────────

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

# ── Contribution overrides ────────────────────────────────────────────────────

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


# ── Daily snapshots ───────────────────────────────────────────────────────────

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

