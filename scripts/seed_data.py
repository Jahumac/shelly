from datetime import datetime

from app import create_app
from app.models import get_connection, init_db

app = create_app()

ACCOUNTS = [
    ("Trading 212 Stocks & Shares ISA", "Trading 212", "Stocks & Shares ISA", "ISA", 4500, 1000, 100000, "manual", "default", None, "Janusz", 1, "90/10 developed world and emerging markets", datetime.now().isoformat()),
    ("Trading 212 Cash ISA", "Trading 212", "Cash ISA", "ISA", 2000, 0, None, "manual", "custom", 0.036, "Janusz", 1, "Emergency fund, target £3,000 then stop", datetime.now().isoformat()),
    ("Lifetime ISA", "AJ Bell Dodl", "Lifetime ISA", "ISA", 250, 333, None, "manual", "default", None, "Janusz", 1, "Invested in HSBC FTSE All World Accumulating, intended for retirement", datetime.now().isoformat()),
    ("SIPP", "InvestEngine", "SIPP", "Pension", 47000, 400, None, "manual", "default", None, "Janusz", 1, "£400 net monthly, £500 gross with tax relief, invested 90/10", datetime.now().isoformat()),
    ("Workplace Pension", "Standard Life", "Workplace Pension", "Pension", 2000, 333, None, "manual", "default", None, "Janusz", 1, "Total contribution including employer match", datetime.now().isoformat()),
]

with app.app_context():
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM accounts")
    conn.execute("DELETE FROM goals")
    conn.execute("DELETE FROM assumptions")

    conn.executemany(
        """
        INSERT INTO accounts (name, provider, wrapper_type, category, current_value, monthly_contribution, goal_value, valuation_mode, growth_mode, growth_rate_override, owner, is_active, notes, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ACCOUNTS,
    )

    conn.execute(
        """
        INSERT INTO goals (name, target_value, goal_type, notes)
        VALUES (?, ?, ?, ?)
        """,
        ("Retirement Goal", 1000000, "retirement", "Primary long-term retirement target"),
    )

    conn.execute(
        """
        INSERT INTO assumptions (id, annual_growth_rate, retirement_age, current_age, retirement_goal_value, isa_allowance, lisa_allowance, target_dev_pct, target_em_pct, emergency_fund_target, updated_at)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (0.07, 60, 43, 1000000, 20000, 4000, 0.90, 0.10, 3000, datetime.now().isoformat()),
    )

    conn.execute(
        """
        INSERT INTO allowance_tracking (tax_year, isa_used, lisa_used, notes)
        VALUES (?, ?, ?, ?)
        """,
        ("2026/27", 6750, 3996, "Initial seeded values based on current contribution plan and balances"),
    )

    conn.commit()
    conn.close()
    print("Seed data written.")
