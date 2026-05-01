# Evidence Quality Agent

**Purpose:** Score the quality of evidence in each research pack. Prevent polished but weak research from advancing to thesis mapping.

## Inputs
- New `research_packs` rows
- Evidence labels from research pack text: `[P1]`, `[P2]`, `[MI]`, `[SC]`, `[UK]`, `[AS]`

## Outputs
- Updated `research_packs.evidence_quality_score`
- Updated `research_packs.unknowns`

## Scoring

For each research pack, count evidence labels and compute:

| Component | Question | Weight |
|---|---|---|
| Freshness | Is the primary data current (within 90 days)? | 25% |
| Source quality | Ratio of `[P1]+[P2]` to total claims | 25% |
| Completeness | Are all minimum required fields present? | 25% |
| Verification | Are key claims independently supported? | 15% |
| Critical unknowns | Are there unresolved `[UK]` items that would be fatal? | 10% |

Score = weighted sum, normalised to 0-100.

Evidence quality labels:
- `high`: score >= 75
- `medium`: score 50-74
- `low`: score < 50

## Hard rule
If any critical unknown (`[UK]`) relates to regulatory risk, token unlock timing, or liquidity — the asset CANNOT become a real candidate regardless of overall score.

## Log
Insert a row into `pipeline_runs` for this stage.
