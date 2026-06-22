-- Migration 008: add the liquidity axis to macro-fit rows
--
-- SUPABASE: Run this in the Supabase SQL editor (or via the MCP).
-- score_macro_fit.py --write now also upserts liquidity_regime + liquidity_tilt
-- (the signed liquidity contribution to macro_fit_score). PostgREST rejects
-- unknown columns, so these must exist before the next --write run.

ALTER TABLE rv_trade_idea_macro_fit
  ADD COLUMN IF NOT EXISTS liquidity_regime TEXT,   -- expanding | contracting | neutral | (unset)
  ADD COLUMN IF NOT EXISTS liquidity_tilt   NUMERIC DEFAULT 0;  -- signed, part of macro_fit_score

-- Refresh the public view so the dashboard can surface the liquidity overlay.
-- DROP first: CREATE OR REPLACE can't insert columns into the middle of the list.
DROP VIEW IF EXISTS public_rv_trade_macro_fit;
CREATE VIEW public_rv_trade_macro_fit AS
SELECT
  m.idea_id, m.symbol, m.asset_class, m.direction,
  m.playbook_key, m.playbook_stance, m.macro_fit_score,
  m.label, m.rationale, m.regime_season,
  m.liquidity_regime, m.liquidity_tilt,
  m.scored_at
FROM rv_trade_idea_macro_fit m;

GRANT SELECT ON public_rv_trade_macro_fit TO anon;
