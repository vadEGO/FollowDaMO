# Shadow Portfolio Simulator Agent

**Purpose:** Test portfolio decisions before real action by simulating outcomes across 10 shadow portfolios.

## Inputs
- `shadow_portfolios` — 10 predefined strategies
- `shadow_positions` — current positions in each shadow portfolio
- `price_history` — historical and current prices
- `position_plans` — candidate entries
- `config/portfolio_rules.yaml` — allocation rules

## Outputs
- Updated `simulation_results`
- Best allocation data in `dashboards/dashboard_data.json`

## Note on simulation approach
Forward simulation (tracking shadow portfolio from entry date forward) is preferred over backtesting.
Backtest results are supplementary only.

## Workflow

### 1. Update shadow portfolio prices
For each `shadow_positions` row with status = `open`, fetch the current price from `price_history`. Compute current value, return, and drawdown.

### 2. Simulate candidate entries
For any new real candidate (from `position_plans`), add a simulated entry to the relevant shadow portfolios. Do not add to `sp_current` (that mirrors real holdings only).

### 3. Compute portfolio metrics
For each shadow portfolio, compute:
- Total return (from `shadow_positions.entry_price` to current price)
- Volatility (daily standard deviation of portfolio value changes)
- Max drawdown (largest peak-to-trough in the tracked period)
- Sharpe-like score (return / volatility, no risk-free rate adjustment)
- Turnover
- Thesis alignment

### 4. Store results
Insert into `simulation_results` with `period_start` and `period_end`.

### 5. Identify best allocation
Compare all 10 shadow portfolios by `portfolio_score`. Write the ranking to `dashboards/dashboard_data.json`.

Return figures must include a period label (YTD / since-inception) — do NOT show unlabelled percentage returns.

### 6. Log
Insert a row into `pipeline_runs` for this stage.
