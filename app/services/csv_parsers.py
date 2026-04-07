"""CSV parsers for bulk-importing investment holdings from brokerage exports."""

import csv
import io
from datetime import datetime


def _safe_float(value, default=0.0):
    """Parse a float from a string, returning default on failure."""
    try:
        return float((value or "").replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def parse_trading212(file_bytes):
    """
    Parse a Trading 212 transaction history CSV.

    Expected columns:
        Action, Time, ISIN, Ticker, Name, No. of shares, Price / share,
        Currency (Price / share), Exchange rate, Result, Total,
        Withholding tax, Currency conversion fee, Notes

    Returns a list of dicts: [{ticker, name, units, price}, ...]
    Only positions with net positive units are returned.
    """
    try:
        text = file_bytes.decode("utf-8-sig")  # strip BOM if present
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))

    # Validate expected columns exist
    fieldnames = reader.fieldnames or []
    if "Ticker" not in fieldnames or "Action" not in fieldnames:
        raise ValueError(
            "File does not look like a Trading 212 transaction history. "
            "Expected columns: Action, Ticker, Name, No. of shares, Price / share, Time."
        )

    BUY_ACTIONS = {"market buy", "limit buy", "stop buy", "market buy (isa)", "limit buy (isa)"}
    SELL_ACTIONS = {"market sell", "limit sell", "stop sell", "market sell (isa)", "limit sell (isa)"}

    # {ticker: {name, net_units, latest_time, latest_price}}
    positions = {}

    for row in reader:
        action = (row.get("Action") or "").strip().lower()
        ticker = (row.get("Ticker") or "").strip()
        name = (row.get("Name") or "").strip()

        if not ticker:
            continue
        if action not in BUY_ACTIONS and action not in SELL_ACTIONS:
            continue

        shares = _safe_float(row.get("No. of shares"))
        price = _safe_float(row.get("Price / share"))

        # Parse trade time for recency tracking
        time_str = (row.get("Time") or "").strip()
        trade_time = datetime.min
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                trade_time = datetime.strptime(time_str, fmt)
                break
            except ValueError:
                continue

        if ticker not in positions:
            positions[ticker] = {
                "name": name or ticker,
                "net_units": 0.0,
                "latest_time": datetime.min,
                "latest_price": 0.0,
            }

        if action in BUY_ACTIONS:
            positions[ticker]["net_units"] += shares
        else:
            positions[ticker]["net_units"] -= shares

        if trade_time >= positions[ticker]["latest_time"]:
            positions[ticker]["latest_time"] = trade_time
            positions[ticker]["latest_price"] = price
            if name:
                positions[ticker]["name"] = name

    result = []
    for ticker, data in positions.items():
        if data["net_units"] > 0.00001:  # filter fully-sold positions
            result.append({
                "ticker": ticker,
                "name": data["name"],
                "units": round(data["net_units"], 6),
                "price": round(data["latest_price"], 4),
            })

    result.sort(key=lambda x: x["ticker"])
    return result


def parse_investengine(file_bytes):
    """
    Parse an InvestEngine CSV — supports both:
      1. Valuation statement (recommended): snapshot of holdings with values
      2. Transaction history (legacy): buy/sell records

    The parser auto-detects the format based on column headers.

    Valuation statement columns (case-insensitive, flexible matching):
        ISIN, Description/Name, Units/Shares, Price, Value/Amount

    Transaction history columns:
        Type, SettleDate, ISIN, Description, Amount, CurrencyPrimary

    Returns a list of dicts: [{ticker, name, units, price}, ...]
    """
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    fieldnames_lc = [f.strip().lower() for f in fieldnames]

    # Detect format: if there's a "Type" column with buy/sell actions, it's
    # transaction history. Otherwise treat as a valuation/snapshot report.
    has_type_col = "Type" in fieldnames or "type" in fieldnames_lc
    has_units_col = _find_col(fieldnames_lc, ["units", "shares", "quantity", "units held"])
    has_value_col = _find_col(fieldnames_lc, ["value", "market value", "total value", "amount"])

    # If we have units or no Type column, treat as valuation snapshot
    if has_units_col or (not has_type_col and has_value_col):
        return _parse_investengine_valuation(text, fieldnames_lc)
    elif has_type_col:
        return _parse_investengine_transactions(text, fieldnames)
    else:
        raise ValueError(
            "File does not look like an InvestEngine export. "
            "Expected either a Valuation statement or Transaction history CSV."
        )


