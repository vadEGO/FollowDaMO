#!/usr/bin/env python3
"""
run_section.py — Run one analysis SECTION on its own cadence.

A section is an ordered group of pipeline stages defined in config/sections.yaml
(e.g. `scores` = score_macro_fit + score_technical). This lets each part of the
analysis run — and be seen to be fresh or stale — independently of the others,
instead of riding one monolithic daily run.

It reuses run_daily.py's stage primitives (run_stage / mark_stage / get_conn) so
there is one source of truth for how a stage executes, and writes a per-section
roll-up into the local `pipeline_section_status` table. sync_to_supabase.py then
pushes that roll-up to Supabase for the dashboard's per-section freshness chips.

Usage:
    python scripts/run_section.py scores
    python scripts/run_section.py portfolio --dry-run
    python scripts/run_section.py council --topic BTC
    python scripts/run_section.py --list
"""
import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"
SECTIONS_YAML = ROOT / "config" / "sections.yaml"

# Reuse the daily runner's primitives — do not duplicate stage-execution logic.
sys.path.insert(0, str(ROOT / "scripts"))
from run_daily import run_stage, mark_stage, get_conn  # noqa: E402


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


def load_sections() -> dict:
    """Return the sections mapping from config/sections.yaml."""
    if not SECTIONS_YAML.exists():
        print(f"Section registry not found: {SECTIONS_YAML}")
        sys.exit(1)
    data = yaml.safe_load(SECTIONS_YAML.read_text()) or {}
    return data.get("sections", {})


def ensure_status_table(conn: sqlite3.Connection) -> None:
    """Create the local roll-up table if missing (mirrors migrations/010 on Supabase)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pipeline_section_status (
             section           TEXT PRIMARY KEY,
             display_name      TEXT,
             status            TEXT NOT NULL,
             cadence           TEXT,
             stale_after_hours REAL,
             last_run_at       TEXT,
             last_ok_at        TEXT,
             stages            TEXT,
             records_processed INTEGER DEFAULT 0,
             error             TEXT,
             updated_at        TEXT NOT NULL
           )"""
    )
    conn.commit()


def record_section(conn: sqlite3.Connection, section: str, spec: dict,
                   status: str, error: str | None) -> None:
    """Upsert the section's roll-up row, preserving last_ok_at across failures."""
    now = _now()
    stages = ",".join(spec.get("stages", []))
    prev = conn.execute(
        "SELECT last_ok_at FROM pipeline_section_status WHERE section = ?", (section,)
    ).fetchone()
    last_ok = prev["last_ok_at"] if prev else None
    if status == "completed":
        last_ok = now
    conn.execute(
        """INSERT INTO pipeline_section_status
             (section, display_name, status, cadence, stale_after_hours,
              last_run_at, last_ok_at, stages, records_processed, error, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(section) DO UPDATE SET
             display_name=excluded.display_name, status=excluded.status,
             cadence=excluded.cadence, stale_after_hours=excluded.stale_after_hours,
             last_run_at=excluded.last_run_at, last_ok_at=excluded.last_ok_at,
             stages=excluded.stages, error=excluded.error, updated_at=excluded.updated_at""",
        (section, spec.get("display_name", section), status, spec.get("cadence"),
         spec.get("stale_after_hours"), now, last_ok, stages, 0, error, now),
    )
    conn.commit()


def _dependency_warning(conn: sqlite3.Connection, spec: dict) -> None:
    """Warn (do not block) if this section depends on another that is stale/missing."""
    dep = spec.get("depends_on")
    if not dep:
        return
    row = conn.execute(
        "SELECT last_ok_at, stale_after_hours FROM pipeline_section_status WHERE section = ?",
        (dep,),
    ).fetchone()
    if not row or not row["last_ok_at"]:
        print(f"  ⚠️  depends on '{dep}', which has no successful run yet.")
        return
    try:
        age_h = (datetime.datetime.utcnow()
                 - datetime.datetime.fromisoformat(row["last_ok_at"])).total_seconds() / 3600
        threshold = row["stale_after_hours"] or 28
        if age_h > threshold:
            print(f"  ⚠️  dependency '{dep}' is stale ({age_h:.0f}h old > {threshold:.0f}h).")
    except (ValueError, TypeError):
        pass


def run_section(section: str, dry_run: bool, topic: str | None) -> bool:
    sections = load_sections()
    spec = sections.get(section)
    if not spec:
        print(f"Unknown section: {section}. Valid: {', '.join(sections)}")
        sys.exit(1)

    if spec.get("external") or not spec.get("stages"):
        print(f"Section '{section}' is external/watermark-only — it has no runner stages.\n"
              f"  Its data is produced elsewhere (external bots / manual); freshness is a\n"
              f"  data watermark published by scripts/sync_to_supabase.py. Nothing to run.")
        sys.exit(0)

    required = spec.get("requires_arg")
    if required and not topic:
        print(f"Section '{section}' requires --{required} (it is agent-driven / on-demand).")
        sys.exit(1)

    if not DB_PATH.exists():
        print("Database not found. Run: python scripts/init_db.py")
        sys.exit(1)

    conn = get_conn()
    ensure_status_table(conn)
    _dependency_warning(conn, spec)

    stages = spec.get("stages", [])
    print(f"MoneyTrail section '{section}' ({spec.get('cadence', '?')}) — {datetime.date.today()}")
    if dry_run:
        print("  [DRY RUN mode — no writes]")

    if not dry_run:
        record_section(conn, section, spec, "running", None)

    def _stage_args(stage: str) -> list[str] | None:
        # Different agent-driven stages take the on-demand arg under different flags.
        if not topic:
            return None
        if stage.startswith("council_"):
            return ["--topic", topic]
        if stage.startswith("research_"):
            return ["--asset", topic]
        return None

    failed_stage = None
    for stage in stages:
        mark_stage(conn, stage, "running")
        ok = run_stage(stage, dry_run, extra_args=_stage_args(stage))
        mark_stage(conn, stage, "completed" if ok else "failed",
                   error=None if ok else "Non-zero exit")
        if not ok:
            failed_stage = stage
            break

    status = "completed" if failed_stage is None else "failed"
    err = None if failed_stage is None else f"stage '{failed_stage}' failed"
    if not dry_run:
        record_section(conn, section, spec, status, err)
    conn.close()

    if failed_stage:
        print(f"\nSection '{section}' FAILED at stage '{failed_stage}'.")
        return False
    print(f"\nSection '{section}' completed.")
    return True


def list_sections() -> None:
    sections = load_sections()
    print("Sections (config/sections.yaml):")
    for name, spec in sections.items():
        dep = f"  depends_on={spec['depends_on']}" if spec.get("depends_on") else ""
        print(f"  {name:12s} [{spec.get('cadence', '?'):9s}] "
              f"stages={','.join(spec.get('stages', []))}{dep}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one MoneyTrail analysis section")
    parser.add_argument("section", nargs="?", help="Section name (see --list)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--topic", help="Topic/asset for agent-driven sections (e.g. council)")
    parser.add_argument("--list", action="store_true", help="List sections and exit")
    args = parser.parse_args()

    if args.list or not args.section:
        list_sections()
        return

    ok = run_section(args.section, args.dry_run, args.topic)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
