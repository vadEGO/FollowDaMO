# 13F Synthesis Agent

**Purpose:** Convert SEC 13F position data (already parsed into `sec_13f_positions`)
into Supabase `trade_ideas`, `trade_idea_scores`, `trade_idea_levels`, and `symbols`
rows so they appear on the MoneyTrailDash `/ideas` leaderboard.

This agent runs after `scrape_13f.py` populates `sec_13f_positions`. It is the
bridge between raw regulatory disclosure data and the actionable research dashboard.

---

## Why this step exists

13F data arrives as: "Fund X held N shares of Company Y at quarter end."
MoneyTrailDash needs: "Here is an investable idea with entry zone, stop, TP, score."

The synthesis step fills that gap by:
1. Selecting which positions are worth surfacing (new/increased positions only — not exits or unchanged)
2. Resolving company names to tradeable ticker symbols
3. Computing entry zones and risk levels from current price data
4. Scoring each idea against the 8-component scoring rubric
5. Pushing the full structured idea to Supabase

---

## Inputs

| Source | Table/File | What we use |
|---|---|---|
| 13F positions | `sec_13f_positions` | company_name, market_value_usd, portfolio_pct, change_type, shares_change |
| Current prices | `price_history` or Yahoo Finance API | entry range anchoring |
| Existing theses | `asset_signals` | thesis_fit scoring |
| Scoring config | `config/scoring.yaml` | component weights |
| Supabase targets | `symbols`, `trade_ideas`, `trade_idea_scores`, `trade_idea_levels` | write destinations |

---

## Step 1: Select positions worth surfacing