def _parse_investengine_valuation(text, fieldnames_lc):
    """Parse InvestEngine Valuation statement CSV (portfolio snapshot)."""
    reader = csv.DictReader(io.StringIO(text))

    col_name = _find_col(fieldnames_lc, ["description", "name", "holding", "investment", "fund"])
    col_isin = _find_col(fieldnames_lc, ["isin", "sedol", "ticker", "symbol"])
    col_units = _find_col(fieldnames_lc, ["units", "shares", "quantity", "units held"])
    col_price = _find_col(fieldnames_lc, ["price", "unit price", "price (p)"])
    col_value = _find_col(fieldnames_lc, ["value", "market value", "total value", "amount"])

    if not col_name and not col_isin:
        raise ValueError(
            "Valuation statement CSV needs at least a Description/Name or ISIN column."
        )

    result = []
    for row in reader:
        row_lc = {k.strip().lower(): v for k, v in row.items()}
        name = (row_lc.get(col_name) or "").strip() if col_name else ""
        isin = (row_lc.get(col_isin) or "").strip() if col_isin else ""
        units = _safe_float(row_lc.get(col_units)) if col_units else None
        price = _safe_float(row_lc.get(col_price)) if col_price else None
        value = _safe_float(row_lc.get(col_value)) if col_value else None

        if not name and not isin:
            continue
        # Skip rows that look like totals or headers
        if name and name.lower() in ("total", "grand total", ""):
            continue

        entry = {"ticker": isin or "", "name": name or isin, "units": units, "price": price}
        if value is not None and not units:
            entry["value"] = value
        result.append(entry)

    result.sort(key=lambda x: x["name"])
    return result


def _parse_investengine_transactions(text, fieldnames):
    """Parse InvestEngine transaction history CSV (legacy format)."""
    reader = csv.DictReader(io.StringIO(text))

    BUY_KEYWORDS = {"buy", "purchase", "invest", "reinvest"}
    SELL_KEYWORDS = {"sell", "sale", "withdrawal", "disinvest"}

    positions = {}

    for row in reader:
        row_type = (row.get("Type") or "").strip().lower()
        isin = (row.get("ISIN") or "").strip()
        description = (row.get("Description") or "").strip()

        key = isin or description
        if not key:
            continue

        amount = _safe_float(row.get("Amount"))

        settle_str = (row.get("SettleDate") or "").strip()
        settle_date = datetime.min
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                settle_date = datetime.strptime(settle_str, fmt)
                break
            except ValueError:
                continue

        if key not in positions:
            positions[key] = {
                "isin": isin,
                "name": description or isin,
                "net_amount": 0.0,
                "latest_date": datetime.min,
            }

        is_buy = any(kw in row_type for kw in BUY_KEYWORDS)
        is_sell = any(kw in row_type for kw in SELL_KEYWORDS)

        if is_buy:
            positions[key]["net_amount"] += abs(amount)
        elif is_sell:
            positions[key]["net_amount"] -= abs(amount)

        if settle_date >= positions[key]["latest_date"]:
            positions[key]["latest_date"] = settle_date
            if description:
                positions[key]["name"] = description

    result = []
    for key, data in positions.items():
        if data["net_amount"] > 0.01:
            result.append({
                "ticker": data["isin"] or key,
                "name": data["name"],
                "units": None,
                "price": None,
                "value": round(data["net_amount"], 2),
            })

    result.sort(key=lambda x: x["name"])
    return result


def parse_vanguard(file_bytes):
    """
    Parse a Vanguard Investor portfolio CSV (holdings snapshot).

    Expected columns (case-insensitive):
        Investment name, Sedol, ISIN, Units, Price, Value

    Returns a list of dicts: [{ticker, name, units, price}, ...]
    """
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]

    # Map flexible column names
    col_name = _find_col(fieldnames, ["investment name", "investment", "fund name", "fund", "name"])
    col_ticker = _find_col(fieldnames, ["sedol", "isin", "ticker", "symbol"])
    col_units = _find_col(fieldnames, ["units", "quantity", "shares", "units held"])
    col_price = _find_col(fieldnames, ["price", "price (p)", "unit price"])
    col_value = _find_col(fieldnames, ["value", "total value", "market value"])

    if not col_name and not col_ticker:
        raise ValueError(
            "File does not look like a Vanguard portfolio export. "
            "Expected columns like: Investment name, Sedol/ISIN, Units, Price, Value."
        )

    result = []
    for row in reader:
        row_lc = {k.strip().lower(): v for k, v in row.items()}
        name = (row_lc.get(col_name) or "").strip() if col_name else ""
        ticker = (row_lc.get(col_ticker) or "").strip() if col_ticker else ""
        units = _safe_float(row_lc.get(col_units)) if col_units else None
        price = _safe_float(row_lc.get(col_price)) if col_price else None
        value = _safe_float(row_lc.get(col_value)) if col_value else None

        # Vanguard sometimes gives price in pence — convert if > 100 and value suggests pounds
        if price and value and units and units > 0:
            expected = units * price
            if expected > value * 50:  # price is probably in pence
                price = price / 100.0

        if not name and not ticker:
            continue

        entry = {"ticker": ticker or "", "name": name or ticker, "units": units, "price": price}
        if value and not units:
            entry["value"] = value
        result.append(entry)

    result.sort(key=lambda x: x["name"])
    return result


