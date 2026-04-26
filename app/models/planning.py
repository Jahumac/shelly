"""Planning module — constants, tags, resets, and re-exports.

The bulk of the logic has been split into focused submodules:
    planning_assumptions.py  — fetch_assumptions, update_assumptions
    planning_allowances.py   — ISA/pension/dividend/CGT/carry-forward/overrides
    planning_reviews.py      — monthly reviews and review items
    planning_snapshots.py    — monthly + daily snapshots, performance history

Re-exports are provided here so that app/models/__init__.py can keep a single
import surface.
"""
from ._conn import get_connection

# Re-export submodule functions so __init__.py only needs to import from here
from .planning_assumptions import fetch_assumptions, update_assumptions
from .planning_allowances import (
    fetch_allowance_tracking,
    add_isa_contribution,
    fetch_isa_contributions,
    delete_isa_contribution,
    add_pension_contribution,
    fetch_pension_contributions,
    delete_pension_contribution,
    add_dividend_record,
    fetch_dividend_records,
    delete_dividend_record,
    add_cgt_disposal,
    fetch_cgt_disposals,
    delete_cgt_disposal,
    fetch_pension_carry_forward,
    upsert_pension_carry_forward,
    delete_pension_carry_forward,
    fetch_contribution_overrides,
    fetch_all_active_overrides,
    create_contribution_override,
    remove_contribution_override_for_month,
    upsert_single_month_contribution_override,
    delete_contribution_override,
)
from .planning_reviews import (
    fetch_or_create_monthly_review,
    fetch_monthly_review,
    fetch_monthly_review_items,
    ensure_monthly_review_items,
    update_monthly_review,
    update_monthly_review_item,
    set_contribution_confirmed,
    mark_review_item_updated,
    fetch_tax_year_contributions,
)
from .planning_snapshots import (
    upsert_monthly_snapshot,
    fetch_net_worth_history,
    fetch_account_snapshot_history,
    fetch_monthly_performance_data,
    fetch_monthly_performance_data_by_account,
    save_daily_snapshot,
    fetch_daily_snapshots,
    save_account_daily_snapshots,
    fetch_account_daily_snapshots,
)


# ── Constants ─────────────────────────────────────────────────────────────────

WRAPPER_TYPE_OPTIONS = [
    "Stocks & Shares ISA",
    "Cash ISA",
    "Lifetime ISA",
    "SIPP",
    "Workplace Pension",
    "General Investment Account",
    "Other",
]

CATEGORY_OPTIONS = [
    "ISA",
    "Pension",
    "Taxable",
    "Other",
]

DEFAULT_TAG_OPTIONS = [
    "Retirement",
    "Emergency Fund",
    "Accessible Investing",
    "General Investing",
    "Short-Term Savings",
    "Bridge to Retirement",
    "Long-Term",
    "Other",
]

TAG_OPTIONS = DEFAULT_TAG_OPTIONS  # backwards compat alias


