#!/usr/bin/env python3
"""
sync_to_supabase.py — Push MoneyTrail data to Supabase for the MoneyTrailDash frontend.

Runs as stage 15 after update_here_now. Safe to re-run (all upserts are idempotent).
Skips gracefully if SUPABASE_SERVICE_ROLE_KEY is not set.

Usage:
    python scripts/sync_to_supabase.py           # full sync
    python scripts/sync_to_supabase.py --dry-run # print what would be pushed, no network calls
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"
DASHBOARD_JSON = ROOT / "dashboards" / "dashboard_data.json"
MACRO_REGIME_JSON = ROOT / "data" / "macro_regime.json"

# Load from secrets/.env.supabase (separate from LLM/Telegram keys to avoid log exposure)
_ENV_FILE = ROOT / "secrets" / ".env.supabase"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _supabase_upsert(table: str, rows: list[dict], dry_run: bool) -> int:
    """POST to Supabase REST API with upsert (onConflict=id)."""
    if not rows:
        return 0
    if dry_run:
        print(f"  [DRY RUN] Would upsert {len(rows)} rows to {table}")
        if rows:
            print(f"    Sample keys: {list(rows[0].keys())}")
        return len(rows)

    import httpx
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    # Batch in chunks of 500 to avoid request size limits
    total = 0
    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        resp = httpx.post(url, headers=headers, json=chunk, timeout=30)
        if resp.status_code not in (200, 201):
            print(f"  ERROR upserting to {table}: {resp.status_code} {resp.text[:200]}")
            return total
        total += len(chunk)
    return total


def _supabase_delete_old_snapshots(dry_run: bool, days: int = 30) -> None:
    """Delete dashboard_snapshots older than N days."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    if dry_run:
        print(f"  [DRY RUN] Would delete dashboard_snapshots older than {cutoff}")
        return
    import httpx
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Prefer": "return=minimal",
    }
    url = f"{SUPABASE_URL}/rest/v1/dashboard_snapshots"
    resp = httpx.delete(url, headers=headers, params={"synced_at": f"lt.{cutoff}T00:00:00Z"}, timeout=15)
    if resp.status_code not in (200, 204):
        print(f"  WARNING: Could not delete old snapshots: {resp.status_code}")


