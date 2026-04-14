"""Models package — public API surface.

Every existing `from app.models import X` import keeps working because this
file re-exports everything from the domain submodules.

Layout:
    _conn.py     — sqlite3 connection + close_db (leaf, no internal deps)
    schema.py    — SCHEMA string + init_db with all migrations
    users.py     — User class, user CRUD, API tokens
    goals.py     — savings/retirement goals
    accounts.py  — accounts, holdings, holding catalogue, prices
    budget.py    — budget items, sections, monthly entries
    planning.py  — assumptions, monthly reviews, snapshots, allowance
                   tracking (ISA/pension/dividend), overrides, tags, resets

If you're adding a new model function, put it in the file that matches its
domain. If it doesn't fit any cleanly, that's a sign you may need a new
submodule — talk it through before spreading the surface area.
"""

# Connection + schema
from ._conn import close_db, get_connection
from .schema import SCHEMA, init_db

# Users + API tokens
from .users import (
    User,
    count_users,
    create_api_token,
    create_user,
    delete_user,
    fetch_all_users,
    fetch_api_tokens,
    fetch_user_by_api_token,
    get_user_by_id,
    get_user_by_username,
    revoke_api_token,
    update_user,
)

# Goals
from .goals import (
    create_goal,
    delete_goal,
    fetch_all_goals,
    fetch_goal,
    fetch_primary_goal,
    update_goal,
)

# Accounts + holdings + catalogue
from .accounts import (
    add_holding,
    add_holding_catalogue_item,
    create_account,
    delete_account,
    delete_holding,
    delete_holding_catalogue_item,
    fetch_account,
    fetch_all_accounts,
    fetch_all_holdings,
    fetch_all_holdings_grouped,
    fetch_catalogue_holding,
    fetch_catalogue_with_prices,
    fetch_first_position_for_catalogue_holding,
    fetch_holding,
    fetch_holding_catalogue,
    fetch_holding_catalogue_in_use,
    fetch_holding_totals_by_account,
    fetch_holdings_for_account,
    fetch_instruments_in_use,
    fetch_latest_price_update,
    reconnect_holdings_to_catalogue,
    sync_holding_prices_from_catalogue,
    update_account,
    update_catalogue_price,
    update_holding,
    update_holding_catalogue_item,
)

# Budget
from .budget import (
    create_budget_item,
    create_budget_section,
    delete_budget_item,
    delete_budget_items_by_section,
    delete_budget_section,
    fetch_budget_entries,
    fetch_budget_item,
    fetch_budget_items,
    fetch_budget_sections,
    fetch_months_with_budget_entries,
    fetch_prior_month_budget_entries,
    update_budget_item,
    update_budget_section,
    upsert_budget_entry,
)

# Planning, snapshots, allowances, overrides, tags, resets
from .planning import (
    CATEGORY_OPTIONS,
    DEFAULT_HOLDING_CATALOGUE,
    DEFAULT_TAG_OPTIONS,
    TAG_OPTIONS,
    WRAPPER_TYPE_OPTIONS,
    add_cgt_disposal,
    add_custom_tag,
    add_dividend_record,
    add_isa_contribution,
    add_pension_contribution,
    create_contribution_override,
    delete_cgt_disposal,
    delete_contribution_override,
    delete_custom_tag,
    delete_dividend_record,
    delete_isa_contribution,
    delete_pension_contribution,
    ensure_monthly_review_items,
    fetch_account_snapshot_history,
    fetch_all_active_overrides,
    fetch_allowance_tracking,
    fetch_assumptions,
    fetch_contribution_overrides,
    fetch_custom_tags,
    fetch_daily_snapshots,
    fetch_cgt_disposals,
    fetch_dividend_records,
    fetch_isa_contributions,
    fetch_monthly_performance_data,
    fetch_monthly_performance_data_by_account,
    fetch_monthly_review_items,
    fetch_net_worth_history,
    fetch_or_create_monthly_review,
    fetch_pension_contributions,
    fetch_user_tags,
    reset_all_user_data,
    reset_catalogue,
    save_daily_snapshot,
    update_assumptions,
    update_monthly_review,
    update_monthly_review_item,
    upsert_monthly_snapshot,
)