DEFAULT_HOLDING_CATALOGUE = [  # kept for reference only — no longer auto-seeded
    # ── Global equity ETFs ─────────────────────────────────────────────────
    {"holding_name": "Vanguard FTSE Developed World UCITS ETF (Acc)", "ticker": "VHVG", "asset_type": "ETF", "bucket": "Developed World Equity", "notes": ""},
    {"holding_name": "Vanguard FTSE All-World UCITS ETF (Acc)", "ticker": "VWRP", "asset_type": "ETF", "bucket": "Global / All-World Equity", "notes": ""},
    {"holding_name": "Vanguard FTSE All-World UCITS ETF (Dist)", "ticker": "VWRL", "asset_type": "ETF", "bucket": "Global / All-World Equity", "notes": ""},
    {"holding_name": "Vanguard FTSE Global All Cap Index Fund", "ticker": "", "asset_type": "Fund", "bucket": "Global / All-World Equity", "notes": "Includes small cap"},
    {"holding_name": "Vanguard FTSE Emerging Markets UCITS ETF (Acc)", "ticker": "VFEG", "asset_type": "ETF", "bucket": "Emerging Markets Equity", "notes": ""},
    {"holding_name": "iShares Core MSCI World UCITS ETF (Acc)", "ticker": "SWDA", "asset_type": "ETF", "bucket": "Developed World Equity", "notes": "MSCI World, USD-based"},
    {"holding_name": "iShares MSCI All Country World UCITS ETF (Acc)", "ticker": "SSAC", "asset_type": "ETF", "bucket": "Global / All-World Equity", "notes": ""},
    {"holding_name": "iShares Core MSCI Emerging Markets IMI UCITS ETF", "ticker": "EMIM", "asset_type": "ETF", "bucket": "Emerging Markets Equity", "notes": ""},
    {"holding_name": "HSBC FTSE All-World Index C Acc", "ticker": "0P00013P6I.L", "asset_type": "Fund", "bucket": "Global / All-World Equity", "notes": ""},
    {"holding_name": "Fidelity Index World Fund P Accumulation", "ticker": "", "asset_type": "Fund", "bucket": "Developed World Equity", "notes": "MSCI World tracker"},
    {"holding_name": "Fidelity Index Emerging Markets Fund P Accumulation", "ticker": "", "asset_type": "Fund", "bucket": "Emerging Markets Equity", "notes": ""},
    {"holding_name": "L&G International Index Trust I Acc", "ticker": "", "asset_type": "Fund", "bucket": "Developed World Equity", "notes": ""},
    {"holding_name": "Invesco FTSE All-World UCITS ETF Acc", "ticker": "FWRG", "asset_type": "ETF", "bucket": "Global / All-World Equity", "notes": "Lower ongoing charges"},
    # ── UK equity ─────────────────────────────────────────────────────────
    {"holding_name": "Vanguard FTSE 100 UCITS ETF (Dist)", "ticker": "VUKE", "asset_type": "ETF", "bucket": "UK Equity", "notes": ""},
    {"holding_name": "Vanguard FTSE UK All Share Index Unit Trust Acc", "ticker": "", "asset_type": "Fund", "bucket": "UK Equity", "notes": ""},
    {"holding_name": "iShares Core FTSE 100 UCITS ETF (Dist)", "ticker": "ISF", "asset_type": "ETF", "bucket": "UK Equity", "notes": ""},
    {"holding_name": "Fidelity Index UK Fund P Accumulation", "ticker": "", "asset_type": "Fund", "bucket": "UK Equity", "notes": ""},
    # ── Vanguard LifeStrategy ──────────────────────────────────────────────
    {"holding_name": "Vanguard LifeStrategy 100% Equity Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "Global / All-World Equity", "notes": "100% equities, UK-biased"},
    {"holding_name": "Vanguard LifeStrategy 80% Equity Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "Mixed / Multi-Asset", "notes": "80% equity, 20% bonds"},
    {"holding_name": "Vanguard LifeStrategy 60% Equity Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "Mixed / Multi-Asset", "notes": "60% equity, 40% bonds"},
    {"holding_name": "Vanguard LifeStrategy 40% Equity Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "Mixed / Multi-Asset", "notes": "40% equity, 60% bonds"},
    # ── Bonds / Fixed income ───────────────────────────────────────────────
    {"holding_name": "Vanguard UK Government Bond Index Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "UK Bonds / Fixed Income", "notes": ""},
    {"holding_name": "Vanguard Global Bond Index Fund GBP Hedged Acc", "ticker": "", "asset_type": "Fund", "bucket": "Global Bonds", "notes": ""},
    {"holding_name": "iShares Core Global Aggregate Bond UCITS ETF GBP Hedged", "ticker": "AGBP", "asset_type": "ETF", "bucket": "Global Bonds", "notes": ""},
    {"holding_name": "Vanguard U.S. Government Bond Index Fund Acc", "ticker": "", "asset_type": "Fund", "bucket": "US Bonds", "notes": ""},
    # ── US equity ─────────────────────────────────────────────────────────
    {"holding_name": "Vanguard S&P 500 UCITS ETF (Acc)", "ticker": "VUAG", "asset_type": "ETF", "bucket": "US Equity", "notes": ""},
    {"holding_name": "Vanguard S&P 500 UCITS ETF (Dist)", "ticker": "VUSA", "asset_type": "ETF", "bucket": "US Equity", "notes": ""},
    {"holding_name": "iShares Core S&P 500 UCITS ETF (Acc)", "ticker": "CSP1", "asset_type": "ETF", "bucket": "US Equity", "notes": ""},
    {"holding_name": "Fidelity Index US Fund P Accumulation", "ticker": "", "asset_type": "Fund", "bucket": "US Equity", "notes": "S&P 500 tracker"},
    # ── Pension fund defaults ──────────────────────────────────────────────
    {"holding_name": "SL abrdn Evolve World Equity Index Pension Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "Standard Life workplace pension default"},
    {"holding_name": "Nest Higher Risk Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "Nest workplace pension"},
    {"holding_name": "Nest Sharia Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "Nest workplace pension"},
    {"holding_name": "Aviva My Future Focus Growth Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Mixed / Multi-Asset", "notes": "Aviva workplace pension default"},
    {"holding_name": "Legal & General PMC Global Equity Fixed Weights (50:50) Index", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "L&G workplace pension"},
    {"holding_name": "Legal & General PMC World Equity Index Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Developed World Equity", "notes": "L&G workplace pension"},
    {"holding_name": "Royal London Global Equity Select Fund", "ticker": "", "asset_type": "Pension Fund", "bucket": "Global / All-World Equity", "notes": "Royal London workplace pension"},
    # ── Money market / cash ────────────────────────────────────────────────
    {"holding_name": "Royal London Short Term Money Market Fund", "ticker": "", "asset_type": "Fund", "bucket": "Cash / Money Market", "notes": ""},
    {"holding_name": "Vanguard Sterling Short-Term Money Market Fund", "ticker": "", "asset_type": "Fund", "bucket": "Cash / Money Market", "notes": ""},
    # ── InvestEngine / Dodl popular ───────────────────────────────────────
    {"holding_name": "iShares MSCI World Small Cap UCITS ETF", "ticker": "WLDS", "asset_type": "ETF", "bucket": "Developed World Equity", "notes": "Small cap global"},
    {"holding_name": "Xtrackers MSCI World Swap UCITS ETF 1C", "ticker": "XDWD", "asset_type": "ETF", "bucket": "Developed World Equity", "notes": "Synthetic replication"},
]


# ── Tags ──────────────────────────────────────────────────────────────────────

def fetch_user_tags(user_id):
    """Return merged list: default tags + user's custom tags (de-duped, ordered)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tag FROM custom_tags WHERE user_id = ? ORDER BY tag",
            (user_id,),
        ).fetchall()
    custom = [r["tag"] for r in rows]
    merged = list(DEFAULT_TAG_OPTIONS)
    for tag in custom:
        if tag not in merged:
            merged.append(tag)
    return merged


def fetch_custom_tags(user_id):
    """Return just the user's custom tags."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tag FROM custom_tags WHERE user_id = ? ORDER BY tag",
            (user_id,),
        ).fetchall()
    return [r["tag"] for r in rows]


def add_custom_tag(user_id, tag):
    """Add a custom tag for a user. Returns True if added, False if duplicate."""
    tag = tag.strip()
    if not tag:
        return False
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO custom_tags (user_id, tag) VALUES (?, ?)",
                (user_id, tag),
            )
            conn.commit()
            return True
        except Exception:
            return False


def delete_custom_tag(user_id, tag):
    """Remove a custom tag. Returns True if deleted."""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM custom_tags WHERE user_id = ? AND tag = ?",
            (user_id, tag),
        )
        conn.commit()
        return cur.rowcount > 0


# ── Data resets ───────────────────────────────────────────────────────────────

def reset_catalogue(user_id):
    """Wipe all catalogue entries for a user."""
    with get_connection() as conn:
        conn.execute("DELETE FROM holding_catalogue WHERE user_id = ?", (user_id,))
        conn.commit()


def reset_all_user_data(user_id):
    """Wipe every piece of user data back to a fresh-login state.

    The user row itself is kept so they can log straight back in.
    """
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM holdings WHERE account_id IN "
            "(SELECT id FROM accounts WHERE user_id = ?)", (user_id,))
        conn.execute(
            "DELETE FROM contribution_overrides WHERE account_id IN "
            "(SELECT id FROM accounts WHERE user_id = ?)", (user_id,))
        conn.execute(
            "DELETE FROM monthly_snapshots WHERE account_id IN "
            "(SELECT id FROM accounts WHERE user_id = ?)", (user_id,))
        conn.execute(
            "DELETE FROM account_daily_snapshots WHERE account_id IN "
            "(SELECT id FROM accounts WHERE user_id = ?)", (user_id,))
        conn.execute("DELETE FROM accounts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM goals WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM assumptions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM holding_catalogue WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM isa_contributions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM pension_contributions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM dividend_records WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM cgt_disposals WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM pension_carry_forward WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM portfolio_daily_snapshots WHERE user_id = ?", (user_id,))
        conn.execute(
            "DELETE FROM monthly_review_items WHERE review_id IN "
            "(SELECT id FROM monthly_reviews WHERE user_id = ?)", (user_id,))
        conn.execute("DELETE FROM monthly_reviews WHERE user_id = ?", (user_id,))
        conn.execute(
            "DELETE FROM budget_entries WHERE budget_item_id IN "
            "(SELECT id FROM budget_items WHERE user_id = ?)", (user_id,))
        conn.execute("DELETE FROM budget_items WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM budget_sections WHERE user_id = ?", (user_id,))
        conn.commit()
