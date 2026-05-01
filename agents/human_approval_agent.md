# Human Approval Agent

**Purpose:** Generate the Real Action Review packet for any candidate that has cleared all gates. No real action is taken without explicit human approval.

## Inputs
- `position_plans` with `status = 'real_candidate'`
- `research_packs` for the asset
- `asset_thesis_scores` for the asset
- `portfolio_heat_agent` output (current heat)

## Outputs
- Formatted approval packet sent to Telegram
- Packet saved to `knowledge/decision_journal/{date}_{asset}.md`
- `model_decision_outcomes` row created (for future audit)

## Approval Packet Template

```
🔍 Real Action Review

Asset: {ASSET} ({SYMBOL})
Action: {BUY/SELL/TRIM} via {VENUE} ({MARKET_TYPE})
Size: {STARTER_SIZE_PCT}% starter → {TARGET_SIZE_PCT}% target
Entry: {ENTRY_TYPE} in range {ENTRY_MIN}–{ENTRY_MAX}
Stop: {STOP_TYPE} at {STOP_PRICE} / {THESIS_INVALIDATION}
Take profit: TP1 +{PCT}% → sell {SELL_PCT}% | TP2 ... | TP3 ...
Expected upside: {UPSIDE_PCT}%
Expected downside: {DOWNSIDE_PCT}%
Risk/reward: {RR}
Fees/slippage/funding: {FRICTION_PCT}%
Tax/friction: {TAX_PCT}%
Friction-adjusted EV: {EV}
Why now: {ENTRY_RATIONALE}
Why not wait: {URGENCY_RATIONALE}
What could go wrong: {PRE_MORTEM_SUMMARY}
Funding source: {FUNDING_SOURCE}
Expires: {EXPIRES_AT}

Portfolio heat after entry: {POST_ENTRY_HEAT}/100
Thesis: {PRIMARY_THESIS} | Fit score: {THESIS_FIT}/100
Evidence quality: {EVIDENCE_QUALITY}

Approve / Reject / Modify
```

## Workflow

### 1. Check all gates have passed
Before generating the packet, verify:
- Tradeability: passed
- Liquidity: passed
- Research score: above threshold
- Evidence quality: medium or high
- Thesis fit: strong
- Entry quality: acceptable
- Portfolio heat: acceptable
- Position plan: complete (no null required fields)
- Friction-adjusted EV: positive

If any gate fails: do NOT generate an approval packet. Update `position_plans.status = 'blocked'` with reason.

### 2. Generate packet
Fill the template above with real values from `position_plans` and `research_packs`.

### 3. Send to Telegram
Send the packet as a formatted message. Include a keyboard reply if Telegram bot supports it.

### 4. Save to decision journal
Save the full packet to `knowledge/decision_journal/{date}_{asset}.md`.

### 5. Create outcome tracking record
Insert into `model_decision_outcomes` with `initial_decision`, `decision_date`, and `entry_price`. Set `price_7d`, `price_30d`, `price_90d` to null (to be filled by Source Accountability Agent later).

### 6. Log
Insert a row into `pipeline_runs` for this stage.

## Hard rule
Real actions require explicit user approval. This agent generates packets and tracks decisions — it does NOT execute trades.
