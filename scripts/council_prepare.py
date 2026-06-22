#!/usr/bin/env python3
"""
Council, step 1 of 3 — PREPARE.

Builds a self-contained deliberation brief for one topic and writes it to disk.
No LLM call, no network: it only gathers the panel definition + context. The
agent (Claude Code, via the moneytrail-council skill) reads the brief, runs the
deliberation as each persona, synthesizes a consensus, and writes a result file;
council_ingest.py then validates + stores it to Supabase.

Topic can be free text ("Bitcoin liquidity through year-end") or a curated asset
symbol — if it matches config/assets.yaml, the asset's research pack is folded in
as context so the council reasons from the same evidence as the funnel.

Outputs:
    knowledge/council_briefs/<SLUG>.md      — panel + context + required schema
    (the agent writes its answer to knowledge/council_results/<SLUG>.json)

Usage:
    python scripts/council_prepare.py --topic "Bitcoin liquidity through year-end"
    python scripts/council_prepare.py --topic BTC      # asset topic — folds in research
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"
COUNCIL_YAML = ROOT / "config" / "council.yaml"
ASSETS_YAML = ROOT / "config" / "assets.yaml"
BRIEF_DIR = ROOT / "knowledge" / "council_briefs"
RESULT_DIR = ROOT / "knowledge" / "council_results"


def slugify(topic: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    return s[:60] or "topic"


def _load_council() -> dict:
    try:
        import yaml
        return yaml.safe_load(COUNCIL_YAML.read_text()) or {}
    except Exception as e:
        print(f"[council_prepare] could not read config/council.yaml: {e}", file=sys.stderr)
        return {"personas": [], "decision_states": []}


def _asset_context(topic: str) -> str:
    """If the topic is a curated symbol, fold in its research pack so the council
    reasons from the same evidence as the funnel. Returns '' for free-text topics."""
    sym = topic.strip().upper()
    try:
        import yaml
        assets = yaml.safe_load(ASSETS_YAML.read_text()) or {}
    except Exception:
        assets = {}
    known = {str(r.get("symbol", "")).upper()
             for grp in assets.values() if isinstance(grp, list)
             for r in grp if isinstance(r, dict)}
    if sym not in known or not DB_PATH.exists():
        return ""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM research_packs WHERE UPPER(symbol) = ? ORDER BY created_at DESC LIMIT 1",
        (sym,),
    ).fetchone()
    conn.close()
    if not row:
        return f"\n## Asset context\n{sym} is in the curated universe but has no research pack yet."
    r = dict(row)
    return (
        f"\n## Asset context — {sym} (latest research pack)\n"
        f"- Viability: {r.get('viability_score')}  Thesis fit: {r.get('thesis_fit_score')}  "
        f"Decision: {r.get('final_decision')}\n"
        f"- Bull: {r.get('bull_case')}\n- Bear: {r.get('bear_case')}\n"
        f"- Risks: {r.get('risks')}\n- Unknowns: {r.get('unknowns')}\n"
    )


# The exact JSON the agent must produce. council_ingest.py validates against this.
RESULT_SCHEMA = {
    "topic": "string — the topic deliberated",
    "decision_state": "one of the decision_states listed in the panel section",
    "confidence": "number 0-1 (panel's overall confidence in the consensus)",
    "consensus_view": "string — 2-4 sentence synthesized view",
    "recommended_next_step": "string — the single most useful next action",
    "agreements": ["points the panel agrees on"],
    "disagreements": ["points the panel splits on"],
    "most_important_uncertainties": ["the uncertainties that matter most"],
    "what_would_change_our_mind": ["concrete conditions that would flip the view"],
    "personal_constraints_public": ["operator constraints worth stating publicly"],
    "personas": [
        {
            "persona": "persona id (one of the panel ids)",
            "thesis": "that persona's position, 2-4 sentences in their voice",
            "supporting_evidence": ["..."],
            "counterpoints": ["..."],
            "risks": ["..."],
            "investment_implications": "string",
            "what_would_change_my_mind": ["..."],
            "confidence": "number 0-1",
        }
    ],
}


def build_brief(topic: str) -> Path:
    council = _load_council()
    personas = council.get("personas", [])
    states = council.get("decision_states", [])
    slug = slugify(topic)

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = RESULT_DIR / f"{slug}.json"

    panel_lines = "\n".join(
        f"- **{p['id']}** ({p.get('name', p['id'])}): {p.get('lens', '').strip()}"
        for p in personas
    )
    states_line = " | ".join(states)
    asset_ctx = _asset_context(topic)

    brief = f"""# MoneyTrail council brief — {topic}

You are running MoneyTrail's investment council yourself (no external API is
called). Deliberate this topic as the standing panel, then synthesize a
consensus. Write your structured answer to:

    {result_path}

## The panel
Adopt each persona in turn and argue their genuine position — do not collapse
them into one voice. Disagreement is the point.

{panel_lines}

Allowed `decision_state` values: {states_line}
{asset_ctx}
## Your task
1. For EACH persona above, write a position in their voice: thesis, supporting
   evidence, counterpoints, risks, investment implications, what would change
   their mind, and a 0-1 confidence.
2. Synthesize the consensus: the decision_state, a 2-4 sentence consensus_view,
   the agreements and the genuine disagreements, the uncertainties that matter
   most, what would change the panel's mind, and any operator constraints.
3. Be calibrated. A split panel should produce medium confidence and real
   disagreements — do not manufacture false consensus.

## Output
Write a single JSON object to the path above with exactly these keys:

```json
{json.dumps(RESULT_SCHEMA, indent=2)}
```
"""
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    brief_path = BRIEF_DIR / f"{slug}.md"
    brief_path.write_text(brief)
    return brief_path


def main():
    parser = argparse.ArgumentParser(description="Prepare a council deliberation brief for the agent")
    parser.add_argument("--topic", required=True, help="Topic or asset symbol to deliberate")
    parser.add_argument("--dry-run", action="store_true", help="(accepted for parity; brief is always written)")
    args = parser.parse_args()

    brief_path = build_brief(args.topic)
    slug = slugify(args.topic)
    print(f"[council_prepare] brief written: {brief_path.relative_to(ROOT)}")
    print(f"[council_prepare] agent should write its deliberation to: "
          f"{(RESULT_DIR / f'{slug}.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
