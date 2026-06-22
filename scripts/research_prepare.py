#!/usr/bin/env python3
"""
Research, step 1 of 3 — PREPARE.

Builds a self-contained research brief for one asset and writes it to disk. No
LLM call, no network: this only gathers context the agent needs. The agent
(Claude Code, via the moneytrail-research skill) reads the brief, does the
analysis, and writes a result file; research_ingest.py then validates + stores it.

This is the deterministic-I/O half of the agent-driven research flow — it
replaces the old in-process Anthropic call.

Outputs:
    knowledge/research_briefs/{SYMBOL}.md     — prompt + context + required schema
    (the agent writes its answer to knowledge/research_results/{SYMBOL}.json)

Usage:
    python scripts/research_prepare.py --asset BTC
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"
PROMPT_PATH = ROOT / "prompts" / "research_prompt.md"
ASSETS_YAML = ROOT / "config" / "assets.yaml"
BRIEF_DIR = ROOT / "knowledge" / "research_briefs"
RESULT_DIR = ROOT / "knowledge" / "research_results"

# The exact JSON the agent must produce. research_ingest.py validates against this.
RESULT_SCHEMA = {
    "bull_case": "string (1-3 sentences)",
    "bear_case": "string (1-3 sentences)",
    "risks": "string (1-3 sentences, top risks)",
    "unknowns": "string (open questions)",
    "research_summary": "string (1-3 sentence overall read)",
    "evidence_quality": "high | medium | low",
    "evidence_quality_score": "number 0-100",
    "viability_score": "number 0-100  (the conviction input to the composite)",
    "thesis_fit_score": "number 0-100",
    "portfolio_fit_score": "number 0-100",
    "final_decision": "enter | watch | research_only | reject | good_asset_bad_entry",
}


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
                        "asset_type": row.get("asset_type", "crypto"),
                        "primary_thesis": row.get("primary_thesis", "none")}
    return {"name": symbol, "asset_type": "crypto", "primary_thesis": "none"}


def _signal_summary(conn: sqlite3.Connection, symbol: str) -> tuple[str, str]:
    rows = conn.execute(
        """SELECT context_snippet, sentiment, intent
           FROM asset_mentions WHERE UPPER(symbol) = ? ORDER BY created_at DESC LIMIT 8""",
        (symbol.upper(),),
    ).fetchall()
    if not rows:
        return ("No social mentions on file — assess purely on independent merit.", "none")
    snippets = [r["context_snippet"] for r in rows if r["context_snippet"]]
    summary = " | ".join(snippets[:5]) if snippets else "Mentioned without quotable context."
    quality = "medium" if len(rows) >= 3 else "low"
    return (summary[:1500], quality)


def build_brief(symbol: str) -> Path:
    symbol = symbol.upper()
    conn = _get_conn()
    meta = _asset_meta(symbol)
    signal_summary, source_quality = _signal_summary(conn, symbol)
    conn.close()

    template = PROMPT_PATH.read_text()
    filled = (template
              .replace("{{ASSET_NAME}}", meta["name"])
              .replace("{{SYMBOL}}", symbol)
              .replace("{{ASSET_TYPE}}", meta["asset_type"])
              .replace("{{SIGNAL_SUMMARY}}", signal_summary)
              .replace("{{SOURCE_QUALITY}}", source_quality))

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = RESULT_DIR / f"{symbol}.json"

    brief = f"""# MoneyTrail research brief — {meta['name']} ({symbol})

You are doing the analysis for this asset yourself (no external API is called).
Work through the research prompt below, then write your structured answer to:

    {result_path}

The file MUST be a single JSON object with exactly these keys:

```json
{json.dumps(RESULT_SCHEMA, indent=2)}
```

Rules:
- viability_score is the conviction the engine ranks on — be calibrated, not generous.
- Claims labelled [SC]/[UK]/[AS] in the prompt cannot raise viability_score.
- If evidence quality is genuinely below "low", set final_decision = "reject".

---

{filled}
"""
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    brief_path = BRIEF_DIR / f"{symbol}.md"
    brief_path.write_text(brief)
    return brief_path


def main():
    parser = argparse.ArgumentParser(description="Prepare a research brief for the agent")
    parser.add_argument("--asset", required=True, help="Symbol, e.g. BTC")
    parser.add_argument("--dry-run", action="store_true", help="(accepted for pipeline parity; brief is always written)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print("Database not found. Run: python scripts/init_db.py", file=sys.stderr)
        sys.exit(1)

    brief_path = build_brief(args.asset)
    result_path = RESULT_DIR / f"{args.asset.upper()}.json"
    print(f"[research_prepare] brief written: {brief_path.relative_to(ROOT)}")
    print(f"[research_prepare] agent should write its analysis to: {result_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
