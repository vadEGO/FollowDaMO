#!/usr/bin/env python3
"""Steps 8-9 — Research prioritisation and pack generation. Implements: agents/research_agent.md"""
import argparse, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--priority-only", action="store_true")
    parser.add_argument("--asset", help="Research a specific asset")
    args = parser.parse_args()
    print("[run_research] stub — see agents/research_agent.md")

if __name__ == "__main__":
    main()
