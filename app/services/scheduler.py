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
        logger.info("Background scheduler started — checking every 15 min (6am–10pm UK)")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        scheduler = None

    return scheduler


def _scheduled_check(app):
    """Runs every 15 minutes (6am-10pm UK). For each user with auto_update
    enabled, triggers a price update if at least 4 hours have passed since
    the last successful run.

    This is more reliable than checking exact time windows because it
    self-heals after restarts — if gunicorn restarts and misses a window,
    the next 15-minute check will catch up automatically.
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

                # Check last run time — skip if less than 4 hours ago
                with get_connection() as conn:
                    last_run = conn.execute(
                        "SELECT run_date, slot FROM scheduler_runs "
                        "WHERE user_id = ? ORDER BY rowid DESC LIMIT 1",
                        (user_id,),
                    ).fetchone()

                    if last_run:
                        last_date = last_run["run_date"]
                        last_slot = last_run["slot"] or ""
                        # Parse last run timestamp
                        try:
                            last_dt = uk_tz.localize(
                                datetime.strptime(last_date + " " + last_slot, "%Y-%m-%d %H:%M")
                            )
                        except (ValueError, TypeError):
                            # Fallback: assume it ran at start of that day
                            last_dt = uk_tz.localize(
                                datetime.strptime(last_date, "%Y-%m-%d")
                            )

                        hours_since = (now - last_dt).total_seconds() / 3600
                        if hours_since < 4:
                            continue

                    # Claim this run
                    slot_time = now.strftime('%H:%M')
                    conn.execute(
                        "INSERT INTO scheduler_runs (user_id, run_date, slot) VALUES (?, ?, ?)",
                        (user_id, today_str, slot_time),
                    )
                    conn.commit()

                logger.info(f"Triggering price update for user {user_id}")
                _run_price_update_for_user(app, user_id, slot_name="auto")

            except Exception as e:
                logger.error(f"Scheduled check error for user {user_id}: {e}")


def _run_price_update_for_user(app, user_id, slot_name=None):
    """Fetch fresh prices and save a snapshot for a single user."""
    # Imports moved inside app_context
    with app.app_context():
        from app.models import (
            get_connection, fetch_holding_catalogue_in_use, fetch_all_accounts,
            fetch_holding_totals_by_account, save_daily_snapshot,
            sync_holding_prices_from_catalogue
        )
        from app.calculations import effective_account_value
        from app.services.prices import refresh_catalogue_prices

        try:
            catalogue = fetch_holding_catalogue_in_use(user_id)
            if not catalogue:
                accounts = fetch_all_accounts(user_id)
                holdings_totals = fetch_holding_totals_by_account(user_id)
                
                from app.models import update_account, fetch_assumptions
                from app.calculations import to_float
                now = datetime.now(timezone.utc)
                for acc in accounts:
                    is_cash_isa = acc.get("wrapper_type", "").lower() == "cash isa"
                    if acc["valuation_mode"] == "manual" or is_cash_isa:
                        last_updated_str = acc.get("last_updated")
                        if last_updated_str:
                            try:
                                last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                                if last_updated.tzinfo is None:
                                    last_updated = last_updated.replace(tzinfo=timezone.utc)
                            except ValueError:
                                last_updated = now
                            
                            days_elapsed = (now - last_updated).days
                            if days_elapsed > 0:
                                current_val = to_float(acc.get("current_value", 0))
                                rate = to_float(acc.get("growth_rate_override")) if acc.get("growth_rate_override") is not None else 0.0
                                if acc.get("growth_mode") != "custom":
                                    row = fetch_assumptions(user_id)
                                    rate = to_float(row["annual_growth_rate"]) if row else 0.05
                                
                                daily_rate = rate / 365.0
                                monthly_contrib = to_float(acc.get("monthly_contribution", 0))
                                daily_contrib = (monthly_contrib * 12) / 365.0
                                
                                new_val = current_val * ((1 + daily_rate) ** days_elapsed) + (daily_contrib * days_elapsed)
                                
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
                                
                                # Accrue uninvested cash interest too
                                cash_rate = to_float(acc.get("cash_interest_rate", 0)) / 365.0
                                cash_val = to_float(acc.get("uninvested_cash", 0))
                                if cash_val > 0 and cash_rate > 0:
                                    update_payload["uninvested_cash"] = cash_val * ((1 + cash_rate) ** days_elapsed)
                                
                                update_account(update_payload)
                
                accounts = fetch_all_accounts(user_id)
                total_value = sum(
                    effective_account_value(account, holdings_totals)
                    for account in accounts
                )
                save_daily_snapshot(user_id, total_value)
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
            
            # Auto-accrue manual accounts and Cash ISAs
            from app.models import update_account, fetch_assumptions
            from app.calculations import to_float
            now = datetime.now(timezone.utc)
            for acc in accounts:
                is_cash_isa = acc.get("wrapper_type", "").lower() == "cash isa"
                if acc["valuation_mode"] == "manual" or is_cash_isa:
                    last_updated_str = acc.get("last_updated")
                    if last_updated_str:
                        try:
                            last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                            if last_updated.tzinfo is None:
                                last_updated = last_updated.replace(tzinfo=timezone.utc)
                        except ValueError:
                            last_updated = now
                        
                        days_elapsed = (now - last_updated).days
                        if days_elapsed > 0:
                            current_val = to_float(acc.get("current_value", 0))
                            rate = to_float(acc.get("growth_rate_override")) if acc.get("growth_rate_override") is not None else 0.0
                            if acc.get("growth_mode") != "custom":
                                row = fetch_assumptions(user_id)
                                rate = to_float(row["annual_growth_rate"]) if row else 0.05
                            
                            daily_rate = rate / 365.0
                            monthly_contrib = to_float(acc.get("monthly_contribution", 0))
                            daily_contrib = (monthly_contrib * 12) / 365.0
                            
                            new_val = current_val * ((1 + daily_rate) ** days_elapsed) + (daily_contrib * days_elapsed)
                            
                            # Create an update payload including all required fields
                            update_payload = dict(acc)
                            update_payload["current_value"] = new_val
                            update_payload["last_updated"] = now.isoformat()
                            # Default missing fields for safety
                            update_payload.setdefault("employer_contribution", 0)
                            update_payload.setdefault("contribution_method", "standard")
                            update_payload.setdefault("annual_fee_pct", 0)
                            update_payload.setdefault("platform_fee_pct", 0)
                            update_payload.setdefault("platform_fee_flat", 0)
                            update_payload.setdefault("platform_fee_cap", 0)
                            update_payload.setdefault("fund_fee_pct", 0)
                            update_payload.setdefault("uninvested_cash", acc.get("uninvested_cash", 0))
                            update_payload.setdefault("cash_interest_rate", acc.get("cash_interest_rate", 0))
                            
                            # Accrue uninvested cash interest too
                            cash_rate = to_float(acc.get("cash_interest_rate", 0)) / 365.0
                            cash_val = to_float(acc.get("uninvested_cash", 0))
                            if cash_val > 0 and cash_rate > 0:
                                update_payload["uninvested_cash"] = cash_val * ((1 + cash_rate) ** days_elapsed)

                            update_account(update_payload)
                            
            # Re-fetch accounts to get the updated values
            accounts = fetch_all_accounts(user_id)

            total_value = sum(
                effective_account_value(account, holdings_totals)
                for account in accounts
            )

            save_daily_snapshot(user_id, total_value)

            successful = sum(1 for r in price_results if r.get("success"))
            failed = len(price_results) - successful
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
