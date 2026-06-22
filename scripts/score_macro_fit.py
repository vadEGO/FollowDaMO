#!/usr/bin/env python3
"""Score trade ideas against the active macro regime.

This is the bridge from macro analysis -> investment guidance: it reads the
current regime (data/macro_regime.json, set via update_macro_regime.py) and the
season playbook (config/macro_seasons.yaml), then scores how well each trade
idea's *direction* aligns with what the regime favours.

A long idea in an asset class the regime favours is a tailwind; a long idea in
a class the regime says to avoid is a headwind. Shorts invert. The magnitude is
scaled by season conviction, so a low-conviction regime nudges rather than
dominates.

Usage:
    # Score the live Supabase trade ideas (needs SUPABASE_* in secrets/.env.supabase)
    python scripts/score_macro_fit.py

    # Score AND persist results to Supabase rv_trade_idea_macro_fit (pipeline default)
    python scripts/score_macro_fit.py --write
    python scripts/score_macro_fit.py --write --dry-run   # show what would be upserted

    # Score ideas from a JSON file/stdin without touching the network
    python scripts/score_macro_fit.py --ideas-json path/to/ideas.json
    cat ideas.json | python scripts/score_macro_fit.py --ideas-json -

    # Print the active regime's resolved playbook and exit
    python scripts/score_macro_fit.py --explain
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).parent.parent
SEASONS_YAML = ROOT / "config" / "macro_seasons.yaml"
REGIME_JSON = ROOT / "data" / "macro_regime.json"

# How strongly the regime tilts the score, by season conviction. A neutral
# (regime-favoured class but only "low" conviction) tailwind moves the score
# less than a high-conviction one. Headwinds use the same magnitude, inverted.
CONVICTION_WEIGHT = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
    None: 0.6,  # unspecified -> treat as medium
}

# Map a trade idea's asset_class onto a key in the season asset_playbook.
ASSET_CLASS_TO_PLAYBOOK = {
    "equity": "equities",
    "equities": "equities",
    "stock": "equities",
    "etf": "equities",
    "crypto": "crypto",
    "fx": "fx",
    "forex": "fx",
    "bond": "bonds",
    "bonds": "bonds",
    "commodity": "commodities",
    "commodities": "commodities",
}

# Normalise the many ways a direction gets expressed into long / short / None.
LONG_WORDS = {"long", "buy", "bullish", "accumulate", "add", "overweight"}
SHORT_WORDS = {"short", "sell", "bearish", "reduce", "trim", "underweight"}

# Score band centred on 50 (neutral). Tailwind pushes up, headwind pushes down.
NEUTRAL_SCORE = 50.0
MAX_TILT = 40.0  # a full-conviction, perfectly-aligned idea -> 90; opposed -> 10

# Liquidity is an axis orthogonal to the growth/inflation season: central-bank
# net liquidity / global M2 / credit impulse can be expanding while the season
# is bearish, or draining while it's bullish. It acts as a SECONDARY, signed
# nudge (max ±LIQUIDITY_MAX_TILT, half of MAX_TILT so the season stays the lead
# signal) that's added to the season tilt — not a multiplier, so it can also
# *disagree* with the season about a given idea (e.g. a risk-off short into a
# liquidity drain). It only moves high-beta / liquidity-sensitive classes.
LIQUIDITY_MAX_TILT = 20.0
LIQUIDITY_SENSITIVE = {"crypto", "equities"}
LIQUIDITY_SIGN = {"expanding": 1, "contracting": -1, "neutral": 0, None: 0}

# Final score is clamped into this band so season+liquidity can't run away past
# 0-100 while still leaving combined extremes distinguishable from pure-season.
SCORE_FLOOR = 2.0
SCORE_CEIL = 98.0
NEUTRAL_BAND = 0.5  # |total tilt| below this rounds to a neutral label


@dataclass
class MacroFit:
    """Result of scoring one trade idea against the regime."""
    idea_id: str
    symbol: str
    asset_class: str
    direction: str           # normalised: long | short | unknown
    playbook_key: str        # equities | crypto | fx | ... | unmapped
    playbook_stance: str     # up | down | neutral | unknown
    macro_fit_score: float   # 0-100, 50 = neutral (season + liquidity combined)
    label: str               # tailwind | neutral | headwind | unknown
    rationale: str
    regime_season: str = ""  # the active season this was scored against
    liquidity_regime: str = ""   # expanding | contracting | neutral | "" (unset)
    liquidity_tilt: float = 0.0  # signed contribution of liquidity to the score

    def as_dict(self) -> dict:
        return asdict(self)


def load_seasons(path: Path = SEASONS_YAML) -> dict:
    """Load the season -> asset_playbook config."""
    data = yaml.safe_load(path.read_text())
    return data.get("seasons", {})


def load_regime(path: Path = REGIME_JSON) -> dict:
    """Load the active regime state (season, phase, convictions)."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def normalise_direction(direction) -> str:
    """Collapse the many direction spellings into long | short | unknown."""
    if not direction:
        return "unknown"
    token = str(direction).strip().lower()
    if token in LONG_WORDS:
        return "long"
    if token in SHORT_WORDS:
        return "short"
    # Tolerate compound strings like "go long" / "sell short".
    if any(w in token.split() for w in LONG_WORDS):
        return "long"
    if any(w in token.split() for w in SHORT_WORDS):
        return "short"
    return "unknown"


