#!/usr/bin/env python3
"""Step 6 — Score signals using JOIN-based query. Implements: agents/signal_scorer.md"""
import argparse, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--idea-ledger", action="store_true")
    args = parser.parse_args()
    print("[score_signals] stub — see agents/signal_scorer.md")

if __name__ == "__main__":
    main()
