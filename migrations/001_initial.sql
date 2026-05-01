-- Migration 001: Initial schema
-- All 16 core tables + 3 additions from autoplan review

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  description TEXT
);

-- Pipeline run tracking (enables restartability)
CREATE TABLE IF NOT EXISTS pipeline_runs (
  id TEXT PRIMARY KEY,
  run_date TEXT NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,      -- running | completed | failed | skipped
  started_at TEXT,
  completed_at TEXT,
  records_processed INTEGER DEFAULT 0,
  error TEXT
);

CREATE TABLE IF NOT EXISTS raw_content (
  id TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  title TEXT,
  author TEXT,
  url TEXT,
  published_at TEXT,
  collected_at TEXT NOT NULL,
  content_hash TEXT UNIQUE,
  raw_text TEXT
);

CREATE TABLE IF NOT EXISTS asset_mentions (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL REFERENCES raw_content(id),
  raw_mention TEXT NOT NULL,
  resolved_asset TEXT,
  symbol TEXT,
  asset_type TEXT,
  confidence TEXT NOT NULL DEFAULT 'low',   -- high | medium | low (not float)
  context_snippet TEXT,
  sentiment TEXT,
  intent TEXT,
  time_horizon TEXT,
  conviction_score REAL,
  needs_review INTEGER NOT NULL DEFAULT 0,
  raw_llm_response TEXT,                    -- full LLM output for audit
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resolution_queue (
  id TEXT PRIMARY KEY,
  raw_mention TEXT NOT NULL,
  candidate_resolutions TEXT,               -- JSON array of candidates
  context_snippet TEXT,
  source_name TEXT,
  created_at TEXT NOT NULL,
  resolved_by TEXT,                         -- 'user' | 'system' | null
  resolution TEXT,                          -- accepted symbol
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS asset_signals (
  id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_type TEXT,
  first_seen TEXT,
  last_seen TEXT,
  mention_count INTEGER DEFAULT 0,
  source_count INTEGER DEFAULT 0,
  average_sentiment REAL,
  signal_score REAL,
  score_audit TEXT,                         -- JSON breakdown of score components
  crowding_score REAL,
  research_priority TEXT,
  status TEXT
);

CREATE TABLE IF NOT EXISTS venue_assets (
  id TEXT PRIMARY KEY,
  venue TEXT NOT NULL,
  market_type TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_id INTEGER,
  base_asset TEXT,
  quote_asset TEXT,
  is_listed INTEGER DEFAULT 0,
  is_tradeable INTEGER DEFAULT 0,
  min_size REAL,
  sz_decimals INTEGER,
  max_leverage REAL,
  margin_table_id INTEGER,
  last_price REAL,
  volume_24h REAL,
  open_interest REAL,
  funding_rate REAL,
  liquidity_score REAL,
  last_checked TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_tradeability (
  id TEXT PRIMARY KEY,
  extracted_asset TEXT NOT NULL,
  resolved_asset TEXT,
  venue TEXT NOT NULL,
  direct_match INTEGER DEFAULT 0,
  proxy_match INTEGER DEFAULT 0,
  proxy_asset TEXT,
  region_allowed INTEGER DEFAULT 0,
  venue_available INTEGER DEFAULT 0,
  liquidity_ok INTEGER DEFAULT 0,
  trade_allowed INTEGER DEFAULT 0,
  research_mode TEXT,
  reason TEXT,
  checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_packs (
  id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  symbol TEXT NOT NULL,
  asset_type TEXT,
  created_at TEXT NOT NULL,
  research_level INTEGER DEFAULT 0,
  research_summary TEXT,
  bull_case TEXT,
  bear_case TEXT,
  risks TEXT,
  unknowns TEXT,
  evidence_quality_score REAL,
  viability_score REAL,
  thesis_fit_score REAL,
  portfolio_fit_score REAL,
  final_decision TEXT,
  markdown_path TEXT
);

CREATE TABLE IF NOT EXISTS asset_thesis_scores (
  id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  thesis TEXT NOT NULL,                     -- scarce_assets | ai_growth | crypto_beta | tactical_satellite
  score REAL NOT NULL DEFAULT 0,
  primary_thesis INTEGER NOT NULL DEFAULT 0, -- 1 = this is the primary thesis for this asset
  portfolio_role TEXT,
  best_expression_rank INTEGER,
  lifecycle_stage TEXT,
  conviction_score REAL,
  invalidation_conditions TEXT,             -- JSON array of structured conditions
  add_conditions TEXT,
  trim_conditions TEXT,
  last_reviewed TEXT,
  version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS lilo_profiles (
  id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  position_role TEXT NOT NULL,              -- part of key: same asset can have multiple roles
  asset_type TEXT,
  conviction TEXT,
  volatility TEXT,
  trend_view TEXT,
  strategy_mode TEXT,
  core_percentage REAL,
  tactical_percentage REAL,
  speculative_percentage REAL,
  aggression_level TEXT,
  layer_out_count INTEGER DEFAULT 0,
  layer_in_count INTEGER DEFAULT 0,
  tax_sensitivity TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS position_plans (
  id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  venue TEXT NOT NULL,
  market_type TEXT,
  position_role TEXT,
  time_horizon TEXT,
  entry_type TEXT,
  entry_min REAL,
  entry_max REAL,
  stop_type TEXT,
  stop_price REAL,
  thesis_invalidation TEXT,
  risk_per_position_pct REAL,
  max_position_size_pct REAL,
  take_profit_plan TEXT,
  reentry_plan TEXT,
  risk_reward REAL,
  friction_adjusted_ev REAL,
  status TEXT DEFAULT 'draft',
  created_at TEXT NOT NULL,
  expires_at TEXT
);

CREATE TABLE IF NOT EXISTS take_profit_layers (
  id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL REFERENCES position_plans(id) ON DELETE CASCADE,
  asset TEXT NOT NULL,
  layer_number INTEGER NOT NULL,
  target_price REAL NOT NULL,
  sell_percentage REAL NOT NULL,
  reason TEXT,
  status TEXT DEFAULT 'pending',
  triggered_at TEXT
);

CREATE TABLE IF NOT EXISTS shadow_portfolios (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  strategy_type TEXT,
  created_at TEXT NOT NULL,
  is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS shadow_positions (
  id TEXT PRIMARY KEY,
  portfolio_id TEXT NOT NULL REFERENCES shadow_portfolios(id),
  asset TEXT NOT NULL,
  asset_type TEXT,
  entry_date TEXT NOT NULL,
  entry_price REAL NOT NULL,
  allocation_pct REAL,
  quantity REAL,
  thesis TEXT,
  entry_reason TEXT,
  status TEXT DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS price_history (
  id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  date TEXT NOT NULL,
  close_price REAL NOT NULL,
  volume REAL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  UNIQUE(asset, date, source)
);

CREATE TABLE IF NOT EXISTS real_positions (
  id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  venue TEXT,
  asset_type TEXT,
  quantity REAL NOT NULL,
  cost_basis REAL,
  current_price REAL,
  currency TEXT DEFAULT 'USD',
  position_role TEXT,
  primary_thesis TEXT,
  notes TEXT,
  last_updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS simulation_results (
  id TEXT PRIMARY KEY,
  portfolio_id TEXT NOT NULL REFERENCES shadow_portfolios(id),
  run_date TEXT NOT NULL,
  total_return REAL,
  cagr REAL,
  volatility REAL,
  max_drawdown REAL,
  sharpe_like REAL,
  turnover REAL,
  portfolio_score REAL,
  period_start TEXT,
  period_end TEXT
);

CREATE TABLE IF NOT EXISTS rotation_candidates (
  id TEXT PRIMARY KEY,
  from_asset TEXT NOT NULL,
  to_asset TEXT NOT NULL,
  reason TEXT,
  score_improvement REAL,
  tax_friction_estimate REAL,
  conviction_delta REAL,
  status TEXT DEFAULT 'pending',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_decision_outcomes (
  id TEXT PRIMARY KEY,
  asset TEXT NOT NULL,
  initial_decision TEXT NOT NULL,
  decision_date TEXT NOT NULL,
  entry_price REAL,
  price_7d REAL,
  price_30d REAL,
  price_90d REAL,
  max_drawdown_90d REAL,
  outcome_score REAL
);

CREATE TABLE IF NOT EXISTS source_scores (
  source_name TEXT PRIMARY KEY,
  source_type TEXT,
  base_credibility REAL DEFAULT 0.5,
  historical_accuracy REAL,
  signal_weight REAL DEFAULT 0.5,
  hype_tendency REAL DEFAULT 0.5,
  late_cycle_tendency REAL DEFAULT 0.5,
  notes TEXT
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_asset_mentions_symbol ON asset_mentions(symbol);
CREATE INDEX IF NOT EXISTS idx_asset_mentions_content_id ON asset_mentions(content_id);
CREATE INDEX IF NOT EXISTS idx_asset_mentions_created ON asset_mentions(created_at);
CREATE INDEX IF NOT EXISTS idx_asset_signals_symbol ON asset_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_venue_assets_symbol_venue ON venue_assets(symbol, venue);
CREATE INDEX IF NOT EXISTS idx_price_history_asset_date ON price_history(asset, date);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_date ON pipeline_runs(run_date);

-- Seed default shadow portfolios
INSERT OR IGNORE INTO shadow_portfolios (id, name, description, strategy_type, created_at) VALUES
  ('sp_current',    'Current Portfolio',       'Mirror of real holdings',          'mirror',     datetime('now')),
  ('sp_best_ideas', 'MoneyTrail Best Ideas',   'Top-scored candidates only',       'best_ideas', datetime('now')),
  ('sp_scarce',     'Scarce Assets',           'Pure scarce assets thesis',        'thesis',     datetime('now')),
  ('sp_ai',         'AI Growth',               'Pure AI growth thesis',            'thesis',     datetime('now')),
  ('sp_blend',      'AI + Scarce Blend',       'Blended thesis allocation',        'blend',      datetime('now')),
  ('sp_balanced',   '33/33/33 Balanced',       'Equal split across three themes',  'balanced',   datetime('now')),
  ('sp_lilo',       'LILO Managed',            'Layer-in / layer-out managed',     'lilo',       datetime('now')),
  ('sp_aggressive', 'Aggressive Rotation',     'High-conviction rotation strategy','rotation',   datetime('now')),
  ('sp_conserv',    'Conservative Rotation',   'Low-turnover conservative',        'rotation',   datetime('now')),
  ('sp_bench',      'No-Rotation Benchmark',   'Buy and hold benchmark',           'benchmark',  datetime('now'));

-- Seed default source scores
INSERT OR IGNORE INTO source_scores (source_name, source_type, base_credibility, signal_weight, hype_tendency) VALUES
  ('investanswers_patreon', 'patreon',   0.85, 0.85, 0.30),
  ('realvision_patreon',    'patreon',   0.80, 0.80, 0.25),
  ('jordi_visser_substack', 'rss',       0.80, 0.80, 0.20),
  ('youtube_transcripts',   'youtube',   0.70, 0.70, 0.35),
  ('local_drop',            'local',     0.70, 0.70, 0.20);

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
  VALUES (1, datetime('now'), 'Initial schema — all 16 core tables + price_history + real_positions + resolution_queue + pipeline_runs');
