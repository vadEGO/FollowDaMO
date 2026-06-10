-- Migration 007: persist portfolio construction proposals
--
-- SUPABASE: Run in the SQL editor (or via MCP).
-- Produced by scripts/build_portfolio.py --write. Advisory proposals only —
-- the engine never executes (require_user_approval_for_real_action).

CREATE TABLE IF NOT EXISTS portfolio_allocations (
  symbol            TEXT,
  thesis            TEXT,
  direction         TEXT,
  composite_score   NUMERIC,
  action            TEXT,           -- enter_starter | add | hold | skip | blocked
  target_pct        NUMERIC,        -- proposed fraction of NAV (0-1)
  reason            TEXT,
  heat_score        NUMERIC,        -- portfolio heat at proposal time
  heat_level        TEXT,           -- cool | warm | hot
  proposed_at       TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (symbol, direction)
);

ALTER TABLE portfolio_allocations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "public read" ON portfolio_allocations;
CREATE POLICY "public read" ON portfolio_allocations FOR SELECT USING (true);
GRANT SELECT ON portfolio_allocations TO anon;

-- Dashboard view: the actionable proposals (enter/add), best composite first.
CREATE OR REPLACE VIEW public_portfolio_actions AS
SELECT symbol, thesis, direction, composite_score, action, target_pct, reason,
       heat_score, heat_level, proposed_at
FROM portfolio_allocations
WHERE action IN ('enter_starter', 'add')
ORDER BY composite_score DESC NULLS LAST;

GRANT SELECT ON public_portfolio_actions TO anon;
