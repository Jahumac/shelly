"""DB schema + init_db.

Isolated here so app/models/__init__.py stays focused on CRUD functions
rather than 500 lines of CREATE TABLE + migration boilerplate.
"""
from flask import current_app

from ._conn import get_connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    provider TEXT,
    wrapper_type TEXT,
    category TEXT,
    tags TEXT DEFAULT '',
    current_value REAL DEFAULT 0,
    monthly_contribution REAL DEFAULT 0,
    pension_contribution_day INTEGER DEFAULT 0,
    goal_value REAL,
    valuation_mode TEXT DEFAULT 'manual',
    growth_mode TEXT DEFAULT 'default',
    growth_rate_override REAL,
    owner TEXT,
    is_active INTEGER DEFAULT 1,
    notes TEXT,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    target_value REAL NOT NULL,
    goal_type TEXT,
    selected_tags TEXT DEFAULT '',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS assumptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    annual_growth_rate REAL DEFAULT 0.07,
    retirement_age INTEGER DEFAULT 60,
    current_age INTEGER DEFAULT 43,
    retirement_goal_value REAL DEFAULT 1000000,
    isa_allowance REAL DEFAULT 20000,
    lisa_allowance REAL DEFAULT 4000,
    dividend_allowance REAL DEFAULT 500,
    target_dev_pct REAL DEFAULT 0.90,
    target_em_pct REAL DEFAULT 0.10,
    emergency_fund_target REAL DEFAULT 3000,
    dashboard_name TEXT DEFAULT 'Shelly',
    auto_update_prices INTEGER DEFAULT 1,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS holding_catalogue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    holding_name TEXT NOT NULL,
    ticker TEXT,
    asset_type TEXT,
    bucket TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    last_price REAL,
    price_currency TEXT,
    price_change_pct REAL,
    price_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    holding_catalogue_id INTEGER,
    holding_name TEXT NOT NULL,
    ticker TEXT,
    asset_type TEXT,
    bucket TEXT,
    value REAL DEFAULT 0,
    units REAL,
    price REAL,
    notes TEXT,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(holding_catalogue_id) REFERENCES holding_catalogue(id)
);

CREATE TABLE IF NOT EXISTS monthly_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    balance REAL DEFAULT 0,
    contribution REAL DEFAULT 0,
    note TEXT,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS allowance_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tax_year TEXT NOT NULL,
    isa_used REAL DEFAULT 0,
    lisa_used REAL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS monthly_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    month_key TEXT NOT NULL,
    status TEXT DEFAULT 'not_started',
    notes TEXT,
    completed_at TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(user_id, month_key)
);

CREATE TABLE IF NOT EXISTS monthly_review_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    expected_contribution REAL DEFAULT 0,
    contribution_confirmed INTEGER DEFAULT 0,
    holdings_updated INTEGER DEFAULT 0,
    balance_updated INTEGER DEFAULT 0,
    notes TEXT,
    FOREIGN KEY(review_id) REFERENCES monthly_reviews(id),
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS budget_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    section TEXT NOT NULL,
    default_amount REAL DEFAULT 0,
    linked_account_id INTEGER,
    notes TEXT,
    sort_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY(linked_account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS budget_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month_key TEXT NOT NULL,
    budget_item_id INTEGER NOT NULL,
    amount REAL DEFAULT 0,
    FOREIGN KEY(budget_item_id) REFERENCES budget_items(id),
    UNIQUE(month_key, budget_item_id)
);

CREATE TABLE IF NOT EXISTS budget_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    UNIQUE(user_id, key)
);

