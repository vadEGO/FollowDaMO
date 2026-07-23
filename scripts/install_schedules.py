#!/usr/bin/env python3
"""
install_schedules.py — Generate one launchd plist per scheduled section.

Reads config/sections.yaml and emits ~/Library/LaunchAgents/com.moneytrail.<section>.plist
for each section whose cadence is schedulable (daily / hourly / weekly). `on_demand`
sections (e.g. council, which is agent-driven and takes --topic) are skipped.

Each plist runs `run_section.py <section>`, giving every part of the analysis its
own independent cadence instead of one monolithic daily run. Dependent sections
(e.g. portfolio depends_on scores) are staggered a few minutes later so upstream
data is fresh first.

Usage:
    python scripts/install_schedules.py --print      # print plists to stdout, write nothing
    python scripts/install_schedules.py --write       # write plists to ~/Library/LaunchAgents
    python scripts/install_schedules.py --write --load # write + print launchctl load commands

This never calls `launchctl` itself — it prints the load commands so you stay in
control of what gets activated.
"""
import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
SECTIONS_YAML = ROOT / "config" / "sections.yaml"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOG_DIR = ROOT / "logs"

# Base run hour for daily sections; dependents are offset by DEP_STAGGER_MIN.
DAILY_HOUR = 7
DEP_STAGGER_MIN = 10


def _schedule_block(spec: dict, order: int) -> str:
    """Return the launchd scheduling XML for a section's cadence."""
    cadence = spec.get("cadence", "daily")
    if cadence == "hourly":
        return (
            "    <key>StartInterval</key>\n"
            "    <integer>3600</integer>\n"
        )
    if cadence == "weekly":
        return (
            "    <key>StartInterval</key>\n"
            "    <integer>604800</integer>\n"
        )
    # daily (default): stagger dependents a few minutes after the base hour
    minute = (order * DEP_STAGGER_MIN) % 60
    return (
        "    <key>StartCalendarInterval</key>\n"
        "    <dict>\n"
        f"        <key>Hour</key>\n        <integer>{DAILY_HOUR}</integer>\n"
        f"        <key>Minute</key>\n        <integer>{minute}</integer>\n"
        "    </dict>\n"
    )


def build_plist(section: str, spec: dict, order: int) -> str:
    label = f"com.moneytrail.{section}"
    runner = ROOT / "scripts" / "run_section.py"
    log = LOG_DIR / f"{section}.log"
    err = LOG_DIR / f"{section}.error.log"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"    <key>Label</key>\n    <string>{label}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"        <string>{sys.executable}</string>\n"
        f"        <string>{runner}</string>\n"
        f"        <string>{section}</string>\n"
        "    </array>\n"
        f"    <key>WorkingDirectory</key>\n    <string>{ROOT}</string>\n"
        + _schedule_block(spec, order) +
        f"    <key>StandardOutPath</key>\n    <string>{log}</string>\n"
        f"    <key>StandardErrorPath</key>\n    <string>{err}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def scheduled_sections() -> list[tuple[str, dict]]:
    data = yaml.safe_load(SECTIONS_YAML.read_text()) or {}
    out = []
    for name, spec in (data.get("sections") or {}).items():
        if spec.get("cadence", "daily") == "on_demand":
            continue
        out.append((name, spec))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate launchd plists per section")
    parser.add_argument("--print", dest="do_print", action="store_true",
                        help="Print plists, write nothing")
    parser.add_argument("--write", action="store_true",
                        help="Write plists to ~/Library/LaunchAgents")
    parser.add_argument("--load", action="store_true",
                        help="Also print launchctl load commands")
    args = parser.parse_args()
    if not (args.do_print or args.write):
        args.do_print = True  # default to safe preview

    sections = scheduled_sections()
    if not sections:
        print("No schedulable sections found in config/sections.yaml.")
        return

    LOG_DIR.mkdir(exist_ok=True)
    load_cmds = []
    for order, (name, spec) in enumerate(sections):
        plist = build_plist(name, spec, order)
        dest = LAUNCH_AGENTS / f"com.moneytrail.{name}.plist"
        if args.do_print and not args.write:
            print(f"\n# ── {dest} ({spec.get('cadence')}) ──")
            print(plist)
        if args.write:
            LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
            dest.write_text(plist)
            print(f"  wrote {dest}  [{spec.get('cadence')}]")
        load_cmds.append(f"launchctl load {dest}")

    if args.load or args.write:
        print("\n# To activate (run these yourself):")
        for cmd in load_cmds:
            print(f"  {cmd}")
        print("# To deactivate: launchctl unload <plist>")


if __name__ == "__main__":
    main()
