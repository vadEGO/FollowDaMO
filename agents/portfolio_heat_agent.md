# Portfolio Heat Agent

**Purpose:** Compute overall portfolio risk level and block new entries when heat is too high.

## Inputs
- `real_positions` — current holdings
- `shadow_positions` — shadow portfolio state
- `config/portfolio_rules.yaml` — heat thresholds and blocked actions

## Outputs
- Portfolio heat score (0-100)
- Blocked actions list
- Heat data written to `dashboards/dashboard_data.json`

## Heat Inputs (from `config/portfolio_rules.yaml`)
- Crypto beta exposure
- AI / growth exposure
- Solana ecosystem concentration
- Single-name concentration
- Dry powder level
- Leverage
- Crowding exposure
- Recent drawdown (30d)

## Workflow

### 1. Load positions
Read `real_positions`. Compute allocation percentages by thesis using `config/assets.yaml`.

### 2. Compute heat components
For each input, normalise to [0, 100]:
- `crypto_beta_exposure`: sum of crypto positions / total portfolio × 100
- `single_name_concentration`: max single position / total × 100
- `dry_powder`: (1 - dry_powder_pct) × 100 (less cash = more heat)
- `crowding`: average crowding_score of owned assets

### 3. Compute composite heat
Heat = weighted average of components (equal weight for now, tunable in config).

### 4. Determine status and blocked actions
- Heat >= `high_threshold` (80): status = `high`, block = `new_high_beta_entries`
- Heat >= 90: status = `critical`, block all new entries

### 5. Write output
Update `dashboards/dashboard_data.json` with portfolio heat block.

### 6. Log
Insert a row into `pipeline_runs` for this stage.
