"""Background scheduler for automatic price updates using APScheduler.

This module handles:
- Scheduling price updates at specified times (UK timezone)
- Fetching fresh prices for all users' holdings
- Saving daily portfolio snapshots
- Respecting per-user auto_update_prices setting
"""
import logging
from datetime import datetime, timezone
import os
from flask import current_app

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

logger = logging.getLogger(__name__)
scheduler = None
_lock_file = None  # Keep reference so fcntl lock isn't released by GC


def init_scheduler(app):
    """Initialize and start the background scheduler.

    This should be called once during app initialization, after the database is set up.
    Uses a file lock to prevent multiple scheduler instances in multi-worker
    environments like Gunicorn.
    """
    global scheduler, _lock_file

    if not APSCHEDULER_AVAILABLE:
        logger.warning("APScheduler not installed. Background price updates disabled.")
        return None

    if scheduler is not None:
        return scheduler

    # In development with Werkzeug reloader, only start in the reloader process
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return None

    # Use a file lock to ensure only one worker starts the scheduler
    import fcntl
    data_dir = str(app.config.get('DATA_DIR', '/app/data'))
    lock_path = os.path.join(data_dir, '.scheduler.lock')
    try:
        _lock_file = open(lock_path, 'w')
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        logger.info("Another worker already holds the scheduler lock — skipping.")
        return None

    scheduler = BackgroundScheduler(timezone='Europe/London')

    # Run every 15 minutes between 8am-10pm UK time.
    # Each user's actual update window is checked inside _scheduled_check
    # against their update_time_morning / update_time_evening settings.
    scheduler.add_job(
        func=_scheduled_check,
        trigger=CronTrigger(minute='*/15', hour='8-22', timezone='Europe/London'),
        id='price_update_check',
        name='Check per-user update times',
        replace_existing=True,
        args=[app],
    )

    # Daily DB backup at 03:00 UK time. Runs on a live DB via sqlite3.backup().
    scheduler.add_job(
        func=_scheduled_backup,
        trigger=CronTrigger(hour=3, minute=0, timezone='Europe/London'),
        id='daily_backup',
        name='Daily SQLite backup',
        replace_existing=True,
        args=[app],
    )

    try:
        scheduler.start()
        logger.info("Background scheduler started — checking every 15 min (8am–10pm UK), hourly per user within their window")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        scheduler = None

    return scheduler


def _scheduled_backup(app):
    """Daily DB backup job. Logs and swallows errors — a failed backup must
    never crash the scheduler loop or affect user traffic."""
    from pathlib import Path

    from app.services.backups import run_backup

    try:
        with app.app_context():
            db_path = Path(app.config["DB_PATH"])
            data_dir = Path(app.config.get("DATA_DIR", db_path.parent))
            run_backup(db_path, data_dir)
    except Exception as e:
        logger.exception(f"Scheduled backup failed: {e}")


def _parse_hhmm(time_str, default_hour):
    """Parse 'HH:MM' string to (hour, minute). Returns (default_hour, 0) on failure."""
    try:
        parts = str(time_str).strip().split(":")
        return int(parts[0]), int(parts[1])
    except Exception:
        return default_hour, 0


