-- Migration 003: SEC 13F filing position tracking
--
-- quarter format: YYYY-QN e.g. "2026-Q1" — enforced by scrape_13f.py
-- shares/shares_change are REAL not INTEGER — API responses often return floats
-- UNIQUE(filer_slug, quarter, ticker) — safe to INSERT OR IGNORE on re-ingest
-- ticker is nullable — delisted stocks may have no ticker (use cusip instead)
-- change_type values: new | increased | decreased | exited | unchanged | gap_unknown
--   gap_unknown = consecutive quarters not detected; diff may be misleading
-- last_raw_snapshot: JSON blob of full holdings list for last_quarter
--   stored so we can recompute diffs locally if WhaleWisdom amended-filing diffs are wrong
-- consecutive_failures: reset to 0 on success; after N failures flag source as degraded

BEGIN;

CREATE TABLE IF NOT EXISTS sec_13f_positions (
  id                   TEXT PRIMARY KEY,      -- uuid4
  filer_slug           TEXT NOT NULL,
  filer_name           TEXT,
  quarter              TEXT NOT NULL,         -- YYYY-QN format
  ticker               TEXT,                  -- nullable: delisted stocks have no ticker
  cusip                TEXT,
  company_name         TEXT,
  shares               REAL,                  -- float-safe
  market_value_usd     REAL,
  portfolio_pct        REAL,
  shares_change        REAL,                  -- NULL = first quarter held (new position)
  change_type          TEXT,
  sector               TEXT,
  industry             TEXT,
  avg_price            REAL,
  quarter_first_owned  TEXT,
  scraped_at           TEXT NOT NULL,
  UNIQUE(filer_slug, quarter, ticker)
);

CREATE INDEX IF NOT EXISTS idx_13f_filer_quarter
  ON sec_13f_positions(filer_slug, quarter);

CREATE INDEX IF NOT EXISTS idx_13f_ticker
  ON sec_13f_positions(ticker);

CREATE TABLE IF NOT EXISTS sec_13f_scrape_state (
  filer_slug           TEXT PRIMARY KEY,
  filer_name           TEXT,
  filer_cik            TEXT,                  -- SEC CIK number, auto-discovered
  last_quarter         TEXT,                  -- YYYY-QN of last successfully scraped filing
  last_raw_snapshot    TEXT,                  -- JSON: full positions list for last_quarter
  last_scraped_at      TEXT,
  position_count       INTEGER,
  last_error           TEXT,
  consecutive_failures INTEGER DEFAULT 0
);

INSERT OR IGNORE INTO schema_version (version, applied_at)
VALUES (3, datetime('now'));

COMMIT;
