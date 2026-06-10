#!/usr/bin/env python3
"""Portfolio construction engine — turn ranked ideas into sized allocations.

The third pillar of the engine (macro: score_macro_fit.py, technical:
score_technical.py). It takes composite-ranked trade ideas plus the current real
positions and proposes position sizes that respect the rules in
config/portfolio_rules.yaml:

  * thesis budgets    — each thesis has a target and a hard max % of NAV
  * single-name caps  — max % per stock / crypto
  * dry-powder floor  — never deploy below the minimum cash reserve
  * portfolio heat    — a 0-100 risk gauge; above the high threshold, new
                        high-beta entries are blocked (only trim/hedge/research)
  * starter sizing    — new positions enter at the starter size, capped by all
                        of the above

Pure, dependency-light, fully unit-testable. The proposal is advisory: it never
executes — require_user_approval_for_real_action is honoured by emitting plans,
not orders.

Usage:
    python scripts/build_portfolio.py                 # from local SQLite + Supabase composite
    python scripts/build_portfolio.py --state-json -  # score a state blob from stdin (offline)
    python scripts/build_portfolio.py --write         # upsert proposals to Supabase
"""
import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "moneytrail.sqlite"
RULES_YAML = ROOT / "config" / "portfolio_rules.yaml"
ASSETS_YAML = ROOT / "config" / "assets.yaml"

# Heat is a weighted blend of risk inputs, each normalised to 0-100. Weights sum
# to 1.0. These mirror the inputs listed in portfolio_rules.yaml.
HEAT_WEIGHTS = {
    "crypto_beta_exposure": 0.25,      # crypto % of NAV vs its max budget
    "single_name_concentration": 0.20, # largest single position vs its cap
    "dry_powder_level": 0.20,          # inverse: low cash = hot
    "thesis_overflow": 0.15,           # how far any thesis exceeds its max
    "recent_drawdown": 0.20,           # portfolio drawdown from cost basis
}


@dataclass
class ThesisExposure:
    thesis: str
    current_pct: float
    target_pct: float
    max_pct: float
    headroom_pct: float   # max_pct - current_pct, floored at 0


@dataclass
class HeatReport:
    score: float                       # 0-100
    level: str                         # cool | warm | hot
    blocked_new_high_beta: bool
    components: dict = field(default_factory=dict)


@dataclass
class Allocation:
    symbol: str
    thesis: str
    direction: str
    composite_score: float | None
    action: str            # enter_starter | add | hold | skip | blocked
    target_pct: float      # proposed % of NAV for this position
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


# ── config ──────────────────────────────────────────────────────────────────

def load_rules(path: Path = RULES_YAML) -> dict:
    return yaml.safe_load(path.read_text())


def load_asset_thesis_map(path: Path = ASSETS_YAML) -> dict[str, dict]:
    """{SYMBOL: {primary_thesis, asset_type}} from the asset registry."""
    data = yaml.safe_load(path.read_text())
    out: dict[str, dict] = {}
    for group in data.values():
        if not isinstance(group, list):
            continue
        for a in group:
            if not isinstance(a, dict):
                continue  # tolerate bare strings / malformed entries in the registry
            sym = a.get("symbol")
            if sym:
                out[sym.upper()] = {
                    "primary_thesis": a.get("primary_thesis"),
                    "asset_type": a.get("asset_type"),
                }
    return out


# ── exposure + heat (pure) ──────────────────────────────────────────────────

def position_value(p: dict) -> float:
    """Market value of a position = quantity * current_price (fallback cost)."""
    qty = float(p.get("quantity") or 0)
    price = p.get("current_price")
    if price is None:
        price = p.get("cost_basis") or 0
    return qty * float(price)


def compute_nav(positions: list[dict], cash: float) -> float:
    return cash + sum(position_value(p) for p in positions)


