# Entry Quality + Friction Gate Agent

**Purpose:** Determine whether the expected upside justifies the costs and volatility of entry.

## Inputs
- `research_packs` with `viability_score >= 60` and `evidence_quality_score >= 50`
- `price_history` — for realised volatility calculation
- `venue_assets` — for current funding rate and spread
- `config/friction_entry.yaml` — rules and thresholds

## Outputs
- Entry quality score per asset
- Updated `position_plans` entries
- Assets classified as `good_asset_bad_entry` where applicable

## Workflow

### 1. Compute volatility buffer
For each asset, fetch 30 days of `price_history`. Compute daily return standard deviation.
`volatility_buffer = realized_30d_vol * buffer_multiplier` (from `config/friction_entry.yaml`).
If no price history available, use static fallback values from config. Mark plan as `ILLUSTRATIVE`.

### 2. Build cost stack
For each asset:
- Entry fee: from `venue_assets` or config default
- Exit fee: same
- Spread estimate: from `venue_assets.liquidity_score` proxy
- Slippage estimate: based on order size vs `volume_24h`
- Funding (perp only): `venue_assets.funding_rate` × expected holding period in days
- Tax/friction estimate: from config
- Volatility buffer: computed in step 1
- Total friction = sum of all above

### 3. Compute friction-adjusted EV
`friction_adjusted_ev = (expected_upside × win_probability) - (expected_downside × loss_probability) - total_friction`

Note: `win_probability` and `loss_probability` are deterministic estimates from the risk/reward ratio, not calibrated probabilities. Mark as estimates.

If `friction_adjusted_ev < 0` → decision = `no_entry`
If `friction_adjusted_ev > 0` but `risk_reward < minimum_risk_reward` → decision = `good_asset_bad_entry`

### 4. Entry quality score
Compute entry quality score using weights from `config/scoring.yaml`.

### 5. Generate position plan
Call `prompts/position_plan_prompt.md` to generate a structured position plan. Validate the returned JSON. Store in `position_plans`.

### 6. Log
Insert a row into `pipeline_runs` for this stage.