CREATE TABLE IF NOT EXISTS contribution_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    from_month TEXT NOT NULL,
    to_month TEXT NOT NULL,
    override_amount REAL NOT NULL,
    reason TEXT,
    created_at TEXT,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS isa_contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount REAL NOT NULL,
    contribution_date TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pension_contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount REAL NOT NULL,
    kind TEXT NOT NULL DEFAULT 'personal',
    contribution_date TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dividend_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount REAL NOT NULL,
    dividend_date TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    run_date TEXT NOT NULL,
    slot TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portfolio_daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    snapshot_date TEXT NOT NULL,
    total_value REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, snapshot_date)
);
"""


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)

        # ── Legacy column additions (accounts) ───────────────────────────────
        for col_name, col_def in [
            ("goal_value", "REAL"),
            ("valuation_mode", "TEXT DEFAULT 'manual'"),
            ("growth_mode", "TEXT DEFAULT 'default'"),
            ("growth_rate_override", "REAL"),
            ("tags", "TEXT DEFAULT ''"),
            ("pension_contribution_day", "INTEGER DEFAULT 0"),
        ]:
            try:
                # Check if column exists first
                info = conn.execute(f"PRAGMA table_info(accounts)").fetchall()
                if not any(row['name'] == col_name for row in info):
                    conn.execute(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_def}")
            except Exception as e:
                current_app.logger.error(f"Migration error (accounts.{col_name}): {e}")

        # ── Legacy column additions (other tables) ───────────────────────────
        for col_sql in [
            "ALTER TABLE assumptions ADD COLUMN dashboard_name TEXT DEFAULT 'Shelly'",
            "ALTER TABLE assumptions ADD COLUMN retirement_goal_value REAL DEFAULT 1000000",
            "ALTER TABLE assumptions ADD COLUMN dividend_allowance REAL DEFAULT 500",
            "ALTER TABLE holdings ADD COLUMN holding_catalogue_id INTEGER",
            "ALTER TABLE goals ADD COLUMN selected_tags TEXT DEFAULT ''",
            "ALTER TABLE monthly_snapshots ADD COLUMN month_key TEXT",
        ]:
            try:
                conn.execute(col_sql)
            except Exception:
                pass

        # ── Legacy table creation ─────────────────────────────────────────────
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contribution_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    from_month TEXT NOT NULL,
                    to_month TEXT NOT NULL,
                    override_amount REAL NOT NULL,
                    reason TEXT,
                    created_at TEXT,
                    FOREIGN KEY(account_id) REFERENCES accounts(id)
                )
            """)
        except Exception:
            pass

        for col in ["last_price REAL", "price_currency TEXT", "price_change_pct REAL", "price_updated_at TEXT"]:
            try:
                conn.execute(f"ALTER TABLE holding_catalogue ADD COLUMN {col}")
            except Exception:
                pass

        # ── Multi-user migrations ─────────────────────────────────────────────
        # Add user_id to accounts (default 1 = first user, safe for existing DBs)
        for tbl, col_sql in [
            ("accounts",         "ALTER TABLE accounts ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)"),
            ("goals",            "ALTER TABLE goals ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)"),
            ("holding_catalogue","ALTER TABLE holding_catalogue ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)"),
            ("budget_items",     "ALTER TABLE budget_items ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)"),
            ("budget_sections",  "ALTER TABLE budget_sections ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)"),
            ("monthly_reviews",  "ALTER TABLE monthly_reviews ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id)"),
        ]:
            try:
                conn.execute(col_sql)
            except Exception:
                pass

        # ── Assumptions table: recreate without CHECK (id=1), add user_id ─────
        if not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = 'v4_assumptions_multi_user'"
        ).fetchone():
            # Check if old single-row assumptions exist
            old_row = conn.execute("SELECT * FROM assumptions LIMIT 1").fetchone()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assumptions_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
                    annual_growth_rate REAL DEFAULT 0.07,
                    retirement_age INTEGER DEFAULT 60,
                    current_age INTEGER DEFAULT 43,
                    retirement_goal_value REAL DEFAULT 1000000,
                    isa_allowance REAL DEFAULT 20000,
                    lisa_allowance REAL DEFAULT 4000,
                    target_dev_pct REAL DEFAULT 0.90,
                    target_em_pct REAL DEFAULT 0.10,
                    emergency_fund_target REAL DEFAULT 3000,
                    dashboard_name TEXT DEFAULT 'Shelly',
                    updated_at TEXT
                )
            """)
            if old_row:
                # Try to copy old data — old table might have id=1 row
                cols = old_row.keys()
                # Map old id=1 row to user_id=1
                conn.execute("""
                    INSERT OR IGNORE INTO assumptions_new
                        (user_id, annual_growth_rate, retirement_age, current_age,
                         retirement_goal_value, isa_allowance, lisa_allowance,
                         target_dev_pct, target_em_pct, emergency_fund_target,
                         dashboard_name, updated_at)
                    SELECT
                        1,
                        COALESCE(annual_growth_rate, 0.07),
                        COALESCE(retirement_age, 60),
                        COALESCE(current_age, 43),
                        COALESCE(retirement_goal_value, 1000000),
                        COALESCE(isa_allowance, 20000),
                        COALESCE(lisa_allowance, 4000),
                        COALESCE(target_dev_pct, 0.90),
                        COALESCE(target_em_pct, 0.10),
                        COALESCE(emergency_fund_target, 3000),
                        COALESCE(dashboard_name, 'Shelly'),
                        updated_at
                    FROM assumptions
                    LIMIT 1
                """)
            conn.execute("DROP TABLE IF EXISTS assumptions")
            conn.execute("ALTER TABLE assumptions_new RENAME TO assumptions")
            conn.execute(
                "INSERT INTO schema_migrations (name) VALUES ('v4_assumptions_multi_user')"
            )

        # ── monthly_reviews: fix UNIQUE(month_key) → UNIQUE(user_id, month_key) ─
        if not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = 'v5_monthly_reviews_per_user'"
        ).fetchone():
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monthly_reviews_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    month_key TEXT NOT NULL,
                    status TEXT DEFAULT 'not_started',
                    notes TEXT,
                    completed_at TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    UNIQUE(user_id, month_key)
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO monthly_reviews_new
                    (id, user_id, month_key, status, notes, completed_at, created_at, updated_at)
                SELECT id, user_id, month_key, status, notes, completed_at, created_at, updated_at
                FROM monthly_reviews
            """)
            conn.execute("DROP TABLE IF EXISTS monthly_reviews")
            conn.execute("ALTER TABLE monthly_reviews_new RENAME TO monthly_reviews")
            conn.execute(
                "INSERT INTO schema_migrations (name) VALUES ('v5_monthly_reviews_per_user')"
            )

        # ── budget_sections: fix UNIQUE(key) → UNIQUE(user_id, key) ──────────
        if not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = 'v5_budget_sections_per_user'"
        ).fetchone():
            conn.execute("""
                CREATE TABLE IF NOT EXISTS budget_sections_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    sort_order INTEGER DEFAULT 0,
                    UNIQUE(user_id, key)
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO budget_sections_new (id, user_id, key, label, sort_order)
                SELECT id, user_id, key, label, sort_order FROM budget_sections
            """)
            conn.execute("DROP TABLE IF EXISTS budget_sections")
            conn.execute("ALTER TABLE budget_sections_new RENAME TO budget_sections")
            conn.execute(
                "INSERT INTO schema_migrations (name) VALUES ('v5_budget_sections_per_user')"
            )

        # ── Add salary_day and update_day to assumptions ────────────────────
        for col in [
            "salary_day INTEGER DEFAULT 0",
            "update_day INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(f"ALTER TABLE assumptions ADD COLUMN {col}")
            except Exception:
                pass

        # ── Migrate current_age → date_of_birth ─────────────────────────────
        # Add date_of_birth column (TEXT, ISO format YYYY-MM-DD)
        try:
            conn.execute("ALTER TABLE assumptions ADD COLUMN date_of_birth TEXT")
        except Exception:
            pass

        # One-time: convert existing current_age to approximate DOB
        if not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = 'v6_dob_from_age'"
        ).fetchone():
            # For each user who has current_age but no DOB, estimate DOB as
            # today minus current_age years (assumes birthday is Jan 1 — user
            # can correct this in Settings).
            from datetime import date as _date
            rows = conn.execute(
                "SELECT user_id, current_age FROM assumptions WHERE date_of_birth IS NULL AND current_age IS NOT NULL"
            ).fetchall()
            for row in rows:
                approx_year = _date.today().year - int(row["current_age"])
                approx_dob = f"{approx_year}-01-01"
                conn.execute(
                    "UPDATE assumptions SET date_of_birth = ? WHERE user_id = ?",
                    (approx_dob, row["user_id"]),
                )
            conn.execute(
                "INSERT INTO schema_migrations (name) VALUES ('v6_dob_from_age')"
            )

        # ── Retirement date mode ───────────────────────────────────────────
        # Options: 'birthday', 'end_of_year', 'end_of_tax_year'
        try:
            conn.execute("ALTER TABLE assumptions ADD COLUMN retirement_date_mode TEXT DEFAULT 'birthday'")
        except Exception:
            pass

        # ── Tax band on assumptions ────────────────────────────────────────
        # Options: 'basic', 'higher', 'additional'
        try:
            conn.execute("ALTER TABLE assumptions ADD COLUMN tax_band TEXT DEFAULT 'basic'")
        except Exception:
            pass

        # ── Pension / contribution / fee fields on accounts ────────────────
        for col in [
            "employer_contribution REAL DEFAULT 0",
            "contribution_method TEXT DEFAULT 'standard'",
            "annual_fee_pct REAL DEFAULT 0",
            "platform_fee_pct REAL DEFAULT 0",
            "platform_fee_flat REAL DEFAULT 0",
            "platform_fee_cap REAL DEFAULT 0",
            "fund_fee_pct REAL DEFAULT 0",
            "uninvested_cash REAL DEFAULT 0",
            "cash_interest_rate REAL DEFAULT 0",
        ]:
            try:
                conn.execute(f"ALTER TABLE accounts ADD COLUMN {col}")
            except Exception:
                pass

        # ── Migrate legacy annual_fee_pct → fund_fee_pct (one-time) ──────
        try:
            if not conn.execute(
                "SELECT 1 FROM schema_migrations WHERE name = 'v4_split_fees'"
            ).fetchone():
                conn.execute("""
                    UPDATE accounts SET fund_fee_pct = annual_fee_pct
                    WHERE annual_fee_pct > 0 AND fund_fee_pct = 0
                """)
                conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES ('v4_split_fees')"
                )
                conn.commit()
        except Exception:
            pass

        # ── One-time catalogue wipe ───────────────────────────────────────────
        if not conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = 'v3_clean_catalogue'"
        ).fetchone():
            conn.execute("DELETE FROM holding_catalogue")
            conn.execute(
                "INSERT INTO schema_migrations (name) VALUES ('v3_clean_catalogue')"
            )

        # ── Unique ticker index per user ──────────────────────────────────────
        # Drop old global unique index if it exists, then create per-user one
        try:
            conn.execute("DROP INDEX IF EXISTS idx_catalogue_ticker")
        except Exception:
            pass
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_catalogue_ticker_user "
                "ON holding_catalogue(user_id, ticker) WHERE ticker IS NOT NULL AND ticker != ''"
            )
        except Exception:
            pass

        # ── Auto-update prices toggle on assumptions ─────────────────────────
        try:
            conn.execute("ALTER TABLE assumptions ADD COLUMN auto_update_prices INTEGER DEFAULT 1")
        except Exception:
            pass

        # ── Scheduler run tracking ────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                run_date TEXT NOT NULL,
                slot TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(user_id, run_date, slot)
            )
        """)

        # ── Configurable price update times ──────────────────────────────────
        for col in [
            "update_time_morning TEXT DEFAULT '08:30'",
            "update_time_evening TEXT DEFAULT '18:00'",
        ]:
            try:
                conn.execute(f"ALTER TABLE assumptions ADD COLUMN {col}")
            except Exception:
                pass

        for col in [
            "annual_income REAL DEFAULT 0",
            "pension_annual_allowance REAL DEFAULT 60000",
            "mpaa_enabled INTEGER DEFAULT 0",
            "mpaa_allowance REAL DEFAULT 10000",
        ]:
            try:
                conn.execute(f"ALTER TABLE assumptions ADD COLUMN {col}")
            except Exception:
                pass
        # ── Custom tags per user ─────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                tag TEXT NOT NULL,
                UNIQUE(user_id, tag)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pension_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                amount REAL NOT NULL,
                kind TEXT NOT NULL DEFAULT 'personal',
                contribution_date TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                token TEXT NOT NULL UNIQUE,
                label TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_used_at TEXT
            )
        """)

        # ── Performance indexes on foreign-key and frequently-queried columns ──
        for stmt in [
            "CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_accounts_active ON accounts(user_id, is_active)",
            "CREATE INDEX IF NOT EXISTS idx_goals_user_id ON goals(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_holding_catalogue_user_id ON holding_catalogue(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_holdings_account_id ON holdings(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_holdings_catalogue_id ON holdings(holding_catalogue_id)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_snapshots_account_id ON monthly_snapshots(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_snapshots_date ON monthly_snapshots(snapshot_date)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_snapshots_month_key ON monthly_snapshots(month_key)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_reviews_user_month ON monthly_reviews(user_id, month_key)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_review_items_review_id ON monthly_review_items(review_id)",
            "CREATE INDEX IF NOT EXISTS idx_monthly_review_items_account_id ON monthly_review_items(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_budget_items_user_id ON budget_items(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_budget_items_linked_account ON budget_items(linked_account_id)",
            "CREATE INDEX IF NOT EXISTS idx_budget_entries_month ON budget_entries(month_key)",
            "CREATE INDEX IF NOT EXISTS idx_budget_entries_item ON budget_entries(budget_item_id)",
            "CREATE INDEX IF NOT EXISTS idx_budget_sections_user_id ON budget_sections(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_contribution_overrides_account ON contribution_overrides(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_isa_contributions_user ON isa_contributions(user_id, contribution_date)",
            "CREATE INDEX IF NOT EXISTS idx_isa_contributions_account ON isa_contributions(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_pension_contributions_user ON pension_contributions(user_id, contribution_date)",
            "CREATE INDEX IF NOT EXISTS idx_pension_contributions_account ON pension_contributions(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_dividend_records_user ON dividend_records(user_id, dividend_date)",
            "CREATE INDEX IF NOT EXISTS idx_dividend_records_account ON dividend_records(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_scheduler_runs_user_date ON scheduler_runs(user_id, run_date)",
            "CREATE INDEX IF NOT EXISTS idx_portfolio_daily_user_date ON portfolio_daily_snapshots(user_id, snapshot_date)",
            "CREATE INDEX IF NOT EXISTS idx_custom_tags_user ON custom_tags(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_api_tokens_token ON api_tokens(token)",
            "CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id)",
        ]:
            try:
                conn.execute(stmt)
            except Exception as e:
                current_app.logger.warning(f"Index create failed ({stmt.split()[-1]}): {e}")

        conn.commit()

