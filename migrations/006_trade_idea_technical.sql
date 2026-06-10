-- Migration 006: persist technical scores + a composite macro×technical view
--
-- SUPABASE: Run in the SQL editor (or via MCP).
-- Produced by scripts/score_technical.py --write. The composite view fuses the
-- macro-fit (migration 005) and technical scores so the dashboard can rank
-- ideas by a single blended conviction.

CREATE TABLE IF NOT EXISTS rv_trade_idea_technical (
  symbol            TEXT PRIMARY KEY,
  technical_score   NUMERIC,        -- 0-100, 50 = neutral
  label             TEXT,           -- strong | bullish | neutral | bearish | weak
  trend             TEXT,           -- up | down | mixed | n/a
  rsi               NUMERIC,
  price             NUMERIC,
  sma_fast          NUMERIC,
  sma_slow          NUMERIC,
  n_candles         INTEGER,
  rationale         TEXT,
  scored_at         TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE rv_trade_idea_technical ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "public read" ON rv_trade_idea_technical;
CREATE POLICY "public read" ON rv_trade_idea_technical FOR SELECT USING (true);
GRANT SELECT ON rv_trade_idea_technical TO anon;

-- Composite conviction: blend macro fit (by idea) with technical (by symbol).
-- macro_fit is keyed per idea_id; technical is keyed per symbol — join on symbol.
-- composite = 0.5*macro + 0.5*technical, falling back to whichever exists.
CREATE OR REPLACE VIEW public_rv_trade_composite AS
SELECT
  m.idea_id,
  m.symbol,
  m.asset_class,
  m.direction,
  m.macro_fit_score,
  m.label              AS macro_label,
  t.technical_score,
  t.label              AS technical_label,
  t.trend,
  t.rsi,
  CASE
    WHEN m.macro_fit_score IS NOT NULL AND t.technical_score IS NOT NULL
      THEN round((m.macro_fit_score + t.technical_score) / 2.0, 1)
    ELSE COALESCE(m.macro_fit_score, t.technical_score)
  END AS composite_score,
  m.regime_season,
  GREATEST(m.scored_at, COALESCE(t.scored_at, m.scored_at)) AS scored_at
FROM rv_trade_idea_macro_fit m
LEFT JOIN rv_trade_idea_technical t ON t.symbol = m.symbol;

GRANT SELECT ON public_rv_trade_composite TO anon;
