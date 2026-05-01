# Report Agent

**Purpose:** Generate the daily Telegram digest and update the here.now dashboard data.

## Inputs
- `asset_signals` — today's signals
- `asset_tradeability` — tradeability status
- `portfolio_heat_agent` output (heat score)
- `position_plans` with status = `real_candidate`
- `dashboards/dashboard_data.json` — assembled by prior agents
- `config/telegram.yaml` — format and priority rules

## Outputs
- Telegram message sent to configured chat
- Updated `dashboards/dashboard_data.json`
- `knowledge/weekly_memos/daily_{date}.md` archive

## Daily Digest Structure

Order defined by `config/telegram.yaml.digest_priority_order`:

**1. Approval packets** (if any)
Any `position_plans` with `status = 'real_candidate'` that haven't been approved. Show asset, action, size, and a link to the full packet in `knowledge/decision_journal/`.

**2. Portfolio heat**
One line with status word and color: 🟢 GREEN / 🟡 AMBER / 🔴 RED + the numeric score.

**3. Action-required signals**
Assets that crossed a threshold today and need a decision. Show: symbol, signal score, tradeability status, recommended action.

**4. Informational signals**
Top N signals (from `config/telegram.yaml.max_signals_in_digest`) that are notable but don't require immediate action.

**5. Blocked and logged**
Count of assets processed that were blocked (not tradeable, low quality) — one line summary.

**6. Pipeline status**
If any stage failed today, include a brief alert at the bottom.

## Data freshness
Every section must include a "Data as of [timestamp]" footer. If any board data is older than the freshness threshold from `config/tradeability.yaml`, flag it.

## Weekly Memo (Sundays)
On the configured day, generate a full weekly memo and save to `knowledge/weekly_memos/`.
Structure defined in `moneytrail_openclaw_solution_design.md` Section 14.

## Log
Insert a row into `pipeline_runs` for this stage.
