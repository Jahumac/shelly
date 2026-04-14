"""Price-resilience tests (helpers only — doesn't hit yfinance)."""
from datetime import datetime, timedelta, timezone

from app.calculations import is_price_stale


def test_is_price_stale_none():
    assert is_price_stale(None) is True
    assert is_price_stale("") is True


def test_is_price_stale_unparseable():
    assert is_price_stale("not-a-date") is True


def test_is_price_stale_fresh():
    now = datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc)
    ts = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M UTC")
    assert is_price_stale(ts, now=now) is False


def test_is_price_stale_36h_plus():
    now = datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc)
    ts = (now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M UTC")
    assert is_price_stale(ts, now=now) is True


def test_is_price_stale_boundary():
    # Exactly 36h old → not yet stale (strict >)
    now = datetime(2026, 4, 14, 12, 0, tzinfo=timezone.utc)
    ts = (now - timedelta(hours=36)).strftime("%Y-%m-%d %H:%M UTC")
    assert is_price_stale(ts, now=now) is False
    # 37h old → stale
    ts = (now - timedelta(hours=37)).strftime("%Y-%m-%d %H:%M UTC")
    assert is_price_stale(ts, now=now) is True
