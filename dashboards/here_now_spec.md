# here.now Dashboard Specification

## Delivery mechanism
**Local static HTML** — `dashboards/index.html` reads `dashboard_data.json` directly via JavaScript `fetch()`. Open in any browser. No server required.

To open: `open ~/MoneyTrail/dashboards/index.html`

The dashboard auto-refreshes if you keep it open (polls `dashboard_data.json` every 60 seconds).

## Dashboard layout

### Entry view (landing state)
When opening the dashboard, the user sees three things first:
1. **Portfolio heat** — one large coloured number: 🟢 / 🟡 / 🔴 with status word
2. **Today's signals** — Signal Radar filtered to today's new items
3. **Approval packets** — any `position_plans` with `status = real_candidate` awaiting action

All other boards are accessible via tabs / scroll below.

## Boards

### Board 1 — Signal Radar
Shows today's signals with explicit time window label: "Last 7 days"

| Asset | Today | 7d | Sources | Sentiment | Signal Score | Status | Action |
|---|---|---|---|---|---|---|---|

- Click a row → opens the research pack (if it exists)
- Empty state: "No signals above threshold today — pipeline ran at [time]"
- Error state: "Signal data unavailable — check logs/run_{date}.log"

### Board 2 — Tradeability Board
| Asset | Venue | Market | Tradeable | Volume 24h | OI | Spread | Action |
|---|---|---|---|---|---|---|---|

- Tradeable column: ✅ Pass / ⚠️ Watch / ❌ Fail / 🔄 Stale
- Watch = volume below threshold (show actual number in tooltip)
- Stale = data older than `data_freshness_max_age_minutes`

### Board 3 — Thesis Board
| Thesis | Strength | Lifecycle | Crowding | Top 3 Expressions |
|---|---|---|---|---|

- Top 3 Expressions: ranked by `thesis_fit_score` (tradeable only unless thesis-critical)
- Example: "1. BTC (95) 2. NEAR (72) 3. — "
- Click expression → opens asset's research pack

### Board 4 — LILO Board
| Asset | Role | LILO Mode | Current Action | Next Layer (quantified) |
|---|---|---|---|---|

- Next Layer must show actual price levels: "Add: -25% from $X" or "TP1: +40% → sell 15%"
- NOT narrative text like "Add on major drawdown"

### Board 5 — Best Allocation Board
| Allocation | Return (YTD) | CAGR | Max DD | Volatility | Thesis Fit | Score |
|---|---|---|---|---|---|---|

- Return must include period label (YTD or since-inception)
- Scores from `simulation_results`

### Board 6 — Model Audit Board
| Asset | Decision Date | Score | Decision | Outcome 30d | Outcome 90d | Category |
|---|---|---|---|---|---|---|

- Category: True Positive / True Negative / False Positive / False Negative
- Empty state: "No decisions aged 30+ days yet — check back after first month"

## Data freshness footer
Every board shows: `Data as of [ISO timestamp]`
If data is older than the configured freshness threshold → board header turns amber with warning icon.

## Color convention
- 🔴 Red: action required, blocked, failed, or portfolio heat critical
- 🟡 Amber: watch, simulate only, elevated heat, stale data
- 🟢 Green: pass, hold, healthy
- ⚫ Gray: log only, archived, research-only

## dashboard_data.json schema
```json
{
  "generated_at": "ISO timestamp",
  "portfolio_heat": {
    "score": 78,
    "status": "high",
    "color": "amber",
    "blocked_actions": ["new_high_beta_entries"]
  },
  "signal_radar": [...],
  "tradeability_board": [...],
  "thesis_board": [...],
  "lilo_board": [...],
  "allocation_board": [...],
  "model_audit_board": [...],
  "pending_approvals": [...],
  "pipeline_status": {
    "last_run": "ISO timestamp",
    "stages_failed": []
  }
}
```
