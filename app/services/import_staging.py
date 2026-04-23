"""Disk-backed scratch area for multi-step imports.

The annual budget import uses this to survive the cookie-size limit that
applies to Flask's default signed-cookie session. Instead of stashing the
full parsed diff in the cookie (which breaks for big workbooks), we write
it to `{DB_PATH.parent}/tmp/annual-import-{token}.json` and keep only the
token in the session.

Tokens are URL-safe random strings. Files older than MAX_AGE_SECONDS are
swept on app startup; a full import flow (upload → confirm/cancel) is
typically seconds, so an hour is plenty of headroom.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any, Optional

from flask import Flask


_PREFIX = "annual-import-"
_SUFFIX = ".json"
MAX_AGE_SECONDS = 3600  # 1 hour — covers any realistic preview → confirm gap


def _staging_dir(app: Flask) -> Path:
    """Return the staging directory, creating it if missing.

    Derived from DB_PATH.parent so tests (which override DB_PATH to a tmp dir)
    get their own isolated staging directory automatically.
    """
    db_path = Path(app.config["DB_PATH"])
    staging = db_path.parent / "tmp"
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def _safe_path(app: Flask, token: str) -> Optional[Path]:
    """Resolve `token` to a staging file path, rejecting anything fishy.

    Tokens must be hex — anything else (path separators, dots, empty) returns
    None so a tampered cookie can't traverse outside the staging dir.
    """
    if not token or not all(c in "0123456789abcdef" for c in token):
        return None
    return _staging_dir(app) / f"{_PREFIX}{token}{_SUFFIX}"


def write_staged(app: Flask, data: Any) -> str:
    """Serialise `data` as JSON into a new staging file. Returns the token."""
    token = secrets.token_hex(16)
    path = _staging_dir(app) / f"{_PREFIX}{token}{_SUFFIX}"
    # Atomic-ish write: write to a .tmp sibling then rename. Prevents a
    # half-written file being read by a racing request.
    tmp_path = path.with_suffix(_SUFFIX + ".tmp")
    tmp_path.write_text(json.dumps(data), encoding="utf-8")
    tmp_path.replace(path)
    return token


def read_staged(app: Flask, token: str) -> Optional[Any]:
    """Return the deserialised data, or None if the token is unknown/expired/invalid."""
    path = _safe_path(app, token)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete_staged(app: Flask, token: str) -> None:
    """Delete the staging file for `token`. No-op if it's already gone."""
    path = _safe_path(app, token)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def sweep_stale(app: Flask, max_age_seconds: int = MAX_AGE_SECONDS) -> int:
    """Remove staging files older than `max_age_seconds`. Returns count deleted."""
    staging = _staging_dir(app)
    cutoff = time.time() - max_age_seconds
    removed = 0
    for p in staging.glob(f"{_PREFIX}*{_SUFFIX}"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    # Also tidy any half-written .tmp files from crashed writes
    for p in staging.glob(f"{_PREFIX}*{_SUFFIX}.tmp"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
        except OSError:
            continue
    return removed
