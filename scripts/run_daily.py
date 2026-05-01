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
    "generate_daily_digest",
    "update_here_now",
]

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
    "generate_daily_digest":         "scripts/generate_daily_digest.py",
    "update_here_now":               "scripts/generate_daily_digest.py --here-now-only",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="MoneyTrail daily pipeline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--from", dest="from_stage", help="Resume from stage")
    parser.add_argument("--only", help="Run only this stage")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if not DB_PATH.exists():
        print("Database not found. Run: python scripts/init_db.py")
        sys.exit(1)

    conn = get_conn()
    today_stages = get_today_stages(conn)

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

    if failed:
        print("\nPipeline halted on failure. Fix the issue and re-run.")
        print("Resume with: python scripts/run_daily.py --from", stage)
        sys.exit(1)
    else:
        print("\nPipeline complete.")


if __name__ == "__main__":
    main()
