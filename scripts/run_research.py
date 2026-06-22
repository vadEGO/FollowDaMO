#!/usr/bin/env python3
"""
Steps 8-9 — Research pack generation (agent-driven).

MoneyTrail no longer calls an LLM API directly. Research is done by the coding
agent (Claude Code) via the `moneytrail-research` skill, using its own model
setup. This script is a thin shim that PREPARES the brief; the agent does the
analysis and research_ingest.py validates + stores it.

Flow:
    1. research_prepare.py  — build the brief (this stage, deterministic)
    2. agent analyses        — writes knowledge/research_results/{SYMBOL}.json
    3. research_ingest.py    — validate + write research_packs

Usage:
    python scripts/run_research.py --asset BTC      # prepares the brief
    python scripts/run_research.py --priority-only  # legacy no-op (pipeline compat)
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser(description="Prepare an agent research brief for one asset")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--priority-only", action="store_true",
                        help="Legacy no-op kept for pipeline-stage compatibility")
    parser.add_argument("--asset", help="Symbol to research, e.g. BTC")
    args = parser.parse_args()

    if args.priority_only:
        print("[run_research] --priority-only is a no-op (agent-driven single-pass model).")
        return

    if not args.asset:
        print("[run_research] no --asset given. Use: python scripts/run_research.py --asset BTC")
        return

    # Delegate to the prepare step. The agent (moneytrail-research skill) then does
    # the analysis and ingest — see ~/MoneyTrail/.claude/skills/moneytrail-research.
    cmd = [sys.executable, "scripts/research_prepare.py", "--asset", args.asset.upper()]
    if args.dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode == 0:
        print("[run_research] Brief ready. The agent must now analyse and run research_ingest.py.")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
