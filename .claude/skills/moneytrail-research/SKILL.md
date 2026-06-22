---
name: moneytrail-research
description: "Run MoneyTrail's investment research for one asset. Use when asked to research an asset, generate a research pack, or produce the conviction/viability score that feeds the opportunity funnel (e.g. 'research BTC', 'run MoneyTrail research for SOL'). You do the analysis yourself — MoneyTrail does not call any LLM API."
---

# MoneyTrail Research

MoneyTrail's research pass is done by **you**, not an external API. You produce the
bull/bear/risk analysis and a calibrated `viability_score` (the conviction the
opportunity funnel ranks on). Python only prepares the brief and validates/stores
your answer.

Run from the MoneyTrail repo root (`~/MoneyTrail`). The asset symbol comes from
the user (e.g. BTC, SOL, NVDA) — it must be in `config/assets.yaml`.

## Steps

1. **Prepare the brief.**
   ```
   python scripts/research_prepare.py --asset <SYMBOL>
   ```
   This writes `knowledge/research_briefs/<SYMBOL>.md` (the research prompt +
   the social-signal context + the exact result schema) and tells you the result
   path.

2. **Read the brief and do the analysis.**
   Read `knowledge/research_briefs/<SYMBOL>.md` in full. Work through every section
   of the research prompt — independent assessment, bull/bear, pre-mortem, risks,
   thesis fit, entry quality, viability. Use your own tools (web search, fetched
   data, reasoning). Do NOT just restate the social thesis; assess the asset on its
   own merits.

   Be calibrated, not generous: `viability_score` drives whether the idea becomes
   actionable. Honour the evidence-labelling rules — claims you can't verify ([SC],
   [UK], [AS]) cannot raise the score. If evidence quality is genuinely below "low",
   set `final_decision` to `reject`.

3. **Write your answer.**
   Write a single JSON object to `knowledge/research_results/<SYMBOL>.json` with
   exactly the keys listed in the brief's schema block (bull_case, bear_case, risks,
   unknowns, research_summary, evidence_quality, evidence_quality_score,
   viability_score, thesis_fit_score, portfolio_fit_score, final_decision).

4. **Ingest.**
   ```
   python scripts/research_ingest.py --asset <SYMBOL>
   ```
   This validates your JSON and writes the row to `research_packs`. If it reports a
   validation error, fix the JSON file and re-run.

5. **(Optional) Build the opportunity row.**
   To take the asset all the way through the funnel and land it on the dashboard:
   ```
   python scripts/build_opportunity.py --asset <SYMBOL>
   ```
   This blends your viability score with macro-fit + technical into the composite,
   gates the lifecycle state, derives the entry/exit plan, and upserts one row to
   Supabase `investment_opportunities` (source='moneytrail').

## Notes
- No `ANTHROPIC_API_KEY` is needed anywhere — you are the analyst.
- The result file is idempotent: re-running overwrites the same `research_<SYMBOL>`
  row, so it's safe to iterate.
- The whole single-asset slice can also be driven by the agent end-to-end:
  prepare → (you analyse + write JSON) → ingest → build_opportunity.
