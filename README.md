# MoneyTrail

Local OpenClaw-based investment intelligence and portfolio decision-support system.

Monitors investment discussions, extracts asset mentions, researches viable candidates, maps to core theses, simulates portfolio decisions, and produces human-reviewed recommendations via Telegram and a here.now dashboard.

**Core principle:** Signals discover ideas. Research validates ideas. Tradeability filters ideas. Simulation tests ideas. Position plans control risk. Human approval executes.

## Quick Start

See [SETUP.md](SETUP.md) for full setup instructions.

Minimum to get a Telegram digest running:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy secrets template and fill in your tokens
cp secrets/.env.example secrets/.env
# Edit secrets/.env — add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID at minimum

# 3. Initialise the database
python scripts/init_db.py

# 4. Smoke test — drop a file, run pipeline, check Telegram
cp tests/fixtures/sample_content.md knowledge/raw/test/sample.md
python scripts/run_daily.py --dry-run
```

## Architecture

```
Investment Sources → Source Collector → Raw Content Vault
  → Asset Extractor → Entity Resolver → Tradeability Gate
  → Signal Scorer → Research Prioritiser → Asset Research Engine
  → Evidence Quality Scorer → Thesis Mapper → Market Regime Brain
  → Portfolio Heat Engine → Entry Quality + Friction Gate
  → Position Plan Generator → Shadow Portfolio Simulator
  → Rotation Engine → Model Auditor
  → Telegram + here.now Dashboard + Human Approval Packet
```

## Folder Structure

```
moneytrail/
  config/           YAML configuration for all system rules
  data/             SQLite database (gitignored)
  knowledge/        Research packs, memos, theses, decision journal
  agents/           OpenClaw agent skill files
  scripts/          Python pipeline scripts
  prompts/          LLM prompt templates
  dashboards/       here.now dashboard spec and data output
  secrets/          Local secrets (gitignored)
  tests/            Unit, integration, and regression tests
  migrations/       SQLite migration files
  logs/             Pipeline run logs (gitignored)
```

## Operating Modes

- **Execution disabled** (default): research, simulate, recommend — no real trades
- **Real trade requires explicit approval**: every real action needs human sign-off

## Investment Theses

1. **Scarce Assets** — Bitcoin, gold, energy infrastructure, uranium, power/grid
2. **AI Growth** — compute, semiconductors, networking, data centres, robotics

## Delivery Roadmap

| Phase | Scope |
|---|---|
| 1 | Signal capture MVP: ingestion, extraction, Telegram digest |
| 2 | Tradeability gate: Hyperliquid universe, liquidity checks |
| 3 | Research pack generator: crypto and equity research |
| 4 | Thesis + regime layer: thesis mapping, market regime brain |
| 5 | Portfolio lab: shadow portfolios, simulation, source accountability |
| 6 | Position planning + LILO |
| 7 | Human approval workflow |
