-- 009 — Portfolio guidance surface for the /portfolio page.
-- A broader proposal view (all actions with reasons, not just buys) + a
-- thesis-allocation table (current vs target per thesis) the pipeline syncs.

-- Full proposal — every ranked idea with its action + reason, so the page can
-- show holds/skips/blocks (and WHY), not only actionable buys.
CREATE OR REPLACE VIEW public_portfolio_proposal AS
SELECT symbol, thesis, direction, composite_score, action, target_pct, reason,
       heat_score, heat_level, proposed_at
FROM portfolio_allocations
ORDER BY
  CASE action
    WHEN 'enter_starter' THEN 1 WHEN 'add' THEN 2 WHEN 'hold' THEN 3
    WHEN 'blocked' THEN 4 ELSE 5 END,
  composite_score DESC NULLS LAST;

GRANT SELECT ON public_portfolio_proposal TO anon, authenticated;

-- Thesis allocation — current vs target/max budget per thesis + dry powder.
CREATE TABLE IF NOT EXISTS portfolio_thesis_allocation (
  thesis        text PRIMARY KEY,
  display_name  text,
  current_pct   numeric NOT NULL DEFAULT 0,
  target_pct    numeric NOT NULL DEFAULT 0,
  max_pct       numeric NOT NULL DEFAULT 0,
  headroom_pct  numeric NOT NULL DEFAULT 0,
  nav           numeric,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE portfolio_thesis_allocation ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon read thesis allocation" ON portfolio_thesis_allocation;
CREATE POLICY "anon read thesis allocation" ON portfolio_thesis_allocation
  FOR SELECT TO anon, authenticated USING (true);

CREATE OR REPLACE VIEW public_thesis_allocation AS
SELECT thesis, display_name, current_pct, target_pct, max_pct, headroom_pct, nav, updated_at
FROM portfolio_thesis_allocation
ORDER BY target_pct DESC;

GRANT SELECT ON public_thesis_allocation TO anon, authenticated;
