"""User accounts and API tokens.

User CRUD + Flask-Login User class + bearer-token management for the
JSON API. Tokens are stored in plaintext (acceptable for a self-hosted
single-instance app where DB access already implies full compromise).
"""
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from ._conn import get_connection


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
    from datetime import datetime, timezone
    pw_hash = generate_password_hash(password)
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, pw_hash, 1 if is_admin else 0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cursor.lastrowid


def count_users():
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


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
                "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1"
            ).fetchone()["n"]
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
            "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1"
        ).fetchone()["n"]
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



# ── API tokens ────────────────────────────────────────────────────────────────
# Bearer tokens for the JSON API. Mint via scripts/api_token.py create <user>.
# Tokens are stored as SHA-256 hashes.

def _hash_token(token):
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def create_api_token(user_id, label=None):
    import secrets
    token = secrets.token_hex(32)
    hashed = _hash_token(token)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO api_tokens (user_id, token, label) VALUES (?, ?, ?)",
            (user_id, hashed, label),
        )
        conn.commit()
    return token


def fetch_user_by_api_token(token):
    if not token:
        return None
    hashed = _hash_token(token)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.* FROM users u
            JOIN api_tokens t ON t.user_id = u.id
            WHERE t.token = ?
            """,
            (hashed,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE api_tokens SET last_used_at = datetime('now') WHERE token = ?",
            (hashed,),
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
