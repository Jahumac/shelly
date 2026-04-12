"""Live price fetching via yfinance (Yahoo Finance).

Usage:
    from app.services.prices import fetch_price, refresh_catalogue_prices

fetch_price(ticker) tries the ticker as-is, then with a .L suffix for
LSE-listed instruments, returning a dict or None if nothing is found.

Install dependency:  pip install yfinance>=0.2.0
"""
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

YFINANCE_AVAILABLE = False
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
    try:
        logging.getLogger("yfinance").setLevel(logging.ERROR)
    except Exception:
        pass
except ImportError:
    pass

# ── Known ticker aliases ────────────────────────────────────────────────────
# Some LSE-listed ETFs (especially newer Vanguard ones) fail with yfinance
# because the ticker doesn't resolve via the standard quoteSummary API.
# Map them to their Yahoo Finance symbol here as a safety net.
TICKER_ALIASES = {
    "VHVG":  "VHVG.L",    # Vanguard FTSE Developed World UCITS ETF (Acc)
    "VFEG":  "VFEG.L",    # Vanguard FTSE Emerging Markets UCITS ETF (Acc)
    "VWRP":  "VWRP.L",    # Vanguard FTSE All-World UCITS ETF (Acc)
    "VWRL":  "VWRL.L",    # Vanguard FTSE All-World UCITS ETF (Dist)
    "VUAG":  "VUAG.L",    # Vanguard S&P 500 UCITS ETF (Acc)
    "VUSA":  "VUSA.L",    # Vanguard S&P 500 UCITS ETF (Dist)
    "VEVE":  "VEVE.L",    # Vanguard FTSE Developed World UCITS ETF (Dist)
    "VFEM":  "VFEM.L",    # Vanguard FTSE Emerging Markets UCITS ETF (Dist)
    "VUKE":  "VUKE.L",    # Vanguard FTSE 100 UCITS ETF (Dist)
    "VMID":  "VMID.L",    # Vanguard FTSE 250 UCITS ETF (Dist)
    "VAGP":  "VAGP.L",    # Vanguard Global Aggregate Bond UCITS ETF (Acc)
    "VGOV":  "VGOV.L",    # Vanguard UK Government Bond UCITS ETF (Dist)
}

logger = logging.getLogger(__name__)


