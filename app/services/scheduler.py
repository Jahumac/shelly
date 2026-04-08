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
    import sys
    global scheduler, _lock_file

    print(f"[Shelly] init_scheduler called (pid={os.getpid()})", flush=True)

    if not APSCHEDULER_AVAILABLE:
        print("[Shelly] APScheduler not installed!", flush=True)
        return None

    if scheduler is not None:
        print("[Shelly] Scheduler already exists, returning", flush=True)
        return scheduler

    # In development with Werkzeug reloader, only start in the reloader process
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
        print("[Shelly] Skipping: Werkzeug reloader child process", flush=True)
        return None

    # Use a file lock to ensure only one worker starts the scheduler
    import fcntl
    data_dir = str(app.config.get('DATA_DIR', '/app/data'))
    lock_path = os.path.join(data_dir, '.scheduler.lock')
    print(f"[Shelly] Attempting lock at: {lock_path}", flush=True)
    try:
        _lock_file = open(lock_path, 'w')
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(f"[Shelly] Lock acquired!", flush=True)
    except (IOError, OSError) as e:
        print(f"[Shelly] Lock failed (another worker has it): {e}", flush=True)
        return None

    scheduler = BackgroundScheduler(timezone='Europe/London')

    # Schedule price updates at 7:00 AM and 5:00 PM UK time
    scheduler.add_job(
        func=_price_update_job,
        trigger=CronTrigger(hour=7, minute=0, timezone='Europe/London'),
        id='price_update_morning',
        name='Morning price update',
        replace_existing=True,
        args=[app],
    )

    scheduler.add_job(
        func=_price_update_job,
        trigger=CronTrigger(hour=17, minute=0, timezone='Europe/London'),
        id='price_update_evening',
        name='Evening price update',
        replace_existing=True,
        args=[app],
    )

    try:
        scheduler.start()
        print("[Shelly] Background scheduler started — price updates at 7:00 AM and 5:00 PM UK time", flush=True)
        logger.info("Background scheduler started (7:00 AM and 5:00 PM UK time)")
    except Exception as e:
        print(f"[Shelly] Failed to start scheduler: {e}", flush=True)
        logger.error(f"Failed to start scheduler: {e}")
        scheduler = None

    return scheduler


def _price_update_job(app):
    """Background job that fetches fresh prices and updates snapshots for all users.

    Steps:
    1. Get all users from the database
    2. For each user (if they have auto_update_prices enabled):
       a. Fetch their holding catalogue items with tickers
       b. Call refresh_catalogue_prices() to get fresh prices
       c. Update the catalogue in the database with new prices
       d. Calculate total portfolio value
       e. Save a daily snapshot
    """
    from app.models import (
        get_connection, fetch_all_users, fetch_holding_catalogue,
        fetch_all_accounts, fetch_holding_totals_by_account,
        fetch_assumptions, save_daily_snapshot
    )
    from app.calculations import effective_account_value
    from app.services.prices import refresh_catalogue_prices

    with app.app_context():
        try:
            logger.info("Starting automatic price update job")
            users = fetch_all_users()

            for user_row in users:
                user_id = user_row["id"]

                # Check if user has auto_update_prices enabled (defaults to 1/True)
                assumptions = fetch_assumptions(user_id)
                auto_update = True
                if assumptions:
                    auto_update = bool(assumptions.get("auto_update_prices", 1))

                if not auto_update:
                    logger.debug(f"Skipping auto-update for user {user_id} (disabled)")
                    continue

                try:
                    # Fetch catalogue items with tickers
                    catalogue = fetch_holding_catalogue(user_id)
                    if not catalogue:
                        continue

                    # Get fresh prices
                    price_results = refresh_catalogue_prices(catalogue)

                    # Update catalogue in database with new prices
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

                    # Calculate total portfolio value
                    accounts = fetch_all_accounts(user_id)
                    holdings_totals = fetch_holding_totals_by_account(user_id)
                    total_value = sum(
                        effective_account_value(account, holdings_totals)
                        for account in accounts
                    )

                    # Save daily snapshot
                    save_daily_snapshot(user_id, total_value)

                    successful = sum(1 for r in price_results if r.get("success"))
                    logger.info(
                        f"Updated {successful}/{len(price_results)} holdings and saved snapshot for user {user_id}"
                    )

                except Exception as e:
                    logger.error(f"Error updating prices for user {user_id}: {e}")

            logger.info("Automatic price update job completed")

        except Exception as e:
            logger.error(f"Price update job failed: {e}")


def trigger_manual_update(app, user_id):
    """Manually trigger a price update for a specific user.

    Returns a dict with status and message.
    """
    from app.models import (
        get_connection, fetch_holding_catalogue, fetch_all_accounts,
        fetch_holding_totals_by_account, fetch_assumptions, save_daily_snapshot
    )
    from app.calculations import effective_account_value
    from app.services.prices import refresh_catalogue_prices

    with app.app_context():
        try:
            # Check auto_update setting
            assumptions = fetch_assumptions(user_id)
            auto_update = bool(assumptions.get("auto_update_prices", 1)) if assumptions else True

            if not auto_update:
                return {
                    "ok": False,
                    "message": "Auto-update is disabled in your settings.",
                }

            # Fetch and update prices
            catalogue = fetch_holding_catalogue(user_id)
            if not catalogue:
                return {
                    "ok": False,
                    "message": "No holdings to update.",
                }

            price_results = refresh_catalogue_prices(catalogue)

            # Update catalogue
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

            # Calculate and save snapshot
            accounts = fetch_all_accounts(user_id)
            holdings_totals = fetch_holding_totals_by_account(user_id)
            total_value = sum(
                effective_account_value(account, holdings_totals)
                for account in accounts
            )
            save_daily_snapshot(user_id, total_value)

            successful = sum(1 for r in price_results if r.get("success"))
            return {
                "ok": True,
                "message": f"Updated {successful} holdings. Portfolio snapshot saved.",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Manual update failed for user {user_id}: {e}")
            return {
                "ok": False,
                "message": f"Update failed: {str(e)}",
            }
