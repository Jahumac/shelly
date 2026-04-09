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
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
        return None

    # Use a file lock to ensure only one worker starts the scheduler
    import fcntl
    data_dir = str(app.config.get('DATA_DIR', '/app/data'))
    lock_path = os.path.join(data_dir, '.scheduler.lock')
    try:
        _lock_file = open(lock_path, 'w')
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        return None

    scheduler = BackgroundScheduler(timezone='Europe/London')

    # Run every 15 minutes between 6am-10pm UK time.
    # Each run checks every user's configured update times and triggers
    # price updates for users whose time falls within the current window.
    scheduler.add_job(
        func=_scheduled_check,
        trigger=CronTrigger(minute='*/15', hour='6-22', timezone='Europe/London'),
        id='price_update_check',
        name='Check per-user update times',
        replace_existing=True,
        args=[app],
    )

    try:
        scheduler.start()
        print("[Shelly] Background scheduler started — checking for price updates every 15 min (6am–10pm UK)", flush=True)
        logger.info("Background scheduler started — checking every 15 min (6am–10pm UK)")
    except Exception as e:
        print(f"[Shelly] Failed to start scheduler: {e}", flush=True)
        logger.error(f"Failed to start scheduler: {e}")
        scheduler = None

    return scheduler


def _scheduled_check(app):
    """Runs every 15 minutes. For each user, checks if the current UK time
    falls within 15 minutes of their configured morning or evening update time.
    If so, triggers a price update for that user (at most once per time slot per day).
    """
    import pytz

    with app.app_context():
        from app.models import fetch_all_users, fetch_assumptions, get_connection

        uk_tz = pytz.timezone('Europe/London')
        now = datetime.now(uk_tz)
        now_minutes = now.hour * 60 + now.minute  # minutes since midnight
        today_str = now.strftime('%Y-%m-%d')

        try:
            users = fetch_all_users()
        except Exception as e:
            logger.error(f"Scheduled check failed to fetch users: {e}")
            return

        for user_row in users:
            user_id = user_row["id"]
            try:
                assumptions = fetch_assumptions(user_id)
                if not assumptions:
                    continue
                if not bool(assumptions.get("auto_update_prices", 1)):
                    continue

                morning = assumptions.get("update_time_morning") or "08:30"
                evening = assumptions.get("update_time_evening") or "18:00"

                for slot_name, time_str in [("morning", morning), ("evening", evening)]:
                    try:
                        h, m = [int(x) for x in time_str.split(":")]
                        slot_minutes = h * 60 + m
                    except (ValueError, AttributeError):
                        continue

                    # Check if we're within the 15-minute window after the configured time
                    if 0 <= (now_minutes - slot_minutes) < 15:
                        # Check we haven't already run this slot today
                        with get_connection() as conn:
                            already = conn.execute(
                                "SELECT 1 FROM scheduler_runs WHERE user_id = ? AND run_date = ? AND slot = ?",
                                (user_id, today_str, slot_name),
                            ).fetchone()
                        if already:
                            continue

                        logger.info(f"Triggering {slot_name} update for user {user_id} (scheduled {time_str})")
                        _run_price_update_for_user(app, user_id, slot_name)

                        # Record that we've run this slot
                        with get_connection() as conn:
                            conn.execute(
                                "INSERT OR IGNORE INTO scheduler_runs (user_id, run_date, slot) VALUES (?, ?, ?)",
                                (user_id, today_str, slot_name),
                            )
                            conn.commit()

            except Exception as e:
                logger.error(f"Scheduled check error for user {user_id}: {e}")


def _run_price_update_for_user(app, user_id, slot_name=None):
    """Fetch fresh prices and save a snapshot for a single user."""
    from app.models import (
        get_connection, fetch_holding_catalogue, fetch_all_accounts,
        fetch_holding_totals_by_account, save_daily_snapshot
    )
    from app.calculations import effective_account_value
    from app.services.prices import refresh_catalogue_prices

    with app.app_context():
        try:
            catalogue = fetch_holding_catalogue(user_id)
            if not catalogue:
                return

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
                conn.commit()

            accounts = fetch_all_accounts(user_id)
            holdings_totals = fetch_holding_totals_by_account(user_id)
            total_value = sum(
                effective_account_value(account, holdings_totals)
                for account in accounts
            )

            save_daily_snapshot(user_id, total_value)

            successful = sum(1 for r in price_results if r.get("success"))
            logger.info(f"Updated {successful}/{len(price_results)} holdings for user {user_id} ({slot_name or 'manual'})")

        except Exception as e:
            logger.error(f"Price update failed for user {user_id}: {e}")


def trigger_manual_update(app, user_id):
    """Manually trigger a price update for a specific user.

    Returns a dict with status and message.
    """
    from app.models import fetch_holding_catalogue, fetch_assumptions

    with app.app_context():
        try:
            catalogue = fetch_holding_catalogue(user_id)
            if not catalogue:
                return {"ok": False, "message": "No holdings to update."}

            _run_price_update_for_user(app, user_id, slot_name="manual")

            return {
                "ok": True,
                "message": "Prices updated and portfolio snapshot saved.",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Manual update failed for user {user_id}: {e}")
            return {"ok": False, "message": f"Update failed: {str(e)}"}