def _yahoo_json(url: str, timeout: int = 10) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def fetch_dividend_profile(ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch dividend metadata for a ticker from Yahoo Finance.

    Returns dict:
      - dividend_yield_pct: float in [0,1] or None
      - frequency: one of 'monthly'|'quarterly'|'semi-annual'|'annual'|'unknown'
      - ex_date: ISO date string or None
      - pay_date: ISO date string or None
      - source: 'yahoo'
      - updated_at: ISO string (UTC)
    """
    if not ticker or not ticker.strip():
        return None

    t = ticker.strip().upper()
    yf_symbol = t
    if not t.endswith(".L") and TICKER_ALIASES.get(t):
        yf_symbol = TICKER_ALIASES[t]
    elif not t.endswith(".L"):
        yf_symbol = t

    out = {
        "dividend_yield_pct": None,
        "frequency": "unknown",
        "ex_date": None,
        "pay_date": None,
        "source": "yahoo",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    try:
        encoded = urllib.parse.quote(yf_symbol)
        url = (
            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{encoded}"
            f"?modules=summaryDetail,calendarEvents"
        )
        data = _yahoo_json(url)
        result = (data.get("quoteSummary") or {}).get("result") or []
        if result:
            r0 = result[0]
            sd = r0.get("summaryDetail") or {}
            ce = r0.get("calendarEvents") or {}

            y = sd.get("dividendYield")
            if isinstance(y, dict):
                y = y.get("raw")
            if y is not None:
                try:
                    y = float(y)
                    if 0 <= y <= 1:
                        out["dividend_yield_pct"] = y
                except Exception:
                    pass

            exd = (ce.get("exDividendDate") or {}).get("raw") if isinstance(ce.get("exDividendDate"), dict) else None
            dd = (ce.get("dividendDate") or {}).get("raw") if isinstance(ce.get("dividendDate"), dict) else None
            if exd:
                out["ex_date"] = datetime.fromtimestamp(int(exd), tz=timezone.utc).date().isoformat()
            if dd:
                out["pay_date"] = datetime.fromtimestamp(int(dd), tz=timezone.utc).date().isoformat()
    except Exception:
        pass

    try:
        encoded = urllib.parse.quote(yf_symbol)
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            f"?range=1y&interval=1d&events=div"
        )
        data = _yahoo_json(url)
        result = (data.get("chart") or {}).get("result") or []
        divs = None
        if result:
            divs = ((result[0].get("events") or {}).get("dividends")) or None
        count = len(divs.keys()) if isinstance(divs, dict) else 0
        if count >= 10:
            out["frequency"] = "monthly"
        elif count >= 4:
            out["frequency"] = "quarterly"
        elif count >= 2:
            out["frequency"] = "semi-annual"
        elif count == 1:
            out["frequency"] = "annual"
        else:
            out["frequency"] = out["frequency"] or "unknown"
    except Exception:
        pass

    return out

def _try_ticker(symbol: str) -> Optional[Dict[str, Any]]:
    """Return dict with price/currency/change_pct for a Yahoo Finance symbol, or None.

    Uses three fallback strategies because yfinance can be flaky:
      1. fast_info  — fastest, works for most tickers
      2. .info dict — slower but richer, covers tickers fast_info misses
      3. .history() — last resort, pulls recent price from historical data
    """
    if not YFINANCE_AVAILABLE:
        return None
    try:
        t = yf.Ticker(symbol)

        # ── Strategy 1: fast_info (fastest) ──────────────────────────
        price = None
        currency = None
        prev_close = None
        name = None
        quote_type = None
        dividend_yield = None
        try:
            fi = t.fast_info
            price = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
            currency = getattr(fi, "currency", None)
            prev_close = getattr(fi, "previous_close", None) or getattr(fi, "regularMarketPreviousClose", None)
        except Exception:
            pass

        # ── Strategy 2: .info dict (slower, more reliable) ───────────
        if not price:
            try:
                info = t.info
                if info and isinstance(info, dict):
                    price = info.get("regularMarketPrice") or info.get("previousClose") or info.get("navPrice")
                    currency = currency or info.get("currency")
                    prev_close = prev_close or info.get("regularMarketPreviousClose") or info.get("previousClose")
                    name = info.get("longName") or info.get("shortName")
                    quote_type = info.get("quoteType")
                    dividend_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield")
            except Exception:
                pass

        # If we got price from fast_info, still try .info for the name
        if price and not name:
            try:
                info = t.info
                if info and isinstance(info, dict):
                    name = info.get("longName") or info.get("shortName")
                    quote_type = quote_type or info.get("quoteType")
                    currency = currency or info.get("currency")
                    dividend_yield = dividend_yield or info.get("dividendYield") or info.get("trailingAnnualDividendYield")
            except Exception:
                pass

        # ── Strategy 3: recent history (last resort) ─────────────────
        if not price:
            try:
                hist = t.history(period="5d")
                if hist is not None and not hist.empty:
                    price = float(hist["Close"].dropna().iloc[-1])
                    if len(hist["Close"].dropna()) >= 2:
                        prev_close = float(hist["Close"].dropna().iloc[-2])
            except Exception:
                pass

        if not price:
            return None

        # Resolve currency if still unknown
        if not currency:
            try:
                currency = (t.info or {}).get("currency", "GBP")
            except Exception:
                currency = "GBP"

        change_pct = None
        if prev_close and prev_close > 0:
            change_pct = ((price - prev_close) / prev_close * 100)

        if dividend_yield is not None:
            try:
                dividend_yield = float(dividend_yield)
            except Exception:
                dividend_yield = None
        if dividend_yield is not None:
            if dividend_yield < 0:
                dividend_yield = 0.0
            if dividend_yield > 1:
                dividend_yield = None

        return {
            "price": round(float(price), 4),
            "currency": currency,
            "change_pct": round(float(change_pct), 2) if change_pct is not None else None,
            "name": name,
            "quote_type": quote_type,
            "dividend_yield": dividend_yield,
        }
    except Exception:
        return None


def _try_yahoo_http(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch current price via direct v8 chart HTTP API.

    This is the most reliable fallback — it uses the same endpoint that
    Yahoo's website uses and handles tickers that yfinance can't resolve.
    """
    try:
        encoded = urllib.parse.quote(symbol)
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            f"?range=5d&interval=1d"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        result = data.get("chart", {}).get("result")
        if not result:
            return None

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        currency = meta.get("currency", "GBP")

        if not price:
            # Try getting price from the timestamp data
            closes = (result[0].get("indicators", {})
                      .get("quote", [{}])[0]
                      .get("close", []))
            valid_closes = [c for c in closes if c is not None]
            if valid_closes:
                price = valid_closes[-1]
                if len(valid_closes) >= 2:
                    prev_close = prev_close or valid_closes[-2]

        if not price:
            return None

        change_pct = None
        if prev_close and prev_close > 0:
            change_pct = ((price - prev_close) / prev_close * 100)

        return {
            "price": round(float(price), 4),
            "currency": currency,
            "change_pct": round(float(change_pct), 2) if change_pct is not None else None,
            "name": meta.get("longName") or meta.get("shortName"),
            "quote_type": meta.get("instrumentType") or meta.get("quoteType"),
        }
    except Exception:
        return None


def _search_yahoo(query: str) -> Optional[str]:
    """Search Yahoo Finance for a symbol by query string.

    Returns the best matching LSE symbol, or None.
    """
    import urllib.request
    import json

    try:
        encoded = urllib.parse.quote(query)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded}&quotesCount=6&newsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        quotes = data.get("quotes", [])

        # Prefer London-listed results
        for q in quotes:
            sym = q.get("symbol", "")
            if sym.endswith(".L"):
                return sym

        # Otherwise return the first equity/ETF match
        for q in quotes:
            if q.get("quoteType") in ("ETF", "EQUITY", "MUTUALFUND"):
                return q.get("symbol")
    except Exception:
        pass
    return None


