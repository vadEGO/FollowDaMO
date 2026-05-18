#!/usr/bin/env python3
"""
Fetch 90 days of daily OHLCV candles for every active symbol in Supabase
and push them to the market_candles table.

Sources (tried in order):
  1. yfinance  — stocks, ETFs, crypto via Yahoo Finance (free, no key)
  2. CoinGecko  — crypto fallback (free tier, 30 req/min)

Symbols are normalised to Yahoo format:
  crypto:  ETH → ETH-USD, BTC → BTC-USD
  stocks:  NVDA → NVDA  (plain ticker)
  fx:      EURUSD → EURUSD=X

Usage:
    python scripts/sync_candles.py                  # all active symbols
    python scripts/sync_candles.py --symbols ETH BTC NVDA
    python scripts/sync_candles.py --dry-run
"""

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "secrets" / ".env.supabase")
    except ImportError:
        pass


def _supa_headers():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not key:
        sys.exit("ERROR: SUPABASE_SERVICE_ROLE_KEY not set. Check secrets/.env.supabase")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def _supa_url():
    url = os.environ.get("SUPABASE_URL", "")
    if not url:
        sys.exit("ERROR: SUPABASE_URL not set. Check secrets/.env.supabase")
    return url.rstrip("/")


def get_active_symbols(url: str, headers: dict) -> list[dict]:
    """Return list of {symbol, asset_class, coingecko_id} from Supabase."""
    import requests
    r = requests.get(
        f"{url}/rest/v1/public_opportunity_action_board"
        "?select=normalized_symbol,asset_class&limit=200",
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    seen = set()
    result = []
    for row in r.json():
        sym = row.get("normalized_symbol") or row.get("symbol") or ""
        sym = sym.strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        result.append({
            "symbol": sym,
            "asset_class": row.get("asset_class") or "unknown",
        })
    return result


def yahoo_ticker(symbol: str, asset_class: str) -> str:
    """Convert a normalised symbol to a Yahoo Finance ticker."""
    ac = (asset_class or "").lower()
    if ac in ("crypto", "defi", "digital asset"):
        # Yahoo crypto format: ETH-USD
        base = symbol.replace("USDT", "").replace("USD", "").replace("-PERP", "")
        return f"{base}-USD"
    if ac == "fx":
        if not symbol.endswith("=X"):
            return f"{symbol}=X"
    return symbol


def fetch_yahoo(ticker: str, days: int = 90) -> list[dict]:
    """Fetch OHLCV from Yahoo Finance via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        return []

    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    try:
        df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(),
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return []
        rows = []
        for ts, row in df.iterrows():
            dt = ts.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0)
            def _f(col):
                v = row[col]
                try:
                    return float(v.iloc[0]) if hasattr(v, 'iloc') else float(v)
                except Exception:
                    return None
            rows.append({
                "open":   _f("Open"),
                "high":   _f("High"),
                "low":    _f("Low"),
                "close":  _f("Close"),
                "volume": _f("Volume") if "Volume" in row.index else None,
                "ts":     dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        return rows
    except Exception as e:
        print(f"    yfinance error for {ticker}: {e}")
        return []


def fetch_coingecko(symbol: str, days: int = 90) -> list[dict]:
    """Fetch OHLCV from CoinGecko free API."""
    import requests

    # Simple symbol → CoinGecko id map for common assets
    ID_MAP = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
        "AVAX": "avalanche-2", "DOT": "polkadot", "LINK": "chainlink",
        "MATIC": "matic-network", "UNI": "uniswap", "ATOM": "cosmos",
        "LTC": "litecoin", "BCH": "bitcoin-cash", "FIL": "filecoin",
        "SUI": "sui", "APT": "aptos", "ARB": "arbitrum", "OP": "optimism",
        "DOGE": "dogecoin", "SHIB": "shiba-inu", "PEPE": "pepe",
        "WIF": "dogwifcoin", "BONK": "bonk", "JUP": "jupiter-exchange-solana",
    }

    cg_id = ID_MAP.get(symbol.upper())
    if not cg_id:
        return []

    try:
        url = (
            f"https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc"
            f"?vs_currency=usd&days={days}"
        )
        r = requests.get(url, timeout=15)
        if r.status_code == 429:
            print("    CoinGecko rate limit — sleeping 60s")
            time.sleep(60)
            r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        rows = []
        for item in r.json():
            ts_ms, o, h, l, c = item
            dt = datetime.datetime.utcfromtimestamp(ts_ms / 1000)
            rows.append({
                "open": o, "high": h, "low": l, "close": c, "volume": None,
                "ts": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        return rows
    except Exception as e:
        print(f"    CoinGecko error for {symbol}: {e}")
        return []


def push_candles(url: str, headers: dict, symbol: str, rows: list[dict],
                 source: str, dry_run: bool) -> int:
    """Upsert candle rows into market_candles. Returns count pushed."""
    import requests

    if not rows:
        return 0

    payload = [
        {
            "symbol":   symbol,
            "interval": "1d",
            "ts":       r["ts"],
            "open":     r["open"],
            "high":     r["high"],
            "low":      r["low"],
            "close":    r["close"],
            "volume":   r.get("volume"),
            "source":   source,
        }
        for r in rows
    ]

    if dry_run:
        print(f"    [DRY RUN] would push {len(payload)} candles")
        return len(payload)

    # Push in batches of 200
    pushed = 0
    for i in range(0, len(payload), 200):
        batch = payload[i:i + 200]
        r = requests.post(
            f"{url}/rest/v1/market_candles",
            headers=headers,
            json=batch,
            timeout=20,
        )
        if r.status_code not in (200, 201):
            print(f"    Supabase error {r.status_code}: {r.text[:200]}")
        else:
            pushed += len(batch)

    return pushed


def sync_symbol(symbol: str, asset_class: str, url: str, headers: dict,
                dry_run: bool) -> bool:
    """Fetch + push candles for one symbol. Returns True if data was pushed."""
    ticker = yahoo_ticker(symbol, asset_class)
    print(f"  {symbol} ({asset_class}) → Yahoo: {ticker}")

    rows = fetch_yahoo(ticker, days=90)

    if not rows:
        print(f"    Yahoo empty — trying CoinGecko")
        rows = fetch_coingecko(symbol, days=90)
        source = "coingecko"
    else:
        source = "yahoo"

    if not rows:
        print(f"    No data found for {symbol}")
        return False

    # Dedupe by ts
    seen = {}
    for r in rows:
        seen[r["ts"]] = r
    rows = sorted(seen.values(), key=lambda x: x["ts"])

    print(f"    {len(rows)} candles from {source} ({rows[0]['ts'][:10]} → {rows[-1]['ts'][:10]})")
    n = push_candles(url, headers, symbol, rows, source, dry_run)
    print(f"    ✓ pushed {n}")
    return n > 0


def main():
    _load_env()

    parser = argparse.ArgumentParser(description="Sync daily candles to Supabase market_candles")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols (default: all active)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Check yfinance installed
    try:
        import yfinance
    except ImportError:
        print("yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    url = _supa_url()
    headers = _supa_headers()

    if args.symbols:
        symbols = [{"symbol": s.upper(), "asset_class": "unknown"} for s in args.symbols]
    else:
        print("Fetching active symbols from Supabase...")
        symbols = get_active_symbols(url, headers)
        print(f"Found {len(symbols)} active symbols: {[s['symbol'] for s in symbols]}")

    if not symbols:
        print("No symbols to sync.")
        return

    ok = 0
    for entry in symbols:
        success = sync_symbol(
            entry["symbol"], entry["asset_class"],
            url, headers, args.dry_run,
        )
        if success:
            ok += 1
        time.sleep(0.5)  # be polite to Yahoo

    print(f"\nDone — {ok}/{len(symbols)} symbols synced.")


if __name__ == "__main__":
    main()
