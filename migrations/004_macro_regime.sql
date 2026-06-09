-- Migration 004: Macro regime table + thesis placeholder flag
--
-- SUPABASE: Run this in the Supabase SQL editor.
-- SQLITE:   The ALTER TABLE line for asset_thesis_scores is handled automatically
--           by update_thesis_memory.py on first run.

-- ── Supabase: macro regime (single-row pattern, id='current') ──────────────

CREATE TABLE IF NOT EXISTS macro_regime (
  id TEXT PRIMARY KEY DEFAULT 'current',
  active_season TEXT,          -- spring | summer | fall | winter
  active_phase TEXT,           -- rec | exp | slo | con
  season_conviction TEXT,      -- low | medium | high
  phase_conviction TEXT,       -- low | medium | high
  season_notes TEXT,
  phase_notes TEXT,
  country_phases JSONB,        -- {country_key: phase_code}
  last_updated TEXT,
  updated_by TEXT
);

ALTER TABLE macro_regime ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read" ON macro_regime
  FOR SELECT USING (true);

-- ── Supabase: ensure dashboard_snapshots has thesis_board column ───────────
-- (This column already exists if Phase 1 SQL was run. Included defensively.)

ALTER TABLE dashboard_snapshots
  ADD COLUMN IF NOT EXISTS thesis_board JSONB;

-- ── SQLite note ────────────────────────────────────────────────────────────
-- The is_placeholder column on asset_thesis_scores is added automatically
-- by update_thesis_memory.py (it checks PRAGMA table_info before adding).
-- If you want to add it manually:
--
--   ALTER TABLE asset_thesis_scores ADD COLUMN is_placeholder INTEGER NOT NULL DEFAULT 1;
