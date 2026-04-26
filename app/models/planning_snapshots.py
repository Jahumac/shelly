"""Portfolio snapshots: monthly, daily, and performance history."""
from datetime import datetime
from ._conn import get_connection


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
    """Return (month_key, total_balance) pairs for the last `limit` months."""
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
    """Return (month_key, balance) pairs for one account."""
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
    """Return monthly performance rows ordered by month.

    For each account, use that month's snapshot when present; otherwise carry
    forward the last known snapshot before that month. This prevents a partial
    month (for example, updating only a new Cash ISA) from making every other
    account look like it fell to zero.
    """
    with get_connection() as conn:
        months = conn.execute(
            """
            SELECT DISTINCT ms.month_key
            FROM monthly_snapshots ms
            JOIN accounts a ON a.id = ms.account_id
            WHERE ms.month_key IS NOT NULL
              AND a.user_id = ?
              AND a.is_active = 1
            ORDER BY ms.month_key ASC
            """,
            (user_id,),
        ).fetchall()
        accounts = conn.execute(
            "SELECT id FROM accounts WHERE user_id = ? AND is_active = 1 ORDER BY id ASC",
            (user_id,),
        ).fetchall()
        rows = []
        for month in months:
            month_key = month["month_key"]
            total_balance = 0.0
            carried_forward = 0
            accounts_with_value = 0

            for account in accounts:
                snap = conn.execute(
                    """
                    SELECT balance, month_key
                    FROM monthly_snapshots
                    WHERE account_id = ?
                      AND month_key <= ?
                    ORDER BY month_key DESC
                    LIMIT 1
                    """,
                    (account["id"], month_key),
                ).fetchone()
                if not snap:
                    continue
                accounts_with_value += 1
                total_balance += float(snap["balance"] or 0)
                if snap["month_key"] != month_key:
                    carried_forward += 1

            if accounts_with_value == 0:
                continue

            contrib = conn.execute(
                """
                SELECT COALESCE(SUM(mri.expected_contribution), 0) AS total_contribution
                FROM monthly_reviews mr
                JOIN monthly_review_items mri ON mri.review_id = mr.id
                JOIN accounts a ON a.id = mri.account_id
                WHERE mr.user_id = ?
                  AND mr.month_key = ?
                  AND a.user_id = ?
                """,
                (user_id, month_key, user_id),
            ).fetchone()
            rows.append({
                "month_key": month_key,
                "total_balance": total_balance,
                "total_contribution": float(contrib["total_contribution"] or 0) if contrib else 0.0,
                "carried_forward_count": carried_forward,
            })
    return [
        (r["month_key"], r["total_balance"], r["total_contribution"], r["carried_forward_count"])
        for r in rows
    ]

def fetch_monthly_performance_data_by_account(user_id):
    """Return per-account monthly performance data keyed by account_id."""
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


# ── Daily snapshots ───────────────────────────────────────────────────────────

def save_daily_snapshot(user_id, total_value, snapshot_date=None):
    """Save or update a portfolio snapshot for a given user and date."""
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
    """Return (snapshot_date, total_value) tuples ordered ASC, last N days."""
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


def save_account_daily_snapshots(user_id, account_values, snapshot_date=None):
    """Save per-account daily snapshots.

    account_values: list of (account_id, value) tuples.
    """
    if snapshot_date is None:
        snapshot_date = datetime.now().strftime("%Y-%m-%d")

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO account_daily_snapshots (user_id, account_id, snapshot_date, value)
            VALUES (?, ?, ?, ?)
            """,
            [(user_id, acct_id, snapshot_date, value) for acct_id, value in account_values],
        )
        conn.commit()


def fetch_account_daily_snapshots(account_id, limit=365):
    """Return (snapshot_date, value) pairs for one account, ordered ASC, last N days."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT snapshot_date, value FROM account_daily_snapshots
            WHERE account_id = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
            """,
            (account_id, limit),
        ).fetchall()
    return [(r["snapshot_date"], float(r["value"])) for r in reversed(rows)]