def sync_dashboard_snapshot(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Push dashboard_data.json as a single snapshot row."""
    if not DASHBOARD_JSON.exists():
        print("  [sync_snapshot] dashboard_data.json not found — skipping")
        return
    try:
        data = json.loads(DASHBOARD_JSON.read_text())
    except Exception as exc:
        print(f"  [sync_snapshot] Could not parse dashboard_data.json: {exc}")
        return

    generated_at = data.get("generated_at")
    if not generated_at:
        print("  [sync_snapshot] dashboard_data.json has no generated_at — skipping")
        return

    row = {
        "generated_at": generated_at,
        "currently_running": data.get("currently_running", False),
        "portfolio_heat": data.get("portfolio_heat"),
        "signal_radar": data.get("signal_radar"),
        "tradeability_board": data.get("tradeability_board"),
        "thesis_board": data.get("thesis_board"),
        "lilo_board": data.get("lilo_board"),
        "allocation_board": data.get("allocation_board"),
        "model_audit_board": data.get("model_audit_board"),
        "pending_approvals": data.get("pending_approvals"),
        "pipeline_status": data.get("pipeline_status"),
    }
    n = _supabase_upsert("dashboard_snapshots", [row], dry_run)
    print(f"  [sync_snapshot] {n} snapshot row pushed (generated_at={generated_at})")


def sync_research(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Push research_packs → public_research (strip raw_llm_response, markdown_path)."""
    rows_db = conn.execute("""
        SELECT id, asset, symbol, asset_type, research_level,
               research_summary, bull_case, bear_case, risks,
               evidence_quality_score, thesis_fit_score, final_decision, created_at
        FROM research_packs
    """).fetchall()
    rows = [dict(r) for r in rows_db]
    # Convert datetime strings to ensure ISO format
    for r in rows:
        if r.get("created_at") and "T" not in str(r["created_at"]):
            r["created_at"] = r["created_at"] + "T00:00:00Z"
    n = _supabase_upsert("public_research", rows, dry_run)
    print(f"  [sync_research] {n} research rows pushed")


def sync_lilo(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Push lilo_profiles + active position_plans → public_lilo."""
    rows_db = conn.execute("""
        SELECT
            lp.id, lp.asset, lp.position_role,
            lp.core_percentage, lp.tactical_percentage, lp.speculative_percentage,
            lp.aggression_level,
            pp.id AS plan_id,
            pp.entry_min, pp.entry_max, pp.stop_price,
            pp.thesis_invalidation, pp.risk_per_position_pct,
            pp.status AS plan_status, pp.expires_at,
            lp.notes AS updated_at
        FROM lilo_profiles lp
        LEFT JOIN position_plans pp ON pp.asset = lp.asset AND pp.status = 'active'
    """).fetchall()
    rows = [dict(r) for r in rows_db]
    # updated_at is mis-mapped from notes; Supabase will use synced_at instead
    for r in rows:
        r["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    n = _supabase_upsert("public_lilo", rows, dry_run)
    print(f"  [sync_lilo] {n} LILO rows pushed")


def sync_tp_layers(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Push pending take_profit_layers → public_tp_layers."""
    rows_db = conn.execute("""
        SELECT tpl.id, tpl.plan_id AS lilo_id, pp.asset,
               tpl.layer_number, tpl.target_price, tpl.sell_percentage,
               tpl.reason, tpl.status
        FROM take_profit_layers tpl
        JOIN position_plans pp ON pp.id = tpl.plan_id
        WHERE tpl.status = 'pending'
    """).fetchall()
    rows = [dict(r) for r in rows_db]
    n = _supabase_upsert("public_tp_layers", rows, dry_run)
    print(f"  [sync_tp_layers] {n} TP layer rows pushed")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def sync_trade_ideas(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Push symbols + trade_ideas + trade_idea_scores from SQLite.

    Skips gracefully if the trade_ideas table doesn't exist yet (RV bot
    populates it from the other machine; this stub runs as soon as the schema
    is ready so the bot only needs to write rows, not change sync logic).
    """
    if not _table_exists(conn, "trade_ideas"):
        print("  [sync_trade_ideas] trade_ideas table not found — skipping (bot not yet synced)")
        return

    # Symbols
    symbols_db = conn.execute("""
        SELECT DISTINCT symbol, asset_name, asset_class, exchange, instrument_type,
               tradingview_id, coingecko_id, last_price, price_updated_at
        FROM trade_ideas
        WHERE symbol IS NOT NULL
    """).fetchall()
    if symbols_db:
        n = _supabase_upsert("symbols", [dict(r) for r in symbols_db], dry_run)
        print(f"  [sync_trade_ideas] {n} symbol rows pushed")

    # Trade ideas
    ideas_db = conn.execute("""
        SELECT idea_id, symbol, source, source_url, source_author, source_rank,
               pl_pct, direction, time_horizon, entry_min, entry_max, stop_loss,
               take_profit_1, take_profit_2, take_profit_3, risk_reward,
               levels_source, status, decision, research_only,
               closed_at, outcome, notes, raw_payload, created_at, updated_at
        FROM trade_ideas
    """).fetchall()
    if ideas_db:
        rows = [dict(r) for r in ideas_db]
        # Ensure research_only is never accidentally False
        for r in rows:
            r["research_only"] = True
        n = _supabase_upsert("trade_ideas", rows, dry_run)
        print(f"  [sync_trade_ideas] {n} idea rows pushed")

    # Scores
    if _table_exists(conn, "trade_idea_scores"):
        scores_db = conn.execute("""
            SELECT idea_id, symbol, total_score, source_quality, evidence_quality,
                   technical_setup, risk_reward_score, thesis_fit, macro_liquidity_fit,
                   portfolio_relevance, freshness, scored_at
            FROM trade_idea_scores
        """).fetchall()
        if scores_db:
            n = _supabase_upsert("trade_idea_scores", [dict(r) for r in scores_db], dry_run)
            print(f"  [sync_trade_ideas] {n} score rows pushed")


def sync_trade_levels(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Push trade_idea_levels (entry, SL, TP, resistance, support) from SQLite."""
    if not _table_exists(conn, "trade_idea_levels"):
        print("  [sync_trade_levels] trade_idea_levels table not found — skipping")
        return

    rows_db = conn.execute("""
        SELECT id, symbol, idea_id, level_type, price, source, label, created_at
        FROM trade_idea_levels
        WHERE symbol IS NOT NULL AND price IS NOT NULL
    """).fetchall()
    if rows_db:
        n = _supabase_upsert("trade_idea_levels", [dict(r) for r in rows_db], dry_run)
        print(f"  [sync_trade_levels] {n} level rows pushed")
    else:
        print("  [sync_trade_levels] 0 level rows (table empty)")


def sync_market_candles(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Push market_candles for symbols with active trade ideas."""
    if not _table_exists(conn, "market_candles"):
        print("  [sync_market_candles] market_candles table not found — skipping")
        return

    rows_db = conn.execute("""
        SELECT mc.symbol, mc.interval, mc.ts, mc.open, mc.high, mc.low, mc.close,
               mc.volume, mc.source
        FROM market_candles mc
        WHERE mc.symbol IN (
            SELECT DISTINCT symbol FROM trade_ideas WHERE status = 'active'
        )
        ORDER BY mc.symbol, mc.interval, mc.ts
    """).fetchall()
    if rows_db:
        # Batch by 500 to stay within Supabase limits
        n = _supabase_upsert("market_candles", [dict(r) for r in rows_db], dry_run)
        print(f"  [sync_market_candles] {n} candle rows pushed")
    else:
        print("  [sync_market_candles] 0 candle rows (no active symbols)")


def sync_macro_regime(dry_run: bool) -> None:
    """Push data/macro_regime.json → Supabase macro_regime table (single row id='current')."""
    if not MACRO_REGIME_JSON.exists():
        print("  [sync_macro_regime] macro_regime.json not found — skipping")
        return
    try:
        data = json.loads(MACRO_REGIME_JSON.read_text())
    except Exception as exc:
        print(f"  [sync_macro_regime] Could not parse macro_regime.json: {exc}")
        return

    row = {"id": "current", **data}
    n = _supabase_upsert("macro_regime", [row], dry_run)
    print(f"  [sync_macro_regime] {n} row pushed (season={data.get('active_season')}, phase={data.get('active_phase')})")


# Data-driven sections: their freshness is the newest timestamp of the actual
# data they own, computed here at sync time — because they are populated OUTSIDE
# run_section.py (scrapers, the external RV/other idea bots, manual macro), so a
# runner "last run" would be misleading or absent. Each spec resolves a watermark
# (max timestamp) from where its data lives: local SQLite, this Supabase project,
# or the macro JSON file.
WATERMARK_SECTIONS = [
    {"section": "feeds", "display_name": "Feeds", "cadence": "daily",
     "stale_after_hours": 28, "kind": "local",
     "table": "raw_content", "column": "collected_at",
     "stages": "ingest_sources"},
    {"section": "filings", "display_name": "13F Filings", "cadence": "weekly",
     "stale_after_hours": 192, "kind": "local",
     "table": "sec_13f_scrape_state", "column": "last_scraped_at",
     "stages": "scrape_13f"},
    {"section": "analysis", "display_name": "Research", "cadence": "on_demand",
     "stale_after_hours": None, "kind": "local",
     "table": "research_packs", "column": "created_at",
     "stages": "research_prepare,research_ingest"},
    {"section": "macro", "display_name": "Macro Regime", "cadence": "weekly",
     "stale_after_hours": 336, "kind": "json",
     "field": "last_updated", "stages": "update_macro_regime"},
    # trade_ideas spans multiple sources (RV + others); the merged idea object is
    # investment_opportunities. Freshness = newest of either → "new ideas arrived
    # OR existing idea statuses were re-evaluated".
    {"section": "trade_ideas", "display_name": "Trade Ideas", "cadence": "daily",
     "stale_after_hours": 28, "kind": "supabase",
     "sources": [("rv_trade_ideas", "updated_at"),
                 ("investment_opportunities", "updated_at")],
     "stages": "rv_bot,build_opportunity"},
]


def _local_max(conn: sqlite3.Connection, table: str, column: str) -> tuple[str | None, int]:
    """Return (max timestamp, row count) for a local SQLite table, or (None, 0)."""
    if not _table_exists(conn, table):
        return None, 0
    row = conn.execute(f"SELECT MAX({column}) AS ts, COUNT(*) AS n FROM {table}").fetchone()
    return (row["ts"], row["n"]) if row else (None, 0)


def _supabase_max(table: str, column: str) -> str | None:
    """GET the newest value of a Supabase column via PostgREST, or None."""
    import httpx
    headers = {"apikey": SUPABASE_SERVICE_ROLE_KEY,
               "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {"select": column, "order": f"{column}.desc", "limit": 1}
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data[0][column] if data else None
    except Exception:
        return None


def _watermark_row(conn: sqlite3.Connection, spec: dict) -> dict | None:
    """Build a pipeline_section_status row from a section's data watermark."""
    ts, count = None, 0
    if spec["kind"] == "local":
        ts, count = _local_max(conn, spec["table"], spec["column"])
    elif spec["kind"] == "json":
        if MACRO_REGIME_JSON.exists():
            try:
                ts = json.loads(MACRO_REGIME_JSON.read_text()).get(spec["field"])
            except Exception:
                ts = None
    elif spec["kind"] == "supabase":
        stamps = [t for t in (_supabase_max(tbl, col) for tbl, col in spec["sources"]) if t]
        ts = max(stamps) if stamps else None

    now = datetime.datetime.utcnow().isoformat()
    return {
        "section": spec["section"],
        "display_name": spec["display_name"],
        "status": "completed" if ts else "never",
        "cadence": spec["cadence"],
        "stale_after_hours": spec["stale_after_hours"],
        "last_run_at": ts,
        "last_ok_at": ts,
        "stages": spec["stages"],
        "records_processed": count,
        "error": None,
        "updated_at": now,
    }


def sync_section_status(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Push the per-section freshness roll-up → Supabase pipeline_section_status.

    Two producer types feed one status feed:
      1. Runner sections (scores/portfolio/council) — written to the local
         pipeline_section_status table by run_section.py (last run / last ok).
      2. Data-watermark sections (feeds/macro/filings/analysis/trade_ideas) —
         computed here from the newest timestamp of each section's actual data,
         since they are populated outside the runner.
    The dashboard reads public_section_status generically, so every section that
    lands here lights up its own freshness chip."""
    rows: list[dict] = []

    # 1. Runner-produced rows (if any runs have happened)
    if _table_exists(conn, "pipeline_section_status"):
        runner = conn.execute(
            """SELECT section, display_name, status, cadence, stale_after_hours,
                      last_run_at, last_ok_at, stages, records_processed, error, updated_at
               FROM pipeline_section_status"""
        ).fetchall()
        rows.extend(dict(r) for r in runner)

    # 2. Data-watermark rows (do not clobber a runner row of the same name)
    runner_names = {r["section"] for r in rows}
    for spec in WATERMARK_SECTIONS:
        if spec["section"] in runner_names:
            continue
        row = _watermark_row(conn, spec)
        if row:
            rows.append(row)

    if not rows:
        print("  [sync_section_status] 0 section rows")
        return
    n = _supabase_upsert("pipeline_section_status", rows, dry_run)
    fresh = sum(1 for r in rows if r["last_ok_at"])
    print(f"  [sync_section_status] {n} section rows pushed ({fresh} with data, "
          f"{len(rows) - fresh} never-run)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync MoneyTrail data to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be pushed, no network calls")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("[sync_to_supabase] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set — skipping.")
        print("  Set these in ~/MoneyTrail/secrets/.env.supabase to enable sync.")
        sys.exit(0)  # non-fatal: local-only runs don't need Supabase

    if not DB_PATH.exists():
        print("[sync_to_supabase] Database not found — skipping.")
        sys.exit(0)

    print(f"[sync_to_supabase] {'(dry run) ' if args.dry_run else ''}Syncing to {SUPABASE_URL}...")
    conn = _get_conn()

    # Push asset detail tables first (snapshot pushed last — it's the timestamp the frontend reads)
    sync_research(conn, args.dry_run)
    sync_lilo(conn, args.dry_run)
    sync_tp_layers(conn, args.dry_run)

    # Trade ideas (skips gracefully if RV bot hasn't populated tables yet)
    sync_trade_ideas(conn, args.dry_run)
    sync_trade_levels(conn, args.dry_run)
    sync_market_candles(conn, args.dry_run)

    # Push snapshot last: if partial failure above, boards show yesterday's snapshot
    # but asset details are already current — acceptable
    sync_dashboard_snapshot(conn, args.dry_run)

    # Macro regime is independent of the SQLite DB — reads from JSON file directly
    sync_macro_regime(args.dry_run)

    # Per-section freshness roll-up (written by run_section.py) → dashboard chips
    sync_section_status(conn, args.dry_run)

    _supabase_delete_old_snapshots(args.dry_run)

    conn.close()
    print("[sync_to_supabase] Done.")


if __name__ == "__main__":
    main()
