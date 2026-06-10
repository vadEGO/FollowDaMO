#!/usr/bin/env python3
"""Self-evolving feedback loop — learn from realized outcomes.

The fourth pillar (macro / technical / portfolio are the first three). This is
what makes the engine *self-evolving*: it scores how past decisions actually
played out and feeds that back into the source-credibility weights that drive
future signal scoring.

Loop:
  1. outcome_score(entry, price_30d, price_90d, max_drawdown) -> 0-100
     A risk-adjusted result: reward return, penalise the drawdown taken to get it.
  2. per-source accuracy = mean outcome_score of that source's decisions.
  3. calibrate: nudge each source's historical_accuracy and signal_weight toward
     its realized accuracy by a bounded learning rate, so credibility evolves
     gradually instead of whipsawing on one trade.

Bootstraps safely: with zero closed outcomes it reports "no data yet" and leaves
weights untouched — it never fabricates a signal.

Usage:
    python scripts/evaluate_outcomes.py             # report only
    python scripts/evaluate_outcomes.py --calibrate # write updated source weights
    python scripts/evaluate_outcomes.py --calibrate --dry-run
"""
import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"

# How fast credibility moves toward realized accuracy per evaluation. Small, so
# one good/bad trade nudges rather than dominates — the engine evolves, not lurches.
LEARNING_RATE = 0.20

# Weight of the 90d vs 30d horizon in the blended return (longer horizon matters
# more for a thesis-driven book, but 30d guards against slow bleed).
HORIZON_WEIGHTS = {"30d": 0.4, "90d": 0.6}

# A drawdown of this fraction fully offsets an equal-sized gain (risk penalty scale).
DRAWDOWN_PENALTY = 1.0

# Clamp source weights to a sane band so calibration can't zero out or over-trust.
WEIGHT_FLOOR, WEIGHT_CEIL = 0.30, 0.98


@dataclass
class SourceCalibration:
    source_name: str
    n_decisions: int
    realized_accuracy: float       # 0-1, mean outcome_score/100 over its decisions
    old_signal_weight: float
    new_signal_weight: float
    delta: float


def outcome_score(entry_price: float, price_30d, price_90d, max_drawdown_90d) -> float | None:
    """Risk-adjusted outcome on a 0-100 scale (50 = flat).

    Blends the 30d/90d return, then subtracts a penalty for the worst drawdown
    endured. Returns None if there isn't enough price data to judge.
    """
    if not entry_price or entry_price <= 0:
        return None
    rets = {}
    if price_30d is not None:
        rets["30d"] = (price_30d - entry_price) / entry_price
    if price_90d is not None:
        rets["90d"] = (price_90d - entry_price) / entry_price
    if not rets:
        return None

    # Weighted blended return over whichever horizons are available.
    wsum = sum(HORIZON_WEIGHTS[h] for h in rets)
    blended = sum(HORIZON_WEIGHTS[h] * r for h, r in rets.items()) / wsum

    dd = abs(max_drawdown_90d) if max_drawdown_90d is not None else 0.0
    risk_adjusted = blended - DRAWDOWN_PENALTY * dd

    # Map a risk-adjusted return to 0-100: 0% -> 50, +50% -> 100, -50% -> 0.
    score = 50.0 + risk_adjusted * 100.0
    return max(0.0, min(100.0, round(score, 1)))


def score_outcomes(conn: sqlite3.Connection) -> list[dict]:
    """Compute outcome_score for every decision that has price follow-through."""
    rows = conn.execute("""
        SELECT id, asset, initial_decision, decision_date, entry_price,
               price_30d, price_90d, max_drawdown_90d
        FROM model_decision_outcomes
    """).fetchall()
    scored = []
    for r in rows:
        s = outcome_score(r["entry_price"], r["price_30d"], r["price_90d"], r["max_drawdown_90d"])
        if s is not None:
            scored.append({"id": r["id"], "asset": r["asset"], "outcome_score": s})
    return scored


