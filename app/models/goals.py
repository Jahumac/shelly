"""Goals — savings/retirement targets users define against tagged accounts."""
from ._conn import get_connection


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


