# MoneyTrail OpenClaw Solution Design

## 1. Executive Summary

MoneyTrail is a local OpenClaw-based investment intelligence and portfolio decision-support system. It monitors investment discussions from existing OpenClaw-accessible sources, extracts mentioned assets, checks whether they are tradeable on the configured venue, performs token-aware asset research, maps assets to core investment theses, simulates portfolio decisions, and produces actionable but human-reviewed recommendations.

The system is designed for medium-to-long-term investing, not high-frequency trading. Its primary goal is to improve investment discipline by separating social signal discovery from independent research, tradeability, portfolio fit, entry quality, and risk management.

MoneyTrail should not blindly follow influencers or social sentiment. It should identify what is being discussed, verify whether the idea is investable, check whether it can actually be traded, assess whether the upside justifies the risk and friction, and only then promote the idea to a shadow portfolio or human-reviewed real action candidate.

Core principle:

> Signals discover ideas. Research validates ideas. Tradeability filters ideas. Simulation tests ideas. Position plans control risk. Human approval executes.

---

## 2. Objectives

### 2.1 Primary Objectives

MoneyTrail must:

1. Ingest investment-related content from existing OpenClaw sources.
2. Extract stocks, crypto assets, ETFs, commodities, sectors, macro themes and trade ideas from posts, transcripts and comments.
3. Resolve ambiguous tickers and asset names.
4. Check whether assets are tradeable on Hyperliquid or otherwise mark them as research-only.
5. Avoid expensive research on assets that cannot be traded unless they are thesis-critical.
6. Perform structured asset research for viable candidates.
7. Map each asset to core theses such as scarce assets and AI growth.
8. Maintain an Idea Ledger for every asset discovered.
9. Score assets across signal quality, evidence quality, research quality, thesis fit, tradeability, liquidity, portfolio fit and entry quality.
10. Simulate candidate entries and portfolio allocations before any real action.
11. Track performance of accepted, rejected and watched ideas.
12. Produce Telegram summaries and here.now dashboard data.
13. Require human approval before any real trade action.

### 2.2 Non-Objectives for Initial Release

The first release must not:

1. Execute real trades automatically.
2. Use leverage without explicit approval.
3. Transfer funds or approve wallet permissions.
4. Treat social sentiment as investment evidence.
5. Research every mention deeply regardless of quality.
6. Recommend trades without an entry, stop loss, take-profit plan and risk/reward assessment.

---

## 3. Operating Philosophy

MoneyTrail is built around seven hard gates.

```text
1. Asset Resolution Gate
2. Tradeability Gate
3. Data Quality Gate
4. Evidence Quality Gate
5. Thesis Fit Gate
6. Friction-Adjusted Entry Gate
7. Portfolio Fit / Human Approval Gate
```

An asset can only move closer to a real trade candidate if it passes the relevant gates.

Most outputs should be one of:

- Log only
- Research only
- Watchlist
- Shadow portfolio candidate
- Good asset, bad entry
- Existing holding — monitor
- Real candidate for user review
- Avoid
- Do nothing

The system must be comfortable saying:

> Interesting signal, but no action.

---

## 4. High-Level Architecture

```text
Investment Sources
  ↓
Source Collector
  ↓
Raw Content Vault
  ↓
Asset Extractor
  ↓
Entity Resolver
  ↓
Tradeability Gate
  ↓
Signal Scorer
  ↓
Research Prioritiser
  ↓
Asset Research Engine
  ↓
Evidence Quality Scorer
  ↓
Thesis Mapper
  ↓
Market Regime Brain
  ↓
Portfolio Heat Engine
  ↓
Entry Quality + Friction Gate
  ↓
Position Plan Generator
  ↓
Shadow Portfolio Simulator
  ↓
Rotation Engine
  ↓
Model Auditor
  ↓
Telegram + here.now + Markdown Reports
  ↓
Human Approval Packet
```

---

## 5. Core Investment Theses

MoneyTrail should initially support two primary strategic theses.

### 5.1 Scarce Assets Thesis

Assets that may benefit from scarcity, debasement, geopolitical uncertainty, supply constraints, energy constraints or monetary instability.

Examples:

- Bitcoin
- Gold
- Energy infrastructure
- Uranium
- Power/grid infrastructure
- High-quality real assets
- Scarce digital networks

Evaluation questions:

- Is supply structurally constrained?
- Is demand increasing?
- Does it protect purchasing power?
- Does it benefit from liquidity expansion or currency debasement?
- Is it politically and regulatorily resilient?
- Is there a tradeable expression of this thesis?

### 5.2 AI Growth Thesis

Assets that may benefit from AI infrastructure, automation, compute demand, productivity growth, robotics, data centres and energy demand.

Examples:

- AI compute
- Semiconductors
- Networking
- Data centres
- Power/grid
- Cooling
- Robotics/autonomy
- AI software
- Energy storage

Evaluation questions:

- Is the asset a direct or second-order AI beneficiary?
- Is revenue already linked to AI demand?
- Is it exposed to compute, power, data, robotics, automation or infrastructure?
- Is valuation already pricing in perfection?
- Is capex growth sustainable?
- Is the asset the best expression of the thesis?

---

## 6. Source Strategy

MoneyTrail must separate discovery sources from evidence sources.

### 6.1 Discovery Sources

Used for attention, sentiment and narrative discovery.

Examples:

- InvestAnswers Patreon
- RealVision
- Jordi Visser content
- YouTube transcripts
- YouTube comments
- X/Twitter lists
- Newsletters
- Podcasts
- Community discussions

Used for:

- Asset mentions
- Narrative detection
- Sentiment
- Conviction language
- Crowding/euphoria detection
- Emerging themes

Discovery sources must not directly increase investment viability unless independently verified.

### 6.2 Tradeability Sources

Used to determine whether the bot can act.

Examples:

- Hyperliquid perpetual metadata
- Hyperliquid spot metadata
- Hyperliquid asset contexts
- Local account configuration
- Region/account eligibility settings

Used for:

- Venue availability
- Asset ID mapping
- Market type
- Liquidity
- Open interest
- Funding
- Spread/slippage estimate
- Trade decision eligibility

### 6.3 Crypto Research Sources

Used to validate crypto assets.

Examples:

- DefiLlama
- CoinGecko
- CoinMarketCap
- Token Terminal
- Artemis
- Dune dashboards
- Token Unlocks
- CryptoRank
- Nansen / Arkham, if available
- Project docs
- Governance forums
- Chain explorers
- GitHub