def thesis_exposures(positions: list[dict], nav: float, rules: dict) -> dict[str, ThesisExposure]:
    """Current % of NAV per thesis vs its target/max budget."""
    budgets = rules.get("thesis_budget", {})
    by_thesis: dict[str, float] = {}
    for p in positions:
        t = p.get("primary_thesis") or "unassigned"
        by_thesis[t] = by_thesis.get(t, 0.0) + position_value(p)

    out: dict[str, ThesisExposure] = {}
    for thesis, budget in budgets.items():
        if thesis == "dry_powder":
            continue
        cur = (by_thesis.get(thesis, 0.0) / nav) if nav > 0 else 0.0
        mx = budget.get("max", 1.0)
        out[thesis] = ThesisExposure(
            thesis=thesis, current_pct=cur,
            target_pct=budget.get("target", 0.0), max_pct=mx,
            headroom_pct=max(0.0, mx - cur),
        )
    return out


def compute_heat(positions: list[dict], cash: float, rules: dict) -> HeatReport:
    """0-100 portfolio heat from the configured risk inputs."""
    nav = compute_nav(positions, cash)
    alloc = rules.get("allocation_rules", {})
    budgets = rules.get("thesis_budget", {})
    comps: dict[str, float] = {}

    # crypto beta exposure vs its max
    crypto_val = sum(position_value(p) for p in positions
                     if (p.get("asset_type") or "").lower() == "crypto")
    crypto_pct = (crypto_val / nav) if nav > 0 else 0.0
    crypto_cap = alloc.get("max_total_crypto_beta", 0.35)
    comps["crypto_beta_exposure"] = min(100.0, (crypto_pct / crypto_cap) * 100.0) if crypto_cap else 0.0

    # largest single position vs single-name cap
    largest_pct = max((position_value(p) / nav for p in positions), default=0.0) if nav > 0 else 0.0
    name_cap = max(alloc.get("max_single_stock", 0.15), alloc.get("max_single_crypto_asset", 0.15))
    comps["single_name_concentration"] = min(100.0, (largest_pct / name_cap) * 100.0) if name_cap else 0.0

    # dry powder: low cash -> hot (inverse of cash vs minimum)
    cash_pct = (cash / nav) if nav > 0 else 1.0
    min_dry = alloc.get("minimum_dry_powder", 0.10)
    # at/below the floor -> 100; at 3x the floor or more -> 0
    if min_dry > 0:
        comps["dry_powder_level"] = max(0.0, min(100.0, (1 - (cash_pct - min_dry) / (2 * min_dry)) * 100.0))
    else:
        comps["dry_powder_level"] = 0.0

    # thesis overflow: worst overshoot of any thesis past its max
    overflow = 0.0
    by_thesis: dict[str, float] = {}
    for p in positions:
        t = p.get("primary_thesis") or "unassigned"
        by_thesis[t] = by_thesis.get(t, 0.0) + position_value(p)
    for thesis, budget in budgets.items():
        if thesis == "dry_powder" or nav <= 0:
            continue
        cur = by_thesis.get(thesis, 0.0) / nav
        mx = budget.get("max", 1.0)
        if cur > mx and mx > 0:
            overflow = max(overflow, (cur - mx) / mx)
    comps["thesis_overflow"] = min(100.0, overflow * 100.0)

    # recent drawdown: portfolio value below aggregate cost basis
    cost = sum(float(p.get("quantity") or 0) * float(p.get("cost_basis") or 0) for p in positions)
    mkt = sum(position_value(p) for p in positions)
    dd = ((cost - mkt) / cost) if cost > 0 else 0.0
    comps["recent_drawdown"] = max(0.0, min(100.0, dd * 100.0 * 2))  # 50% dd -> 100

    score = round(sum(HEAT_WEIGHTS[k] * comps.get(k, 0.0) for k in HEAT_WEIGHTS), 1)
    high = rules.get("portfolio_heat", {}).get("high_threshold", 80)
    level = "hot" if score >= high else ("warm" if score >= high * 0.6 else "cool")
    return HeatReport(score=score, level=level,
                      blocked_new_high_beta=score >= high, components=comps)


