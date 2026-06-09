#!/usr/bin/env python3
"""
Refresh the Hyperliquid asset universe cache (venue_assets table).
Fetches perp and spot metadata from the Hyperliquid API.

Implements: agents/tradeability_gate.md (universe refresh step)
"""
import datetime
import json
import sys
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

HL_BASE = "https://api.hyperliquid.xyz"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
)
def _fetch_meta() -> dict:
    """Fetch Hyperliquid meta (perps + spot) with retry."""
    with httpx.Client(timeout=30) as client:
        perp_resp = client.post(HL_BASE + "/info", json={"type": "meta"})
        perp_resp.raise_for_status()
        spot_resp = client.post(HL_BASE + "/info", json={"type": "spotMeta"})
        spot_resp.raise_for_status()
        return {
            "perp": perp_resp.json(),
            "spot": spot_resp.json(),
        }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
)
def _fetch_prices() -> dict:
    """Fetch all mid prices."""
    with httpx.Client(timeout=30) as client:
        resp = client.post(HL_BASE + "/info", json={"type": "allMids"})
        resp.raise_for_status()
        return resp.json()


def _get_conn():
    import sqlite3
    conn = sqlite3.connect(ROOT / "data" / "moneytrail.sqlite")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("[refresh_hyperliquid_universe] Fetching Hyperliquid meta...")
    try:
        meta = _fetch_meta()
        prices = _fetch_prices()
    except Exception as exc:
        print(f"  ERROR fetching Hyperliquid data: {exc}")
        print("  Will use existing cached data if available.")
        sys.exit(0)  # non-fatal — tradeability gate will detect staleness

    conn = _get_conn()
    now = datetime.datetime.utcnow().isoformat()
    upserted = 0

    # Perp assets — index in the universe array IS the Hyperliquid asset ID
    for perp_idx, asset_meta in enumerate(meta["perp"].get("universe", [])):
        symbol = asset_meta.get("name", "")
        price = float(prices.get(symbol, 0) or 0)
        row = (
            f"hl_perp_{symbol}", "hyperliquid", "perp", symbol,
            perp_idx,  # asset_id: position in universe array = Hyperliquid asset ID
            symbol, "USD",
            1, 1,  # is_listed, is_tradeable
            float(asset_meta.get("minSize", 0) or 0),
            int(asset_meta.get("szDecimals", 0) or 0),
            float(asset_meta.get("maxLeverage", 1) or 1),
            None,  # margin_table_id
            price, 0.0, 0.0, 0.0,  # volume/OI/funding fetched separately
            1.0, now,
        )
        if not args.dry_run:
            conn.execute(
                """INSERT OR REPLACE INTO venue_assets
                   (id, venue, market_type, symbol, asset_id, base_asset, quote_asset,
                    is_listed, is_tradeable, min_size, sz_decimals, max_leverage,
                    margin_table_id, last_price, volume_24h, open_interest,
                    funding_rate, liquidity_score, last_checked)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        upserted += 1

    # Spot assets
    for token in meta["spot"].get("tokens", []):
        symbol = token.get("name", "")
        if not symbol:
            continue
        price = float(prices.get(f"{symbol}/USDC", 0) or 0)
        row = (
            f"hl_spot_{symbol}", "hyperliquid", "spot", symbol,
            token.get("index", 0),
            symbol, "USDC",
            1, 1,
            0.0, int(token.get("szDecimals", 0) or 0), 1.0, None,
            price, 0.0, 0.0, 0.0, 1.0, now,
        )
        if not args.dry_run:
            conn.execute(
                """INSERT OR REPLACE INTO venue_assets
                   (id, venue, market_type, symbol, asset_id, base_asset, quote_asset,
                    is_listed, is_tradeable, min_size, sz_decimals, max_leverage,
                    margin_table_id, last_price, volume_24h, open_interest,
                    funding_rate, liquidity_score, last_checked)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        upserted += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"[refresh_hyperliquid_universe] {'(dry run) ' if args.dry_run else ''}{upserted} assets cached")


if __name__ == "__main__":
    main()