Used for:

- Market cap
- FDV
- Tokenomics
- Unlock schedule
- TVL
- Fees/revenue
- Stablecoin flows
- Developer activity
- Wallet concentration
- Exchange liquidity
- Protocol risk

### 6.4 Equity Research Sources

Used to validate stocks.

Examples:

- SEC EDGAR
- Company investor relations pages
- Annual reports
- 10-K / 10-Q / 8-K filings
- Earnings transcripts
- Company presentations
- Financial data providers
- Insider transactions
- 13F/institutional ownership data

Used for:

- Revenue growth
- CAGR
- Margins
- Free cash flow
- Debt
- Dilution
- Valuation
- Earnings quality
- Management commentary
- Catalysts

### 6.5 Macro and Liquidity Sources

Used for market regime assessment.

Examples:

- FRED
- Federal Reserve data
- RBA data
- Treasury data
- Trading Economics
- Global liquidity proxies
- Stablecoin supply data
- Yield curve data
- Dollar index data
- Credit spreads

Used for:

- Liquidity expansion/contraction
- Risk-on/risk-off regime
- Real rates
- Dollar strength
- Inflation pressure
- Credit stress
- Crypto liquidity support
- Scarce asset support

### 6.6 AI and Infrastructure Sources

Used to validate the AI growth thesis.

Examples:

- Hyperscaler earnings and capex reports
- Semiconductor industry commentary
- Data centre REIT reports
- Utility/grid reports
- Energy agencies
- AI infrastructure research
- Robotics and automation industry reports

Used for:

- AI capex trend
- Compute demand
- Data centre growth
- Power bottlenecks
- Grid constraints
- Robotics adoption
- Second-order AI beneficiaries

---

## 7. Core Modules

## 7.1 Source Collector

### Purpose

Collect raw source content from existing OpenClaw-accessible sources and local files.

### Responsibilities

- Pull new posts, transcripts and comments.
- Import local Markdown/transcript files.
- Deduplicate by content hash.
- Store source metadata.
- Preserve raw text for auditability.

### Inputs

- Existing OpenClaw source connectors
- Local Markdown files
- Transcripts
- Exported posts/comments

### Outputs

- Raw content records
- Source metadata
- Content hash

---

## 7.2 Raw Content Vault

### Purpose

Provide a local audit trail of all ingested content.

### Storage

- SQLite for metadata
- Local Markdown/text files for raw content snapshots

### Folder Example

```text
knowledge/raw/{source}/{date}/{content_id}.md
```

---

## 7.3 Asset Extractor

### Purpose

Extract investable assets, sectors, themes and trade ideas from messy content.

### Extracted Entities

- Stock tickers
- Company names
- Crypto tickers
- Crypto names
- ETFs
- Commodities
- Macro instruments
- Sectors
- Themes
- Options ideas
- Trade actions

### Output Fields

```json
{
  "raw_mention": "SOL",
  "resolved_asset": "Solana",
  "symbol": "SOL",
  "asset_type": "crypto",
  "context_snippet": "Solana has one of the best risk/reward setups...",
  "investment_intent": "bullish thesis",
  "sentiment": "bullish",
  "time_horizon": "cycle trade",
  "confidence": 0.94,
  "needs_review": false
}
```

### Special Handling

The extractor must treat comments as low-quality input for viability, but useful input for attention and euphoria detection.

---

## 7.4 Entity Resolver

### Purpose

Resolve ambiguous mentions and prevent false ticker matches.

### Examples of Ambiguity

| Mention | Possible Meaning |
|---|---|
| AI | Artificial intelligence theme or C3.ai ticker |
| ARM | Arm Holdings or ordinary word |
| META | Meta Platforms or generic concept |
| NEAR | NEAR Protocol or normal phrase |
| HYPE | Hyperliquid token or generic hype |
| RENDER | Render token or rendering concept |

### Rules

- Do not promote low-confidence mappings to research automatically.
- Require context-based resolution.
- Mark ambiguous items as `needs_review`.
- Do not execute or simulate using ticker string alone.

---

## 7.5 Tradeability Gate

### Purpose

Avoid researching or recommending assets that cannot be traded by the configured bot/venue.

### Checks

- Is the asset listed on Hyperliquid perps?
- Is the asset listed on Hyperliquid spot?
- Is the correct asset ID known?
- Is the asset available in the configured region/account?
- Is liquidity sufficient?
- Is open interest sufficient?
- Is funding acceptable?
- Is spread/slippage acceptable?
- Is there a valid tradeable proxy?

### States

| State | Meaning | Action |
|---|---|---|
| Tradeable | Listed, eligible and liquid | Full workflow |
| Research-only | Not tradeable, but thesis-relevant | Lightweight research |
| Proxy candidate | Direct asset unavailable, proxy available | Research proxy |
| Reject | Not tradeable and not thesis-critical | Log only |

### Hard Rules

- No tradeability, no trade decision.
- No liquidity, no position.
- No eligibility certainty, no execution.
- Never rely on ticker string alone for order construction.

---

## 7.6 Signal Scorer

### Purpose

Score the quality of the original signal before research.

### Signal Score Components

| Factor | Weight |
|---|---:|
| Investment intent | 25% |
| Sentiment strength | 15% |
| Source quality | 20% |
| Specificity | 15% |
| Repetition | 15% |
| Community confirmation | 10% |

### Output

```json
{
  "asset": "SOL",
  "mention_count_7d": 8,
  "source_count": 3,
  "sentiment": "bullish",
  "signal_score": 82,
  "crowding_score": 61,
  "research_priority": "high"
}
```

---

## 7.7 Research Prioritiser

### Purpose

Control token and API cost by deciding which assets deserve deep research.

### Research Levels

| Level | Name | Description |
|---:|---|---|
| 0 | Log only | Mention recorded, no research |
| 1 | Signal card | Basic summary |
| 2 | Quick research | Basic viability check |
| 3 | Full research pack | Detailed asset research |
| 4 | Active thesis tracking | Ongoing monitoring |

### Deep Research Triggers

- Signal score above threshold.
- Multiple high-quality sources.
- Asset is already owned.
- Asset is tradeable and liquid.
- Strong negative signal on owned asset.
- Thesis-critical asset.
- User explicitly requests research.

### Cost Controls

- Maximum deep research assets per day.
- Do not re-research stale low-quality assets too often.
- Summarise comments before using them.
- Deduplicate repeated claims.
- Use prior thesis memory.

---

## 7.8 Asset Research Engine