# ── allocation proposal (pure) ──────────────────────────────────────────────

HIGH_BETA_TYPES = {"crypto"}


def propose_allocations(
    ideas: list[dict],
    positions: list[dict],
    cash: float,
    rules: dict,
    asset_map: dict[str, dict],
) -> tuple[list[Allocation], HeatReport]:
    """Propose sized entries for ranked ideas, respecting every budget rule.

    `ideas` are composite rows (symbol, direction, composite_score), best first.
    Returns (allocations, heat). Purely advisory — no execution.
    """
    nav = compute_nav(positions, cash)
    heat = compute_heat(positions, cash, rules)
    exposures = thesis_exposures(positions, nav, rules)
    alloc_rules = rules.get("allocation_rules", {})
    min_dry = alloc_rules.get("minimum_dry_powder", 0.10)
    starter = alloc_rules.get("max_new_position_starter", 0.02)

    held = {(p.get("asset") or "").upper() for p in positions}
    deployable = max(0.0, cash / nav - min_dry) if nav > 0 else 0.0  # % of NAV we may add
    # track simulated additions so multiple ideas don't all claim the same headroom
    added_to_thesis: dict[str, float] = {}
    out: list[Allocation] = []

    for idea in ideas:
        sym = (idea.get("symbol") or "").upper()
        direction = (idea.get("direction") or "").lower()
        comp = idea.get("composite_score")
        meta = asset_map.get(sym, {})
        thesis = meta.get("primary_thesis") or "tactical_satellite"
        asset_type = (meta.get("asset_type") or idea.get("asset_class") or "").lower()
        is_high_beta = asset_type in HIGH_BETA_TYPES

        def emit(action, pct, reason):
            out.append(Allocation(symbol=sym, thesis=thesis, direction=direction,
                                  composite_score=comp, action=action,
                                  target_pct=round(pct, 4), reason=reason))

        # Only long ideas build the portfolio; shorts/hedges are handled elsewhere.
        if direction not in ("long", "buy"):
            emit("skip", 0.0, f"Direction '{direction}' is not a long entry.")
            continue

        # Conviction gate: a below-neutral composite isn't a buy.
        if comp is not None and comp < 50:
            emit("skip", 0.0, f"Composite {comp:.0f} below neutral — not a buy.")
            continue

        if sym in held:
            emit("hold", 0.0, "Already held — managed by LILO, not re-entered here.")
            continue

        # Heat gate: hot portfolio blocks new high-beta entries.
        if heat.blocked_new_high_beta and is_high_beta:
            emit("blocked", 0.0,
                 f"Portfolio heat {heat.score:.0f} ≥ high threshold — no new high-beta entries.")
            continue

        # Size = starter, capped by single-name cap, thesis headroom, and dry powder.
        name_cap = (alloc_rules.get("max_single_crypto_asset", 0.15) if is_high_beta
                    else alloc_rules.get("max_single_stock", 0.15))
        exp = exposures.get(thesis)
        thesis_headroom = (exp.headroom_pct if exp else 1.0) - added_to_thesis.get(thesis, 0.0)
        size = min(starter, name_cap, max(0.0, thesis_headroom), deployable)

        if size <= 0:
            if thesis_headroom <= 0:
                emit("skip", 0.0, f"Thesis '{thesis}' at its max budget — no headroom.")
            else:
                emit("skip", 0.0, "Dry-powder floor reached — no capital to deploy.")
            continue

        added_to_thesis[thesis] = added_to_thesis.get(thesis, 0.0) + size
        deployable -= size
        emit("enter_starter", size,
             f"Starter entry {size*100:.1f}% NAV — composite {comp:.0f}, thesis '{thesis}' "
             f"headroom {thesis_headroom*100:.1f}%, heat {heat.level}.")

    return out, heat


# ── I/O ──────────────────────────────────────────────────────────────────────

