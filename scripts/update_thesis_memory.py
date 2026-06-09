#!/usr/bin/env python3
"""Step 10 — Update thesis memory and asset_thesis_scores.

Seeds asset_thesis_scores from config/assets.yaml + config/thesis_budget.yaml.
If research_packs exist with viability_score >= 60, uses their thesis_fit_score
instead of the default placeholder score.

Usage:
    python scripts/update_thesis_memory.py
    python scripts/update_thesis_memory.py --dry-run
"""
import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"
ASSETS_YAML = ROOT / "config" / "assets.yaml"
THESIS_YAML = ROOT / "config" / "thesis_budget.yaml"
DASHBOARD_JSON = ROOT / "dashboards" / "dashboard_data.json"

THESIS_NAMES = {
    "scarce_assets": "Scarce Assets",
    "ai_growth": "AI Growth",
    "crypto_beta": "Crypto Beta",
    "tactical_satellite": "Tactical Satellite",
}

DEFAULT_SCORE = 0.75
DEFAULT_LIFECYCLE = "accumulating"
DEFAULT_CROWDING = 0.40


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def load_assets(path: Path) -> list[dict]:
    """Flatten all asset sections into a single list."""
    data = yaml.safe_load(path.read_text())
    assets = []
    for section in ("crypto", "equities", "etfs"):
        for item in data.get(section, []):
            assets.append(item)
    return assets


