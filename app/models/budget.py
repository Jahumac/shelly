"""Budget items, sections, and per-month entries.

A budget_item is a recurring line ("Rent", "Groceries"). A section groups
items ("Income", "Fixed expenses"). An entry is the actual amount for a
given month. Default is the item's default_amount; entries override.
"""
from ._conn import get_connection


def fetch_budget_items(user_id):
    with get_connection() as conn:
        _ensure_account_contribution_items(conn, user_id)
        return conn.execute(
            "SELECT * FROM budget_items WHERE is_active = 1 AND user_id = ? ORDER BY section, sort_order, id",
            (user_id,),
        ).fetchall()


def _ensure_account_contribution_items(conn, user_id):
    """Keep account monthly contributions visible in Budget automatically."""
    existing_sections = conn.execute(
        "SELECT key FROM budget_sections WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    existing_keys = {row["key"] for row in existing_sections}
    missing = [(k, l, o) for k, l, o in _DEFAULT_SECTIONS if k not in existing_keys]
    if missing:
        conn.executemany(
            "INSERT OR IGNORE INTO budget_sections (user_id, key, label, sort_order) VALUES (?, ?, ?, ?)",
            [(user_id, k, l, o) for k, l, o in missing],
        )

    investment_section = conn.execute(
        """
        SELECT key FROM budget_sections
        WHERE user_id = ?
          AND (lower(key) LIKE '%invest%' OR lower(key) LIKE '%saving%')
        ORDER BY sort_order, id
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    section_key = investment_section["key"] if investment_section else "investment"

    accounts = conn.execute(
        """
        SELECT id, name
        FROM accounts
        WHERE user_id = ?
          AND is_active = 1
          AND COALESCE(monthly_contribution, 0) > 0
        ORDER BY id ASC
        """,
        (user_id,),
    ).fetchall()

    for account in accounts:
        existing = conn.execute(
            """
            SELECT id FROM budget_items
            WHERE user_id = ?
              AND linked_account_id = ?
              AND is_active = 1
            LIMIT 1
            """,
            (user_id, account["id"]),
        ).fetchone()
        if not existing:
            sort_row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) AS max_sort FROM budget_items WHERE user_id = ? AND section = ?",
                (user_id, section_key),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO budget_items (
                    user_id, name, section, default_amount, linked_account_id,
                    notes, sort_order, is_active
                )
                VALUES (?, ?, ?, 0, ?, ?, ?, 1)
                """,
                (
                    user_id,
                    account["name"],
                    section_key,
                    account["id"],
                    "Auto-created from account contribution.",
                    (sort_row["max_sort"] or -1) + 1,
                ),
            )
        # Retire any old unlinked items in the investment section with the same name —
        # they were created manually before auto-linking existed and are now duplicates.
        conn.execute(
            """
            UPDATE budget_items
            SET is_active = 0
            WHERE user_id = ?
              AND section = ?
              AND linked_account_id IS NULL
              AND is_active = 1
              AND name = ?
            """,
            (user_id, section_key, account["name"]),
        )
    conn.commit()


def fetch_budget_item(item_id, user_id=None):
    with get_connection() as conn:
        if user_id is not None:
            return conn.execute(
                "SELECT * FROM budget_items WHERE id = ? AND user_id = ?",
                (item_id, user_id),
            ).fetchone()
        return conn.execute(
            "SELECT * FROM budget_items WHERE id = ?", (item_id,)
        ).fetchone()


def create_budget_item(payload, user_id):
    with get_connection() as conn:
        linked_account_id = _owned_linked_account_id(conn, payload.get("linked_account_id"), user_id)
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
                linked_account_id,
                payload.get("notes", ""),
                payload.get("sort_order", 0),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_budget_item(payload, user_id):
    """Update a budget item, scoped to user_id."""
    with get_connection() as conn:
        linked_account_id = _owned_linked_account_id(conn, payload.get("linked_account_id"), user_id)
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
                linked_account_id,
                payload.get("notes", ""),
                payload["id"],
                user_id,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0


def _owned_linked_account_id(conn, account_id, user_id):
    if not account_id:
        return None
    row = conn.execute(
        "SELECT id FROM accounts WHERE id = ? AND user_id = ?",
        (account_id, user_id),
    ).fetchone()
    return row["id"] if row else None


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


def fetch_budget_trend(user_id, months):
    """Return budget vs actual data for multiple months.

    months: list of 'YYYY-MM' strings.
    Returns list of dicts: {section_name, item_name, item_id, default_amount,
                             month_key, actual_amount}
    Only includes items that have at least one entry in the given months.
    """
    if not months:
        return []
    placeholders = ",".join("?" * len(months))
    with get_connection() as conn:
        return conn.execute(
            f"""
            SELECT
                bs.label AS section_name,
                bi.name AS item_name,
                bi.id AS item_id,
                bi.default_amount,
                be.month_key,
                be.amount AS actual_amount
            FROM budget_entries be
            JOIN budget_items bi ON bi.id = be.budget_item_id
            JOIN budget_sections bs ON bs.key = bi.section AND bs.user_id = bi.user_id
            WHERE bi.user_id = ?
              AND be.month_key IN ({placeholders})
            ORDER BY bs.sort_order ASC, bi.sort_order ASC, be.month_key ASC
            """,
            [user_id, *months],
        ).fetchall()


def upsert_budget_entry(month_key, item_id, amount, user_id=None):
    with get_connection() as conn:
        if user_id is not None:
            owned = conn.execute(
                "SELECT 1 FROM budget_items WHERE id = ? AND user_id = ?",
                (item_id, user_id),
            ).fetchone()
            if not owned:
                return
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