def _scheduled_check(app):
    """Runs every 15 minutes (6am-10pm UK). For each user with auto_update
    enabled, triggers a price update if:
      - Current time is within the user's configured morning–evening window, AND
      - At least 1 hour has passed since the last successful run.

    The window defaults to 08:30–22:00 but respects per-user settings.
    Self-heals after restarts — if gunicorn misses a window the next
    15-minute tick will catch up automatically.
    """
    import pytz

    with app.app_context():
        from app.models import fetch_all_users, fetch_assumptions, get_connection

        uk_tz = pytz.timezone('Europe/London')
        now = datetime.now(uk_tz)
        today_str = now.strftime('%Y-%m-%d')
        now_iso = now.strftime('%Y-%m-%d %H:%M:%S')

        logger.info(f"Scheduled check running at {now_iso} UK time")

        try:
            users = fetch_all_users()
        except Exception as e:
            logger.error(f"Scheduled check failed to fetch users: {e}")
            return

        for user_row in users:
            user_id = user_row["id"]
            try:
                row = fetch_assumptions(user_id)
                if not row:
                    continue
                assumptions = dict(row)
                if not bool(assumptions.get("auto_update_prices", 1)):
                    continue

                # Resolve per-user update window (defaults: 08:30 – 22:00)
                morning_h, morning_m = _parse_hhmm(assumptions.get("update_time_morning", "08:30"), 8)
                evening_h, evening_m = _parse_hhmm(assumptions.get("update_time_evening", "22:00"), 22)
                window_start = now.replace(hour=morning_h, minute=morning_m, second=0, microsecond=0)
                window_end   = now.replace(hour=evening_h, minute=evening_m, second=0, microsecond=0)

                if not (window_start <= now <= window_end):
                    continue  # outside this user's active window

                # Check last run time — skip if less than 1 hour ago
                with get_connection() as conn:
                    last_run = conn.execute(
                        "SELECT run_date, slot FROM scheduler_runs "
                        "WHERE user_id = ? ORDER BY rowid DESC LIMIT 1",
                        (user_id,),
                    ).fetchone()

                    if last_run:
                        last_date = last_run["run_date"]
                        last_slot = last_run["slot"] or ""
                        try:
                            last_dt = uk_tz.localize(
                                datetime.strptime(last_date + " " + last_slot, "%Y-%m-%d %H:%M")
                            )
                        except (ValueError, TypeError):
                            last_dt = uk_tz.localize(
                                datetime.strptime(last_date, "%Y-%m-%d")
                            )

                        hours_since = (now - last_dt).total_seconds() / 3600
                        if hours_since < 1:
                            continue

                    # Claim this run and prune old records (keep 90 days)
                    slot_time = now.strftime('%H:%M')
                    conn.execute(
                        "INSERT OR IGNORE INTO scheduler_runs (user_id, run_date, slot) VALUES (?, ?, ?)",
                        (user_id, today_str, slot_time),
                    )
                    conn.execute(
                        "DELETE FROM scheduler_runs WHERE run_date < date('now', '-90 days')",
                    )
                    conn.commit()

                logger.info(f"Triggering price update for user {user_id}")
                _run_price_update_for_user(app, user_id, slot_name="auto")

            except Exception as e:
                logger.error(f"Scheduled check error for user {user_id}: {e}")


def _accrue_manual_accounts(user_id, accounts):
    """Accrue growth, contributions, and cash interest for manual-valuation
    accounts and Cash ISAs. Mutates the DB via update_account; callers should
    re-fetch accounts afterwards to get the updated values."""
    from app.models import update_account, fetch_assumptions
    from app.calculations import to_float

    now = datetime.now(timezone.utc)
    for acc in accounts:
        is_cash_isa = acc.get("wrapper_type", "").lower() == "cash isa"
        if acc["valuation_mode"] != "manual" and not is_cash_isa:
            continue
        last_updated_str = acc.get("last_updated")
        if not last_updated_str:
            continue
        try:
            last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=timezone.utc)
        except ValueError:
            last_updated = now

        days_elapsed = (now - last_updated).days
        if days_elapsed <= 0:
            continue

        current_val = to_float(acc.get("current_value", 0))
        rate = to_float(acc.get("growth_rate_override")) if acc.get("growth_rate_override") is not None else 0.0
        if acc.get("growth_mode") != "custom":
            row = fetch_assumptions(user_id)
            rate = to_float(row["annual_growth_rate"]) if row else 0.05

        monthly_contrib = to_float(acc.get("monthly_contribution", 0))
        daily_contrib = (monthly_contrib * 12) / 365.0

        # For cash accounts (Cash ISA, savings) use cash_interest_rate to grow
        # the account value rather than the market growth rate.
        cash_interest = to_float(acc.get("cash_interest_rate", 0))
        if cash_interest > 0 and (is_cash_isa or acc.get("category", "").lower() in ("cash", "savings")):
            effective_rate = cash_interest / 365.0
        else:
            effective_rate = rate / 365.0

        new_val = current_val * ((1 + effective_rate) ** days_elapsed) + (daily_contrib * days_elapsed)

        update_payload = dict(acc)
        update_payload["current_value"] = new_val
        update_payload["last_updated"] = now.isoformat()
        update_payload.setdefault("employer_contribution", 0)
        update_payload.setdefault("contribution_method", "standard")
        update_payload.setdefault("annual_fee_pct", 0)
        update_payload.setdefault("platform_fee_pct", 0)
        update_payload.setdefault("platform_fee_flat", 0)
        update_payload.setdefault("platform_fee_cap", 0)
        update_payload.setdefault("fund_fee_pct", 0)
        update_payload.setdefault("uninvested_cash", acc.get("uninvested_cash", 0))
        update_payload.setdefault("cash_interest_rate", acc.get("cash_interest_rate", 0))

        cash_rate = to_float(acc.get("cash_interest_rate", 0)) / 365.0
        cash_val = to_float(acc.get("uninvested_cash", 0))
        if cash_val > 0 and cash_rate > 0:
            update_payload["uninvested_cash"] = cash_val * ((1 + cash_rate) ** days_elapsed)

        update_account(update_payload, user_id)


