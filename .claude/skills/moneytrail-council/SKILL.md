---
name: moneytrail-council
description: "Run MoneyTrail's investment council on a topic or asset. Use when asked to convene the council, get the panel's view, deliberate a topic, or produce a multi-persona consensus (e.g. 'run the council on BTC', 'what does the council think about rate cuts'). You do the deliberation yourself — MoneyTrail does not call any LLM API."
---

# MoneyTrail Council

MoneyTrail's investment council is run by **you**, not an external API. You adopt
each persona, argue their genuine position, and synthesize a consensus. Python
only prepares the brief and validates/stores your answer to Supabase (the tables
the dashboard's /research page reads). Mirrors the `moneytrail-research` skill.

Run from the MoneyTrail repo root (`~/MoneyTrail`). The topic is free text
("Bitcoin liquidity through year-end") or a curated asset symbol (BTC, SOL, …),
in which case the asset's research pack is folded in as context.

## Steps

1. **Prepare the brief.**
   ```
   python scripts/council_prepare.py --topic "<TOPIC or SYMBOL>"
   ```
   Writes `knowledge/council_briefs/<SLUG>.md` (the panel definition + context +
   the exact result schema) and tells you the result path.

2. **Read the brief and deliberate.**
   Read `knowledge/council_briefs/<SLUG>.md` in full. The panel is defined in
   `config/council.yaml`: capitalcosm (macro/liquidity), pulse (momentum), flow
   (market structure), sentinel (risk/downside), professor_xiang (strategic
   systems), steward (portfolio fit for the operator).

   Adopt EACH persona in turn and argue their real position — do not collapse them
   into one voice. Disagreement is the point. Use your own tools (web search,
   fetched data, the asset context in the brief). Be calibrated: a genuinely split
   panel should yield medium confidence and real disagreements, not false
   consensus.

3. **Write your answer.**
   Write a single JSON object to `knowledge/council_results/<SLUG>.json` with
   exactly the keys in the brief's schema: topic, decision_state (one of the
   allowed list), confidence (0-1), consensus_view, recommended_next_step,
   agreements, disagreements, most_important_uncertainties,
   what_would_change_our_mind, personal_constraints_public, and a `personas` array
   (one entry per persona: thesis, supporting_evidence, counterpoints, risks,
   investment_implications, what_would_change_my_mind, confidence).

4. **Ingest.**
   ```
   python scripts/council_ingest.py --topic "<TOPIC or SYMBOL>"
   ```
   Validates your JSON and upserts to Supabase `council_runs` + `persona_positions`.
   On a validation error, fix the JSON file and re-run.

## Notes
- No `ANTHROPIC_API_KEY` is needed anywhere — you are the council.
- Idempotent: re-running a topic overwrites the same `moneytrail_<slug>` run, so
  it's safe to iterate.
- The slug is derived from the topic (lowercased, non-alphanumerics → `_`); pass
  the same `--topic` string to prepare and ingest so the paths match.
- Persona ids must match `config/council.yaml` so they line up with the existing
  belief register on the dashboard.
