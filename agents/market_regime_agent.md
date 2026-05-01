# Market Regime Agent

**Purpose:** Assess the macroeconomic and liquidity environment to inform asset-level decisions.

## Inputs
- Macro data sources: FRED, stablecoin supply proxies, BTC dominance, credit spread proxies
- `config/sources.yaml` for macro source URLs
- `config/thesis_budget.yaml` — which theses benefit from which regimes

## Outputs
- `knowledge/weekly_memos/regime_{date}.md` — regime assessment
- Regime data written to `dashboards/dashboard_data.json` for here.now board

## Regime States
- `liquidity_expansion`
- `liquidity_contraction`
- `risk_on_expansion`
- `risk_on_crowded`
- `neutral_choppy`
- `inflation_scare`
- `ai_capex_boom`
- `risk_off`
- `crisis_capitulation`

## Workflow

### 1. Collect macro signals
Fetch available macro data. Use free/public sources where possible:
- FRED: M2 money supply, real rates, yield curve (10Y-2Y spread)
- CoinGecko / CoinMarketCap: stablecoin total supply (USDT + USDC + DAI)
- Crypto Fear & Greed or BTC 30d return as risk proxy
- Dollar index (DXY) estimate from BTC/USD correlation proxy

### 2. Assess each signal
For each signal, assign: positive | negative | neutral for each thesis.

### 3. Determine regime
Combine signals to determine the most likely current regime.

### 4. Generate action bias
```text
Current Market Regime:
Liquidity: [expanding/contracting/neutral]
Risk appetite: [high/medium/low]
AI thesis: [active/crowded/cooling]
Scarce assets thesis: [active/neutral/headwind]
Action bias: [brief recommendation]
```

### 5. Write output
Save to `knowledge/weekly_memos/regime_{date}.md`. Update `dashboards/dashboard_data.json`.

### 6. Log
Insert a row into `pipeline_runs` for this stage.
