#!/usr/bin/env python3
"""Update macro regime state in data/macro_regime.json.

Usage:
    python scripts/update_macro_regime.py --season summer --phase exp
    python scripts/update_macro_regime.py --country china rec --country japan slo
    python scripts/update_macro_regime.py --notes "Oil drawing down fast, stagflation risk rising"
    python scripts/update_macro_regime.py --conviction season=high phase=medium
    python scripts/update_macro_regime.py --season fall --phase slo --conviction season=high
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
REGIME_PATH = ROOT / "data" / "macro_regime.json"

VALID_SEASONS = {"spring", "summer", "fall", "winter"}
VALID_PHASES = {"rec", "exp", "slo", "con"}
VALID_CONVICTIONS = {"low", "medium", "high"}


def load_regime() -> dict:
    if REGIME_PATH.exists():
        return json.loads(REGIME_PATH.read_text())
    return {
        "last_updated": None,
        "updated_by": None,
        "active_season": None,
        "active_phase": None,
        "season_conviction": None,
        "phase_conviction": None,
        "season_notes": None,
        "phase_notes": None,
        "country_phases": {},
    }


def save_regime(data: dict) -> None:
    REGIME_PATH.write_text(json.dumps(data, indent=2) + "\n")


def parse_conviction(value: str) -> tuple[str, str]:
    """Parse 'season=high' or 'phase=medium' into (field, value)."""
    if "=" not in value:
        print(f"ERROR: conviction must be 'season=<level>' or 'phase=<level>', got: {value}", file=sys.stderr)
        sys.exit(1)
    key, level = value.split("=", 1)
    if key not in ("season", "phase"):
        print(f"ERROR: conviction key must be 'season' or 'phase', got: {key}", file=sys.stderr)
        sys.exit(1)
    if level not in VALID_CONVICTIONS:
        print(f"ERROR: conviction level must be one of {sorted(VALID_CONVICTIONS)}, got: {level}", file=sys.stderr)
        sys.exit(1)
    return key, level


def main() -> None:
    parser = argparse.ArgumentParser(description="Update macro regime state")
    parser.add_argument("--season", choices=sorted(VALID_SEASONS), help="Global macro season")
    parser.add_argument("--phase", choices=sorted(VALID_PHASES), help="Global growth momentum phase")
    parser.add_argument("--country", nargs=2, metavar=("NAME", "PHASE"), action="append",
                        help="Set phase for a country, e.g. --country china rec")
    parser.add_argument("--notes", help="Season notes (or use --phase-notes for phase-specific)")
    parser.add_argument("--phase-notes", help="Phase/momentum notes")
    parser.add_argument("--conviction", action="append", metavar="FIELD=LEVEL",
                        help="Set conviction, e.g. --conviction season=high --conviction phase=medium")
    parser.add_argument("--show", action="store_true", help="Print current state and exit")
    args = parser.parse_args()

    data = load_regime()

    if args.show:
        print(json.dumps(data, indent=2))
        return

    if not any([args.season, args.phase, args.country, args.notes, args.phase_notes, args.conviction]):
        parser.print_help()
        sys.exit(0)

    changed = False

    if args.season:
        data["active_season"] = args.season
        changed = True
        print(f"  Season → {args.season}")

    if args.phase:
        data["active_phase"] = args.phase
        changed = True
        print(f"  Phase → {args.phase}")

    if args.conviction:
        for conv in args.conviction:
            key, level = parse_conviction(conv)
            data[f"{key}_conviction"] = level
            changed = True
            print(f"  {key.capitalize()} conviction → {level}")

    if args.notes:
        data["season_notes"] = args.notes
        changed = True
        print(f"  Season notes → {args.notes[:60]}...")

    if args.phase_notes:
        data["phase_notes"] = args.phase_notes
        changed = True
        print(f"  Phase notes → {args.phase_notes[:60]}...")

    if args.country:
        if "country_phases" not in data or data["country_phases"] is None:
            data["country_phases"] = {}
        for country_name, phase in args.country:
            country_key = country_name.lower().replace(" ", "_")
            if phase not in VALID_PHASES:
                print(f"ERROR: phase for {country_name} must be one of {sorted(VALID_PHASES)}, got: {phase}", file=sys.stderr)
                sys.exit(1)
            data["country_phases"][country_key] = phase
            changed = True
            print(f"  {country_name} → {phase}")

    if changed:
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["updated_by"] = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
        save_regime(data)
        print(f"Saved to {REGIME_PATH}")
        print(f"Updated at {data['last_updated']} by {data['updated_by']}")
    else:
        print("No changes made.")


if __name__ == "__main__":
    main()
