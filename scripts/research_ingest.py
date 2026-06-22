#!/usr/bin/env python3
"""
Research, step 3 of 3 — INGEST.

Validates the analysis the agent produced (knowledge/research_results/{SYMBOL}.json)
and writes one row to `research_packs`. No LLM call, no network: deterministic
validate-and-store. `viability_score` becomes the conviction input the composite
scorer consumes.

Usage:
    python scripts/research_ingest.py --asset BTC
    python scripts/research_ingest.py --asset BTC --dry-run   # validate only, no DB write
"""
import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"
ASSETS_YAML = ROOT / "config" / "assets.yaml"
RESULT_DIR = ROOT / "knowledge" / "research_results"

try:
    from pydantic import BaseModel, field_validator, ValidationError
except ImportError:
    print("pydantic not installed. Run: pip install pydantic", file=sys.stderr)
    sys.exit(1)


class ResearchResult(BaseModel):
    bull_case: str
    bear_case: str
    risks: str
    unknowns: str = ""
    research_summary: str = ""
    evidence_quality: str = "low"
    evidence_quality_score: float = 0.0
    viability_score: float = 0.0
    thesis_fit_score: float = 0.0
    portfolio_fit_score: float = 0.0
    final_decision: str = "research_only"

    @field_validator("evidence_quality", mode="before")
    @classmethod
    def _coerce_quality(cls, v):
        s = str(v).lower().strip()
        return s if s in ("high", "medium", "low") else "low"

    @field_validator("final_decision", mode="before")
    @classmethod
    def _coerce_decision(cls, v):
        s = str(v).lower().strip()
        allowed = {"enter", "watch", "research_only", "reject", "good_asset_bad_entry"}
        return s if s in allowed else "research_only"

    @field_validator("evidence_quality_score", "viability_score", "thesis_fit_score",
                     "portfolio_fit_score", mode="before")
    @classmethod
    def _clamp_score(cls, v):
        try:
            return max(0.0, min(100.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


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
                return {"name": row.get("name", symbol),
                        "asset_type": row.get("asset_type", "crypto")}
    return {"name": symbol, "asset_type": "crypto"}


def _apply_evidence_gate(result: ResearchResult) -> ResearchResult:
    if result.evidence_quality == "low" and result.evidence_quality_score < 20:
        result.final_decision = "reject"
        result.viability_score = min(result.viability_score, 40.0)
    return result


def ingest(symbol: str, dry_run: bool) -> bool:
    symbol = symbol.upper()
    result_path = RESULT_DIR / f"{symbol}.json"
    if not result_path.exists():
        print(f"[research_ingest] no result file at {result_path.relative_to(ROOT)} — "
              f"run research_prepare.py and have the agent write its analysis first.", file=sys.stderr)
        return False

    try:
        raw = json.loads(result_path.read_text())
        result = _apply_evidence_gate(ResearchResult(**raw))
    except (json.JSONDecodeError, ValidationError) as e:
        print(f"[research_ingest] invalid result file: {e}", file=sys.stderr)
        return False

    print(f"[research_ingest] {symbol}: viability={result.viability_score:.0f} "
          f"thesis_fit={result.thesis_fit_score:.0f} decision={result.final_decision}")

    if dry_run:
        print("  [DRY RUN] validated; not writing research_packs.")
        return True

    meta = _asset_meta(symbol)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO research_packs
           (id, asset, symbol, asset_type, created_at, research_level, research_summary,
            bull_case, bear_case, risks, unknowns, evidence_quality_score, viability_score,
            thesis_fit_score, portfolio_fit_score, final_decision, markdown_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (f"research_{symbol}", meta["name"], symbol, meta["asset_type"], now, 3,
         result.research_summary, result.bull_case, result.bear_case, result.risks,
         result.unknowns, result.evidence_quality_score, result.viability_score,
         result.thesis_fit_score, result.portfolio_fit_score, result.final_decision,
         str(result_path.relative_to(ROOT))),
    )
    conn.commit()
    conn.close()
    print(f"  → research_packs (research_{symbol})")
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate + store the agent's research analysis")
    parser.add_argument("--asset", required=True, help="Symbol, e.g. BTC")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print("Database not found. Run: python scripts/init_db.py", file=sys.stderr)
        sys.exit(1)

    ok = ingest(args.asset, args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