### Purpose

Assess whether an asset is a viable investment independent of social sentiment.

### Research Pack Structure

```markdown
# Asset Research Pack: [Asset]

## 1. Signal Summary
## 2. What People Are Saying
## 3. Independent Research
## 4. Money Flow
## 5. Bull Case
## 6. Bear Case
## 7. Pre-Mortem
## 8. Key Risks
## 9. Unknowns Register
## 10. Thesis Mapping
## 11. Tradeability and Liquidity
## 12. Entry Quality
## 13. LILO Strategy
## 14. Portfolio Fit
## 15. Final Viability Assessment
```

### Crypto Minimum Research Requirements

- Market cap
- FDV
- Token supply
- Unlocks
- Liquidity
- Exchange availability
- TVL / usage / fees where relevant
- Holder concentration where available
- Developer activity where relevant
- Regulatory/security risks
- Funding and open interest if perp tradeable

### Stock Minimum Research Requirements

- Business model
- Revenue growth
- CAGR where available
- Margins
- Free cash flow
- Debt
- Valuation
- Earnings trend
- Management commentary
- Insider/institutional activity where available
- Catalysts
- Bear case

---

## 7.9 Evidence Quality Scorer

### Purpose

Prevent polished but weak research packs.

### Evidence Labels

Each major claim must be classified as:

- Verified primary evidence
- Verified secondary evidence
- Model interpretation
- Social source claim
- Unknown
- Assumption

### Evidence Quality Score

| Component | Question |
|---|---|
| Freshness | Is the data current? |
| Source quality | Is it primary or secondary? |
| Completeness | Are key metrics present? |
| Verification | Are claims independently supported? |
| Critical unknowns | Are there unresolved fatal risks? |

### Rule

If critical facts are unverified, the asset cannot become a real candidate.

---

## 7.10 Thesis Mapper

### Purpose

Map each asset to strategic investment theses and determine whether it is a good expression of those theses.

### Outputs

```json
{
  "asset": "BTC",
  "scarce_assets_score": 95,
  "ai_growth_score": 5,
  "portfolio_role": "core scarce asset",
  "best_expression_rank": 1,
  "thesis_fit_score": 88
}
```

### Position Roles

| Role | Meaning |
|---|---|
| Core scarce asset | Long-term scarce asset holding |
| Core AI compounder | High-quality long-term AI/growth exposure |
| AI infrastructure | Second-order AI beneficiary |
| High-beta accelerator | Higher-risk growth/crypto exposure |
| Tactical satellite | Small asymmetric idea |
| Hedge | Defensive or diversifying position |
| Research-only | Interesting but not actionable |
| Reject | Not suitable |

---

## 7.11 Market Regime Brain

### Purpose

Assess the environment before making asset-level decisions.

### Regime States

- Liquidity expansion
- Liquidity contraction
- Risk-on expansion
- Risk-on but crowded
- Neutral/choppy
- Inflation scare
- AI capex boom
- Risk-off
- Crisis/capitulation

### Inputs

- Rates
- Real yields
- Dollar strength
- Credit spreads
- Stablecoin supply
- Equity breadth
- BTC/crypto liquidity
- Macro calendar
- AI capex commentary

### Output

```text
Current Market Regime:
Liquidity: neutral to improving
Risk appetite: medium
AI thesis: active but crowded
Scarce assets thesis: active
Action bias: hold/add selectively, avoid chasing crowded assets
```

---

## 7.12 Portfolio Heat Engine

### Purpose

Block new risk when portfolio risk is already too high.

### Heat Inputs

- Crypto beta exposure
- AI/growth exposure
- Solana ecosystem exposure
- Single-name concentration
- Dry powder level
- Leverage
- Crowding exposure
- Correlation/factor exposure
- Recent drawdown

### Output

```json
{
  "portfolio_heat": 84,
  "status": "high",
  "blocked_actions": ["new_high_beta_entries"],
  "allowed_actions": ["research", "simulation", "trim", "hedge"]
}
```

### Rule

If portfolio heat is above the configured threshold, new high-beta entries are blocked.

---

## 7.13 Friction-Adjusted Entry Gate

### Purpose

Ensure the expected upside is large enough to justify fees, spread, slippage, funding, tax/friction and volatility risk.

### Cost Stack

- Entry fee
- Exit fee
- Spread
- Slippage
- Funding
- Borrow/margin cost
- FX cost
- Tax/friction estimate
- Opportunity cost
- Volatility buffer

### Required Calculations

```text
Expected upside
Expected downside
Risk/reward
Round-trip friction
Probability-weighted expected value
Volatility buffer
Net opportunity
```

### Rule

No small edges in high-volatility assets.

If friction plus volatility buffer consumes the edge, the decision is:

```text
Good asset, bad entry.
```

---

## 7.14 Position Plan Generator

### Purpose

Create entry, stop loss, take profit and position size before any simulated or real entry.

### Required Fields

- Asset
- Venue
- Position role
- Time horizon
- Entry type
- Entry range
- Stop type
- Stop price or thesis invalidation
- Take-profit layers
- Re-entry plan
- Risk/reward
- Friction-adjusted EV
- Position size
- Funding source
- Expiry date

### Entry Types

- Pullback entry
- Breakout entry
- Reclaim entry
- Layered DCA entry
- Thesis-confirmation entry
- Capitulation entry
- No-entry

### Stop Types

- Price stop
- Thesis stop
- Time stop
- Volatility stop
- Portfolio stop
- Liquidity stop
- Event stop

### Rule

No plan, no entry.

---

## 7.15 LILO Manager

### Purpose

Manage Layer In / Layer Out logic for medium-to-long-term positions.

### Strategy

- Keep core positions for strong long-term theses.
- Manage tactical/speculative portions with layers.
- Use wider layers for volatile assets.
- Do not churn if fees/tax/friction make the layer unattractive.
- Layer out during euphoria, overvaluation or portfolio concentration.
- Layer back in only when the discount or risk/reward is meaningful.

### Example LILO Plan

```text
Asset: SOL
Core: 50%
Tactical: 35%
Speculative: 15%

TP1: +40% — sell 15% of tactical
TP2: +90% — sell 20% of tactical
TP3: +160% — sell 25% of tactical
Re-entry: only after 25–40% pullback or thesis-confirming reset
```

---

## 7.16 Shadow Portfolio Simulator

### Purpose

Test decisions before real action.

### Shadow Portfolios