def fetch_history(ticker: str, period: str = "1y") -> Optional[Dict[str, Any]]:
    """Fetch historical prices for a given ticker."""
    ticker_clean = ticker.strip()
    if not ticker_clean:
        return None

    # Apply aliases
    alias = TICKER_ALIASES.get(ticker_clean.upper())
    symbol = alias or ticker_clean

    # Map periods to Yahoo chart API params for the HTTP fallback
    period = (period or "1y").strip()
    http_range = period
    http_interval = "1d"
    if period == "1d":
        http_interval = "5m"
    elif period in ("5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y"):
        http_interval = "1d"
    else:
        http_range = "1y"

    def _fetch_history_http(sym: str):
        try:
            encoded = urllib.parse.quote(sym)
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range={http_range}&interval={http_interval}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            result = data.get("chart", {}).get("result")
            if not result:
                return None

            meta = result[0].get("meta", {}) or {}
            currency = meta.get("currency", "GBP")
            divider = 100.0 if currency == "GBp" else 1.0

            timestamps = result[0].get("timestamp", []) or []
            closes = (
                (result[0].get("indicators", {}) or {})
                .get("quote", [{}])[0]
                .get("close", [])
            ) or []

            history_data = []
            for ts, close in zip(timestamps, closes):
                if close is None:
                    continue
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                if period == "1d":
                    label = dt.strftime("%H:%M")
                else:
                    label = dt.strftime("%Y-%m-%d")
                history_data.append({
                    "date": label,
                    "price": round(float(close) / divider, 4),
                })

            return history_data or None
        except Exception:
            return None

    try:
        if YFINANCE_AVAILABLE:
            t = yf.Ticker(symbol)
            if period == "1d":
                hist = t.history(period="1d", interval="5m")
            else:
                hist = t.history(period=period)
            if hist is None or hist.empty:
                if not symbol.endswith(".L"):
                    symbol_l = symbol + ".L"
                    t = yf.Ticker(symbol_l)
                    if period == "1d":
                        hist = t.history(period="1d", interval="5m")
                    else:
                        hist = t.history(period=period)

            if hist is not None and not hist.empty:
                currency = t.info.get("currency") if hasattr(t, "info") and isinstance(t.info, dict) else "GBP"
                divider = 100.0 if currency == "GBp" else 1.0

                history_data = []
                for date, row in hist.iterrows():
                    price = float(row["Close"]) / divider
                    history_data.append({
                        "date": date.strftime("%H:%M") if period == "1d" else date.strftime("%Y-%m-%d"),
                        "price": round(price, 4)
                    })
                return history_data or None

        http_data = _fetch_history_http(symbol)
        if http_data:
            return http_data
        if not symbol.endswith(".L"):
            http_data = _fetch_history_http(symbol + ".L")
            if http_data:
                return http_data
        return None
    except Exception as e:
        logger.error(f"Error fetching history for {ticker}: {e}")
        return None


