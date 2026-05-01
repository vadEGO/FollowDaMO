# Model Auditor Agent

**Purpose:** Evaluate whether MoneyTrail's own recommendations are working. Run weekly.

## Inputs
- `model_decision_outcomes` — all past decisions with outcome data
- `asset_signals` — signal scores at time of decision
- `config/scoring.yaml` — current scoring thresholds

## Outputs
- Weekly audit section in `knowledge/weekly_memos/`
- Scoring threshold recommendations
- `dashboards/dashboard_data.json` model audit board data

## Audit Fields
- Best call this week (highest-scored asset that performed well)
- Worst call this week (highest-scored asset that underperformed)
- False positive (accepted asset that fell materially)
- False negative (rejected asset that rallied materially)
- Avoided loss (rejected asset that fell)
- Missed winner (rejected asset that rallied)
- Overtrading warning (if turnover is exceeding config limit)

## Workflow

### 1. Load recent outcomes
Query `model_decision_outcomes` for decisions in the last 7-30 days with price data available.

### 2. Classify outcomes
For each outcome, classify as: true_positive | true_negative | false_positive | false_negative.
A result is positive if the 90-day return is > 0.

### 3. Find scoring calibration issues
If false positives cluster at a particular signal score range → recommend lowering the threshold.
If false negatives cluster → recommend reviewing the evidence quality gate.

### 4. Write example with root cause
For the worst false positive, write a short analysis:
```
False Positive: [ASSET]
Initial score: [N]
Outcome: [return]%
Cause: [what drove the false positive — e.g. comment sentiment overweighted]
Adjustment: [proposed scoring change]
```

### 5. Update dashboard
Write audit data to `dashboards/dashboard_data.json` with actual outcomes (not template text).

### 6. Log
Insert a row into `pipeline_runs` for this stage.
