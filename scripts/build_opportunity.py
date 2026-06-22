#!/usr/bin/env python3
"""
Build one unified opportunity row for a single asset — the MoneyTrail → dashboard
bridge (Part B of the redesign).

Takes everything the engine knows about one asset and lands it as a single
fully-populated row in Supabase `investment_opportunities` (source='moneytrail'),
which the dashboard's Funnel board + IdeaDrawer already render. It:

  B3  composite = mean(macro_fit, technical, conviction) × (1 − 0.25·crowding),
      then distributed across the 7 sub-scores so they sum to total_score
  B4  composite + price-vs-entry-zone                                   → action_state / lifecycle
  B5  technical levels + R/R                                            → entry / stop / take-profits
  B6  upsert the row + append an opportunity_engine_events transition

Conviction comes from research_packs.viability_score (run_research.py). The three
working scorers (score_macro_fit, score_technical) are imported and run per-asset.

Usage:
    python scripts/build_opportunity.py --asset BTC
    python scripts/build_opportunity.py --asset BTC --dry-run   # compute + print, no write
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DB_PATH = ROOT / "data" / "moneytrail.sqlite"
ASSETS_YAML = ROOT / "config" / "assets.yaml"

import score_technical as st
import score_macro_fit as smf


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _asset_meta(symbol: str) -> dict:
    symbol = symbol.upper()
    try:
        import yaml
        data = yaml.safe_load(ASSETS_YAML.read_text())
    except Exception:
        data = {}
    for group in (data or {}).values():
        if not isinstance(group, list):
            continue
        for row in group:
            if str(row.get("symbol", "")).upper() == symbol:
                return {
                    "name": row.get("name", symbol),
                    "asset_type": row.get("asset_type", "crypto"),
                    "asset_class": row.get("asset_type", "crypto"),
                    "primary_thesis": row.get("primary_thesis", "none"),
                }
    return {"name": symbol, "asset_type": "crypto", "asset_class": "crypto", "primary_thesis": "none"}


def _research(conn: sqlite3.Connection, symbol: str) -> dict:
    """Latest research pack for the asset (conviction source). Empty if none."""
    row = conn.execute(
        "SELECT * FROM research_packs WHERE UPPER(symbol) = ? ORDER BY created_at DESC LIMIT 1",
        (symbol.upper(),),
    ).fetchone()
    return dict(row) if row else {}


def _crowding(conn: sqlite3.Connection, symbol: str) -> float:
    """Crowding 0..1 from asset_signals (0 = uncrowded). Defaults to 0 when unknown."""
    row = conn.execute(
        "SELECT crowding_score FROM asset_signals WHERE UPPER(symbol) = ? ORDER BY last_seen DESC LIMIT 1",
        (symbol.upper(),),
    ).fetchone()
    if row and row["crowding_score"] is not None:
        return max(0.0, min(1.0, float(row["crowding_score"])))
    return 0.0


# ── B3: composite ───────────────────────────────────────────────────────────

def composite_score(macro: float, technical: float, conviction: float, crowding: float) -> float:
    """Blend the four factors into one 0-100 number.

    Macro and technical are 0-100 (50 = neutral); conviction (viability) is 0-100.
    We average the three signal scores, then apply a crowding penalty (a fully
    crowded idea loses up to 25% of its score). Neutral inputs → ~50, so a
    research-less idea still ranks sensibly rather than collapsing to zero.
    """
    base = (macro + technical + conviction) / 3.0
    penalty = 1.0 - 0.25 * crowding
    return round(max(0.0, min(100.0, base * penalty)), 1)


# ── B4: lifecycle gate ────────────────────────────────────────────────────────

# Below this composite, an idea is still in research — not actionable.
READY_THRESHOLD = 55.0


def gate_state(comp: float, price, entry_min, entry_max, do_not_chase, invalidated: bool) -> tuple[str, str]:
    """Map composite + price position → (action_state, lifecycle).

    Mirrors the enum the dashboard view orders by:
      ready | wait_for_entry | chasing_risk | exit_trim | invalidated | research
    """
    if invalidated:
        return "invalidated", "active_review"
    if comp < READY_THRESHOLD:
        return "research", "candidate"
    if price is None or entry_min is None or entry_max is None:
        return "wait_for_entry", "candidate"
    if do_not_chase is not None and price > do_not_chase:
        return "chasing_risk", "candidate"
    if entry_min <= price <= entry_max:
        return "ready", "candidate"
    if price < entry_min:
        return "wait_for_entry", "candidate"
    return "chasing_risk", "candidate"


# ── B5: entry / exit plan ─────────────────────────────────────────────────────

def plan_levels(tech: "st.TechnicalScore", closes: list[float], direction: str) -> dict:
    """Derive a concrete entry/stop/TP plan from technical context.

    Entry zone: just below current price (a pullback band) anchored on SMA20.
    Stop: below the trailing range low. Take-profits: staged R-multiples.
    Long-only for the slice (the curated crypto universe is long-biased).
    """
    price = tech.price
    if price is None or not closes:
        return {}

    lookback = closes[-st.RANGE_LOOKBACK:] if len(closes) >= st.RANGE_LOOKBACK else closes
    lo = min(lookback)
    sma_fast = tech.sma_fast or price

    # Entry band: between the SMA20 and current price (a pullback to support),
    # clamped so entry_min < entry_max <= price.
    entry_max = round(price, 6)
    entry_min = round(min(sma_fast, price) * 0.985, 6)
    if entry_min >= entry_max:
        entry_min = round(entry_max * 0.97, 6)
    ideal_entry = round((entry_min + entry_max) / 2, 6)
    do_not_chase = round(entry_max * 1.03, 6)

    # Stop below the trailing low (or 8% under entry if the low is too tight).
    stop = round(min(lo * 0.99, entry_min * 0.92), 6)
    risk = ideal_entry - stop
    if risk <= 0:
        return {}

    tp1 = round(ideal_entry + 1.5 * risk, 6)
    tp2 = round(ideal_entry + 3.0 * risk, 6)
    tp3 = round(ideal_entry + 5.0 * risk, 6)

    return {
        "current_price": round(price, 6),
        "ideal_entry": ideal_entry,
        "entry_min": entry_min,
        "entry_max": entry_max,
        "do_not_chase_above": do_not_chase,
        "stop_loss": stop,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "take_profit_3": tp3,
        "trailing_exit_trigger": "Trail stop to entry after TP1; to TP1 after TP2.",
    }


# ── B6: upsert to investment_opportunities ────────────────────────────────────

# Per-component maxes the dashboard IdeaDrawer renders (sum = 100).
SUB_MAXES = {
    "thesis_score": 20, "entry_score": 20, "risk_reward_score": 15,
    "catalyst_score": 15, "source_score": 15, "liquidity_score": 10,
    "portfolio_fit_score": 5,
}


def _sub_scores(comp: float, tech: float, conviction: float, rr_score: float, research: dict) -> dict:
    """Break the composite down into the 7 sub-scores the IdeaDrawer renders.

    Contract (matches the existing RealVision rows): the 7 sub-scores SUM TO
    total_score. So we compute each factor's fraction of its own max, take the
    factor-weighted average, then scale every bucket by `comp / that average` so
    the parts add up to the composite. Each bucket stays within [0, its max].
    """
    thesis_fit = float(research.get("thesis_fit_score") or conviction)
    pf = float(research.get("portfolio_fit_score") or 50.0)
    evidence = float(research.get("evidence_quality_score") or 50.0)

    # Each factor as a 0-1 fraction of full marks.
    frac = {
        "thesis_score": thesis_fit / 100,
        "entry_score": tech / 100,
        "risk_reward_score": min(100.0, rr_score) / 100,
        "catalyst_score": conviction / 100,
        "source_score": evidence / 100,
        "liquidity_score": 0.7,   # curated universe is liquid; refined later from venue data
        "portfolio_fit_score": pf / 100,
    }
    raw = {k: frac[k] * SUB_MAXES[k] for k in SUB_MAXES}
    raw_total = sum(raw.values())
    # Rescale so the breakdown sums to the composite (guard against div-by-zero).
    scale = (comp / raw_total) if raw_total > 0 else 0.0
    subs = {}
    for k, mx in SUB_MAXES.items():
        subs[k] = round(min(float(mx), raw[k] * scale), 1)
    return subs


def build_row(symbol: str, conn: sqlite3.Connection) -> "dict | None":
    meta = _asset_meta(symbol)
    sym = symbol.upper()
    direction = "long"

    url, key = st._load_env_supabase()
    if not url or not key:
        print("  SUPABASE creds not set (secrets/.env.supabase) — cannot fetch candles or write.", file=sys.stderr)
        return None

    # Technical
    closes = st._fetch_closes(sym, url, key)
    tech = st.score_technical(sym, closes)
    technical = float(tech.technical_score)

    # Macro
    regime = smf.load_regime()
    seasons = smf.load_seasons()
    macro_fit = smf.score_macro_fit(
        {"id": f"moneytrail_{sym}", "symbol": sym, "asset_class": meta["asset_class"], "direction": direction},
        regime, seasons)
    macro = float(macro_fit.macro_fit_score)

    # Conviction (research)
    research = _research(conn, sym)
    conviction = float(research.get("viability_score") or 50.0)
    invalidated = (research.get("final_decision") == "reject")
    crowding = _crowding(conn, sym)

    comp = composite_score(macro, technical, conviction, crowding)

    # Entry/exit plan
    levels = plan_levels(tech, closes, direction)
    risk = (levels.get("ideal_entry", 0) - levels.get("stop_loss", 0)) if levels else 0
    reward = (levels.get("take_profit_1", 0) - levels.get("ideal_entry", 0)) if levels else 0
    rr = (reward / risk) if risk > 0 else 0
    rr_score = min(100.0, rr * 33.0)  # ~3R → 100

    # Lifecycle gate
    action_state, lifecycle = gate_state(
        comp, levels.get("current_price"), levels.get("entry_min"),
        levels.get("entry_max"), levels.get("do_not_chase_above"), invalidated)

    subs = _sub_scores(comp, technical, conviction, rr_score, research)
    # total_score == sum of the breakdown (the contract the existing rows follow
    # and the IdeaDrawer assumes); clamping a bucket at its max may shave a point
    # off the raw composite, so take the real sum rather than `comp`.
    total = round(sum(subs.values()), 1)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    bull = research.get("bull_case") or ""
    summary = research.get("research_summary") or ""
    thesis_text = summary or bull or f"{meta['name']} — {meta['primary_thesis']} thesis (engine-scored)."

    row = {
        "id": f"moneytrail_{sym}",
        "source": "moneytrail",
        "source_record_id": f"research_{sym}",
        "symbol": sym,
        "normalized_symbol": sym,
        "title": f"{meta['name']} ({sym})",
        "thesis": thesis_text[:2000],
        "direction": direction,
        "asset_class": meta["asset_class"],
        "status": research.get("final_decision") or "research",
        "action_state": action_state,
        "lifecycle": lifecycle,
        "total_score": total,
        **subs,
        "current_price": levels.get("current_price"),
        "ideal_entry": levels.get("ideal_entry"),
        "entry_min": levels.get("entry_min"),
        "entry_max": levels.get("entry_max"),
        "do_not_chase_above": levels.get("do_not_chase_above"),
        "stop_loss": levels.get("stop_loss"),
        "take_profit_1": levels.get("take_profit_1"),
        "take_profit_2": levels.get("take_profit_2"),
        "take_profit_3": levels.get("take_profit_3"),
        "trailing_exit_trigger": levels.get("trailing_exit_trigger"),
        "invalidation": (research.get("risks") or "")[:1000] or "Thesis breaks on a daily close below the stop.",
        "why_now": macro_fit.rationale,
        "next_action": _next_action(action_state),
        "what_to_watch": research.get("unknowns") or None,
        "is_tracked": False,
        "is_watchlisted": True,
        "discovered_at": now,
        "updated_at": now,
        "theme_tags": [meta["primary_thesis"]],
        "thesis_topics": [meta["primary_thesis"]],
        "thesis_lenses": [],
        "primary_theme": meta["primary_thesis"],
    }
    # Stash extras the caller logs but the table doesn't store
    row["_debug"] = {"macro": macro, "technical": technical, "conviction": conviction,
                     "crowding": crowding, "rr": round(rr, 2), "n_candles": tech.n_candles}
    return row


def _next_action(state: str) -> str:
    return {
        "ready": "In the entry zone — size a starter position.",
        "wait_for_entry": "Below the zone — set an alert at entry_max.",
        "chasing_risk": "Extended — wait for a pullback into the zone.",
        "research": "Build conviction before acting.",
        "invalidated": "Stand aside — thesis rejected.",
    }.get(state, "Monitor.")


def _upsert(row: dict, dry_run: bool) -> bool:
    url, key = st._load_env_supabase()
    payload = {k: v for k, v in row.items() if not k.startswith("_")}
    if dry_run:
        print(f"  [DRY RUN] would upsert to investment_opportunities:")
        print(f"    {json.dumps({k: payload[k] for k in ('id','action_state','lifecycle','total_score','ideal_entry','stop_loss','take_profit_1')}, default=str)}")
        return True
    if not url or not key:
        print("  SUPABASE creds not set — skipping write.", file=sys.stderr)
        return False
    try:
        import httpx
    except ImportError:
        print("  httpx not installed (pip install httpx) — cannot write.", file=sys.stderr)
        return False
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    try:
        r = httpx.post(f"{url}/rest/v1/investment_opportunities", headers=headers, json=[payload], timeout=30)
    except httpx.HTTPError as e:
        print(f"  ERROR upserting opportunity: {e}", file=sys.stderr)
        return False
    if r.status_code not in (200, 201):
        print(f"  ERROR upserting opportunity: {r.status_code} {r.text[:300]}", file=sys.stderr)
        return False

    # Append a transition event (best-effort — failure here must not fail the slice)
    ev = {
        "id": f"moneytrail_{row['symbol']}_{row['action_state']}",
        "opportunity_id": row["id"],
        "event_type": "action_state_snapshot",
        "action_state": row["action_state"],
        "symbol": row["symbol"],
        "title": row["title"],
        "detail": f"MoneyTrail composite {row['total_score']} → {row['action_state']}",
        "event_at": row["updated_at"],
    }
    try:
        httpx.post(f"{url}/rest/v1/opportunity_engine_events", headers=headers, json=[ev], timeout=30)
    except httpx.HTTPError as e:
        print(f"  (event log skipped: {e})", file=sys.stderr)
    return True


def build_opportunity(symbol: str, dry_run: bool) -> bool:
    conn = _get_conn()
    row = build_row(symbol, conn)
    conn.close()
    if not row:
        return False
    d = row["_debug"]
    print(f"[build_opportunity] {symbol.upper()}: macro={d['macro']:.0f} tech={d['technical']:.0f} "
          f"conv={d['conviction']:.0f} crowd={d['crowding']:.2f} → COMP {row['total_score']} "
          f"| {row['action_state']} | R/R {d['rr']} | {d['n_candles']} candles")
    return _upsert(row, dry_run)


def main():
    parser = argparse.ArgumentParser(description="Build one investment_opportunities row from MoneyTrail intelligence")
    parser.add_argument("--asset", required=True, help="Symbol, e.g. BTC")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    ok = build_opportunity(args.asset, args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
