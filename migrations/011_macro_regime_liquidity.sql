-- Migration 011: add the liquidity axis to the macro_regime table.
--
-- update_macro_regime.py writes liquidity_regime / liquidity_conviction /
-- liquidity_notes into data/macro_regime.json, and sync_to_supabase.py upserts
-- the whole object into macro_regime. Those columns were added to
-- rv_trade_idea_macro_fit in migration 008 but never to macro_regime itself, so
-- PostgREST rejected the upsert (PGRST204: could not find 'liquidity_conviction').
-- Add the three columns so the regime row syncs cleanly.

ALTER TABLE macro_regime
  ADD COLUMN IF NOT EXISTS liquidity_regime     TEXT,   -- expanding | contracting | neutral
  ADD COLUMN IF NOT EXISTS liquidity_conviction TEXT,   -- low | medium | high
  ADD COLUMN IF NOT EXISTS liquidity_notes      TEXT;
