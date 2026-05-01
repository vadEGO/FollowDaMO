# Position Plan Prompt

Create a complete position plan for the following investment candidate.

**Asset:** {{ASSET_NAME}} ({{SYMBOL}})
**Asset type:** {{ASSET_TYPE}}
**Venue:** {{VENUE}}
**Market type:** {{MARKET_TYPE}}
**Research viability score:** {{VIABILITY_SCORE}}
**Thesis fit score:** {{THESIS_FIT_SCORE}}
**Current price:** {{CURRENT_PRICE}}
**Portfolio role:** {{PORTFOLIO_ROLE}}

## Required output

Produce a structured position plan with all required fields. If any field cannot be determined from available data, return `"no_entry"` as the final decision with the missing field named.

```json
{
  "asset": "{{SYMBOL}}",
  "venue": "{{VENUE}}",
  "market_type": "{{MARKET_TYPE}}",
  "position_role": "core_scarce | core_ai | ai_infrastructure | high_beta | tactical_satellite | hedge",
  "time_horizon": "days | weeks | months | cycle | long_term",
  "entry_type": "pullback | breakout | reclaim | layered_dca | thesis_confirmation | capitulation | no_entry",
  "entry_min": null,
  "entry_max": null,
  "stop_type": "price | thesis | time | volatility | portfolio | liquidity | event",
  "stop_price": null,
  "thesis_invalidation": "describe the specific condition",
  "take_profit_layers": [
    {"layer": 1, "target_price": null, "sell_pct": null, "reason": ""},
    {"layer": 2, "target_price": null, "sell_pct": null, "reason": ""},
    {"layer": 3, "target_price": null, "sell_pct": null, "reason": ""}
  ],
  "reentry_plan": "describe reentry conditions",
  "risk_reward": null,
  "friction_adjusted_ev": null,
  "starter_size_pct": null,
  "target_size_pct": null,
  "max_size_pct": null,
  "funding_source": "dry_powder | trim_existing | rebalance",
  "expires_at": "date after which plan is invalid",
  "final_decision": "enter | watch | no_entry | good_asset_bad_entry",
  "decision_rationale": "one sentence"
}
```

## Rules

- If risk_reward < minimum for asset class → final_decision = "good_asset_bad_entry"
- If friction_adjusted_ev < 0 → final_decision = "no_entry"
- If entry_type = "no_entry" → all price fields are null
- No plan, no entry. Return no_entry if any required field is genuinely unknowable.

## Friction cost stack

Include these costs in friction_adjusted_ev calculation:
- Entry fee: {{ENTRY_FEE_PCT}}%
- Exit fee: {{EXIT_FEE_PCT}}%
- Spread estimate: {{SPREAD_BPS}} bps
- Slippage estimate: {{SLIPPAGE_BPS}} bps
- Funding (for perp): {{FUNDING_RATE_DAILY}}% daily
- Tax/friction estimate: {{TAX_FRICTION_PCT}}%
- Volatility buffer: {{VOLATILITY_BUFFER_PCT}}% (computed from 30d realized vol)