def parse_hl(file_bytes):
    """
    Parse a Hargreaves Lansdown portfolio CSV.

    Expected columns (case-insensitive):
        Stock, Sedol, Units held, Price (p), Value (£)
    """
    return _parse_portfolio_snapshot(file_bytes, "Hargreaves Lansdown", [
        (["stock", "holding name", "investment", "name"], "name"),
        (["sedol", "ticker", "epic", "isin"], "ticker"),
        (["units held", "quantity", "units", "shares"], "units"),
        (["price (p)", "price", "current price"], "price"),
        (["value (£)", "value", "total value", "market value"], "value"),
    ], pence_price=True)


def parse_ajbell(file_bytes):
    """
    Parse an AJ Bell portfolio CSV.

    Expected columns (case-insensitive):
        Investment, SEDOL, Quantity, Price, Value
    """
    return _parse_portfolio_snapshot(file_bytes, "AJ Bell", [
        (["investment", "holding", "name", "fund"], "name"),
        (["sedol", "ticker", "isin", "epic"], "ticker"),
        (["quantity", "units", "shares", "units held"], "units"),
        (["price", "current price", "price (p)"], "price"),
        (["value", "total value", "market value", "value (£)"], "value"),
    ], pence_price=True)


def parse_freetrade(file_bytes):
    """
    Parse a Freetrade activity export CSV.

    Expected columns (case-insensitive):
        Title, Ticker, Type, Quantity, Price per share, Total amount
    """
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]

    col_name = _find_col(fieldnames, ["title", "name", "instrument", "holding"])
    col_ticker = _find_col(fieldnames, ["ticker", "symbol", "epic", "isin"])
    col_type = _find_col(fieldnames, ["type", "activity type", "action"])
    col_qty = _find_col(fieldnames, ["quantity", "shares", "no. of shares", "units"])
    col_price = _find_col(fieldnames, ["price per share", "price", "price / share"])

    if not col_ticker and not col_name:
        raise ValueError(
            "File does not look like a Freetrade export. "
            "Expected columns like: Title, Ticker, Type, Quantity, Price per share."
        )

    BUY_KW = {"buy", "purchase", "dividend reinvestment"}
    SELL_KW = {"sell", "sale"}

    positions = {}
    for row in reader:
        row_lc = {k.strip().lower(): v for k, v in row.items()}
        action = (row_lc.get(col_type) or "").strip().lower() if col_type else "buy"
        ticker = (row_lc.get(col_ticker) or "").strip() if col_ticker else ""
        name = (row_lc.get(col_name) or "").strip() if col_name else ticker
        qty = _safe_float(row_lc.get(col_qty)) if col_qty else 0.0
        price = _safe_float(row_lc.get(col_price)) if col_price else 0.0

        key = ticker or name
        if not key:
            continue

        if key not in positions:
            positions[key] = {"name": name or ticker, "net_units": 0.0, "latest_price": 0.0}

        is_buy = any(kw in action for kw in BUY_KW)
        is_sell = any(kw in action for kw in SELL_KW)

        if is_sell:
            positions[key]["net_units"] -= qty
        elif is_buy or not col_type:
            positions[key]["net_units"] += qty

        if price:
            positions[key]["latest_price"] = price
        if name:
            positions[key]["name"] = name

    result = []
    for key, data in positions.items():
        if data["net_units"] > 0.00001:
            result.append({
                "ticker": key,
                "name": data["name"],
                "units": round(data["net_units"], 6),
                "price": round(data["latest_price"], 4),
            })
    result.sort(key=lambda x: x["ticker"])
    return result