- Current Portfolio
- MoneyTrail Best Ideas
- Scarce Assets
- AI Growth
- AI + Scarce Blend
- 33/33/33 Balanced
- LILO Managed
- Aggressive Rotation
- Conservative Rotation
- No-Rotation Benchmark

### Metrics

- Total return
- CAGR where applicable
- Volatility
- Max drawdown
- Turnover
- Risk-adjusted score
- Thesis alignment
- Hit rate
- False positives
- False negatives

### Priority

Forward shadow simulation should be trusted more than historical backtesting.

---

## 7.17 Rotation Engine

### Purpose

Assess whether newer entries are better than existing holdings.

### Rotation Conditions

A rotation candidate requires:

- New asset score materially higher than existing asset.
- Better thesis fit.
- Better portfolio diversification.
- Acceptable entry quality.
- Expected benefit exceeds tax/friction cost.
- Existing asset is weakening, euphoric, overweight or lower quality.

### Output

```text
Rotation Candidate:
Trim weak/high-beta satellite → add stronger AI infrastructure candidate.
Reason: better thesis fit, lower duplication, better risk/reward.
Status: simulate first.
```

---

## 7.18 Source Accountability Tracker

### Purpose

Measure source quality over time.

### Metrics

- Assets mentioned
- Mention date
- Price before mention
- Price after 7/30/90/180 days
- Max drawdown after mention
- Hit rate
- Asset-class strength
- Hype tendency
- Late-cycle tendency
- Accountability behaviour

### Source Usage Examples

- Use high-conviction macro sources for regime insight.
- Use influencer content for discovery.
- Use comments for euphoria/crowding only.
- Do not use comments for viability or position sizing.

---

## 7.19 Model Auditor

### Purpose

Evaluate whether MoneyTrail’s own recommendations are working.

### Weekly Audit Fields

- Best call
- Worst call
- False positive
- False negative
- Avoided loss
- Missed winner
- Overtrading warning
- Scoring threshold adjustment

### Example

```text
False Positive: HYPE
Initial score: 74
Outcome: -31%
Cause: comment sentiment overweighted, tokenomics underweighted
Adjustment: reduce comment contribution to signal score
```

---

## 7.20 Human Approval Packet

### Purpose

Provide a concise review packet before any real action.

### Template

```text
Real Action Review

Asset:
Action:
Size:
Entry:
Stop:
Take profit:
Expected upside:
Expected downside:
Risk/reward:
Fees/slippage/funding:
Tax/friction:
Why now:
Why not wait:
What could go wrong:
Funding source:
Expiry:
Approve / reject / modify:
```

### Rule

Real actions require explicit user approval.

---

## 8. Database Design

SQLite is recommended for the first release.

### 8.1 `raw_content`

```sql
CREATE TABLE raw_content (
  id TEXT PRIMARY KEY,
  source_name TEXT,
  source_type TEXT,
  title TEXT,
  author TEXT,
  url TEXT,
  published_at TEXT,
  collected_at TEXT,
  content_hash TEXT,
  raw_text TEXT
);
```

### 8.2 `asset_mentions`

```sql
CREATE TABLE asset_mentions (
  id TEXT PRIMARY KEY,
  content_id TEXT,
  raw_mention TEXT,
  resolved_asset TEXT,
  symbol TEXT,
  asset_type TEXT,
  confidence REAL,
  context_snippet TEXT,
  sentiment TEXT,
  intent TEXT,
  time_horizon TEXT,
  conviction_score REAL,
  created_at TEXT
);
```

### 8.3 `asset_signals`

```sql
CREATE TABLE asset_signals (
  id TEXT PRIMARY KEY,
  asset TEXT,
  symbol TEXT,
  asset_type TEXT,
  first_seen TEXT,
  last_seen TEXT,
  mention_count INTEGER,
  source_count INTEGER,
  average_sentiment REAL,
  signal_score REAL,
  crowding_score REAL,
  research_priority TEXT,
  status TEXT
);
```

### 8.4 `venue_assets`

```sql
CREATE TABLE venue_assets (
  id TEXT PRIMARY KEY,
  venue TEXT,
  market_type TEXT,
  symbol TEXT,
  asset_id INTEGER,
  base_asset TEXT,
  quote_asset TEXT,
  is_listed INTEGER,
  is_tradeable INTEGER,
  min_size REAL,
  sz_decimals INTEGER,
  max_leverage REAL,
  margin_table_id INTEGER,
  last_price REAL,
  volume_24h REAL,
  open_interest REAL,
  funding_rate REAL,
  liquidity_score REAL,
  last_checked TEXT
);
```

### 8.5 `asset_tradeability`

```sql
CREATE TABLE asset_tradeability (
  id TEXT PRIMARY KEY,
  extracted_asset TEXT,
  resolved_asset TEXT,
  venue TEXT,
  direct_match INTEGER,
  proxy_match INTEGER,
  proxy_asset TEXT,
  region_allowed INTEGER,
  venue_available INTEGER,
  liquidity_ok INTEGER,
  trade_allowed INTEGER,
  research_mode TEXT,
  reason TEXT,
  checked_at TEXT
);
```

### 8.6 `research_packs`

```sql
CREATE TABLE research_packs (
  id TEXT PRIMARY KEY,
  asset TEXT,
  symbol TEXT,
  asset_type TEXT,
  created_at TEXT,
  research_level INTEGER,
  research_summary TEXT,
  bull_case TEXT,
  bear_case TEXT,
  risks TEXT,
  unknowns TEXT,
  evidence_quality_score REAL,
  viability_score REAL,
  thesis_fit_score REAL,
  portfolio_fit_score REAL,
  final_decision TEXT,
  markdown_path TEXT
);
```

### 8.7 `asset_theses`

```sql
CREATE TABLE asset_theses (
  asset TEXT PRIMARY KEY,
  thesis_summary TEXT,
  thesis_status TEXT,
  thesis_lifecycle_stage TEXT,
  conviction_score REAL,
  scarce_asset_score REAL,
  ai_growth_score REAL,
  invalidation_conditions TEXT,
  add_conditions TEXT,
  trim_conditions TEXT,
  last_reviewed TEXT
);
```

### 8.8 `lilo_profiles`

```sql
CREATE TABLE lilo_profiles (
  asset TEXT PRIMARY KEY,
  asset_type TEXT,
  conviction TEXT,
  volatility TEXT,
  trend_view TEXT,
  strategy_mode TEXT,
  core_percentage REAL,
  tactical_percentage REAL,
  speculative_percentage REAL,
  aggression_level TEXT,
  layer_out_count INTEGER,
  layer_in_count INTEGER,
  tax_sensitivity TEXT,
  notes TEXT
);
```