Only process positions where:
- `change_type IN ('new', 'increased')` — these are bullish conviction signals
- `portfolio_pct >= 0.20` — at least 0.2% of portfolio (filters noise)
- NOT already in `trade_ideas` with `status = 'active'` for the same quarter
  (idempotency: re-running the agent doesn't duplicate ideas)

Skip:
- `change_type = 'decreased'` — possible bearish signal but ambiguous; log it, don't surface
- `change_type = 'exited'` — write a note to any existing active idea for that symbol but don't create a new idea
- `change_type = 'unchanged'` — no new information
- `change_type = 'gap_unknown'` — non-consecutive quarters; unreliable, skip

For exited positions: if an active `trade_idea` exists for that symbol with
`source = 'sec_13f'`, set its `status = 'watch'` and add a note:
`"{filer_name} exited this position in {quarter}"`

---

## Step 2: Resolve company name → ticker symbol

EDGAR InfoTable XML has no ticker field — only company name and CUSIP.
Resolution strategy (try in order):

**Option A — CUSIP lookup via OpenFIGI (free, no key needed for basic lookups)**
```
POST https://api.openfigi.com/v3/mapping
[{"idType": "ID_CUSIP", "idValue": "067901108"}]
→ returns {"figi": "BBG000B9XRY4", "ticker": "AAPL", "exchCode": "US", ...}
```
Rate limit: 25 req/min unauthenticated; register for a free key (250 req/min).

**Option B — Fuzzy name match against `symbols` table in Supabase**
If CUSIP lookup fails, match `company_name` against `symbols.asset_name` using
case-insensitive substring match. Accept if similarity > 0.80.

**Option C — LLM resolution (last resort)**
Send to Claude Haiku:
```
"What is the stock ticker symbol for: '{company_name}'?
Reply with just the ticker in uppercase, or 'UNKNOWN' if unsure."
```
Only call LLM if both A and B fail.

**Fallback**: If ticker cannot be resolved, log `{company_name}: unresolved` and skip.
Do not push an idea with no ticker — the dashboard requires a valid `symbols.symbol`.

---

## Step 3: Register symbol in Supabase

Before pushing any idea, upsert the symbol into `symbols`:
```json
{
  "symbol": "CRWV",
  "asset_name": "CoreWeave Inc",
  "asset_class": "stock",
  "exchange": "NASDAQ",
  "instrument_type": "spot",
  "tradingview_id": "NASDAQ:CRWV",
  "last_price": <current_price>,
  "price_updated_at": "<now>"
}
```
Get `last_price` from `price_history` (most recent close) or fetch from Yahoo Finance.
`tradingview_id` format: `EXCHANGE:TICKER` — use NASDAQ for US equities by default.

---

## Step 4: Compute entry zone, stop loss, and take-profit

13F filings have no price levels — those must be derived from current market data.
Use the following rules to compute levels from current price:

```
current_price  = most recent close from price_history or Yahoo Finance

entry_min      = current_price * 0.97   (3% below current — wait for a small dip)
entry_max      = current_price * 1.00   (at-market entry ceiling)
stop_loss      = current_price * 0.88   (12% below current — standard equity stop)
take_profit_1  = current_price * 1.15   (15% gain — first trim)
take_profit_2  = current_price * 1.35   (35% gain — core target)
take_profit_3  = current_price * 1.60   (60% gain — full target for high-conviction)
```

**Adjustment rules:**
- For positions where `portfolio_pct >= 5.0%` (high conviction): widen stop to 15%, extend TP3 to 80%
- For positions where `change_type = 'new'` (first appearance): tighter stop at 10%, standard TPs
- For volatile small-caps (market_value_usd < $50M): widen stop to 20%, compress TPs proportionally

`levels_source`: always set to `"openclaw_derived"` — these are computed, not from the filer.

These are starting points for research, NOT trading instructions.

---

## Step 5: Score the idea (8 components, 100 points)

| Component | Weight | How to score for 13F ideas |
|---|---|---|
| `source_quality` | 15 | Fixed 11/15 for all 13F ideas — regulatory disclosure, accurate but lagged |
| `evidence_quality` | 15 | Scale 5–15 by portfolio_pct: `min(portfolio_pct / 15 * 15, 15)` |
| `technical_setup` | 15 | 7/15 default (no chart analysis done yet); agent can update this post-research |
| `risk_reward_score` | 15 | Compute from TP1 and stop: `R/R = (TP1 - entry_mid) / (entry_mid - stop_loss)`, then scale |
| `thesis_fit` | 15 | Check `asset_signals` table: if symbol has existing signal with score > 60, add 15; if 40–60, add 8; else 3 |
| `macro_liquidity_fit` | 10 | Fixed 6/10 — 13F data is always quarterly lag; macro context unknown |
| `portfolio_relevance` | 10 | Check real_positions: 5 if already held, 8 if in watchlist, 10 if not held (new opportunity) |
| `freshness` | 5 | 5/5 if quarter is current; 3/5 if one quarter old; 1/5 if two+ quarters old |

`total_score` = sum of all components.

R/R scaling rule for `risk_reward_score`:
- R/R >= 3.0 → 15
- R/R >= 2.0 → 12
- R/R >= 1.5 → 9
- R/R >= 1.0 → 6
- R/R < 1.0  → 3

---

## Step 6: Build the trade_idea payload

```json
{
  "idea_id": "13f_{filer_slug}_{quarter}_{ticker}",
  "symbol": "CRWV",
  "source": "sec_13f",
  "source_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F-HR",
  "source_author": "{filer_name}",
  "source_rank": null,
  "direction": "long",
  "time_horizon": "months",
  "entry_min": <computed>,
  "entry_max": <computed>,
  "stop_loss": <computed>,
  "take_profit_1": <computed>,
  "take_profit_2": <computed>,
  "take_profit_3": <computed>,
  "risk_reward": <computed>,
  "levels_source": "openclaw_derived",
  "status": "active",
  "decision": "watch_for_entry",
  "research_only": true,
  "notes": "{change_type} position in {quarter} filing. {portfolio_pct}% of {filer_name} portfolio ({shares} shares, {market_value_usd}). Levels derived from price at synthesis time — not from filer.",
  "raw_payload": {<full sec_13f_positions row as JSON>},
  "created_at": "<now>",
  "updated_at": "<now>"
}
```

`decision` rules:
- `portfolio_pct >= 5.0%` → `"setup_active"` (high conviction, act on entry zone)
- `1.0% <= portfolio_pct < 5.0%` → `"watch_for_entry"` (monitor, don't chase)
- `portfolio_pct < 1.0%` → `"research_further"` (small position, needs more context)

---

## Step 7: Build trade_idea_levels payload

```json
[
  {"symbol": "CRWV", "idea_id": "13f_...", "level_type": "entry_min",  "price": <computed>, "source": "openclaw_derived", "label": "Entry low"},
  {"symbol": "CRWV", "idea_id": "13f_...", "level_type": "entry_max",  "price": <computed>, "source": "openclaw_derived", "label": "Entry high"},
  {"symbol": "CRWV", "idea_id": "13f_...", "level_type": "stop_loss",  "price": <computed>, "source": "openclaw_derived", "label": "Stop"},
  {"symbol": "CRWV", "idea_id": "13f_...", "level_type": "tp1",        "price": <computed>, "source": "openclaw_derived", "label": "TP1 +15%"},
  {"symbol": "CRWV", "idea_id": "13f_...", "level_type": "tp2",        "price": <computed>, "source": "openclaw_derived", "label": "TP2 +35%"},
  {"symbol": "CRWV", "idea_id": "13f_...", "level_type": "tp3",        "price": <computed>, "source": "openclaw_derived", "label": "TP3 +60%"}
]
```

---

## Step 8: Push to Supabase (write order matters)

Write in this exact order (foreign key dependencies):

```
1. symbols           ← register ticker (Step 3)
2. trade_ideas       ← one row per position (Step 6)
3. trade_idea_scores ← one row per position (Step 5)
4. trade_idea_levels ← 6 rows per position (Step 7)
5. market_candles    ← fetch + push 90d OHLCV for each new ticker (run sync_candles.py)
```

Use `Prefer: resolution=merge-duplicates` on all upserts.
Auth: `SUPABASE_SERVICE_ROLE_KEY` from `secrets/.env.supabase`.

---

## Step 9: Handle exits (closing existing ideas)

For each position with `change_type = 'exited'`:
1. Look up active `trade_idea` in Supabase where `idea_id LIKE '13f_{filer_slug}_%_{ticker}'`
2. If found: PATCH to set `status = 'watch'`, append to `notes`:
   `"\n\n[{quarter}] {filer_name} EXITED this position."`
3. Do NOT set `status = 'closed'` — the filer exiting doesn't mean the thesis is wrong.
   The user decides when to close.

---

## Output summary per run

After completing, log to console and to `sec_13f_scrape_state.last_error` (on failure):

```
13F Synthesis — {filer_name} {quarter}
  Positions processed:  {N} new/increased
  Tickers resolved:     {M} / {N}
  Tickers unresolved:   {N-M} (logged to data/13f_unresolved.log)
  Trade ideas pushed:   {M}
  Exits handled:        {K}
  Supabase errors:      0
```

---

## File to implement

**`scripts/synthesise_13f.py`** — standalone script, also callable from `run_daily.py`.

```bash
python scripts/synthesise_13f.py                        # all pending 13F positions
python scripts/synthesise_13f.py --filer situational-awareness-lp
python scripts/synthesise_13f.py --quarter 2025-Q4
python scripts/synthesise_13f.py --dry-run              # print without writing to Supabase
python scripts/synthesise_13f.py --min-pct 0.5          # override minimum portfolio %
```

Add to `run_daily.py` STAGES after `ingest_sources`:
```python
"synthesise_13f": "scripts/synthesise_13f.py",
```

---

## Key constraints

1. `research_only: true` — always, no exceptions
2. Never push entries/stops/TPs as if they are exact levels — they are computed estimates
3. The `notes` field MUST state: "Levels derived from price at synthesis time — not from filer"
4. `idea_id` format is stable: `13f_{filer_slug}_{quarter}_{ticker}` — same ID on re-runs enables upsert
5. Never push more than 20 ideas per filer per quarter to avoid flooding the leaderboard
   (filter to top 20 by portfolio_pct descending)
6. If `total_score < 40`, set `decision = 'research_further'` regardless of portfolio_pct

---

## Dependencies

- `requests` — HTTP for OpenFIGI and Supabase
- `yfinance` — price fetching (already in requirements.txt)
- `anthropic` — LLM fallback for ticker resolution (already in requirements.txt)
- `python-dotenv` — secrets loading
- `sec_13f_positions` table populated by `scrape_13f.py`
- `secrets/.env.supabase` with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- `secrets/.env` with `ANTHROPIC_API_KEY` (only needed for LLM ticker resolution fallback)