def parse_ii(file_bytes):
    """
    Parse an Interactive Investor portfolio CSV.

    Expected columns (case-insensitive):
        Holding, EPIC/Ticker, Quantity, Price, Value
    """
    return _parse_portfolio_snapshot(file_bytes, "Interactive Investor", [
        (["holding", "investment", "name", "stock"], "name"),
        (["epic/ticker", "epic", "ticker", "sedol", "isin"], "ticker"),
        (["quantity", "units", "shares", "units held"], "units"),
        (["price", "current price", "price (p)"], "price"),
        (["value", "total value", "market value"], "value"),
    ], pence_price=True)


def parse_generic(file_bytes):
    """
    Parse a generic holdings CSV.

    Looks for columns: ticker/symbol, name/holding, units/quantity/shares, price, value
    """
    return _parse_portfolio_snapshot(file_bytes, "generic", [
        (["name", "holding", "investment", "fund", "stock", "title", "description"], "name"),
        (["ticker", "symbol", "epic", "sedol", "isin", "code"], "ticker"),
        (["units", "quantity", "shares", "no. of shares", "units held"], "units"),
        (["price", "price per share", "unit price", "price (p)", "current price"], "price"),
        (["value", "total value", "market value", "value (£)"], "value"),
    ], pence_price=False)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_col(fieldnames, candidates):
    """Find the first matching column name from a list of candidates."""
    for c in candidates:
        if c in fieldnames:
            return c
    return None


def _parse_portfolio_snapshot(file_bytes, platform_label, col_spec, pence_price=False):
    """
    Generic parser for portfolio snapshot CSVs (one row per holding).

    col_spec is a list of (candidate_names, field_key) tuples.
    """
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]

    col_map = {}
    for candidates, key in col_spec:
        col_map[key] = _find_col(fieldnames, candidates)

    if not col_map.get("name") and not col_map.get("ticker"):
        raise ValueError(
            f"File does not look like a {platform_label} portfolio export. "
            f"Could not find columns for holding name or ticker/SEDOL."
        )

    result = []
    for row in reader:
        row_lc = {k.strip().lower(): v for k, v in row.items()}

        name = (row_lc.get(col_map["name"]) or "").strip() if col_map.get("name") else ""
        ticker = (row_lc.get(col_map["ticker"]) or "").strip() if col_map.get("ticker") else ""
        units = _safe_float(row_lc.get(col_map["units"])) if col_map.get("units") else None
        price = _safe_float(row_lc.get(col_map["price"])) if col_map.get("price") else None
        value = _safe_float(row_lc.get(col_map["value"])) if col_map.get("value") else None

        if not name and not ticker:
            continue

        # Convert pence to pounds if needed
        if pence_price and price and value and units and units > 0:
            expected_pence = units * price
            if abs(expected_pence - value * 100) < abs(expected_pence - value):
                price = price / 100.0

        entry = {"ticker": ticker or "", "name": name or ticker, "units": units, "price": price}
        if value is not None and not units:
            entry["value"] = value
        result.append(entry)

    result.sort(key=lambda x: x["name"])
    return result


def match_parsed_to_holdings(parsed_rows, existing_holdings):
    """
    Match parsed CSV rows to existing holdings.

    Matching priority:
      1. Exact ticker match (case-insensitive)
      2. Partial name match (CSV name contains or is contained by holding name)

    Returns:
        matched   — list of {csv_row, holding} pairs
        csv_only  — parsed rows with no match found
        db_only   — existing holdings not matched by any CSV row
    """
    matched = []
    csv_only = []
    matched_holding_ids = set()

    for csv_row in parsed_rows:
        csv_ticker = (csv_row.get("ticker") or "").upper().strip()
        csv_name = (csv_row.get("name") or "").lower().strip()

        best = None

        # Pass 1: exact ticker match
        if csv_ticker:
            for h in existing_holdings:
                h_ticker = (h["ticker"] or "").upper().strip()
                if h_ticker and h_ticker == csv_ticker:
                    best = h
                    break

        # Pass 2: name substring match (both directions)
        if best is None and csv_name:
            for h in existing_holdings:
                h_name = (h["holding_name"] or "").lower().strip()
                if (csv_name in h_name or h_name in csv_name) and len(csv_name) > 3:
                    best = h
                    break

        if best is not None:
            matched.append({"csv": csv_row, "holding": dict(best)})
            matched_holding_ids.add(best["id"])
        else:
            csv_only.append(csv_row)

    db_only = [dict(h) for h in existing_holdings if h["id"] not in matched_holding_ids]

    return matched, csv_only, db_only
