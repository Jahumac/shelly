"""Monthly reviews: fetch, create, update, review items, contribution flags."""
from ._conn import get_connection
from .accounts import fetch_all_accounts


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


def fetch_monthly_review(month_key, user_id):
    """Read-only fetch — returns None if no review exists (never creates one)."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM monthly_reviews WHERE month_key = ? AND user_id = ?",
            (month_key, user_id),
        ).fetchone()


def fetch_monthly_review_items(review_id):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT mri.*, a.name AS account_name, a.provider, a.wrapper_type, a.valuation_mode,
                   a.monthly_contribution AS account_monthly_contribution, a.current_value
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
        review = conn.execute(
            "SELECT month_key, status FROM monthly_reviews WHERE id = ? AND user_id = ?",
            (review_id, user_id),
        ).fetchone()
        if not review:
            return
        month_key = review["month_key"]
        is_complete = review["status"] == "complete"

        existing_rows = conn.execute(
            "SELECT account_id, expected_contribution FROM monthly_review_items WHERE review_id = ?",
            (review_id,),
        ).fetchall()
        existing_map = {row["account_id"]: float(row["expected_contribution"] or 0) for row in existing_rows}

        for account in accounts:
            override = conn.execute(
                """
                SELECT override_amount
                FROM contribution_overrides
                WHERE account_id = ?
                  AND from_month <= ?
                  AND to_month >= ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (account["id"], month_key, month_key),
            ).fetchone()
            expected = (
                float(override["override_amount"])
                if override is not None
                else float(account["monthly_contribution"] or 0)
            )

            if account["id"] not in existing_map:
                conn.execute(
                    """
                    INSERT INTO monthly_review_items (
                        review_id, account_id, expected_contribution,
                        contribution_confirmed, holdings_updated, balance_updated, notes
                    )
                    VALUES (?, ?, ?, 0, 0, 0, '')
                    """,
                    (review_id, account["id"], expected),
                )
            elif not is_complete and existing_map[account["id"]] != expected:
                # Sync when account contribution changed and review isn't locked
                conn.execute(
                    """
                    UPDATE monthly_review_items
                    SET expected_contribution = ?
                    WHERE review_id = ? AND account_id = ?
                    """,
                    (expected, review_id, account["id"]),
                )
        conn.commit()


def update_monthly_review(review_id, status, notes, user_id=None):
    user_clause = " AND user_id = ?" if user_id is not None else ""
    with get_connection() as conn:
        if status == "complete":
            conn.execute(
                f"""
                UPDATE monthly_reviews
                SET status = ?, notes = ?, completed_at = datetime('now'), updated_at = datetime('now')
                WHERE id = ?{user_clause}
                """,
                (status, notes, review_id) if user_id is None else (status, notes, review_id, user_id),
            )
        else:
            conn.execute(
                f"""
                UPDATE monthly_reviews
                SET status = ?, notes = ?, completed_at = NULL, updated_at = datetime('now')
                WHERE id = ?{user_clause}
                """,
                (status, notes, review_id) if user_id is None else (status, notes, review_id, user_id),
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


def set_contribution_confirmed(item_id, review_id, confirmed):
    """Toggle contribution_confirmed for a single review item."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE monthly_review_items SET contribution_confirmed = ? WHERE id = ? AND review_id = ?",
            (1 if confirmed else 0, item_id, review_id),
        )
        conn.commit()


def fetch_tax_year_contributions(user_id, from_month, to_month):
    """Return per-account contribution data for months in a tax year range.

    from_month / to_month: 'YYYY-MM' strings (inclusive).
    Returns a list of dicts: {account_id, account_name, wrapper_type, month_key,
                               expected_contribution, contribution_confirmed}
    """
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                a.id AS account_id,
                a.name AS account_name,
                a.wrapper_type,
                mr.month_key,
                mri.expected_contribution,
                mri.contribution_confirmed,
                CASE WHEN co.id IS NOT NULL THEN 1 ELSE 0 END AS is_skipped
            FROM monthly_review_items mri
            JOIN monthly_reviews mr ON mr.id = mri.review_id
            JOIN accounts a ON a.id = mri.account_id
            LEFT JOIN contribution_overrides co
                   ON co.account_id = mri.account_id
                  AND mr.month_key >= co.from_month
                  AND mr.month_key <= co.to_month
                  AND co.override_amount = 0
            WHERE mr.user_id = ?
              AND mr.month_key >= ?
              AND mr.month_key <= ?
            ORDER BY a.name ASC, mr.month_key ASC
            """,
            (user_id, from_month, to_month),
        ).fetchall()


def mark_review_item_updated(review_id, account_id, field):
    """Mark holdings_updated or balance_updated = 1 for a review item."""
    if field == "holdings_updated":
        col = "holdings_updated"
    elif field == "balance_updated":
        col = "balance_updated"
    else:
        return
    with get_connection() as conn:
        conn.execute(
            f"UPDATE monthly_review_items SET {col} = 1 WHERE review_id = ? AND account_id = ?",
            (review_id, account_id),
        )
        conn.commit()
