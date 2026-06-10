"""Unit tests for the portfolio construction engine (scripts/build_portfolio.py).

Pure functions over plain dicts — exposure, heat, and the allocation rules.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from scripts.build_portfolio import (
    compute_nav, position_value, thesis_exposures, compute_heat,
    propose_allocations,
)

# Minimal rules mirroring config/portfolio_rules.yaml.
RULES = {
    "allocation_rules": {
        "minimum_dry_powder": 0.10,
        "max_single_stock": 0.15,
        "max_single_crypto_asset": 0.15,
        "max_total_crypto_beta": 0.35,
        "max_new_position_starter": 0.02,
    },
    "thesis_budget": {
        "scarce_assets": {"target": 0.25, "max": 0.40},
        "ai_growth": {"target": 0.30, "max": 0.40},
        "crypto_beta": {"target": 0.20, "max": 0.35},
        "tactical_satellite": {"target": 0.05, "max": 0.10},
        "dry_powder": {"target": 0.10, "min": 0.075},
    },
    "portfolio_heat": {"high_threshold": 80},
}

ASSET_MAP = {
    "BTC": {"primary_thesis": "scarce_assets", "asset_type": "crypto"},
    "NVDA": {"primary_thesis": "ai_growth", "asset_type": "equity"},
    "SOL": {"primary_thesis": "crypto_beta", "asset_type": "crypto"},
    "WIF": {"primary_thesis": "tactical_satellite", "asset_type": "crypto"},
}


def pos(asset, thesis, atype, qty, price, cost=None):
    return {"asset": asset, "primary_thesis": thesis, "asset_type": atype,
            "quantity": qty, "current_price": price, "cost_basis": cost if cost is not None else price}


# ── value / NAV ───────────────────────────────────────────────────────────────

def test_position_value_uses_current_price():
    assert position_value(pos("BTC", "scarce_assets", "crypto", 2, 50000)) == 100000


def test_position_value_falls_back_to_cost():
    p = {"quantity": 3, "current_price": None, "cost_basis": 10}
    assert position_value(p) == 30


def test_compute_nav_includes_cash():
    positions = [pos("NVDA", "ai_growth", "equity", 10, 100)]  # 1000
    assert compute_nav(positions, cash=500) == 1500


# ── thesis exposure ───────────────────────────────────────────────────────────

def test_thesis_exposure_and_headroom():
    positions = [pos("NVDA", "ai_growth", "equity", 10, 100)]  # 1000, all ai_growth
    nav = compute_nav(positions, cash=1000)                    # 2000
    exp = thesis_exposures(positions, nav, RULES)
    assert exp["ai_growth"].current_pct == pytest.approx(0.5)
    # max is 0.40, current 0.50 -> headroom floored at 0
    assert exp["ai_growth"].headroom_pct == pytest.approx(0.0)
    assert exp["scarce_assets"].current_pct == pytest.approx(0.0)
    assert exp["scarce_assets"].headroom_pct == pytest.approx(0.40)


# ── heat ──────────────────────────────────────────────────────────────────────

def test_heat_cool_for_balanced_book():
    positions = [pos("NVDA", "ai_growth", "equity", 1, 100)]  # 100 invested
    heat = compute_heat(positions, cash=900, rules=RULES)      # 90% cash -> cool
    assert heat.level == "cool"
    assert not heat.blocked_new_high_beta


def test_heat_hot_when_crypto_heavy_and_low_cash():
    # All crypto, tiny cash -> crypto exposure maxed + dry powder starved
    positions = [pos("BTC", "scarce_assets", "crypto", 1, 950)]
    heat = compute_heat(positions, cash=50, rules=RULES)
    assert heat.score > 60
    assert heat.components["crypto_beta_exposure"] == pytest.approx(100.0)


def test_heat_blocks_above_threshold():
    positions = [pos("BTC", "scarce_assets", "crypto", 1, 990),
                 pos("SOL", "crypto_beta", "crypto", 1, 5)]
    heat = compute_heat(positions, cash=5, rules=RULES)
    assert heat.score >= 80
    assert heat.blocked_new_high_beta


# ── allocation proposals ──────────────────────────────────────────────────────

def base_state():
    # Balanced, cool book with room to add: 50% cash.
    positions = [pos("NVDA", "ai_growth", "equity", 1, 100)]  # 100
    return positions, 100.0  # cash 100 -> NAV 200, 50% cash


def test_long_idea_gets_starter_entry():
    positions, cash = base_state()
    ideas = [{"symbol": "BTC", "direction": "long", "composite_score": 72}]
    allocs, heat = propose_allocations(ideas, positions, cash, RULES, ASSET_MAP)
    a = allocs[0]
    assert a.action == "enter_starter"
    assert a.target_pct == pytest.approx(0.02)  # starter size
    assert a.thesis == "scarce_assets"


def test_below_neutral_composite_is_skipped():
    positions, cash = base_state()
    ideas = [{"symbol": "BTC", "direction": "long", "composite_score": 41}]
    allocs, _ = propose_allocations(ideas, positions, cash, RULES, ASSET_MAP)
    assert allocs[0].action == "skip"
    assert "below neutral" in allocs[0].reason


def test_short_idea_is_skipped_from_construction():
    positions, cash = base_state()
    ideas = [{"symbol": "BTC", "direction": "short", "composite_score": 80}]
    allocs, _ = propose_allocations(ideas, positions, cash, RULES, ASSET_MAP)
    assert allocs[0].action == "skip"


def test_already_held_is_hold_not_reentered():
    positions, cash = base_state()
    ideas = [{"symbol": "NVDA", "direction": "long", "composite_score": 90}]
    allocs, _ = propose_allocations(ideas, positions, cash, RULES, ASSET_MAP)
    assert allocs[0].action == "hold"


def test_thesis_at_max_gets_no_headroom():
    # ai_growth already at 50% (> 40% max); a new ai_growth long must be skipped.
    positions = [pos("NVDA", "ai_growth", "equity", 5, 100)]  # 500
    cash = 500.0  # NAV 1000, ai_growth = 50%
    ideas = [{"symbol": "TSM", "direction": "long", "composite_score": 85}]
    amap = {"TSM": {"primary_thesis": "ai_growth", "asset_type": "equity"}}
    allocs, _ = propose_allocations(ideas, positions, cash, RULES, amap)
    assert allocs[0].action == "skip"
    assert "max budget" in allocs[0].reason


def test_hot_portfolio_blocks_new_high_beta():
    # Hot, crypto-heavy book; a new crypto long is blocked, an equity long is not.
    positions = [pos("BTC", "scarce_assets", "crypto", 1, 990)]
    cash = 10.0
    ideas = [
        {"symbol": "SOL", "direction": "long", "composite_score": 80},   # crypto -> blocked
    ]
    allocs, heat = propose_allocations(ideas, positions, cash, RULES, ASSET_MAP)
    assert heat.blocked_new_high_beta
    assert allocs[0].action == "blocked"
    assert "high-beta" in allocs[0].reason


def test_dry_powder_floor_stops_deployment():
    # Cash exactly at the 10% floor -> nothing deployable.
    positions = [pos("NVDA", "ai_growth", "equity", 9, 100)]  # 900
    cash = 100.0  # NAV 1000, cash 10% == floor
    ideas = [{"symbol": "BTC", "direction": "long", "composite_score": 75}]
    allocs, _ = propose_allocations(ideas, positions, cash, RULES, ASSET_MAP)
    assert allocs[0].action == "skip"
    assert "Dry-powder floor" in allocs[0].reason


def test_multiple_ideas_share_thesis_headroom():
    # Two crypto_beta longs but only enough headroom/powder for limited adds;
    # the engine must not double-count the same headroom.
    positions = [pos("NVDA", "ai_growth", "equity", 1, 100)]
    cash = 100.0  # NAV 200, 50% cash, plenty cool
    ideas = [
        {"symbol": "SOL", "direction": "long", "composite_score": 80},
        {"symbol": "WIF", "direction": "long", "composite_score": 70},
    ]
    allocs, _ = propose_allocations(ideas, positions, cash, RULES, ASSET_MAP)
    total = sum(a.target_pct for a in allocs if a.action == "enter_starter")
    # combined adds never exceed deployable cash above the dry-powder floor
    assert total <= (cash / 200) - RULES["allocation_rules"]["minimum_dry_powder"] + 1e-9