### 8.9 `position_plans`

```sql
CREATE TABLE position_plans (
  id TEXT PRIMARY KEY,
  asset TEXT,
  venue TEXT,
  market_type TEXT,
  position_role TEXT,
  time_horizon TEXT,
  entry_type TEXT,
  entry_min REAL,
  entry_max REAL,
  stop_type TEXT,
  stop_price REAL,
  thesis_invalidation TEXT,
  risk_per_position_pct REAL,
  max_position_size_pct REAL,
  take_profit_plan TEXT,
  reentry_plan TEXT,
  risk_reward REAL,
  friction_adjusted_ev REAL,
  status TEXT,
  created_at TEXT,
  expires_at TEXT
);
```

### 8.10 `take_profit_layers`

```sql
CREATE TABLE take_profit_layers (
  id TEXT PRIMARY KEY,
  plan_id TEXT,
  asset TEXT,
  layer_number INTEGER,
  target_price REAL,
  sell_percentage REAL,
  reason TEXT,
  status TEXT,
  triggered_at TEXT
);
```

### 8.11 `shadow_portfolios`

```sql
CREATE TABLE shadow_portfolios (
  id TEXT PRIMARY KEY,
  name TEXT,
  description TEXT,
  strategy_type TEXT,
  created_at TEXT,
  is_active INTEGER
);
```

### 8.12 `shadow_positions`

```sql
CREATE TABLE shadow_positions (
  id TEXT PRIMARY KEY,
  portfolio_id TEXT,
  asset TEXT,
  asset_type TEXT,
  entry_date TEXT,
  entry_price REAL,
  allocation_pct REAL,
  quantity REAL,
  thesis TEXT,
  entry_reason TEXT,
  status TEXT
);
```

### 8.13 `simulation_results`

```sql
CREATE TABLE simulation_results (
  id TEXT PRIMARY KEY,
  portfolio_id TEXT,
  run_date TEXT,
  total_return REAL,
  cagr REAL,
  volatility REAL,
  max_drawdown REAL,
  sharpe_like REAL,
  turnover REAL,
  portfolio_score REAL
);
```

### 8.14 `rotation_candidates`

```sql
CREATE TABLE rotation_candidates (
  id TEXT PRIMARY KEY,
  from_asset TEXT,
  to_asset TEXT,
  reason TEXT,
  score_improvement REAL,
  tax_friction_estimate REAL,
  conviction_delta REAL,
  status TEXT,
  created_at TEXT
);
```

### 8.15 `model_decision_outcomes`

```sql
CREATE TABLE model_decision_outcomes (
  id TEXT PRIMARY KEY,
  asset TEXT,
  initial_decision TEXT,
  decision_date TEXT,
  entry_price REAL,
  price_7d REAL,
  price_30d REAL,
  price_90d REAL,
  max_drawdown_90d REAL,
  outcome_score REAL
);
```

### 8.16 `source_scores`

```sql
CREATE TABLE source_scores (
  source_name TEXT PRIMARY KEY,
  source_type TEXT,
  base_credibility REAL,
  historical_accuracy REAL,
  signal_weight REAL,
  hype_tendency REAL,
  late_cycle_tendency REAL,
  notes TEXT
);
```

---

## 9. Folder Structure

```text
moneytrail-openclaw/
  README.md
  config/
    control_policy.yaml
    sources.yaml
    assets.yaml
    scoring.yaml
    research_rules.yaml
    thesis_budget.yaml
    tradeability.yaml
    friction_entry.yaml
    portfolio_rules.yaml
    telegram.yaml
  data/
    moneytrail.sqlite
  knowledge/
    raw/
    processed/
    research_packs/
    weekly_memos/
    asset_theses/
    decision_journal/
    unknowns_register/
  agents/
    source_collector.md
    asset_extractor.md
    entity_resolver.md
    tradeability_gate.md
    signal_scorer.md
    research_agent.md
    evidence_quality_agent.md
    thesis_mapper.md
    market_regime_agent.md
    portfolio_heat_agent.md
    entry_quality_agent.md
    lilo_agent.md
    simulator_agent.md
    rotation_agent.md
    source_accountability_agent.md
    model_auditor.md
    report_agent.md
  scripts/
    ingest_sources.py
    extract_mentions.py
    resolve_assets.py
    refresh_hyperliquid_universe.py
    check_tradeability.py
    score_signals.py
    run_research.py
    update_thesis_memory.py
    generate_position_plan.py
    simulate_portfolios.py
    generate_daily_digest.py
    generate_weekly_memo.py
  dashboards/
    here_now_spec.md
    dashboard_data.json
  prompts/
    extraction_prompt.md
    research_prompt.md
    contrarian_prompt.md
    premortem_prompt.md
    portfolio_prompt.md
  logs/
  tests/
```

---

## 10. Configuration Design

## 10.1 Master Control Policy

```yaml
mode:
  execution: disabled
  real_trade_requires_user_approval: true
  max_research_cost_per_day_usd: 5
  max_llm_calls_per_day: 100
  max_deep_research_assets_per_day: 3

allowed_actions:
  - ingest_sources
  - extract_assets
  - score_signals
  - create_research_packs
  - create_shadow_positions
  - simulate_portfolios
  - send_telegram_alerts

blocked_actions:
  - real_trade_execution
  - leverage_increase
  - wallet_transfer
  - approve_token_spend
  - export_private_keys
```

## 10.2 Tradeability Rules

```yaml
tradeability_rules:
  require_tradeability_before_deep_research: true
  allow_research_only_if_thesis_critical: true
  require_region_eligibility_confirmation: true
  block_trade_if_region_uncertain: true
  refresh_before_trade_decision: true
  never_use_ticker_string_only: true

liquidity_gate:
  min_24h_volume_usd: 10000000
  min_open_interest_usd: 5000000
  max_spread_bps: 20
  max_price_impact_for_order_bps: 30
```

## 10.3 Friction-Adjusted Entry Rules

```yaml
friction_adjusted_entry:
  enabled: true

  minimum_gross_upside:
    btc_core: 0.20
    major_crypto: 0.30
    high_beta_alt: 0.60
    speculative_token: 1.00
    high_growth_equity: 0.25
    index_etf: 0.10

  minimum_risk_reward:
    btc_core: 2.0
    major_crypto: 2.5
    high_beta_alt: 3.0
    speculative_token: 4.0
    high_growth_equity: 2.0
    index_etf: 1.5

  max_friction_as_pct_of_expected_upside: 0.10

  volatility_buffer:
    btc_core: 0.08
    major_crypto: 0.12
    high_beta_alt: 0.20
    speculative_token: 0.30
    high_growth_equity: 0.10
    index_etf: 0.04
```

