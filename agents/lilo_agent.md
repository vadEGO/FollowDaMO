# LILO Manager Agent

**Purpose:** Manage Layer In / Layer Out logic for medium-to-long-term positions.

## Inputs
- `real_positions` — current holdings
- `lilo_profiles` — existing LILO configs per asset + role
- `position_plans` — active plans
- `take_profit_layers` — active TP layers
- `price_history` — current prices
- `config/friction_entry.yaml` — friction cost checks

## Outputs
- Updated `lilo_profiles`
- Updated `take_profit_layers`
- LILO recommendations added to `dashboards/dashboard_data.json`

## LILO Strategy Rules
- Keep core positions for strong long-term theses
- Manage tactical / speculative portions with layers
- Use wider layers for volatile assets (higher volatility buffer)
- Do NOT churn if fees/tax/friction make the layer unattractive
- Layer out during euphoria, overvaluation, or portfolio concentration
- Layer back in only when the discount or risk/reward is meaningful

## Workflow

### 1. Load owned assets with LILO profiles
Query `real_positions` JOIN `lilo_profiles` on asset.

### 2. Check active take-profit layers
For each owned asset with active `take_profit_layers`:
- Compare current price from `price_history` to `target_price`
- If triggered: mark layer as `triggered`, create a recommendation in `real_action_candidates`
- Triggered layers require human approval before execution

### 3. Check layer-in conditions
For assets on watchlist or with a `pullback_entry` position plan:
- Compare current price to `entry_min` / `entry_max` in `position_plans`
- If in range: flag as a layer-in candidate

### 4. Check friction before any recommendation
For any layer recommendation, verify the layer size × fee stack makes the trade worthwhile.
If friction > 10% of expected layer benefit → recommend skipping the layer with explanation.

### 5. Write LILO board data
Update `dashboards/dashboard_data.json` with current LILO state per owned asset:
- Show actual price-level triggers (not narrative text)
- Next layer: "Add: -25% from current price" or "TP1: +40% → sell 15%"

### 6. Log
Insert a row into `pipeline_runs` for this stage.
