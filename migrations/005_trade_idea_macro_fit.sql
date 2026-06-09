-- Migration 005: persist macro-fit scores for trade ideas
--
-- SUPABASE: Run this in the Supabase SQL editor (or via the MCP).
-- Produced by scripts/score_macro_fit.py --write — one row per idea, upserted each run.

CREATE TABLE IF NOT EXISTS rv_trade_idea_macro_fit (
  idea_id           TEXT PRIMARY KEY,
  symbol            TEXT,
  asset_class       TEXT,
  direction         TEXT,           -- long | short | unknown
  playbook_key      TEXT,           -- equities | crypto | fx | ...
  playbook_stance   TEXT,           -- up | down | neutral | unknown
  macro_fit_score   NUMERIC,        -- 0-100, 50 = neutral
  label             TEXT,           -- tailwind | neutral | headwind | unknown
  rationale         TEXT,
  regime_season     TEXT,           -- the active season this was scored against
  scored_at         TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE rv_trade_idea_macro_fit ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "public read" ON rv_trade_idea_macro_fit;
CREATE POLICY "public read" ON rv_trade_idea_macro_fit
  FOR SELECT USING (true);

-- Public view the dashboard reads (anon-granted, matches the public_* pattern).
CREATE OR REPLACE VIEW public_rv_trade_macro_fit AS
SELECT
  m.idea_id, m.symbol, m.asset_class, m.direction,
  m.playbook_key, m.playbook_stance, m.macro_fit_score,
  m.label, m.rationale, m.regime_season, m.scored_at
FROM rv_trade_idea_macro_fit m;

GRANT SELECT ON rv_trade_idea_macro_fit TO anon;
GRANT SELECT ON public_rv_trade_macro_fit TO anon;