## 10.4 Portfolio Rules

```yaml
allocation_rules:
  minimum_dry_powder: 0.10
  max_single_stock: 0.15
  max_single_crypto_asset: 0.15
  max_total_crypto_beta: 0.35
  max_tactical_satellites: 0.10
  max_new_position_starter: 0.02
  max_new_position_full_size: 0.05
  max_weekly_turnover: 0.05
  require_user_approval_for_real_action: true

thesis_budget:
  scarce_assets:
    target: 0.25
    max: 0.40
  ai_growth:
    target: 0.30
    max: 0.40
  crypto_beta:
    target: 0.20
    max: 0.35
  tactical_satellites:
    target: 0.05
    max: 0.10
  dry_powder:
    target: 0.10
    min: 0.075
```

---

## 11. Scoring Framework

## 11.1 Signal Score

Measures the quality of the original mention.

```text
Signal Score =
  25% investment intent
+ 15% sentiment strength
+ 20% source quality
+ 15% specificity
+ 15% repetition
+ 10% community confirmation
```

## 11.2 Research Score

Measures whether the asset is independently viable.

```text
Research Score =
  25% fundamentals / usage quality
+ 20% growth / adoption
+ 15% valuation / tokenomics
+ 15% money flow
+ 15% risk profile
+ 10% timing
```

## 11.3 Thesis Fit Score

Measures strategic alignment.

```text
Thesis Fit Score =
  30% alignment with core thesis
+ 20% trend strength
+ 20% evidence quality
+ 15% valuation / entry quality
+ 15% portfolio usefulness
```

## 11.4 Entry Quality Score

Measures whether now is a good time to enter.

```text
Entry Quality =
  25% expected upside
+ 25% risk/reward
+ 20% friction-adjusted EV
+ 15% timing
+ 10% liquidity/exit quality
+ 5% funding/tax impact
```

## 11.5 Portfolio Score

Measures allocation quality.

```text
Portfolio Score =
  30% risk-adjusted return
+ 20% thesis alignment
+ 15% max drawdown control
+ 10% liquidity
+ 10% diversification
+ 10% dry powder discipline
+ 5% tax/friction efficiency
```

---

## 12. Decision Ladder

Every asset should progress through a controlled ladder.

```text
Mentioned
↓
Logged
↓
Watchlist
↓
Research Candidate
↓
Shadow Position
↓
Real Candidate
↓
Approved Position
↓
Active Thesis
↓
Trim / Exit / Archived
```

### Graduation to Real Candidate Requires

- Tradeability passed.
- Liquidity passed.
- Research score above threshold.
- Evidence quality medium/high.
- Thesis fit strong.
- Entry quality acceptable.
- Portfolio heat acceptable.
- Position plan complete.
- Friction-adjusted upside attractive.
- Human approval packet generated.

---

## 13. Daily Workflow

```text
1. Collect new content.
2. Deduplicate raw content.
3. Extract assets and themes.
4. Resolve tickers/entities.
5. Refresh Hyperliquid universe if required.
6. Check tradeability.
7. Score signals.
8. Update Idea Ledger.
9. Determine research priority.
10. Create quick/full research packs where triggered.
11. Update thesis memory.
12. Update shadow portfolios.
13. Generate Telegram daily digest.
14. Update here.now dashboard data.
```

### Daily Telegram Example

```text
🧭 MoneyTrail Daily

Processed:
- 7 posts/transcripts
- 184 comments
- 23 asset mentions
- 8 unique assets

Top signals:
1. SOL — Bullish — Score 82
   Tradeability: Hyperliquid yes
   Action: Existing holding — monitor, no chase

2. COIN — Bullish — Score 76
   Tradeability: no direct Hyperliquid match
   Action: research-only / proxy review

3. HYPE — Speculative — Score 68
   Tradeability: yes
   Action: simulate only, crowding high

Blocked:
- XYZ — not tradeable, no useful proxy

Portfolio heat: 78/100
Action bias: research and simulate; avoid new high-beta chase
```

---

## 14. Weekly Workflow

```text
1. Review core theses.
2. Update market regime.
3. Review portfolio heat.
4. Run shadow portfolio simulations.
5. Compare current allocation against alternatives.
6. Review source accountability.
7. Audit model decisions.
8. Generate rotation candidates.
9. Prune watchlist.
10. Produce weekly memo.
```

### Weekly Memo Example

```text
🧭 MoneyTrail Weekly Portfolio Lab

Core Thesis State:
- Scarce Assets: Active, 78/100
- AI Growth: Active but crowded, 82/100
- Crypto Beta: Mixed, 66/100

Best simulated allocation:
AI + Scarce Blend
Score: 83/100
Max drawdown: controlled vs aggressive crypto basket

New entries this week:
- HYPE: simulated only, no real action
- AI power infrastructure theme: research candidate

Rotation candidates:
- Reduce weak crypto satellite exposure if euphoria rises
- Research AI power/grid as second-order AI exposure

Model audit:
- Reject/euphoria filter continues to add value
- Watchlist category too broad; threshold review recommended

Recommended real portfolio changes:
None.
Reason: no candidate cleared all gates after friction, entry quality and portfolio heat checks.
```

---

## 15. here.now Dashboard Design

## 15.1 Signal Radar

| Asset | Mentions | Sources | Sentiment | Signal Score | Status |
|---|---:|---:|---|---:|---|
| SOL | 8 | 3 | Bullish | 82 | Existing holding |
| HYPE | 6 | 1 | Speculative | 68 | Simulate |
| COIN | 4 | 2 | Bullish | 76 | Research-only |

## 15.2 Tradeability Board

| Asset | Venue | Market | Tradeable | Liquidity | Action |
|---|---|---|---|---|---|
| SOL | Hyperliquid | Perp | Yes | Pass | Full workflow |
| HYPE | Hyperliquid | Spot/Perp | Yes | Watch | Simulate |
| NVDA | Hyperliquid | N/A | No | N/A | Research-only |

## 15.3 Thesis Board