def _load_state_from_db(rules: dict) -> tuple[list[dict], float]:
    """Load real_positions from SQLite. Cash is inferred from a CASH/USD row if
    present, else assumed at the dry-powder target of a 100k notional NAV."""
    if not DB_PATH.exists():
        return [], 0.0
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM real_positions").fetchall()]
    conn.close()
    cash_rows = [r for r in rows if (r.get("asset") or "").upper() in ("CASH", "USD", "USDC")]
    positions = [r for r in rows if r not in cash_rows]
    cash = sum(position_value(r) for r in cash_rows)
    if cash == 0 and positions:
        # No explicit cash row — seed dry powder at the configured target so the
        # engine has something to deploy rather than reporting 0% cash.
        target = rules.get("thesis_budget", {}).get("dry_powder", {}).get("target", 0.10)
        invested = sum(position_value(p) for p in positions)
        cash = invested * target / max(1e-9, (1 - target))
    return positions, cash


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a portfolio proposal from ranked ideas")
    parser.add_argument("--state-json", help="JSON {positions, cash, ideas} or '-' for stdin (offline)")
    parser.add_argument("--write", action="store_true", help="Upsert proposals to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="With --write, print instead of send")
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    rules = load_rules()
    asset_map = load_asset_thesis_map()

    if args.state_json:
        raw = sys.stdin.read() if args.state_json == "-" else Path(args.state_json).read_text()
        state = json.loads(raw)
        positions, cash, ideas = state.get("positions", []), state.get("cash", 0.0), state.get("ideas", [])
    else:
        positions, cash = _load_state_from_db(rules)
        ideas = _fetch_composite_ideas()

    allocs, heat = propose_allocations(ideas, positions, cash, rules, asset_map)

    print(f"Portfolio heat: {heat.score:.0f} ({heat.level})"
          f"{' — NEW HIGH-BETA BLOCKED' if heat.blocked_new_high_beta else ''}")
    print(f"  components: " + ", ".join(f"{k}={v:.0f}" for k, v in heat.components.items()))
    print(f"\nProposed actions ({len(allocs)} ideas):")
    print(f"{'ACTION':14s}  {'SYMBOL':8s}  {'THESIS':16s}  {'%NAV':>6s}  REASON")
    for a in allocs[: args.top]:
        print(f"{a.action:14s}  {a.symbol:8s}  {a.thesis:16s}  {a.target_pct*100:5.1f}%  {a.reason}")

    if args.write:
        n = _write_to_supabase(allocs, heat, args.dry_run)
        print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Wrote {n} allocation rows to Supabase.")


def _fetch_composite_ideas() -> list[dict]:
    """Pull composite-ranked ideas from Supabase (best first)."""
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
        print("  No Supabase creds — use --state-json to run offline.", file=sys.stderr)
        return []
    import httpx
    resp = httpx.get(f"{url}/rest/v1/public_rv_trade_composite",
                     params={"select": "symbol,direction,asset_class,composite_score",
                             "order": "composite_score.desc.nullslast", "limit": "200"},
                     headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
    return resp.json() if resp.status_code == 200 else []


def _write_to_supabase(allocs: list[Allocation], heat: HeatReport, dry_run: bool) -> int:
    rows = [{**a.as_dict(), "heat_score": heat.score, "heat_level": heat.level} for a in allocs]
    if dry_run:
        print(f"  [DRY RUN] Would upsert {len(rows)} rows to portfolio_allocations")
        if rows:
            print(f"    Sample: {rows[0]}")
        return len(rows)
    if not rows:
        return 0
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("  SUPABASE creds not set — skipping write.", file=sys.stderr)
        return 0
    import httpx
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    resp = httpx.post(f"{url}/rest/v1/portfolio_allocations", headers=headers, json=rows, timeout=30)
    if resp.status_code not in (200, 201, 204):
        print(f"  ERROR upserting allocations: {resp.status_code} {resp.text[:160]}", file=sys.stderr)
        return 0
    return len(rows)


if __name__ == "__main__":
    main()
