# Rotation Engine Agent

**Purpose:** Identify whether newer candidates are materially better than existing holdings, net of friction.

## Inputs
- `real_positions` — current holdings
- `research_packs` — scores for new candidates
- `asset_thesis_scores` — thesis fit for all assets
- `config/portfolio_rules.yaml` — turnover limits

## Outputs
- New rows in `rotation_candidates`
- Rotation recommendations in weekly memo

## Rotation Conditions (all must be true)
1. New asset score materially higher than existing asset (>15 point gap)
2. Better thesis fit for the primary thesis
3. Better portfolio diversification (not adding to existing overweights)
4. Acceptable entry quality
5. Expected benefit exceeds tax + friction cost
6. Existing asset is weakening, euphoric, overweight, or lower quality

## Workflow

### 1. For each new real candidate
Compare its thesis fit score and research score to all existing holdings in the same thesis bucket.

### 2. Identify dominated holdings
If a new candidate clearly dominates an existing holding on both score AND fits the portfolio better: flag as a rotation candidate.

### 3. Friction check
Compute `tax_friction_estimate` for exiting the existing position + entering the new one. If friction > score improvement benefit, reject the rotation.

### 4. Write rotation candidates
Insert into `rotation_candidates` with `status = 'pending'`. These require simulation before human review.

### 5. Weekly rotation summary
Generate a rotation summary for the weekly memo.

### 6. Log
Insert a row into `pipeline_runs` for this stage.