| Thesis | Strength | Lifecycle | Crowding | Best Expressions |
|---|---:|---|---|---|
| Scarce Assets | 78 | Accumulating | Medium | BTC, gold, energy |
| AI Growth | 82 | Expansion/crowded | High | power, networking, robotics |
| Crypto Beta | 66 | Mixed | Medium/high | BTC, SOL, COIN proxies |

## 15.4 LILO Board

| Asset | Role | LILO Mode | Current Action | Next Layer |
|---|---|---|---|---|
| BTC | Core scarce | Conservative | Hold | Add on major drawdown |
| SOL | High-beta crypto | Aggressive | Hold / prepare trim | TP1 if euphoria |
| HYPE | Satellite | Very aggressive | Sim only | No real entry |

## 15.5 Best Allocation Board

| Allocation | Return | Max DD | Volatility | Thesis Fit | Score |
|---|---:|---:|---:|---:|---:|
| Current Portfolio | +12% | -21% | High | 76 | 68 |
| 33/33/33 Balanced | +10% | -13% | Medium | 82 | 79 |
| AI + Scarce | +15% | -17% | Medium/high | 88 | 83 |
| LILO Managed | +14% | -12% | Medium | 84 | 86 |

## 15.6 Model Audit Board

| Category | Outcome |
|---|---|
| Best call | Asset that performed well after strong score |
| Worst call | Asset that failed after high score |
| Avoided loss | Rejected asset that fell materially |
| Missed winner | Rejected asset that rallied materially |
| Adjustment | Scoring threshold changes |

---

## 16. Prompts

## 16.1 Asset Extraction Prompt

```text
You are an investment entity extraction agent.

Given the content below, extract all investable assets, tickers, crypto assets, ETFs, commodities, sectors, macro instruments and options trade ideas.

For each item return:
- raw mention
- resolved asset name
- ticker if known
- asset type
- context snippet
- whether this was an actual investment idea
- sentiment: bullish, bearish, neutral, mixed
- investment intent: buy, sell, hold, watch, trim, hedge, educational, casual mention
- time horizon if implied
- confidence score from 0 to 100
- reason for classification

Ignore casual mentions that clearly have no investment relevance, but include uncertain cases with low confidence.
```

## 16.2 Research Prompt

```text
You are a rigorous investment research analyst.

Research the following asset as a potential medium-to-long-term investment. Do not rely only on the social-source thesis. Independently assess whether this is viable.

You must cover:
1. What the asset is
2. Why it was mentioned
3. Bull case
4. Bear case
5. Fundamentals or usage
6. Growth profile and CAGR where applicable
7. Valuation or tokenomics
8. Money flow / market structure
9. Key risks
10. What would invalidate the thesis
11. Portfolio suitability
12. Evidence quality
13. Final viability score
14. Recommended action

Be sceptical. Penalise hype, weak evidence, poor liquidity, bad tokenomics, extreme valuation and over-concentration.
```

## 16.3 Pre-Mortem Prompt

```text
Assume this investment loses 50% over the next 12 months.

Explain the most likely reasons.
Which warning signs would have been visible today?
What data should be monitored weekly to catch this early?
What would prove that the thesis is failing?
```

## 16.4 Position Plan Prompt

```text
Create a position plan for this asset.

Include:
- position role
- time horizon
- entry type
- entry range
- stop loss or thesis invalidation
- take-profit layers
- re-entry rules
- risk/reward
- friction-adjusted EV
- suggested starter size
- target size
- maximum size
- funding source
- expiry date

If any required element is missing or weak, return no-entry.
```

---

## 17. Risk Controls

### 17.1 No-Trade Conditions

No simulated or real entry if:

- Asset is not tradeable and not thesis-critical.
- Region/account eligibility is uncertain.
- Liquidity fails minimum threshold.
- Research pack is stale.
- Evidence quality is low.
- Critical unknowns remain.
- Portfolio heat is too high.
- Entry quality is poor.
- Upside does not justify fees, slippage, funding and volatility.
- Position plan is incomplete.
- Human approval has not been given for real action.

### 17.2 Anti-FOMO Circuit Breaker

If price has moved sharply and social sentiment is euphoric:

```text
No new entry.
Existing position: consider LILO layer-out.
```

### 17.3 Correlation and Factor Risk

Track exposure to:

- Crypto beta
- AI/growth beta
- Liquidity beta
- Solana ecosystem
- High-beta equities
- Scarce assets
- USD/rates sensitivity
- Energy/power

### 17.4 Watchlist Pruning

Remove assets from active watchlist if:

- No meaningful mention for 60 days.
- Research score below threshold.
- Evidence quality remains low.
- Thesis no longer active.
- Shadow return underperforms materially.

Archived assets remain in the Idea Ledger.

---

## 18. Security and Access Controls

### 18.1 Secrets

- Do not store raw passwords in repository.
- Do not commit cookies or tokens.
- Use local secrets files excluded by `.gitignore`.
- Separate source collection from decisioning.
- Keep source content local unless explicitly exported.

### 18.2 Execution Safety

Initial mode must be execution disabled.

Blocked by default:

- Real trade execution
- Leverage increase
- Wallet transfer
- Token approvals
- Private key export
- Automatic order placement

### 18.3 Auditability

Every recommendation must log:

- Date
- Asset
- Source signal
- Research status
- Scores
- Decision
- Rationale
- User approval status
- Outcome tracking reference

---

## 19. Delivery Roadmap

## Phase 1: Signal Capture MVP

### Scope

- Source ingestion
- Raw content vault
- Asset extraction
- Entity resolution
- Idea Ledger
- Basic signal scoring
- Daily Telegram digest

### Success Criteria

- Assets are extracted accurately from posts/transcripts/comments.
- Duplicates are reduced.
- Mentions are logged with context.
- Daily summary is useful.

---

## Phase 2: Tradeability Gate

### Scope

- Hyperliquid universe cache
- Perp/spot metadata refresh
- Asset ID mapping
- Liquidity gate
- Research-only classification

### Success Criteria

- Untradeable assets are blocked from trade workflow.
- Tradeable assets are correctly matched to venue metadata.
- Liquidity warnings are generated.

---

## Phase 3: Research Pack Generator

### Scope

- Quick research
- Full research packs
- Evidence quality scoring
- Crypto and stock minimum research requirements
- Markdown output

### Success Criteria

- Research packs separate social claims from verified evidence.
- Critical unknowns are captured.
- Viability score is traceable.

---

## Phase 4: Thesis + Regime Layer

### Scope

- Scarce assets thesis
- AI growth thesis
- Thesis mapping
- Market regime brain
- Thesis lifecycle tracking
- Best expression ranking

