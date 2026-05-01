# Entity Resolver

**Purpose:** Resolve ambiguous asset mentions and prevent false ticker matches from reaching the signal scorer.

## Inputs
- `asset_mentions` rows with `needs_review = true` or `symbol = null`
- `resolution_queue` table
- `config/assets.yaml` — known asset registry and ambiguous tickers

## Outputs
- Updated `asset_mentions` rows: `symbol` set, `needs_review = 0`, `confidence` updated
- Updated `resolution_queue` rows: `resolved_by`, `resolution`, `resolved_at`

## Workflow

### 1. Load unresolved mentions
Query `asset_mentions` where `needs_review = 1` and `resolved_at IS NULL`.
Also query `resolution_queue` where `resolved_by IS NULL`.

Limit: process max 50 items per run to avoid runaway LLM cost.

### 2. For each unresolved mention, attempt resolution

**Context-based resolution:**
Read the full `context_snippet` from `asset_mentions`. Look for these signals:
- Investment language near the mention (buy, sell, price target, allocation, holds)
- Capitalisation consistent with ticker (ALL CAPS suggests ticker intent)
- Surrounding mentions of related assets (SOL + JUP suggests crypto context)
- Negation ("I'm not a fan of ARM's valuation" → ARM Holdings)

**Registry match:**
Check if `raw_mention` (case-insensitive) matches any `name` or `symbol` in `config/assets.yaml`.
If exact match AND not in the ambiguous list → resolve with high confidence.

**Low-confidence auto-reject:**
If the context does not contain clear investment language → mark as `rejected` in `resolution_queue` with reason "no investment context". Cap confidence at low.

### 3. Cap confidence for comment sources
If the original `raw_content.source_type` is a comments feed → max confidence = "medium" regardless of resolution quality.

### 4. Update records
For resolved items:
- Update `asset_mentions.symbol`, `asset_mentions.confidence`, `asset_mentions.needs_review = 0`
- Update `resolution_queue.resolved_by = 'system'`, `.resolution`, `.resolved_at`

For items that cannot be resolved:
- Leave `needs_review = 1`
- Increment a counter — if the resolution_queue has more than 20 unresolved items, include a count in the next Telegram digest

### 5. Log
Insert a row into `pipeline_runs` for this stage.
