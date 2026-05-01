# Tradeability Gate

**Purpose:** Determine whether each asset can be traded on Hyperliquid. Prevent research and simulation on untradeable assets unless they are thesis-critical.

## Inputs
- `asset_mentions` with `needs_review = 0` and not yet tradeability-checked
- `venue_assets` table (Hyperliquid universe cache)
- `config/tradeability.yaml` — rules, liquidity thresholds, freshness requirements
- `config/assets.yaml` — asset types (equity/etf are always research-only)

## Outputs
- New or updated rows in `asset_tradeability`
- `asset_signals.status` updated with tradeability outcome

## Tradeability States

| State | Meaning | Next Action |
|---|---|---|
| `tradeable` | Listed, eligible, and liquid | Full workflow |
| `research_only` | Not tradeable but thesis-relevant | Lightweight research only |
| `proxy_candidate` | Direct asset unavailable, proxy available | Research proxy asset |
| `stale_data` | Venue data is older than `data_freshness_max_age_minutes` | Refresh before deciding |
| `reject` | Not tradeable and not thesis-critical | Log only |

## Workflow

### 1. Check data freshness
Query `venue_assets` for the most recent `last_checked`. If older than `data_freshness_max_age_minutes` from `config/tradeability.yaml`:
- Mark all pending tradeability checks as `stale_data`
- Trigger a venue refresh (call `scripts/refresh_hyperliquid_universe.py`)
- Re-run this agent after refresh completes

### 2. For each unresolved asset, check tradeability

For each asset symbol:
1. Check `venue_assets` for a match on `symbol` AND `venue = 'hyperliquid'`
2. If no match → check `config/assets.yaml` for `asset_type` (equity/etf → research_only)
3. If match found: check `is_listed`, `is_tradeable`, region_allowed (from config), liquidity thresholds from `config/tradeability.yaml`

Liquidity check:
- `volume_24h >= min_24h_volume_usd` AND `open_interest >= min_open_interest_usd`
- If liquidity below threshold → status = `research_only` (tradeable but not liquid enough)

Never use ticker string alone to construct an order — always use the `asset_id` from `venue_assets`.

### 3. Proxy check
If asset is not directly tradeable, check for a correlated proxy in `venue_assets`. Example: NVDA not on Hyperliquid → is there an AI index or ETF equivalent?

### 4. Write results
Insert or update `asset_tradeability` for each asset. Update `asset_signals.status` accordingly.

### 5. Log
Insert a row into `pipeline_runs` for this stage.

## Hard rules
- No tradeability → no trade decision, ever
- No liquidity → no position
- No eligibility certainty → no execution
- Never construct an order from ticker string alone
