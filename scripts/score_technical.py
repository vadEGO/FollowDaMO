#!/usr/bin/env python3
"""Score the technical posture of a symbol from its daily candles.

The technical half of the analysis engine (macro half: score_macro_fit.py).
Given a series of daily closes it computes a small, transparent set of classic
indicators — trend (SMA stack), momentum (RSI), and distance from the recent
range — and folds them into a single 0-100 technical score with a label.

Deliberately dependency-light: pure Python, no pandas/numpy, so it runs anywhere
the rest of the pipeline runs and is trivially unit-testable.

Usage:
    # Score symbols from their Supabase market_candles (needs SUPABASE_* creds)
    python scripts/score_technical.py --symbols SOL,ETH,BTC

    # Score a bare close series from JSON (offline / testing)
    echo '[100,101,103,102,105,107,110]' | python scripts/score_technical.py --closes -

    # Persist results to Supabase rv_trade_idea_technical (pipeline default)
    python scripts/score_technical.py --write
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Score band centred on 50 (neutral). Each component contributes a signed tilt.
NEUTRAL_SCORE = 50.0

# Component weights (sum = 1.0). Trend dominates; momentum and range refine it.
WEIGHTS = {
    "trend": 0.50,       # SMA stack: price vs SMA20 vs SMA50
    "momentum": 0.30,    # RSI(14)
    "range": 0.20,       # position within the trailing high/low range
}

RSI_PERIOD = 14
SMA_FAST = 20
SMA_SLOW = 50
RANGE_LOOKBACK = 30


@dataclass
class TechnicalScore:
    symbol: str
    technical_score: float   # 0-100, 50 = neutral
    label: str               # strong | bullish | neutral | bearish | weak | insufficient_data
    trend: str               # up | down | mixed | n/a
    rsi: float | None
    price: float | None
    sma_fast: float | None
    sma_slow: float | None
    n_candles: int
    rationale: str

    def as_dict(self) -> dict:
        return asdict(self)


# ── indicator primitives (pure) ─────────────────────────────────────────────

def sma(closes: list[float], period: int) -> float | None:
    """Simple moving average of the last `period` closes; None if too few."""
    if len(closes) < period or period <= 0:
        return None
    return sum(closes[-period:]) / period


def rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """Wilder's RSI over `period`. None if fewer than period+1 closes.

    Returns 0-100. 100 means an unbroken up-run (no losses in window).
    """
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    # Seed the average gain/loss over the first `period` deltas.
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    # Wilder smoothing over the remaining deltas.
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def range_position(closes: list[float], lookback: int = RANGE_LOOKBACK) -> float | None:
    """Where the latest close sits in the trailing high/low range, 0-1.

    1.0 = at the period high, 0.0 = at the period low. None if too few or flat.
    """
    if len(closes) < 2:
        return None
    window = closes[-lookback:]
    hi, lo = max(window), min(window)
    if hi == lo:
        return None
    return (closes[-1] - lo) / (hi - lo)


# ── scoring core (pure) ─────────────────────────────────────────────────────

def _trend_tilt(price, fast, slow) -> tuple[float, str]:
    """Signed [-1, 1] trend tilt from the SMA stack, plus a label.

    Bull stack (price > fast > slow) -> +1; bear stack -> -1; mixed -> partial.
    """
    if fast is None or slow is None or price is None:
        return 0.0, "n/a"
    above_fast = price > fast
    above_slow = price > slow
    fast_above_slow = fast > slow
    score = (int(above_fast) + int(above_slow) + int(fast_above_slow) - 1.5) / 1.5  # -1..1
    if above_fast and above_slow and fast_above_slow:
        return 1.0, "up"
    if (not above_fast) and (not above_slow) and (not fast_above_slow):
        return -1.0, "down"
    return max(-1.0, min(1.0, score)), "mixed"


def _momentum_tilt(rsi_val) -> float:
    """Signed [-1, 1] momentum tilt from RSI, centred at 50.

    RSI 50 -> 0; 80 -> strongly positive; 20 -> strongly negative. Overbought
    (>70) is still positive momentum here — this scores posture, not mean-reversion.
    """
    if rsi_val is None:
        return 0.0
    return max(-1.0, min(1.0, (rsi_val - 50.0) / 30.0))


def _range_tilt(pos) -> float:
    """Signed [-1, 1] tilt from position in the trailing range (0.5 -> 0)."""
    if pos is None:
        return 0.0
    return max(-1.0, min(1.0, (pos - 0.5) * 2.0))


def _label(score: float) -> str:
    if score >= 75:
        return "strong"
    if score >= 60:
        return "bullish"
    if score > 40:
        return "neutral"
    if score > 25:
        return "bearish"
    return "weak"


def score_technical(symbol: str, closes: list[float]) -> TechnicalScore:
    """Compute the composite technical score for a close series.

    Returns a neutral 'insufficient_data' result (never raises) when there are
    too few candles to compute the indicators — the engine must not break on a
    thinly-traded or newly-listed symbol.
    """
    closes = [float(c) for c in closes if c is not None]
    n = len(closes)
    if n < SMA_FAST + 1:
        return TechnicalScore(
            symbol=symbol, technical_score=NEUTRAL_SCORE, label="insufficient_data",
            trend="n/a", rsi=None, price=(closes[-1] if closes else None),
            sma_fast=None, sma_slow=None, n_candles=n,
            rationale=f"Only {n} candles; need >= {SMA_FAST + 1} for a technical read.",
        )

    price = closes[-1]
    fast = sma(closes, SMA_FAST)
    slow = sma(closes, SMA_SLOW)
    rsi_val = rsi(closes)
    rpos = range_position(closes)

    trend_tilt, trend_label = _trend_tilt(price, fast, slow)
    mom_tilt = _momentum_tilt(rsi_val)
    rng_tilt = _range_tilt(rpos)

    tilt = (WEIGHTS["trend"] * trend_tilt
            + WEIGHTS["momentum"] * mom_tilt
            + WEIGHTS["range"] * rng_tilt)
    score = round(NEUTRAL_SCORE + tilt * NEUTRAL_SCORE, 1)  # map [-1,1] -> [0,100]
    score = max(0.0, min(100.0, score))
    label = _label(score)

    rsi_txt = f"{rsi_val:.0f}" if rsi_val is not None else "n/a"
    rationale = (f"Trend {trend_label} (price {'>' if fast and price > fast else '<='} SMA{SMA_FAST}), "
                 f"RSI {rsi_txt}, "
                 f"{(rpos * 100):.0f}% of {RANGE_LOOKBACK}d range." if rpos is not None
                 else f"Trend {trend_label}, RSI {rsi_txt}.")

    return TechnicalScore(
        symbol=symbol, technical_score=score, label=label, trend=trend_label,
        rsi=round(rsi_val, 1) if rsi_val is not None else None,
        price=round(price, 4), sma_fast=round(fast, 4) if fast else None,
        sma_slow=round(slow, 4) if slow else None, n_candles=n, rationale=rationale,
    )


# ── I/O helpers ─────────────────────────────────────────────────────────────

def _load_env_supabase() -> tuple[str, str]:
    env_file = ROOT / "secrets" / ".env.supabase"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    return (os.environ.get("SUPABASE_URL", "").rstrip("/"),
            os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))


def _fetch_closes(symbol: str, url: str, key: str) -> list[float]:
    """Fetch ascending daily closes for one symbol from market_candles."""
    import httpx
    resp = httpx.get(
        f"{url}/rest/v1/market_candles",
        params={"select": "ts,close", "symbol": f"eq.{symbol}",
                "interval": "eq.1d", "order": "ts.asc", "limit": "400"},
        headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
    if resp.status_code != 200:
        print(f"  {symbol}: fetch failed {resp.status_code} {resp.text[:120]}", file=sys.stderr)
        return []
    return [row["close"] for row in resp.json() if row.get("close") is not None]


def _write_to_supabase(scores: list[TechnicalScore], dry_run: bool) -> int:
    rows = [s.as_dict() for s in scores if s.label != "insufficient_data"]
    if dry_run:
        print(f"  [DRY RUN] Would upsert {len(rows)} rows to rv_trade_idea_technical")
        if rows:
            print(f"    Sample: {rows[0]}")
        return len(rows)
    if not rows:
        return 0
    url, key = _load_env_supabase()
    if not url or not key:
        print("  SUPABASE creds not set — skipping write.", file=sys.stderr)
        return 0
    import httpx
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    resp = httpx.post(f"{url}/rest/v1/rv_trade_idea_technical", headers=headers, json=rows, timeout=30)
    if resp.status_code not in (200, 201, 204):
        print(f"  ERROR upserting technical scores: {resp.status_code} {resp.text[:160]}", file=sys.stderr)
        return 0
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score symbols' technical posture from daily candles")
    parser.add_argument("--symbols", help="Comma-separated symbols to score from Supabase candles")
    parser.add_argument("--closes", help="JSON array of closes (or '-' for stdin); scores one series")
    parser.add_argument("--write", action="store_true", help="Upsert results to Supabase rv_trade_idea_technical")
    parser.add_argument("--dry-run", action="store_true", help="With --write, print instead of sending")
    args = parser.parse_args()

    scores: list[TechnicalScore] = []

    if args.closes:
        raw = sys.stdin.read() if args.closes == "-" else args.closes
        scores.append(score_technical("SERIES", json.loads(raw)))
    else:
        url, key = _load_env_supabase()
        if not url or not key:
            print("No Supabase creds (SUPABASE_URL / key). Use --closes to score offline.", file=sys.stderr)
            return
        symbols = (args.symbols or "").split(",") if args.symbols else []
        if not symbols:
            # Default: every symbol that has daily candles.
            import httpx
            resp = httpx.get(f"{url}/rest/v1/market_candles",
                             params={"select": "symbol", "interval": "eq.1d"},
                             headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
            symbols = sorted({r["symbol"] for r in resp.json()}) if resp.status_code == 200 else []
        for sym in [s.strip() for s in symbols if s.strip()]:
            scores.append(score_technical(sym, _fetch_closes(sym, url, key)))

    scores.sort(key=lambda s: s.technical_score, reverse=True)
    print(f"{'SCORE':>6}  {'LABEL':12s}  {'SYMBOL':8s}  {'TREND':6s}  {'RSI':>4s}  RATIONALE")
    for s in scores:
        print(f"{s.technical_score:6.1f}  {s.label:12s}  {s.symbol:8s}  {s.trend:6s}  "
              f"{(f'{s.rsi:.0f}' if s.rsi is not None else 'n/a'):>4s}  {s.rationale}")

    if args.write:
        n = _write_to_supabase(scores, args.dry_run)
        print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Wrote {n} technical rows to Supabase.")


if __name__ == "__main__":
    main()
