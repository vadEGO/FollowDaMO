# Source Collector

**Purpose:** Collect raw content from all enabled sources in `config/sources.yaml` and store in the Raw Content Vault.

## Inputs
- `config/sources.yaml` — list of enabled sources
- `secrets/.env` — credentials for authenticated sources
- `data/moneytrail.sqlite` — check content_hash for deduplication

## Outputs
- New rows in `raw_content` table
- Files saved to `knowledge/raw/{source_name}/{date}/{content_id}.md`
- Log entry in `pipeline_runs` for this stage

## Workflow

### 1. Load enabled sources
Read `config/sources.yaml`. Filter to `enabled: true` sources only.

### 2. For each source, collect content

**local_folder:** Scan the configured path for `.md`, `.txt`, `.pdf` files added since last run. Read each file's text.

**patreon:** Use the Patreon scraper (see `scripts/scrape_patreon.py`). Load browser cookies from the path in `PATREON_COOKIES_FILE`. Navigate to the creator's Patreon page. Extract the latest posts (up to `max_posts_per_run`). Extract title, author, published date, full text.

**youtube:** For each channel or playlist ID, fetch new video IDs since last run. Use `youtube-transcript-api` to get the transcript. Combine title + transcript as raw text.

**rss:** Fetch the RSS feed URL. Parse entries published since last run. Extract title + description/content.

### 3. Deduplicate
For each collected item, compute SHA-256 hash of the raw text. Check against `raw_content.content_hash`. Skip items that already exist.

### 4. Store
For each new item:
- Insert a row into `raw_content`
- Save a copy to `knowledge/raw/{source_name}/{YYYY-MM-DD}/{content_id}.md`

### 5. Log
Insert a row into `pipeline_runs`: stage = `source_collector`, status = `completed`, records_processed = N.

## Error handling
- If a source fails (network error, auth failure, timeout): log the error in `pipeline_runs` with status = `failed`. Continue with remaining sources. Do NOT halt the entire pipeline.
- If credentials are missing: mark source as `skipped` with reason. Send a Telegram alert if `control_policy.yaml` has `telegram_on_failure: true`.
- Never silently skip a source — always write a status record.