### Success Criteria

- Assets are mapped to strategic theses.
- Reports distinguish strong thesis from good entry.
- Dashboard shows thesis strength and crowding.

---

## Phase 5: Portfolio Lab

### Scope

- Shadow portfolios
- Simulation results
- Best allocation board
- Model outcome tracking
- Source accountability
- Weekly memo

### Success Criteria

- Agent decisions can be measured.
- Strong candidates, rejects and watchlist ideas are tracked.
- Shadow portfolio performance is visible.

---

## Phase 6: Position Planning + LILO

### Scope

- Entry plans
- Stop loss / thesis invalidation
- Take-profit layers
- Re-entry rules
- LILO manager
- Friction-adjusted entry gate

### Success Criteria

- No candidate can progress without entry, stop, take profit and position sizing.
- High-volatility assets require sufficient upside.
- LILO layers are wide enough to justify friction.

---

## Phase 7: Human Approval Workflow

### Scope

- Real Action Review packet
- Approval/reject/modify tracking
- Decision journal
- Outcome linkage

### Success Criteria

- No real action is recommended without a complete approval packet.
- User decisions are logged and auditable.
- Agent remains decision-support, not unattended execution.

---

## 20. Final System Rules

1. Social sentiment discovers ideas; it does not validate investments.
2. Primary evidence and market data drive viability.
3. No tradeability means no trade decision.
4. No liquidity means no position.
5. No small edges in high-volatility assets.
6. Good asset does not mean good entry.
7. Good entry does not mean good portfolio fit.
8. Core holdings use thesis stops; tactical positions use price/volatility stops.
9. Every real candidate needs entry, stop loss, take profit, position size and expiry.
10. Most days, the best decision may be no action.
11. Forward simulation is more important than backtest optimisation.
12. The model must audit its own mistakes.
13. Human approval is required before real execution.

---

## 21. Definition of Success

MoneyTrail is successful if it:

- Finds useful investment ideas earlier.
- Reduces FOMO.
- Avoids untradeable or illiquid opportunities.
- Separates hype from evidence.
- Identifies crowded/euphoric assets.
- Improves portfolio discipline.
- Tracks whether its recommendations work.
- Helps decide when to watch, enter, hold, trim, rotate or reject.
- Produces concise, actionable Telegram and here.now outputs.

The system should not be judged only by immediate profit. It should first be judged by whether it improves decision quality, risk control, evidence discipline and portfolio allocation over time.


---

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|---------|
| 1 | CEO | Build as designed (7 phases, 20 modules) | Mechanical | P6 (bias toward action) + user premise P4 confirmed | User confirmed 7-phase roadmap as premise | Options B (inverted) and C (3-phase) |
| 2 | CEO | Add LLM output validation layer (Pydantic) | Mechanical | P1 (completeness) + P2 (blast radius < 1 file) | Critical safety gap; affects every pipeline stage; 1-file fix | Deferring |
| 3 | CEO | Add asset_thesis_scores junction table | Mechanical | P5 (explicit) + P2 (blast radius = schema only) | Fixes asset-as-primary-key breaking multi-thesis assets; schema-only change | Deferring |
| 4 | CEO | Add conviction override fast-track path | Mechanical | P1 (completeness) | Prevents paralysis for high-conviction existing holdings; in blast radius | No fast-track |
| 5 | CEO | Defer multi-venue abstraction to TODOS | Mechanical | P3 (pragmatic) + outside blast radius | Multi-week effort; outside Hyperliquid scope per user premise P2 | In-scope now |
| 6 | CEO | Defer third thesis (capital preservation) | Mechanical | P3 (pragmatic) | Medium severity; additive later; not blocking Phase 1 | In-scope now |
| 7 | Design | Dashboard delivery: add `delivery_mechanism` spec to Section 15 | TASTE DECISION | P5 (explicit) | Static HTML file vs local web server affects entire frontend impl | Left ambiguous |
| 8 | Design | Require per-board data freshness timestamp | Mechanical | P1 (completeness) + P5 (explicit) | Critical missing state; stale data presented as current is dangerous in financial context | Omit |
| 9 | Design | Define information hierarchy (landing view vs secondary) | Mechanical | P5 (explicit) | No primary view defined; implementer will invent convention | Flat list of 6 boards |
| 10 | Design | Define empty/error states for each board | Mechanical | P1 (completeness) | 4 critical states missing; first-run experience is undefined | Happy path only |
| 11 | Design | Color convention (Red/Amber/Green/Gray) | TASTE DECISION | P5 (explicit) — neutral posture | Specific colors are a taste call; convention itself is required | No color spec |
| 12 | Eng | Add price_history table and refresh_prices.py | Mechanical | P1 (completeness) + P2 (blast radius) | Shadow simulation fundamentally broken without price data | Defer |
| 13 | Eng | Add real_positions table (missing from schema) | Mechanical | P2 (blast radius = 1 table) | Portfolio Heat Engine references current holdings; no table exists | Defer |
| 14 | Eng | Add resolution_queue table for entity ambiguity | Mechanical | P1 (completeness) | needs_review items currently have no human/system resolution path | Defer |
| 15 | Eng | Add pipeline_runs table for restartability | Mechanical | P5 (explicit) | Stage error propagation undefined; partial-state DB is unrecoverable | Defer |
| 16 | Eng | Specify SQLite WAL mode + busy_timeout in init_db.py | Mechanical | P5 (explicit) + P3 (pragmatic) | Concurrent writers will produce SQLITE_BUSY silently | Defer |
| 17 | Eng | Define scoring normalization in scoring.yaml | Mechanical | P1 (completeness) | Composite scores compute wrong values if inputs aren't normalized; Model Auditor cannot explain scores | Defer |
| 18 | DX | Add SETUP.md with install, init, smoke test | Mechanical | P1 (completeness) | TTHW currently 0 — zero path from plan to working system | Defer |
| 19 | DX | Document all 9 config schemas with defaults | Mechanical | P1 (completeness) | 5 of 9 configs undocumented; developer cannot configure system | Defer |
| 20 | DX | Add example agent.md with OpenClaw format | Mechanical | P5 (explicit) | 17 agent files must be created; no format example exists anywhere | Defer |
| 21 | DX | Specify macOS launchd scheduler config | Mechanical | P1 (completeness) | Daily automation cannot be set up without scheduler config | Defer |
| 22 | DX | Add logs/ strategy and debug runbook | Mechanical | P1 (completeness) | Zero debuggability when pipeline fails silently | Defer |

