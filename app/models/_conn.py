"""Database connection handling — the leaf module of the models package.

Kept separate so schema.py and every other submodule can import
get_connection without creating a cycle with __init__.py.
"""
import sqlite3
from pathlib import Path

from flask import current_app, g


def get_connection():
    if "db" not in g:
        db_path = Path(current_app.config["DB_PATH"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        g.db = conn
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