def source_for_decision(conn: sqlite3.Connection, asset: str) -> str | None:
    """Best-effort: which source drove the most mentions for this asset.

    Joins asset_mentions -> raw_content to attribute a decision to a source.
    Returns None if unattributable (graceful — that decision just doesn't
    contribute to any source's accuracy).
    """
    row = conn.execute("""
        SELECT rc.source_name AS src, COUNT(*) AS n
        FROM asset_mentions am
        JOIN raw_content rc ON rc.id = am.content_id
        WHERE UPPER(am.symbol) = UPPER(?)
        GROUP BY rc.source_name
        ORDER BY n DESC
        LIMIT 1
    """, (asset,)).fetchone()
    return row["src"] if row else None


def compute_source_accuracy(conn: sqlite3.Connection, scored: list[dict]) -> dict[str, list[float]]:
    """Group outcome scores by the source that drove each decision."""
    by_source: dict[str, list[float]] = {}
    for s in scored:
        src = source_for_decision(conn, s["asset"])
        if src:
            by_source.setdefault(src, []).append(s["outcome_score"])
    return by_source


def calibrate_sources(conn: sqlite3.Connection, by_source: dict[str, list[float]]) -> list[SourceCalibration]:
    """Nudge each source's signal weight toward its realized accuracy."""
    out: list[SourceCalibration] = []
    for src, scores in by_source.items():
        if not scores:
            continue
        realized = (sum(scores) / len(scores)) / 100.0  # 0-1
        row = conn.execute(
            "SELECT signal_weight FROM source_scores WHERE source_name = ?", (src,)
        ).fetchone()
        if not row:
            continue
        old = float(row["signal_weight"] if row["signal_weight"] is not None else 0.7)
        # EWMA-style move toward realized accuracy, then clamp to the sane band.
        new = old + LEARNING_RATE * (realized - old)
        new = max(WEIGHT_FLOOR, min(WEIGHT_CEIL, round(new, 4)))
        out.append(SourceCalibration(
            source_name=src, n_decisions=len(scores), realized_accuracy=round(realized, 3),
            old_signal_weight=round(old, 4), new_signal_weight=new, delta=round(new - old, 4),
        ))
    return out


def write_calibration(conn: sqlite3.Connection, cals: list[SourceCalibration], dry_run: bool) -> int:
    if dry_run:
        for c in cals:
            print(f"  [DRY RUN] {c.source_name}: signal_weight {c.old_signal_weight} -> {c.new_signal_weight} "
                  f"(realized {c.realized_accuracy}, n={c.n_decisions})")
        return len(cals)
    for c in cals:
        conn.execute(
            "UPDATE source_scores SET historical_accuracy = ?, signal_weight = ? WHERE source_name = ?",
            (c.realized_accuracy, c.new_signal_weight, c.source_name),
        )
    conn.commit()
    return len(cals)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate decision outcomes and calibrate source weights")
    parser.add_argument("--calibrate", action="store_true", help="Write updated source signal weights")
    parser.add_argument("--dry-run", action="store_true", help="With --calibrate, print instead of write")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print("No database found.", file=sys.stderr)
        return

    conn = get_conn()
    scored = score_outcomes(conn)

    if not scored:
        print("No closed outcomes yet — feedback loop is in bootstrap mode "
              "(source weights left at their priors). Nothing to calibrate.")
        conn.close()
        return

    avg = sum(s["outcome_score"] for s in scored) / len(scored)
    print(f"Evaluated {len(scored)} decision outcomes — mean outcome score {avg:.1f}/100.")
    by_source = compute_source_accuracy(conn, scored)
    cals = calibrate_sources(conn, by_source)

    print(f"\n{'SOURCE':28s}  {'N':>3s}  {'REALIZED':>8s}  {'WEIGHT':>14s}")
    for c in sorted(cals, key=lambda x: x.realized_accuracy, reverse=True):
        arrow = "↑" if c.delta > 0 else ("↓" if c.delta < 0 else "·")
        print(f"{c.source_name:28s}  {c.n_decisions:3d}  {c.realized_accuracy:8.2f}  "
              f"{c.old_signal_weight:.3f} {arrow} {c.new_signal_weight:.3f}")

    if args.calibrate:
        n = write_calibration(conn, cals, args.dry_run)
        print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Calibrated {n} sources.")
    else:
        print("\n(report only — pass --calibrate to write updated weights)")

    conn.close()


if __name__ == "__main__":
    main()
