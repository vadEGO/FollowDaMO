# Signal Scorer

**Purpose:** Score the quality of each asset signal before research is triggered. Uses a JOIN-based query to avoid N+1 database calls.

## Inputs
- `asset_mentions` with `needs_review = 0`
- `source_scores` table — credibility weights per source
- `raw_content` — source metadata
- `config/scoring.yaml` — weights and thresholds

## Outputs
- Updated or new rows in `asset_signals` with `signal_score`, `crowding_score`, `research_priority`, `score_audit`

## Workflow

### 1. Aggregate mentions per asset (single JOIN query)
```sql
SELECT
    am.symbol,
    am.asset_type,
    COUNT(*) as mention_count,
    COUNT(DISTINCT rc.source_name) as source_count,
    AVG(CASE am.sentiment
        WHEN 'bullish' THEN 1.0
        WHEN 'mixed' THEN 0.5
        WHEN 'neutral' THEN 0.0
        WHEN 'bearish' THEN -1.0
        ELSE 0.0 END) as avg_sentiment,
    AVG(CASE am.intent
        WHEN 'buy' THEN 1.0
        WHEN 'hold' THEN 0.7
        WHEN 'watch' THEN 0.4
        WHEN 'trim' THEN 0.2
        WHEN 'sell' THEN 0.0
        ELSE 0.3 END) as avg_intent,
    AVG(COALESCE(ss.signal_weight, 0.5)) as avg_source_quality,
    AVG(CASE am.confidence
        WHEN 'high' THEN 1.0
        WHEN 'medium' THEN 0.5
        WHEN 'low' THEN 0.2
        ELSE 0.2 END) as avg_specificity
FROM asset_mentions am
JOIN raw_content rc ON am.content_id = rc.id
LEFT JOIN source_scores ss ON rc.source_name = ss.source_name
WHERE am.needs_review = 0
  AND am.created_at >= date('now', '-7 days')
GROUP BY am.symbol, am.asset_type
```

### 2. Compute signal score
For each asset, compute the weighted signal score using weights from `config/scoring.yaml`.
All component sub-scores must be normalised to [0, 100] before weighting.

Components:
- `investment_intent` (25%) — from `avg_intent` × 100
- `sentiment_strength` (15%) — from `avg_sentiment` mapped to 0-100
- `source_quality` (20%) — from `avg_source_quality` × 100
- `specificity` (15%) — from `avg_specificity` × 100
- `repetition` (15%) — `min(mention_count / 10, 1.0)` × 100
- `community_confirmation` (10%) — `min(source_count / 3, 1.0)` × 100

Signal score = weighted sum of normalised components.

Compute `score_audit` as JSON: `{"intent": 72, "sentiment": 60, "source": 85, ...}`

### 3. Compute crowding score
If most signals come from comments or low-quality sources with `hype_tendency > 0.6`, add a crowding premium to the score. If `crowding_score > 70`, flag euphoria risk.

### 4. Determine research priority
Based on thresholds in `config/scoring.yaml`:
- Below `watchlist` threshold → `log_only`
- Between `watchlist` and `quick_research` → `watchlist`
- Between `quick_research` and `deep_research` → `level_2`
- Above `deep_research` → `level_3`
- Above `high_priority` → `level_4`

Also check:
- Asset already owned (`real_positions`) → upgrade to at least `level_2`
- Strong negative signal on owned asset → `level_3`
- User-requested → `level_4` regardless of score

### 5. Write results
Upsert into `asset_signals`. Store `score_audit` as JSON in the `score_audit` column.

### 6. Log
Insert a row into `pipeline_runs` for this stage.
