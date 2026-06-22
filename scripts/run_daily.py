#!/usr/bin/env python3
"""
Daily pipeline runner. Executes all 14 workflow steps in order.
Restarts from the last successful stage if interrupted.

Usage:
    python scripts/run_daily.py           # full run
    python scripts/run_daily.py --dry-run # no Telegram send, no DB writes
    python scripts/run_daily.py --status  # show today's pipeline status
    python scripts/run_daily.py --from signal_scorer  # resume from specific stage
"""
import argparse
import datetime
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"

STAGES = [
    "ingest_sources",
    "extract_mentions",
    "resolve_assets",
    "refresh_hyperliquid_universe",
    "check_tradeability",
    "score_signals",
    "update_idea_ledger",
    "determine_research_priority",
    "run_research",
    "update_thesis_memory",
    "update_shadow_portfolios",
    "refresh_prices",
    "evaluate_outcomes",   # self-evolving: score closed outcomes, calibrate source weights
    "score_macro_fit",     # tag trade ideas as macro tailwind/neutral/headwind vs active regime
    "score_technical",     # score each symbol's technical posture from market_candles
    "build_portfolio",     # size composite-ranked ideas vs thesis budgets + portfolio heat
    "generate_daily_digest",
    "update_here_now",
    "sync_supabase",       # stage 15: push to Supabase for MoneyTrailDash (skips if key not set)
]

DASHBOARD_JSON = ROOT / "dashboards" / "dashboard_data.json"


