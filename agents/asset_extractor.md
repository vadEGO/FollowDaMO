# Asset Extractor

**Purpose:** Extract investable assets, tickers, themes, and trade ideas from raw content. All LLM output must be validated before any database write.

## Inputs
- New `raw_content` rows (collected today, not yet extracted)
- `prompts/extraction_prompt.md` — the extraction prompt template
- `config/assets.yaml` — known asset registry and ambiguous ticker list

## Outputs
- New rows in `asset_mentions` table (validated only)
- Items requiring human review → inserted into `resolution_queue`

## Workflow

### 1. Load unprocessed content
Query `raw_content` for rows that do not yet have corresponding `asset_mentions` records.

### 2. Pre-process content
For each content item:
- If source type is `youtube` comments or social comments: flag as `comment_source = true`
- Split content into chunks of max 2000 tokens to avoid context overflow
- For multi-part content, process each chunk separately and deduplicate results

### 3. Run extraction prompt
For each content chunk, call the LLM with `prompts/extraction_prompt.md`.
Replace `{{CONTENT}}` with the content chunk.

### 4. Validate LLM output — REQUIRED before any database write
Validate the returned JSON against the required schema:
- Must be a JSON array
- Each item must have: `raw_mention` (string), `confidence` (one of: high/medium/low), `needs_review` (boolean)
- `symbol` must match a known ticker in `config/assets.yaml` OR be null
- `confidence` must be categorical (high/medium/low) — reject float values
- If `source_type` is comments: cap confidence at "medium"
- If `symbol` matches an ambiguous ticker in `config/assets.yaml`: set `needs_review = true`

If validation fails: log the error with the raw LLM response. Do NOT write to `asset_mentions`. Insert into `resolution_queue` with `candidate_resolutions` = the raw response.

### 5. Store validated mentions
For each valid extraction:
- Insert into `asset_mentions` with `raw_llm_response` stored for audit
- Set `needs_review = true` for any item with confidence = "low" or an unresolved ambiguous ticker

### 6. Route ambiguous items
For items with `needs_review = true` or `symbol = null`:
- Insert into `resolution_queue` with context snippet and candidate resolutions
- These items will NOT flow to Signal Scorer until resolved

### 7. Log
Insert a row into `pipeline_runs` for this stage.

## Error handling
- Malformed JSON from LLM → log raw response, insert to resolution_queue, continue
- LLM timeout → retry once with a shorter chunk, then skip and log
- Database write error → log and halt this stage (do not continue with corrupted state)
