# MoneyTrail Setup Guide

## Prerequisites

- Python 3.10+
- OpenClaw installed and configured (for running agents)
- A Telegram bot token ([create one via @BotFather](https://t.me/botfather))
- Hyperliquid account (for Phase 2 tradeability checks)

## Step 1 — Install Python dependencies

```bash
cd ~/MoneyTrail
pip install -r requirements.txt
```

## Step 2 — Configure secrets

```bash
cp secrets/.env.example secrets/.env
```

Edit `secrets/.env` and fill in:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

Optional (required for later phases):
```
HYPERLIQUID_API_KEY=
HYPERLIQUID_API_SECRET=
OPENAI_API_KEY=          # or ANTHROPIC_API_KEY
COINGECKO_API_KEY=       # free tier works
```

## Step 3 — Initialise the database

```bash
python scripts/init_db.py
```

This creates `data/moneytrail.sqlite` with all tables and runs any pending migrations.

Verify:
```bash
python scripts/init_db.py --check
# Expected: "Schema version 1 OK — 16 tables created"
```

## Step 4 — Configure sources

Edit `config/sources.yaml`. For Phase 1, enable just one source — a local folder drop is the easiest:

```yaml
sources:
  - name: local_drop
    type: local_folder
    path: knowledge/raw/drop/
    enabled: true
    quality_weight: 0.6
```

## Step 5 — Smoke test

```bash
# Drop the sample content file
mkdir -p knowledge/raw/drop
cp tests/fixtures/sample_content.md knowledge/raw/drop/

# Run the Phase 1 pipeline (dry-run = no Telegram send)
python scripts/run_daily.py --dry-run

# Expected output:
# [source_collector] Processed 1 file, 1 new records
# [asset_extractor] Extracted N asset mentions
# [entity_resolver] Resolved N/N mentions (0 needs_review)
# [signal_scorer] Scored N assets
# [DRY RUN] Telegram digest ready — skipped send
```

Remove `--dry-run` to send to Telegram.

## Step 6 — Schedule daily runs (macOS)

Create a launchd plist to run every day at 7am:

```bash
cat > ~/Library/LaunchAgents/com.moneytrail.daily.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.moneytrail.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/YOURUSERNAME/MoneyTrail/scripts/run_daily.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/YOURUSERNAME/MoneyTrail/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOURUSERNAME/MoneyTrail/logs/launchd_error.log</string>
</dict>
</plist>
EOF

# Replace YOURUSERNAME, then load
launchctl load ~/Library/LaunchAgents/com.moneytrail.daily.plist
```

## Debugging a Failed Run

```bash
# 1. Check the latest run log
ls -t logs/ | head -3
tail -50 logs/run_$(date +%Y-%m-%d).log

# 2. Check pipeline stage statuses
python scripts/run_daily.py --status

# 3. Check database for last known state
python -c "
import sqlite3
conn = sqlite3.connect('data/moneytrail.sqlite')
for row in conn.execute('SELECT stage, status, error FROM pipeline_runs ORDER BY started_at DESC LIMIT 10'):
    print(row)
"
```

## Adding a New Source

1. Add an entry to `config/sources.yaml`
2. Add a row to `source_scores` table: `python scripts/manage_sources.py add --name NAME --type TYPE --quality 0.7`
3. Verify: `python scripts/ingest_sources.py --source NAME --dry-run`

## Phase Upgrades

Each phase adds new tables. Run migrations before using new features:

```bash
python scripts/init_db.py --migrate
# Applies any pending files in migrations/ in order
```
