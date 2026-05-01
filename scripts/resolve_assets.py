#!/usr/bin/env python3
"""Step 3 — Resolve ambiguous asset mentions. Implements: agents/entity_resolver.md"""
# TODO Phase 1: implement context-based resolution logic
# See agents/entity_resolver.md for full spec
import argparse, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print("[resolve_assets] stub — see agents/entity_resolver.md")

if __name__ == "__main__":
    main()