def playbook_stance(seasons: dict, season: str, asset_class: str) -> tuple[str, str]:
    """Resolve (playbook_key, stance) for an asset class in a season.

    stance is one of up | down | neutral | unknown.
    """
    key = ASSET_CLASS_TO_PLAYBOOK.get(str(asset_class or "").strip().lower(), "unmapped")
    season_def = seasons.get(season or "", {})
    playbook = season_def.get("asset_playbook", {})
    stance = playbook.get(key, "unknown") if key != "unmapped" else "unknown"
    return key, stance


def liquidity_tilt(playbook_key: str, direction: str,
                   liq_regime: str, liq_conviction: str) -> float:
    """Signed liquidity contribution to the score for one idea.

    Liquidity only moves high-beta / liquidity-sensitive classes (crypto,
    equities). Expanding liquidity rewards longs and penalises shorts there;
    contracting inverts; neutral/unset/insensitive -> 0. Magnitude scales by
    liquidity conviction, capped at ±LIQUIDITY_MAX_TILT. `direction` is assumed
    already normalised to long | short (callers bail on unknown first).
    """
    sign = LIQUIDITY_SIGN.get(liq_regime, 0)
    if sign == 0 or playbook_key not in LIQUIDITY_SENSITIVE:
        return 0.0
    dir_sign = 1 if direction == "long" else -1
    weight = CONVICTION_WEIGHT.get(liq_conviction, 0.6)
    return sign * dir_sign * weight * LIQUIDITY_MAX_TILT


