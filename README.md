# shelly-finance

A self-hosted personal finance dashboard for UK investors 🐢. Track your accounts, holdings, budget, goals and retirement projections — hosted on your own server/home network.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Flask](https://img.shields.io/badge/Flask-3.x-green) ![SQLite](https://img.shields.io/badge/SQLite-local-lightgrey) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Why shelly-finance?

Most finance apps want your login credentials or send your data to the cloud. Shelly runs entirely on your machine (or home server) with a local SQLite database. No accounts to create with a third party, no API keys to hand over, no data leaving your network.

It's designed specifically for **UK investors** — ISAs, SIPPs, Lifetime ISAs, workplace pensions, GIAs — with GBP currency, UK tax year tracking, and CSV import from major UK brokers.

---

## Features

### Accounts & Holdings
Track any combination of investment accounts: Stocks & Shares ISA, Cash ISA, Lifetime ISA, SIPP, Workplace Pension, GIA, and more. Each account can be valued manually (enter a balance) or built up from individual holdings with live price lookups via Yahoo Finance.

### Broker CSV Import
Import holdings directly from your broker's CSV export. Supported platforms:

- **Trading 212** — transaction history (buys/sells reconciled to net positions)
- **InvestEngine** — valuation statements or transaction history
- **Vanguard Investor** — portfolio snapshot
- **Hargreaves Lansdown** — portfolio snapshot (handles pence-to-pounds conversion)
- **AJ Bell** — portfolio snapshot
- **Freetrade** — activity export (buys/sells/dividend reinvestments)
- **Interactive Investor** — portfolio snapshot
- **Generic CSV** — flexible column matching for any other format

Don't use any of these? Download the [CSV template](app/static/shelly-holdings-template.csv) and fill in your holdings manually.

### Monthly Review
A guided monthly workflow to update your holdings and account balances. Upload a broker CSV or edit values manually, preview changes before applying, and mark the month as complete. Snapshots are saved so you can track how your portfolio changes over time.

### Budget
Monthly income, expenses and savings overview with auto-save. Navigate between months with arrows. Budget items can be linked directly to account contributions so your savings plan stays in sync.

### Goals
Set savings targets and track progress. Goals can be linked to tagged accounts — e.g. tag your ISA accounts as "Retirement" and create a goal that tracks the combined balance.

### Retirement Projections
Year-by-year and month-by-month projections based on current balances, monthly contributions and growth assumptions. Respects Lifetime ISA contribution rules (stops at age 50). Export projections to Excel (.xlsx) with per-account breakdowns.

### Granular Fee Tracking
Accounts support detailed fee modelling: platform fee (% with optional £ cap), flat annual platform fee (£), and fund fee / OCF (%). Shelly combines these into an effective annual fee, subtracts it from your growth rate, and shows the lifetime cost of fees in both the app and Excel exports. All fee fields are optional — tucked behind an "Advanced: Fees" toggle so they don't clutter the setup for casual users. Projections show "with fees" vs "without fees" so you can see exactly what your broker and funds cost you over time.

### Performance Tracking
Track your actual portfolio returns over time using the modified Dietz method. Compare actual performance against a projected "on-plan" growth line.

### Tax Year Tracking
ISA and Lifetime ISA allowance progress bars, tax year countdown, and automatic tax year labelling (April 6 boundary).

### Multi-User Support
Multiple users can share a single Shelly instance, each with their own accounts, budgets and data. Admin user manages access.

### Contribution Overrides
Temporarily change a monthly contribution (e.g. parental leave, career break) without losing your long-term plan.

### PWA & Mobile
- Install Shelly as a phone app — visit the URL in your mobile browser and tap "Add to Home Screen". Works full-screen with its own icon.
- Offline-friendly app shell with a service worker; network-first for pages and API to keep data fresh.

### Install on Mobile
- iOS (Safari): open the URL → Share → Add to Home Screen
- Android (Chrome): open the URL → menu → Install app / Add to Home screen

### Demo Mode (Read‑only)
- Optional read‑only demo user for safe exploration (default username: `demo`). Any POST writes from the demo account are blocked.
- Optional passwordless demo entry: set `DEMO_PUBLIC_LOGIN_ENABLED=1` and create the demo user, then use `/demo` (or the “Try demo” button on the login page).

---

## Quick Start (Local)

**Requirements:** Python 3.10+

```bash
# 1. Clone the repo
git clone https://github.com/jahumac/shelly-finance.git
cd shelly-finance

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python run.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser. On first run you'll be asked to create an admin account. The SQLite database is created automatically in `data/finance.db`.

To run in debug mode with auto-reload:

```bash
FLASK_DEBUG=1 python run.py
```

---

## Docker (Recommended for Self-Hosting)

```bash
docker compose up -d
```

The app runs on port **8001** by default (mapped to port 8000 inside the container). Your database persists in the `data/` directory which is mounted as a volume.

To change the port, edit `docker-compose.yml`:

```yaml
ports:
  - "9000:8000"   # host:container — change the left number
```

### Unraid / Home Server

See [DEPLOY.md](DEPLOY.md) for step-by-step instructions on deploying to Unraid via Docker, including SSH setup, volume mounting, and update workflow.

---

## CSV Import Guide

### From Your Broker

1. Go to **Monthly Review** in Shelly
2. Select your broker from the dropdown
3. Upload the CSV file your broker provides (usually found under "Statements", "Export", or "Download" in your broker's app/website)
4. Shelly will match the CSV rows to your existing holdings, showing you a preview
5. Review, adjust if needed, and confirm the import

### Using the Template

If your broker isn't listed, or you prefer to enter holdings manually in bulk:

1. Download [`shelly-holdings-template.csv`](app/static/shelly-holdings-template.csv)
2. Fill in your holdings — one row per holding with: `name`, `ticker`, `units`, `price`, `value`
3. Import using the **Generic CSV** option in Monthly Review

The template looks like this:

```csv
name,ticker,units,price,value
Vanguard FTSE Global All Cap Index Fund,GB00BD3RZ582,150.2345,187.63,28186.72
Vanguard LifeStrategy 80% Equity Fund,GB00B4PQW151,85.1200,243.10,20693.47
iShares Core MSCI World ETF,SWDA,42.0000,82.15,3450.30
```

**Note:** The CSV import updates existing holdings that are already set up in Shelly (matched by ticker or name). To get started, add your accounts and holdings through the app first, then use CSV import for quick monthly updates going forward.

---

## Project Structure

```
app/
├── __init__.py            # App factory, blueprint registration, login manager
├── config.py              # Database path, secret key management
├── models.py              # SQLite schema + all data access functions
├── calculations.py        # Projections, returns, goal tracking, tax year logic
├── routes/
│   ├── auth.py            # Login, setup, user management
│   ├── overview.py        # Dashboard with metrics and net worth chart
│   ├── accounts.py        # Account + holdings CRUD, allocation charts
│   ├── holdings.py        # Ticker lookup API (Yahoo Finance)
│   ├── budget.py          # Budget CRUD, AJAX auto-save, monthly navigation
│   ├── goals.py           # Goal tracking with tag-based account linking
│   ├── projections.py     # Retirement projection engine
│   ├── performance.py     # Modified Dietz returns tracking
│   ├── monthly_review.py  # Monthly update workflow + CSV import
│   ├── export.py          # Excel export (projections + budget)
│   └── settings.py        # Global assumptions (growth rate, ages, allowances)
├── services/
│   ├── csv_parsers.py     # 8 broker-specific CSV parsers
│   └── prices.py          # Yahoo Finance price fetcher
├── templates/             # Jinja2 HTML templates (dark theme)
└── static/
    ├── css/styles.css     # Single stylesheet — dark theme design system
    ├── js/charts.js       # Chart rendering
    ├── manifest.json      # PWA manifest
    ├── sw.js              # Service worker
    └── icons/             # App icons (180px, 192px, 512px)
data/
├── finance.db             # SQLite database (auto-created, git-ignored)
└── secret_key.txt         # Flask secret key (auto-generated, git-ignored)
```

---

## Screenshots

To add screenshots to the repo front page:

1. Create a folder (e.g. `docs/screenshots/`) and add PNGs
2. Add image links here, for example:

```md
![Overview](docs/screenshots/overview.png)
![Accounts](docs/screenshots/accounts.png)
![Budget](docs/screenshots/budget.png)
```

---

## Roadmap

- Read‑only demo mode for public try‑outs (done).
- Better offline experience: cached read‑only views with clear “offline” indicators.
- Diagnostics page: last scheduler run, Yahoo price fetch status, DB health.
- Import UX: smarter column matching and validation hints.
- Alerts: allowance nearing limits, spending spikes, price update failures.
- Desktop packaging: Tauri/Electron wrapper.
- Optional migration to versioned API endpoints to simplify mobile-native clients.

---

## How It Works

### Data Storage
Everything lives in a single SQLite file (`data/finance.db`). No external database to configure. The `data/` directory is git-ignored — your financial data never ends up in version control.

### Live Prices
Holdings with a ticker symbol get live price lookups via Yahoo Finance. Shelly tries the ticker as-is first, then appends `.L` for London Stock Exchange listings. Prices are cached in a local catalogue and updated when you refresh.

### Monthly Snapshots
Each time you complete a monthly review (or update an account balance), Shelly saves a snapshot. These snapshots power the net worth history chart on the overview page and the performance tracking calculations.

### Security
Shelly uses Flask-Login for authentication with hashed passwords. It's designed for home network use — if you want to expose it to the internet, put it behind a reverse proxy with additional auth (e.g. Authelia, Cloudflare Tunnel, or basic auth).

---

## Supported Account Types

| Type | Description |
|------|-------------|
| Stocks & Shares ISA | Tax-free investment wrapper |
| Cash ISA | Tax-free cash savings |
| Lifetime ISA | Government-bonused savings (25% top-up, age restrictions) |
| SIPP | Self-invested personal pension |
| Workplace Pension | Employer pension scheme |
| General Investment Account | Standard taxable investment account |
| Other | Anything else you want to track |

---

## Known Limitations

- **GBP only** — no multi-currency support yet
- **UK-focused** — account types and tax year logic are UK-specific
- **Yahoo Finance** — live prices depend on Yahoo Finance availability; some funds may not have tickers
- **Single device** — no cloud sync between devices (by design)

---

## Contributing

Shelly is a personal project shared for others to use and learn from. If you find a bug or have a feature idea, feel free to open an issue. Pull requests are welcome.

---

## License

MIT — use it, fork it, break it, fix it.
