#!/usr/bin/env python3
"""
Refresh price history for tracked assets.
Sources: Hyperliquid (for listed crypto), CoinGecko (for research-only crypto).

Also updates model_decision_outcomes with 30/90d prices for past decisions.
"""
import datetime
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(ROOT / "data" / "moneytrail.sqlite")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def fetch_hl_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch current prices from Hyperliquid."""
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post("https://api.hyperliquid.xyz/info", json={"type": "allMids"})
            resp.raise_for_status()
            mids = resp.json()
            return {sym: float(mids[sym]) for sym in symbols if sym in mids}
    except Exception as exc:
        print(f"  Hyperliquid price fetch error: {exc}")
        return {}


def fetch_coingecko_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch prices from CoinGecko free API (no key needed for basic queries)."""
    # CoinGecko uses IDs not symbols — this is a simplified version
    # For production: build a symbol→id mapping from CoinGecko /coins/list
    cg_map = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "JUP": "jupiter-exchange-solana", "SUI": "sui",
        "NEAR": "near", "RENDER": "render-token", "TAO": "bittensor",
    }
    ids = [cg_map[s] for s in symbols if s in cg_map]
    if not ids:
        return {}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ",".join(ids), "vs_currencies": "usd"},
            )
            resp.raise_for_status()
            data = resp.json()
            id_to_sym = {v: k for k, v in cg_map.items() if k in symbols}
            return {id_to_sym[k]: v["usd"] for k, v in data.items() if k in id_to_sym}
    except Exception as exc:
        print(f"  CoinGecko price fetch error: {exc}")
        return {}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = _get_conn()
    today = datetime.date.today().isoformat()
    now = datetime.datetime.utcnow().isoformat()

    # Assets to track: owned + watchlist
    tracked = set()
    for row in conn.execute("SELECT DISTINCT asset FROM real_positions"):
        tracked.add(row["asset"])
    for row in conn.execute("SELECT DISTINCT symbol FROM asset_signals WHERE status != 'reject'"):
        if row["symbol"]:
            tracked.add(row["symbol"])

    if not tracked:
        print("[refresh_prices] No assets to track")
        conn.close()
        return

    print(f"[refresh_prices] Fetching prices for {len(tracked)} assets...")

    # Fetch from Hyperliquid first, then CoinGecko for remainder
    hl_prices = fetch_hl_prices(list(tracked))
    remaining = [s for s in tracked if s not in hl_prices]
    cg_prices = fetch_coingecko_prices(remaining) if remaining else {}
    all_prices = {**hl_prices, **cg_prices}

    stored = 0
    for symbol, price in all_prices.items():
        if args.dry_run:
            print(f"  [DRY RUN] {symbol}: ${price:,.4f}")
            continue
        conn.execute(
            """INSERT OR IGNORE INTO price_history (id, asset, date, close_price, source, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f"{symbol}_{today}", symbol, today, price,
             "hyperliquid" if symbol in hl_prices else "coingecko", now),
        )
        stored += 1

    # Update model_decision_outcomes with historical prices at day 30 and day 90.
    # Look up price_history for the exact date (decision_date + N days) rather than
    # using today's price — avoids writing a day-45 price into the price_30d column
    # if the pipeline missed a run.
    for row in conn.execute(
        "SELECT id, asset, decision_date FROM model_decision_outcomes "
        "WHERE price_30d IS NULL OR price_90d IS NULL"
    ):
        decision_dt = datetime.date.fromisoformat(row["decision_date"][:10])
        days_since = (datetime.date.today() - decision_dt).days

        if days_since >= 30:
            target_date_30 = (decision_dt + datetime.timedelta(days=30)).isoformat()
            hist = conn.execute(
                "SELECT close_price FROM price_history WHERE asset = ? AND date = ? LIMIT 1",
                (row["asset"], target_date_30),
            ).fetchone()
            if hist and not args.dry_run:
                conn.execute(
                    "UPDATE model_decision_outcomes SET price_30d = ? WHERE id = ? AND price_30d IS NULL",
                    (hist["close_price"], row["id"]),
                )

        if days_since >= 90:
            target_date_90 = (decision_dt + datetime.timedelta(days=90)).isoformat()
            hist = conn.execute(
                "SELECT close_price FROM price_history WHERE asset = ? AND date = ? LIMIT 1",
                (row["asset"], target_date_90),
            ).fetchone()
            if hist and not args.dry_run:
                conn.execute(
                    "UPDATE model_decision_outcomes SET price_90d = ? WHERE id = ? AND price_90d IS NULL",
                    (hist["close_price"], row["id"]),
                )

    if not args.dry_run:
        conn.commit()
    conn.close()
    print(f"[refresh_prices] {'(dry run) ' if args.dry_run else ''}Stored {stored} price records")


if __name__ == "__main__":
    main()