def score_macro_fit(idea: dict, regime: dict, seasons: dict) -> MacroFit:
    """Score a single trade idea against the active regime.

    `idea` needs: id, symbol, asset_class, direction (any of the usual spellings).
    Returns a MacroFit. A missing/unknown regime or unmappable class yields a
    neutral 50 with an explanatory rationale rather than a hard failure — the
    scorer must never block the pipeline.
    """
    idea_id = str(idea.get("id") or idea.get("idea_id") or "")
    symbol = str(idea.get("symbol") or idea.get("normalized_symbol") or "?")
    asset_class = str(idea.get("asset_class") or "")
    raw_direction = idea.get("direction") or idea.get("action")
    direction = normalise_direction(raw_direction)

    season = regime.get("active_season")
    conviction = regime.get("season_conviction")
    liq_regime = regime.get("liquidity_regime")
    liq_conviction = regime.get("liquidity_conviction")

    key, stance = playbook_stance(seasons, season, asset_class)

    def result(score, label, why, liq=0.0):
        return MacroFit(
            idea_id=idea_id, symbol=symbol, asset_class=asset_class,
            direction=direction, playbook_key=key, playbook_stance=stance,
            macro_fit_score=round(score, 1), label=label, rationale=why,
            regime_season=season or "",
            liquidity_regime=liq_regime or "", liquidity_tilt=round(liq, 1),
        )

    # Hard-neutral degradation paths: we can't sign a tilt without a season and
    # a known direction, so liquidity doesn't apply either.
    if not season:
        return result(NEUTRAL_SCORE, "neutral",
                      "No active macro season set — run update_macro_regime.py.")
    if direction == "unknown":
        return result(NEUTRAL_SCORE, "neutral",
                      f"Idea direction '{raw_direction}' not recognised; left neutral.")
    if stance in ("unknown",):
        return result(NEUTRAL_SCORE, "neutral",
                      f"No playbook stance for '{asset_class}' in {season}.")

    weight = CONVICTION_WEIGHT.get(conviction, 0.6)
    dir_sign = 1 if direction == "long" else -1

    # Season tilt: bullish stance ("up") rewards longs, "down" inverts,
    # "neutral" contributes nothing — but liquidity can still move the idea.
    if stance == "neutral":
        season_tilt = 0.0
        season_why = f"{season.title()} is neutral on {key}"
    else:
        stance_sign = 1 if stance == "up" else -1
        season_tilt = stance_sign * dir_sign * weight * MAX_TILT
        if stance_sign * dir_sign > 0:
            season_why = (f"{season.title()} favours {key} ({stance}); a {direction} "
                          f"idea rides the regime (conviction={conviction or 'medium'})")
        else:
            season_why = (f"{season.title()} says {key} {stance}; a {direction} idea "
                          f"fights the regime (conviction={conviction or 'medium'})")

    # Liquidity tilt: orthogonal, signed, secondary. May reinforce or oppose.
    liq = liquidity_tilt(key, direction, liq_regime, liq_conviction)
    total_tilt = max(-MAX_TILT - LIQUIDITY_MAX_TILT,
                     min(MAX_TILT + LIQUIDITY_MAX_TILT, season_tilt + liq))
    score = max(SCORE_FLOOR, min(SCORE_CEIL, NEUTRAL_SCORE + total_tilt))

    why = season_why
    if liq:
        liq_dir = "lifts" if liq > 0 else "weighs on"
        why += (f"; {liq_regime} liquidity {liq_dir} this {direction} "
                f"(conviction={liq_conviction or 'medium'})")
    elif stance == "neutral":
        why += "; no liquidity tilt"

    if total_tilt > NEUTRAL_BAND:
        label = "tailwind"
    elif total_tilt < -NEUTRAL_BAND:
        label = "headwind"
    else:
        label = "neutral"

    return result(score, label, why + ".", liq)


def score_all(ideas: list[dict], regime: dict, seasons: dict) -> list[MacroFit]:
    """Score a list of ideas and return them sorted best-fit first."""
    scored = [score_macro_fit(i, regime, seasons) for i in ideas]
    scored.sort(key=lambda m: m.macro_fit_score, reverse=True)
    return scored


# ── I/O helpers (kept separate from the pure scoring core above) ────────────

def _load_ideas_from_json(arg: str) -> list[dict]:
    """Load ideas from a JSON file path, or '-' for stdin."""
    raw = sys.stdin.read() if arg == "-" else Path(arg).read_text()
    data = json.loads(raw)
    return data if isinstance(data, list) else data.get("ideas", [])