def _run_price_update_for_user(app, user_id, slot_name=None):
    """Fetch fresh prices and save a snapshot for a single user.
    Must be called from within an active app context."""
    from app.models import (
        get_connection, fetch_holding_catalogue_in_use, fetch_all_accounts,
        fetch_holding_totals_by_account, save_daily_snapshot,
        save_account_daily_snapshots, sync_holding_prices_from_catalogue
    )
    from app.calculations import effective_account_value
    from app.services.prices import refresh_catalogue_prices

    try:
        catalogue = fetch_holding_catalogue_in_use(user_id)
        if not catalogue:
            accounts = fetch_all_accounts(user_id)
            holdings_totals = fetch_holding_totals_by_account(user_id)
            _accrue_manual_accounts(user_id, accounts)
            accounts = fetch_all_accounts(user_id)
            acct_vals = [(a["id"], effective_account_value(a, holdings_totals)) for a in accounts]
            save_daily_snapshot(user_id, sum(v for _, v in acct_vals))
            save_account_daily_snapshots(user_id, acct_vals)
            logger.info(f"Saved portfolio snapshot for user {user_id} ({slot_name or 'manual'})")
            return

        logger.info(f"Fetching prices for {len(catalogue)} instruments...")
        price_results = refresh_catalogue_prices(catalogue)

        with get_connection() as conn:
            for result in price_results:
                if result.get("success"):
                    conn.execute(
                        """
                        UPDATE holding_catalogue
                        SET last_price = ?, price_currency = ?, price_change_pct = ?, price_updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            result.get("price"),
                            result.get("currency"),
                            result.get("change_pct"),
                            result.get("updated_at"),
                            result.get("id"),
                        ),
                    )
                    # Propagate fresh price to all linked holdings in account pots
                    sync_holding_prices_from_catalogue(
                        result.get("id"),
                        result.get("price"),
                        result.get("currency")
                    )
                else:
                    current_app.logger.error(f"[Shelly] ✗ {result.get('ticker')}: {result.get('error')}")
            conn.commit()

        accounts = fetch_all_accounts(user_id)
        holdings_totals = fetch_holding_totals_by_account(user_id)
        _accrue_manual_accounts(user_id, accounts)
        accounts = fetch_all_accounts(user_id)

        acct_vals = [(a["id"], effective_account_value(a, holdings_totals)) for a in accounts]
        save_daily_snapshot(user_id, sum(v for _, v in acct_vals))
        save_account_daily_snapshots(user_id, acct_vals)

        successful = sum(1 for r in price_results if r.get("success"))
        logger.info(f"Updated {successful}/{len(price_results)} holdings for user {user_id} ({slot_name or 'manual'})")

    except Exception as e:
        current_app.logger.error(f"[Shelly] Price update FAILED for user {user_id}: {e}")
        logger.error(f"Price update failed for user {user_id}: {e}")


def trigger_manual_update(app, user_id):
    """Manually trigger a price update for a specific user.

    Returns a dict with status and message.
    """
    from app.models import fetch_holding_catalogue_in_use

    with app.app_context():
        try:
            catalogue = fetch_holding_catalogue_in_use(user_id)
            if not catalogue:
                _run_price_update_for_user(app, user_id, slot_name="manual")
                return {
                    "ok": True,
                    "message": "No holdings to update — saved a portfolio snapshot.",
                    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                }

            _run_price_update_for_user(app, user_id, slot_name="manual")

            return {
                "ok": True,
                "message": "Prices updated and portfolio snapshot saved.",
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            }

        except Exception as e:
            logger.error(f"Manual update failed for user {user_id}: {e}")
            return {"ok": False, "message": f"Update failed: {str(e)}"}
