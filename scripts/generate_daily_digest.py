#!/usr/bin/env python3
"""Steps 13-14 — Generate Telegram digest and update here.now dashboard.
Implements: agents/report_agent.md + agents/human_approval_agent.md"""
import argparse, os, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--here-now-only", action="store_true")
    args = parser.parse_args()
    print("[generate_daily_digest] stub — see agents/report_agent.md")
    if not args.dry_run:
        _send_telegram("🧭 MoneyTrail daily pipeline ran.\n(Full digest: coming in Phase 1)")

def _send_telegram(text: str):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "secrets" / ".env")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("  Telegram not configured — skipping send")
        return
    import httpx
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    httpx.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)

if __name__ == "__main__":
    main()
