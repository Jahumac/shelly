# Architecture

Quick orientation for anyone (you, me, or a future contributor) coming back to this repo. Read once, refer when adding things.

## Layer cake

```
┌──────────────────────────────────────────────────────────────────┐
│  app/templates/*.html        Jinja templates (the UI)            │
│  app/static/css/, js/        Stylesheets, scripts                │
└──────────────────────────────────────────────────────────────────┘
                          ▲
┌──────────────────────────────────────────────────────────────────┐
│  app/routes/*.py             Flask blueprints                    │
│    auth, overview, accounts, holdings, goals, budget,            │
│    monthly_review, projections, performance, allowance,          │
│    settings, export, api                                         │
└──────────────────────────────────────────────────────────────────┘
                          ▲
┌──────────────────────────────────────────────────────────────────┐
│  app/services/*.py           Stateless logic that talks to the   │
│    csv_parsers, prices,      outside world (broker CSVs, Yahoo   │
│    backups, scheduler        Finance, scheduled jobs, backups)   │
└──────────────────────────────────────────────────────────────────┘
                          ▲
┌──────────────────────────────────────────────────────────────────┐
│  app/calculations.py         Pure number-crunching (no DB,       │
│                              no I/O, easy to unit-test)          │
└──────────────────────────────────────────────────────────────────┘
                          ▲
┌──────────────────────────────────────────────────────────────────┐
│  app/models/                 Persistence: tables + CRUD          │
│    _conn, schema, users,     fns. Every mutation scoped to       │
│    accounts, goals,          current user_id at this layer.      │
│    budget, planning                                              │
└──────────────────────────────────────────────────────────────────┘
                          ▲
┌──────────────────────────────────────────────────────────────────┐
│  data/finance.db             SQLite (WAL mode, FK enforced)      │
│  data/backups/               Daily snapshots, 30-day rotation    │
└──────────────────────────────────────────────────────────────────┘
```

**Direction of import is one-way down.** Routes import from models/services. Models never import routes. Services never import routes. Templates never call models directly.

## Models package layout

`app/models/` is split by domain. To find something, open the file that matches:

| File           | What lives here                                                       |
|----------------|-----------------------------------------------------------------------|
| `_conn.py`     | `get_connection`, `close_db`. Leaf module — imports nothing else.     |
| `schema.py`    | The full SQL schema + `init_db()` with all migrations and indexes.    |
| `users.py`     | `User` class, user CRUD, API token CRUD.                              |
| `goals.py`     | Savings/retirement goals.                                             |
| `accounts.py`  | Accounts, holdings, holding catalogue, prices.                        |
| `budget.py`    | Budget items, sections, monthly entries.                              |
| `planning.py`  | Assumptions, monthly reviews, snapshots, ISA/pension/dividend records, contribution overrides, tags, data resets. |
| `__init__.py`  | Re-exports everything so `from app.models import X` still works.      |

Every public symbol is re-exported from `__init__.py`. **Add a new function?** Put it in the right domain file, then add it to the `__init__.py` re-export list.

## Where to add things

### Add a new web page
1. Pick (or create) a blueprint in `app/routes/`.
2. Add a `@<bp>.route("/path")` decorator + `@login_required`.
3. Call model functions; render a Jinja template from `app/templates/`.
4. If the page has a hero summary strip, use `{% from '_macros.html' import hero_stat %}`.
5. Add a smoke test to `tests/test_smoke.py` (one line in `BLUEPRINT_PAGES`).

### Add a new database column or table
1. Add the `CREATE TABLE` / `ALTER TABLE ... ADD COLUMN` to `app/models/schema.py` inside `init_db()`. Wrap in `try/except` if it's a column on an existing table (idempotent).
2. Add an index for any new foreign key (search the indexes block at the end of `init_db()` for the pattern).
3. Add fetch/create/update/delete functions to the appropriate domain file (e.g. `accounts.py`).
4. **Always scope mutations to `user_id`** — use the existing `update_holding(payload, user_id)` style. Smoke tests in `tests/test_ownership.py` will catch missed scoping.
5. Re-export from `models/__init__.py`.

### Add a new API endpoint
1. Add the route to `app/routes/api.py` under the `/api/v1/*` prefix.
2. Decorate with `@api_auth_required`.
3. Use `g.api_user.id` for the current user.
4. Return JSON with the standard `_err(code, message, status)` helper for errors.
5. Add tests to `tests/test_api.py`. Document in `API.md`.

### Add a new broker CSV importer
1. Add a `parse_<broker>(file_bytes) -> list[dict]` function to `app/services/csv_parsers.py`.
2. Wire it into the `PARSERS` dict in `app/routes/monthly_review.py`.
3. Add a `PLATFORM_LABELS` entry.

### Add a new scheduled job
1. Add the function to `app/services/scheduler.py` (suffix it `_scheduled_*`).
2. Register it in `init_scheduler()` with a `CronTrigger`.
3. Wrap the body in `try/except` so a job failure can never crash the scheduler loop.

## Conventions worth following

- **All times in the scheduler** are UK time (`Europe/London`) — match that in any new job.
- **Config from env vars first** (`app/config.py`). New options should follow `os.environ.get("X", default)`.
- **Don't bypass the model layer** from routes — even one-off SQL belongs as a named function in `models/`.
- **Tests live in `tests/`** and run with `.venv/bin/pytest` (~9s, 71 tests as of writing). The fixtures in `tests/conftest.py` give you an ephemeral SQLite DB per test plus an authenticated client.
- **Demo mode**: the `enforce_read_only_demo` hook in `app/__init__.py` blocks POSTs from a designated `DEMO_READ_ONLY_USERNAME`. Don't disable it; the hook handles both HTML and JSON paths.
- **CSRF**: enabled by default. The `/api/v1/*` blueprint is exempt because it uses Bearer-token auth instead of cookies.
- **Migrations**: versioned via the `schema_migrations` table for one-shot data migrations; for additive column adds use the idempotent `try ALTER TABLE / except` pattern. Both already exist in `schema.py` — copy the nearest example.

## What lives where, in one paragraph

A user POSTs to `/accounts/123/holdings/456/edit`. **`app/routes/accounts.py`** receives it, validates the form, then calls **`app/models/accounts.py::update_holding(payload, current_user.id)`** which scopes the mutation by user. The model writes to **`data/finance.db`** via the connection from **`app/models/_conn.py`**. If the route needs to fetch a price, it calls **`app/services/prices.py::fetch_price(ticker)`** which talks to Yahoo Finance. If a calculation is needed (e.g. effective fee), **`app/calculations.py`** has pure functions for it. The response renders **`app/templates/accounts.html`**, which uses utilities from **`app/static/css/styles.css`** and macros from **`app/templates/_macros.html`**. The `/api/v1/health` endpoint (in **`app/routes/api.py`**) checks that `data/backups/` has a recent file produced by the daily job in **`app/services/backups.py`** — itself triggered by **`app/services/scheduler.py`**.

That's the whole shape.
