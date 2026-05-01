# Thesis Mapper

**Purpose:** Map each viable asset to investment theses and determine whether it is a good expression of those theses.

## Inputs
- `research_packs` with `viability_score >= 60`
- `config/thesis_budget.yaml` — thesis definitions
- `config/assets.yaml` — primary thesis assignments

## Outputs
- New or updated rows in `asset_thesis_scores`
- `research_packs.thesis_fit_score` updated

## Workflow

### 1. Load thesis definitions
Read `config/thesis_budget.yaml` for evaluation questions per thesis.

### 2. Score thesis fit
For each asset, evaluate against each thesis using the research pack content.

**Thesis fit score components (from `config/scoring.yaml`):**
- Core thesis alignment (30%)
- Trend strength (20%)
- Evidence quality (20%)
- Valuation / entry quality (15%)
- Portfolio usefulness (15%)

### 3. Assign primary thesis
If the asset matches both Scarce Assets and AI Growth (e.g. energy/power/grid), assign to its primary thesis from `config/assets.yaml`. It counts toward ONE thesis budget only.

### 4. Determine best expression rank
Within each thesis, rank assets by `thesis_fit_score`. Best expression = rank 1.

### 5. Write results
Insert into `asset_thesis_scores` with `version` tracking. Do NOT overwrite prior versions — insert a new row with `version = prior_version + 1` and set `superseded_by` on the old row.

### 6. Update research pack
Update `research_packs.thesis_fit_score` for the asset.

### 7. Log
Insert a row into `pipeline_runs` for this stage.