def fetch_price(ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch the current price for a ticker.

    Strategy for a UK-focused dashboard:
    1. Check known aliases (e.g. VHVG → VHVG.L) for tickers that are
       known to fail with yfinance but work via the HTTP API.
    2. Try the raw ticker via yfinance.
    3. If it doesn't end with .L, also try ticker + ".L" (London Stock Exchange).
    4. If yfinance fails, try Yahoo's v8 chart HTTP API directly — this
       bypasses yfinance entirely and handles many tickers yfinance can't.
    5. Last resort: search Yahoo Finance by name and try the best match.

    Returns a dict with keys: price, currency, change_pct, yf_symbol
    or None if the price cannot be fetched.
    """
    if not ticker or not ticker.strip():
        return None
    ticker = ticker.strip().upper()

    # ── Phase 0: prefer known alias up-front (reduces yfinance noise) ────
    alias = TICKER_ALIASES.get(ticker)
    if alias and not ticker.endswith(".L"):
        alias_result = _try_ticker(alias)
        if alias_result:
            alias_result["yf_symbol"] = alias
            return alias_result

    # ── Phase 1: yfinance (fast path) ────────────────────────────────────
    raw_result = _try_ticker(ticker)
    lse_result = None

    if not ticker.endswith(".L"):
        lse_result = _try_ticker(ticker + ".L")

    # Prefer the LSE version if it exists and is priced in GBP/GBp
    if lse_result and lse_result.get("currency") in ("GBP", "GBp"):
        lse_result["yf_symbol"] = ticker + ".L"
        return lse_result

    if raw_result:
        raw_result["yf_symbol"] = ticker
        return raw_result

    # Fallback: return LSE even if not GBP (better than nothing)
    if lse_result:
        lse_result["yf_symbol"] = ticker + ".L"
        return lse_result

    # ── Phase 2: direct HTTP API (bypasses yfinance entirely) ────────────
    # Try known alias first, then raw, then .L
    symbols_to_try = []
    if alias:
        symbols_to_try.append(alias)
    symbols_to_try.append(ticker)
    if not ticker.endswith(".L"):
        symbols_to_try.append(ticker + ".L")

    for sym in symbols_to_try:
        http_result = _try_yahoo_http(sym)
        if http_result:
            http_result["yf_symbol"] = sym
            logger.info(f"${ticker} resolved via HTTP API → {sym}")
            return http_result

    # ── Phase 3: search Yahoo Finance for the symbol ─────────────────────
    found_symbol = _search_yahoo(ticker)
    if found_symbol:
        # Try yfinance first (faster), then HTTP
        search_result = _try_ticker(found_symbol)
        if not search_result:
            search_result = _try_yahoo_http(found_symbol)
        if search_result:
            search_result["yf_symbol"] = found_symbol
            logger.info(f"${ticker} resolved via search → {found_symbol}")
            return search_result

    return None


def lookup_instrument(query: str) -> Optional[Dict[str, Any]]:
    """Look up an instrument by ticker or partial name via Yahoo Finance.

    Returns a dict with keys: ticker, yf_symbol, name, price, price_gbp,
    currency, change_pct, asset_type  — or None if nothing found.
    """
    if not query or not query.strip():
        return None
    query = query.strip()
    price_data = fetch_price(query)
    if not price_data:
        return None

    yf_symbol = price_data["yf_symbol"]
    ticker_used = query.upper()

    # Use name/type already fetched by _try_ticker (avoids a second .info call)
    name = price_data.get("name") or ticker_used
    qt = (price_data.get("quote_type") or "").upper()
    if qt == "MUTUALFUND":
        asset_type = "Fund"
    elif qt == "ETF":
        asset_type = "ETF"
    elif qt == "EQUITY":
        asset_type = "Share"
    elif qt:
        asset_type = "Other"
    else:
        asset_type = "ETF"

    price = price_data["price"]
    currency = price_data["currency"]
    price_gbp = price / 100.0 if currency == "GBp" else price

    return {
        "ticker": ticker_used,
        "yf_symbol": yf_symbol,
        "name": name,
        "price": round(price, 4),
        "price_gbp": round(price_gbp, 4),
        "currency": currency,
        "change_pct": price_data.get("change_pct"),
        "asset_type": asset_type,
        "dividend_yield_pct": price_data.get("dividend_yield"),
    }


def refresh_catalogue_prices(catalogue_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fetch fresh prices for all catalogue items in bulk.

    Returns a list of dicts: {id, name, ticker, success, price, currency,
                               change_pct, error}
    """
    results = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    # 1. Collect unique tickers and map them back to rows
    ticker_to_rows = {}
    for row in catalogue_rows:
        t = (row.get("ticker") or "").strip().upper()
        if not t:
            continue
        if t not in ticker_to_rows:
            ticker_to_rows[t] = []
        ticker_to_rows[t].append(row)

    if not ticker_to_rows:
        return []

    # 2. Try bulk fetch via yfinance if available
    bulk_data = {}
    if YFINANCE_AVAILABLE:
        try:
            # We try both raw and .L versions in bulk to be safe
            symbols_to_fetch = []
            for t in ticker_to_rows.keys():
                symbols_to_fetch.append(t)
                if not t.endswith(".L"):
                    symbols_to_fetch.append(t + ".L")
                if TICKER_ALIASES.get(t):
                    symbols_to_fetch.append(TICKER_ALIASES[t])

            # yfinance download is often more reliable/faster for many tickers than Tickers().info
            # We fetch 1d period to get current price + prev close for change_pct
            tickers_str = " ".join(list(set(symbols_to_fetch)))
            df = yf.download(tickers_str, period="5d", interval="1d", group_by='ticker', progress=False, threads=True)
            
            for sym in symbols_to_fetch:
                try:
                    # Get the most recent valid price
                    if sym in df.columns.levels[0]:
                        s_df = df[sym].dropna(subset=['Close'])
                        if not s_df.empty:
                            price = s_df['Close'].iloc[-1]
                            prev_close = s_df['Close'].iloc[-2] if len(s_df) >= 2 else None
                            change_pct = None
                            if prev_close and prev_close > 0:
                                change_pct = (price - prev_close) / prev_close * 100
                            
                            bulk_data[sym] = {
                                "price": round(float(price), 4),
                                "change_pct": round(float(change_pct), 2) if change_pct is not None else None,
                                "yf_symbol": sym,
                                "currency": None # download doesn't give currency easily, fallback will handle it
                            }
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Bulk fetch failed: {e}")

    # 3. Process results, falling back to fetch_price if bulk failed or needs currency
    for ticker, rows in ticker_to_rows.items():
        # Find the best match from bulk_data
        data = None
        best_sym = None
        
        # Try order: Alias -> .L -> Raw
        for sym in [TICKER_ALIASES.get(ticker), ticker + ".L", ticker]:
            if sym and sym in bulk_data:
                data = bulk_data[sym]
                best_sym = sym
                break
        
        # If bulk succeeded but missing currency, or bulk failed entirely, use fetch_price
        if not data or not data.get("currency"):
            data = fetch_price(ticker)
        
        for row in rows:
            if data:
                results.append({
                    "id": row["id"],
                    "name": row["holding_name"],
                    "ticker": ticker,
                    "yf_symbol": data.get("yf_symbol") or best_sym or ticker,
                    "price": data["price"],
                    "currency": data.get("currency"),
                    "change_pct": data.get("change_pct"),
                    "updated_at": now,
                    "success": True,
                    "error": None,
                })
            else:
                results.append({
                    "id": row["id"],
                    "name": row["holding_name"],
                    "ticker": ticker,
                    "price": None,
                    "currency": None,
                    "change_pct": None,
                    "updated_at": now,
                    "success": False,
                    "error": f"No data found for {ticker}",
                })

    return results