def _load_ideas_from_supabase() -> list[dict]:
    """Pull live trade ideas from Supabase via the REST API.

    Reuses the same secrets file as sync_to_supabase.py. Returns [] (with a
    clear message) if creds are missing, so --ideas-json stays usable offline.
    """
    env_file = ROOT / "secrets" / ".env.supabase"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        print("  No Supabase creds (SUPABASE_URL / key). Use --ideas-json to score offline.",
              file=sys.stderr)
        return []

    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed. Run: pip install requests", file=sys.stderr)
        return []

    endpoint = f"{url.rstrip('/')}/rest/v1/rv_trade_ideas"
    params = {"select": "id,symbol,normalized_symbol,asset_class,direction,action,status", "limit": "500"}
    resp = requests.get(endpoint, params=params,
                        headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
    if resp.status_code != 200:
        print(f"  Supabase fetch failed: {resp.status_code} {resp.text[:160]}", file=sys.stderr)
        return []
    return resp.json()


def _write_to_supabase(scored: list[MacroFit], dry_run: bool) -> int:
    """Upsert macro-fit results into Supabase rv_trade_idea_macro_fit.

    Mirrors sync_to_supabase.py: same secrets file, service-role key, and
    merge-duplicates upsert. Rows without an idea_id are skipped (the PK).
    """
    rows = [m.as_dict() for m in scored if m.idea_id]
    if not rows:
        print("  Nothing to write (no ideas had an id).", file=sys.stderr)
        return 0
    if dry_run:
        print(f"  [DRY RUN] Would upsert {len(rows)} rows to rv_trade_idea_macro_fit")
        print(f"    Sample: {rows[0]}")
        return len(rows)

    env_file = ROOT / "secrets" / ".env.supabase"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set — skipping write.", file=sys.stderr)
        return 0

    try:
        import httpx
    except ImportError:
        print("ERROR: httpx not installed. Run: pip install httpx", file=sys.stderr)
        return 0

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    endpoint = f"{url}/rest/v1/rv_trade_idea_macro_fit"
    total = 0
    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        resp = httpx.post(endpoint, headers=headers, json=chunk, timeout=30)
        if resp.status_code not in (200, 201, 204):
            print(f"  ERROR upserting to rv_trade_idea_macro_fit: {resp.status_code} {resp.text[:200]}",
                  file=sys.stderr)
            return total
        total += len(chunk)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Score trade ideas against the active macro regime")
    parser.add_argument("--ideas-json", help="Path to a JSON list of ideas, or '-' for stdin")
    parser.add_argument("--write", action="store_true",
                        help="Upsert results to Supabase rv_trade_idea_macro_fit")
    parser.add_argument("--dry-run", action="store_true",
                        help="With --write, print what would be upserted without sending")
    parser.add_argument("--explain", action="store_true",
                        help="Print the active regime's resolved playbook and exit")
    parser.add_argument("--top", type=int, default=20, help="How many ranked ideas to print")
    args = parser.parse_args()

    seasons = load_seasons()
    regime = load_regime()
    season = regime.get("active_season")

    if args.explain:
        print(f"Active season: {season or '(none set)'} "
              f"(conviction={regime.get('season_conviction') or 'n/a'})")
        print(f"Liquidity regime: {regime.get('liquidity_regime') or '(none set)'} "
              f"(conviction={regime.get('liquidity_conviction') or 'n/a'}) "
              f"— tilts {sorted(LIQUIDITY_SENSITIVE)} by ±{LIQUIDITY_MAX_TILT:.0f}")
        if season and season in seasons:
            playbook = seasons[season].get("asset_playbook", {})
            print(f"  {seasons[season].get('subtitle', '')}")
            for k in ("equities", "crypto", "fx", "bonds", "commodities", "cash"):
                if k in playbook:
                    print(f"    {k:12s} -> {playbook[k]}")
        return

    if args.ideas_json:
        ideas = _load_ideas_from_json(args.ideas_json)
    else:
        ideas = _load_ideas_from_supabase()

    if not ideas:
        print("No ideas to score.")
        return

    scored = score_all(ideas, regime, seasons)
    tail = sum(1 for m in scored if m.label == "tailwind")
    head = sum(1 for m in scored if m.label == "headwind")
    print(f"Scored {len(scored)} ideas against {season or '(no)'} regime: "
          f"{tail} tailwind, {head} headwind, {len(scored) - tail - head} neutral\n")
    print(f"{'SCORE':>6}  {'LABEL':9s}  {'SYMBOL':8s}  {'CLASS':8s}  {'DIR':6s}  RATIONALE")
    for m in scored[: args.top]:
        print(f"{m.macro_fit_score:6.1f}  {m.label:9s}  {m.symbol:8s}  "
              f"{m.asset_class:8s}  {m.direction:6s}  {m.rationale}")

    if args.write:
        n = _write_to_supabase(scored, args.dry_run)
        print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Wrote {n} macro-fit rows to Supabase.")


if __name__ == "__main__":
    main()
