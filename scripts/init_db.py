#!/usr/bin/env python3
"""
Initialise and migrate the MoneyTrail SQLite database.

Usage:
    python scripts/init_db.py           # create / migrate
    python scripts/init_db.py --check   # verify schema version only
    python scripts/init_db.py --migrate # apply pending migrations only
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"
MIGRATIONS_DIR = ROOT / "migrations"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_applied_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT MAX(version) as v FROM schema_version"
        ).fetchone()
        return row["v"] or 0
    except sqlite3.OperationalError:
        return 0


def apply_migrations(conn: sqlite3.Connection, current_version: int) -> int:
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    applied = 0
    for mf in migration_files:
        # File name: 001_initial.sql → version = 1
        version = int(mf.name.split("_")[0])
        if version <= current_version:
            continue
        print(f"  Applying migration {mf.name}...")
        sql = mf.read_text()
        conn.executescript(sql)
        conn.commit()
        applied += 1
        print(f"  Migration {version} applied.")
    return applied


def check(conn: sqlite3.Connection) -> bool:
    version = get_applied_version(conn)
    if version == 0:
        print("ERROR: Database not initialised. Run: python scripts/init_db.py")
        return False
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    expected = [
        "schema_version", "pipeline_runs", "raw_content", "asset_mentions",
        "resolution_queue", "asset_signals", "venue_assets", "asset_tradeability",
        "research_packs", "asset_thesis_scores", "lilo_profiles", "position_plans",
        "take_profit_layers", "shadow_portfolios", "shadow_positions", "price_history",
        "real_positions", "simulation_results", "rotation_candidates",
        "model_decision_outcomes", "source_scores",
        "patreon_scrape_state", "patreon_comments",
        "sec_13f_positions", "sec_13f_scrape_state",
    ]
    missing = [t for t in expected if t not in tables]
    if missing:
        print(f"ERROR: Missing tables: {missing}")
        return False
    print(f"Schema version {version} OK — {len(tables)} tables present.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="MoneyTrail DB init / migrate")
    parser.add_argument("--check", action="store_true", help="Verify schema only")
    parser.add_argument("--migrate", action="store_true", help="Apply pending migrations")
    args = parser.parse_args()

    conn = get_connection()

    if args.check:
        ok = check(conn)
        sys.exit(0 if ok else 1)

    current_version = get_applied_version(conn)
    if current_version == 0:
        print(f"Initialising database at {DB_PATH}...")
    else:
        print(f"Database at schema version {current_version}. Checking for migrations...")

    applied = apply_migrations(conn, current_version)
    new_version = get_applied_version(conn)

    if applied == 0:
        print(f"No new migrations. Schema version {new_version}.")
    else:
        print(f"Applied {applied} migration(s). Schema version {new_version}.")

    # Seed real_positions from existing portfolio CSV if present
    portfolio_csv = ROOT.parent / "Portfolio" / "sample_portfolio.csv"
    if portfolio_csv.exists() and new_version >= 1:
        _seed_real_positions(conn, portfolio_csv)

    conn.close()
    print("Done.")


def _seed_real_positions(conn: sqlite3.Connection, csv_path: Path) -> None:
    import csv, datetime
    existing = {
        r[0]
        for r in conn.execute("SELECT asset FROM real_positions").fetchall()
    }
    seeded = 0
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"].strip()
            if symbol in existing:
                continue
            conn.execute(
                """INSERT INTO real_positions
                   (id, asset, asset_type, quantity, cost_basis, current_price, currency, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"rp_{symbol.lower()}",
                    symbol,
                    row.get("asset_type", "unknown"),
                    float(row.get("quantity", 0)),
                    float(row.get("cost_basis", 0)),
                    float(row.get("current_price", 0)),
                    row.get("currency", "USD"),
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
            seeded += 1
    if seeded:
        conn.commit()
        print(f"  Seeded {seeded} real positions from {csv_path.name}.")


if __name__ == "__main__":
    main()