def _stamp_pipeline_start() -> None:
    """Write currently_running=true + generated_at at pipeline start.
    Frontend uses this to detect stuck pipelines (running > 2h = hard error banner)."""
    data: dict = {}
    if DASHBOARD_JSON.exists():
        try:
            data = json.loads(DASHBOARD_JSON.read_text())
        except Exception:
            pass
    data["generated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    data["currently_running"] = True
    DASHBOARD_JSON.parent.mkdir(exist_ok=True)
    DASHBOARD_JSON.write_text(json.dumps(data, indent=2))


def _stamp_pipeline_end() -> None:
    """Flip currently_running to false when pipeline completes (success or fail)."""
    if not DASHBOARD_JSON.exists():
        return
    try:
        data = json.loads(DASHBOARD_JSON.read_text())
        data["currently_running"] = False
        DASHBOARD_JSON.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _check_real_positions(conn: sqlite3.Connection) -> None:
    """Warn if real_positions is empty on a non-first run.
    Empty real_positions → portfolio heat = 0 → all entries appear safe (wrong)."""
    count = conn.execute("SELECT COUNT(*) FROM real_positions").fetchone()[0]
    if count > 0:
        return
    prev_runs = conn.execute(
        "SELECT COUNT(*) FROM pipeline_runs WHERE status = 'completed'"
    ).fetchone()[0]
    if prev_runs > 0:
        print(
            "\n⚠️  WARNING: real_positions table is empty but previous pipeline runs exist.\n"
            "   Portfolio heat will read 0 (all entries appear safe — this is INCORRECT).\n"
            "   Populate real_positions before running or use --skip-positions-check to override.\n"
        )


STAGE_SCRIPTS = {
    "ingest_sources":                "scripts/ingest_sources.py",
    "extract_mentions":              "scripts/extract_mentions.py",
    "resolve_assets":                "scripts/resolve_assets.py",
    "refresh_hyperliquid_universe":  "scripts/refresh_hyperliquid_universe.py",
    "check_tradeability":            "scripts/check_tradeability.py",
    "score_signals":                 "scripts/score_signals.py",
    "update_idea_ledger":            "scripts/score_signals.py --idea-ledger",
    "determine_research_priority":   "scripts/run_research.py --priority-only",
    "run_research":                  "scripts/run_research.py",
    "update_thesis_memory":          "scripts/update_thesis_memory.py",
    "update_shadow_portfolios":      "scripts/simulate_portfolios.py",
    "refresh_prices":                "scripts/refresh_prices.py",
    "evaluate_outcomes":             "scripts/evaluate_outcomes.py --calibrate",
    "score_macro_fit":               "scripts/score_macro_fit.py --write",
    "score_technical":               "scripts/score_technical.py --write",
    "build_portfolio":               "scripts/build_portfolio.py --write",
    "generate_daily_digest":         "scripts/generate_daily_digest.py",
    "update_here_now":               "scripts/generate_daily_digest.py --here-now-only",
    "sync_supabase":                 "scripts/sync_to_supabase.py",
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_today_stages(conn: sqlite3.Connection) -> dict[str, str]:
    today = datetime.date.today().isoformat()
    rows = conn.execute(
        "SELECT stage, status FROM pipeline_runs WHERE run_date = ? ORDER BY started_at",
        (today,),
    ).fetchall()
    return {r["stage"]: r["status"] for r in rows}


def show_status() -> None:
    if not DB_PATH.exists():
        print("Database not found. Run: python scripts/init_db.py")
        sys.exit(1)
    conn = get_conn()
    stages = get_today_stages(conn)
    today = datetime.date.today().isoformat()
    print(f"Pipeline status for {today}:")
    for stage in STAGES:
        status = stages.get(stage, "pending")
        icon = {"completed": "✓", "failed": "✗", "running": "…", "skipped": "–"}.get(status, "○")
        print(f"  {icon} {stage}: {status}")
    conn.close()


def run_stage(stage: str, dry_run: bool) -> bool:
    script = STAGE_SCRIPTS.get(stage)
    if not script:
        print(f"  No script mapped for stage: {stage}")
        return False

    cmd = [sys.executable] + script.split()
    if dry_run:
        cmd.append("--dry-run")

    print(f"  Running {stage}...", end=" ", flush=True)
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)

    if result.returncode == 0:
        print("OK")
        return True
    else:
        print(f"FAILED (exit {result.returncode})")
        if result.stderr:
            print(f"    {result.stderr.strip()[:200]}")
        return False


def mark_stage(conn: sqlite3.Connection, stage: str, status: str, error: str = None) -> None:
    today = datetime.date.today().isoformat()
    now = datetime.datetime.utcnow().isoformat()
    run_id = f"{today}_{stage}"
    conn.execute(
        """INSERT OR REPLACE INTO pipeline_runs
           (id, run_date, stage, status, started_at, completed_at, error)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, today, stage, status, now, now if status in ("completed", "failed", "skipped") else None, error),
    )
    conn.commit()


def run_asset_slice(symbol: str, dry_run: bool) -> None:
    """Single-asset vertical slice — agent-driven.

    Research is done by the coding agent (the moneytrail-research skill), not an
    LLM API. This command prepares the brief and then checks whether the agent's
    analysis has been ingested:

      • If a research pack exists  → builds the opportunity row (composite →
        lifecycle → entry/exit plan → one investment_opportunities row).
      • If not                     → prepares the brief and stops, pointing at the
        skill so the agent can analyse → ingest → re-run.

    This keeps the deterministic I/O here and the reasoning in the agent.
    """
    symbol = symbol.upper()
    print(f"MoneyTrail vertical slice — {symbol}{' [DRY RUN]' if dry_run else ''}")

    pack = None
    if DB_PATH.exists():
        conn = get_conn()
        pack = conn.execute(
            "SELECT viability_score FROM research_packs WHERE UPPER(symbol) = ?",
            (symbol,),
        ).fetchone()
        conn.close()

    if pack is None:
        # No conviction yet — prepare the brief and hand off to the agent.
        print("  No research pack on file — preparing the brief for the agent.")
        cmd = [sys.executable, "scripts/research_prepare.py", "--asset", symbol]
        subprocess.run(cmd, cwd=ROOT)
        print("\nNext: use the `moneytrail-research` skill to analyse "
              f"{symbol}, then re-run `run_daily.py --asset {symbol}`.")
        return

    # Conviction is in place — build the opportunity row.
    print(f"  Research pack found (viability={pack['viability_score']}). Building opportunity...")
    cmd = [sys.executable, "scripts/build_opportunity.py", "--asset", symbol]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\nSlice halted: build_opportunity failed (exit {result.returncode}).")
        sys.exit(1)
    print(f"\nSlice complete for {symbol}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="MoneyTrail daily pipeline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--from", dest="from_stage", help="Resume from stage")
    parser.add_argument("--only", help="Run only this stage")
    parser.add_argument("--asset", help="Run the single-asset vertical slice: research → "
                        "build one investment_opportunities row for this symbol (e.g. BTC)")
    parser.add_argument("--skip-positions-check", action="store_true",
                        help="Skip the real_positions empty-table warning")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.asset:
        run_asset_slice(args.asset, args.dry_run)
        return

    if not DB_PATH.exists():
        print("Database not found. Run: python scripts/init_db.py")
        sys.exit(1)

    conn = get_conn()
    today_stages = get_today_stages(conn)

    if not args.skip_positions_check and not args.dry_run:
        _check_real_positions(conn)

    # Stamp pipeline start: sets generated_at + currently_running=true in dashboard JSON
    # so the frontend can detect a stuck pipeline (running > 2h = hard error banner)
    if not args.dry_run:
        _stamp_pipeline_start()

    start_from = args.from_stage or STAGES[0]
    if start_from not in STAGES:
        print(f"Unknown stage: {start_from}. Valid stages: {', '.join(STAGES)}")
        sys.exit(1)

    stages_to_run = STAGES[STAGES.index(start_from):]
    if args.only:
        stages_to_run = [s for s in STAGES if s == args.only]

    print(f"MoneyTrail daily pipeline — {datetime.date.today()}")
    if dry_run := args.dry_run:
        print("  [DRY RUN mode — no DB writes, no Telegram]")

    failed = False
    for stage in stages_to_run:
        # Skip already-completed stages (unless resuming explicitly)
        if today_stages.get(stage) == "completed" and not args.from_stage:
            print(f"  ↩ {stage}: already completed today")
            continue

        mark_stage(conn, stage, "running")
        success = run_stage(stage, dry_run)
        if success:
            mark_stage(conn, stage, "completed")
        else:
            mark_stage(conn, stage, "failed", error=f"Non-zero exit")
            failed = True
            break  # halt pipeline on failure — restartable from this stage

    conn.close()

    if not args.dry_run:
        _stamp_pipeline_end()

    if failed:
        print("\nPipeline halted on failure. Fix the issue and re-run.")
        print("Resume with: python scripts/run_daily.py --from", stage)
        sys.exit(1)
    else:
        print("\nPipeline complete.")


if __name__ == "__main__":
    main()