def load_theses(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    return data.get("theses", {})


def get_research_scores(conn: sqlite3.Connection) -> dict[str, float]:
    """Return {symbol: thesis_fit_score} for viable research packs."""
    rows = conn.execute("""
        SELECT symbol, thesis_fit_score
        FROM research_packs
        WHERE viability_score >= 60 AND thesis_fit_score IS NOT NULL
    """).fetchall()
    return {row["symbol"]: row["thesis_fit_score"] for row in rows}


def ensure_is_placeholder_column(conn: sqlite3.Connection, dry_run: bool) -> None:
    """Add is_placeholder column if it doesn't exist yet."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(asset_thesis_scores)").fetchall()]
    if "is_placeholder" not in cols:
        if dry_run:
            print("  [DRY RUN] Would add is_placeholder column to asset_thesis_scores")
        else:
            conn.execute("ALTER TABLE asset_thesis_scores ADD COLUMN is_placeholder INTEGER NOT NULL DEFAULT 1")
            conn.commit()
            print("  Added is_placeholder column to asset_thesis_scores")


def upsert_thesis_scores(
    conn: sqlite3.Connection,
    assets: list[dict],
    research_scores: dict[str, float],
    dry_run: bool,
) -> dict[str, list[dict]]:
    """Upsert asset_thesis_scores rows. Returns {thesis: [rows]} for ranking."""
    now = datetime.now(timezone.utc).isoformat()
    thesis_assets: dict[str, list[dict]] = {}

    rows_to_write = []
    for asset in assets:
        thesis = asset.get("primary_thesis")
        if not thesis:
            continue
        symbol = asset.get("symbol", "")
        research_score = research_scores.get(symbol)
        is_placeholder = research_score is None
        score = research_score if research_score is not None else DEFAULT_SCORE

        row = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"thesis_score_{symbol}_{thesis}")),
            "asset": asset.get("name", symbol),
            "thesis": thesis,
            "score": score / 100.0 if research_score and research_score > 1 else score,
            "primary_thesis": 1,
            "portfolio_role": None,
            "best_expression_rank": None,
            "lifecycle_stage": DEFAULT_LIFECYCLE,
            "conviction_score": score if not is_placeholder else None,
            "invalidation_conditions": None,
            "add_conditions": None,
            "trim_conditions": None,
            "last_reviewed": now,
            "version": 1,
            "is_placeholder": 1 if is_placeholder else 0,
        }
        rows_to_write.append(row)
        thesis_assets.setdefault(thesis, []).append({"symbol": symbol, "score": row["score"], "is_placeholder": is_placeholder})

    # Rank within each thesis
    for thesis, items in thesis_assets.items():
        items.sort(key=lambda x: x["score"], reverse=True)
        for rank, item in enumerate(items, 1):
            item["rank"] = rank

    # Build a rank lookup
    rank_lookup: dict[tuple, int] = {}
    for thesis, items in thesis_assets.items():
        for item in items:
            rank_lookup[(item["symbol"], thesis)] = item["rank"]

    for row in rows_to_write:
        symbol = next((a["symbol"] for a in assets if a.get("name", a.get("symbol")) == row["asset"]), row["asset"])
        row["best_expression_rank"] = rank_lookup.get((symbol, row["thesis"]))

    if dry_run:
        print(f"  [DRY RUN] Would upsert {len(rows_to_write)} rows to asset_thesis_scores")
        for row in rows_to_write[:5]:
            print(f"    {row['asset']} / {row['thesis']} score={row['score']:.2f} placeholder={row['is_placeholder']}")
        if len(rows_to_write) > 5:
            print(f"    ... and {len(rows_to_write) - 5} more")
    else:
        for row in rows_to_write:
            conn.execute("""
                INSERT OR REPLACE INTO asset_thesis_scores
                (id, asset, thesis, score, primary_thesis, portfolio_role, best_expression_rank,
                 lifecycle_stage, conviction_score, invalidation_conditions, add_conditions,
                 trim_conditions, last_reviewed, version, is_placeholder)
                VALUES
                (:id, :asset, :thesis, :score, :primary_thesis, :portfolio_role, :best_expression_rank,
                 :lifecycle_stage, :conviction_score, :invalidation_conditions, :add_conditions,
                 :trim_conditions, :last_reviewed, :version, :is_placeholder)
            """, row)
        conn.commit()
        print(f"  Upserted {len(rows_to_write)} rows to asset_thesis_scores")

    return thesis_assets


def build_thesis_board(thesis_assets: dict[str, list[dict]], theses_config: dict) -> list[dict]:
    """Build the thesis_board JSON structure for dashboard_data.json."""
    board = []
    for thesis_key, items in thesis_assets.items():
        if thesis_key not in THESIS_NAMES:
            continue
        top = items[:3]
        all_placeholder = all(item["is_placeholder"] for item in items)
        avg_score = sum(i["score"] for i in items) / len(items) if items else DEFAULT_SCORE
        board.append({
            "thesis": thesis_key,
            "display_name": THESIS_NAMES[thesis_key],
            "strength": round(avg_score, 2),
            "lifecycle_stage": DEFAULT_LIFECYCLE,
            "crowding_score": DEFAULT_CROWDING,
            "is_placeholder": all_placeholder,
            "top_expressions": [
                {
                    "symbol": item["symbol"],
                    "score": round(item["score"], 2),
                    "is_placeholder": item["is_placeholder"],
                }
                for item in top
            ],
        })
    board.sort(key=lambda x: x["strength"], reverse=True)
    return board


def update_dashboard_json(thesis_board: list[dict], dry_run: bool) -> None:
    if not DASHBOARD_JSON.exists():
        print("  dashboard_data.json not found — skipping dashboard update")
        return
    data = json.loads(DASHBOARD_JSON.read_text())
    if dry_run:
        print(f"  [DRY RUN] Would update thesis_board with {len(thesis_board)} entries")
        for entry in thesis_board:
            print(f"    {entry['display_name']}: strength={entry['strength']}, placeholder={entry['is_placeholder']}, top={[e['symbol'] for e in entry['top_expressions']]}")
    else:
        data["thesis_board"] = thesis_board
        DASHBOARD_JSON.write_text(json.dumps(data, indent=2))
        print(f"  Updated thesis_board in dashboard_data.json ({len(thesis_board)} theses)")


def log_pipeline_run(conn: sqlite3.Connection, status: str, records: int, dry_run: bool) -> None:
    if dry_run:
        return
    conn.execute("""
        INSERT OR REPLACE INTO pipeline_runs (id, run_date, stage, status, started_at, completed_at, records_processed)
        VALUES (?, date('now'), 'update_thesis_memory', ?, datetime('now'), datetime('now'), ?)
    """, (str(uuid.uuid4()), status, records))
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed asset_thesis_scores from config")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change, no writes")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"[update_thesis_memory] {'(dry run) ' if args.dry_run else ''}Loading config...")
    assets = load_assets(ASSETS_YAML)
    theses = load_theses(THESIS_YAML)
    print(f"  Loaded {len(assets)} assets, {len(theses)} thesis definitions")

    conn = get_conn()
    try:
        ensure_is_placeholder_column(conn, args.dry_run)
        research_scores = get_research_scores(conn)
        print(f"  Found {len(research_scores)} assets with research pack scores")

        thesis_assets = upsert_thesis_scores(conn, assets, research_scores, args.dry_run)

        thesis_board = build_thesis_board(thesis_assets, theses)
        update_dashboard_json(thesis_board, args.dry_run)

        total = sum(len(v) for v in thesis_assets.values())
        log_pipeline_run(conn, "completed", total, args.dry_run)

        print("[update_thesis_memory] Done.")
        for thesis, items in thesis_assets.items():
            name = THESIS_NAMES.get(thesis, thesis)
            scored = sum(1 for i in items if not i["is_placeholder"])
            print(f"  {name}: {len(items)} assets ({scored} scored, {len(items)-scored} placeholder)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
