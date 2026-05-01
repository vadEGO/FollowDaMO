# Source Accountability Tracker Agent

**Purpose:** Measure whether each source's past signals actually led to good outcomes. Run weekly.

## Inputs
- `source_scores` — current credibility weights
- `model_decision_outcomes` — outcomes for past decisions
- `asset_mentions` — historical mentions with source links
- `price_history` — price data for measuring post-mention performance

## Outputs
- Updated `source_scores.historical_accuracy`
- Weekly source report section in `knowledge/weekly_memos/`

## Metrics per source
- Assets mentioned (last 90 days)
- Mention date → price at mention → price at 30/90 days
- Hit rate (positive return at 90 days)
- Max drawdown after mention
- Hype tendency (were mentions clustered at cycle tops?)
- Late-cycle tendency

## Workflow

### 1. Find decisions that are now aged 30/90 days
Query `model_decision_outcomes` where `decision_date` was 30 or 90 days ago and `price_30d` or `price_90d` is still null.

### 2. Fetch current prices
For each open outcome, fetch current price from `price_history`. Update `price_30d` or `price_90d`.

### 3. Compute per-source metrics
For each source, aggregate outcomes for all assets they originally mentioned.

### 4. Update source scores
Update `source_scores.historical_accuracy` based on trailing 90-day hit rate.

### 5. Write report
Add source performance section to the weekly memo.

### 6. Log
Insert a row into `pipeline_runs` for this stage.
