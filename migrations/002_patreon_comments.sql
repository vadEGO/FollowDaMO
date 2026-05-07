-- Migration 002: Patreon comment tracking
-- Adds per-post comment scrape state and individual comment storage.
-- Comments are scraped for posts from the last N days (configurable via sources.yaml).

PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

-- Track when each post's comments were last scraped so we don't re-scrape stale posts
CREATE TABLE IF NOT EXISTS patreon_scrape_state (
  post_url        TEXT PRIMARY KEY,
  source_name     TEXT NOT NULL,
  post_title      TEXT,
  comments_last_scraped_at TEXT,     -- ISO-8601 UTC
  comment_count   INTEGER DEFAULT 0
);

-- Individual comments, deduplicated by content hash
CREATE TABLE IF NOT EXISTS patreon_comments (
  id              TEXT PRIMARY KEY,
  post_url        TEXT NOT NULL,
  source_name     TEXT NOT NULL,
  author          TEXT,
  comment_text    TEXT NOT NULL,
  published_at    TEXT,              -- ISO-8601 UTC, NULL if not parseable
  content_hash    TEXT UNIQUE NOT NULL,
  scraped_at      TEXT NOT NULL,     -- ISO-8601 UTC
  FOREIGN KEY (post_url) REFERENCES patreon_scrape_state(post_url)
);

CREATE INDEX IF NOT EXISTS idx_patreon_comments_post_url  ON patreon_comments(post_url);
CREATE INDEX IF NOT EXISTS idx_patreon_comments_scraped   ON patreon_comments(scraped_at);
CREATE INDEX IF NOT EXISTS idx_patreon_state_source       ON patreon_scrape_state(source_name);

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
  VALUES (2, datetime('now'), 'Patreon comment tracking — patreon_scrape_state + patreon_comments');
