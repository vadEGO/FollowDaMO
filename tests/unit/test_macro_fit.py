"""Unit tests for the macro-fit scorer (scripts/score_macro_fit.py).

These exercise the pure scoring core: regime + season playbook -> tailwind /
neutral / headwind. No network or DB.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from scripts.score_macro_fit import (
    MacroFit,
    normalise_direction,
    playbook_stance,
    score_macro_fit,
    score_all,
    NEUTRAL_SCORE,
)

# Minimal season config mirroring config/macro_seasons.yaml shape.
SEASONS = {
    "summer": {
        "subtitle": "Inflationary Boom",
        "asset_playbook": {
            "equities": "up", "crypto": "up", "commodities": "up",
            "bonds": "down", "fx": "neutral",
        },
    },
    "winter": {
        "subtitle": "Deflationary Bust",
        "asset_playbook": {
            "equities": "down", "crypto": "down", "bonds": "up",
        },
    },
}

REGIME_SUMMER_HIGH = {"active_season": "summer", "season_conviction": "high"}
REGIME_SUMMER_LOW = {"active_season": "summer", "season_conviction": "low"}
REGIME_NONE = {}


def idea(**kw):
    base = {"id": "x", "symbol": "AAA", "asset_class": "equity", "direction": "long"}
    base.update(kw)
    return base


# ── direction normalisation ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("long", "long"), ("buy", "long"), ("BULLISH", "long"), ("go long", "long"),
    ("short", "short"), ("sell", "short"), ("Bearish", "short"), ("sell short", "short"),
    ("", "unknown"), (None, "unknown"), ("sideways", "unknown"),
])
def test_normalise_direction(raw, expected):
    assert normalise_direction(raw) == expected


# ── playbook stance resolution ──────────────────────────────────────────────

def test_playbook_stance_maps_asset_class():
    assert playbook_stance(SEASONS, "summer", "equity") == ("equities", "up")
    assert playbook_stance(SEASONS, "summer", "etf") == ("equities", "up")
    assert playbook_stance(SEASONS, "summer", "crypto") == ("crypto", "up")
    assert playbook_stance(SEASONS, "winter", "bond") == ("bonds", "up")


def test_playbook_stance_unmapped_class():
    key, stance = playbook_stance(SEASONS, "summer", "wombats")
    assert key == "unmapped"
    assert stance == "unknown"


# ── core scoring ────────────────────────────────────────────────────────────

def test_long_in_favoured_class_is_tailwind():
    m = score_macro_fit(idea(direction="long", asset_class="equity"), REGIME_SUMMER_HIGH, SEASONS)
    assert m.label == "tailwind"
    assert m.macro_fit_score > NEUTRAL_SCORE
    # high conviction, perfectly aligned -> top of the band (90)
    assert m.macro_fit_score == pytest.approx(90.0)


def test_short_in_favoured_class_is_headwind():
    m = score_macro_fit(idea(direction="short", asset_class="crypto"), REGIME_SUMMER_HIGH, SEASONS)
    assert m.label == "headwind"
    assert m.macro_fit_score < NEUTRAL_SCORE
    assert m.macro_fit_score == pytest.approx(10.0)


def test_long_in_disfavoured_class_is_headwind():
    # summer says bonds=down, so a long-bond idea fights the regime
    m = score_macro_fit(idea(direction="buy", asset_class="bond"), REGIME_SUMMER_HIGH, SEASONS)
    assert m.label == "headwind"
    assert m.macro_fit_score < NEUTRAL_SCORE


def test_short_in_disfavoured_class_is_tailwind():
    # winter says equities=down; shorting equities aligns with the regime
    m = score_macro_fit(idea(direction="sell", asset_class="equity"), {"active_season": "winter", "season_conviction": "high"}, SEASONS)
    assert m.label == "tailwind"
    assert m.macro_fit_score > NEUTRAL_SCORE


def test_conviction_scales_magnitude():
    high = score_macro_fit(idea(), REGIME_SUMMER_HIGH, SEASONS).macro_fit_score
    low = score_macro_fit(idea(), REGIME_SUMMER_LOW, SEASONS).macro_fit_score
    # both tailwinds, but low conviction tilts less
    assert high > low > NEUTRAL_SCORE


def test_neutral_stance_class_stays_neutral():
    m = score_macro_fit(idea(asset_class="fx", direction="long"), REGIME_SUMMER_HIGH, SEASONS)
    assert m.label == "neutral"
    assert m.macro_fit_score == pytest.approx(NEUTRAL_SCORE)


# ── graceful degradation: the scorer must never block the pipeline ──────────

def test_no_active_season_is_neutral():
    m = score_macro_fit(idea(), REGIME_NONE, SEASONS)
    assert m.label == "neutral"
    assert m.macro_fit_score == pytest.approx(NEUTRAL_SCORE)
    assert "update_macro_regime" in m.rationale


def test_unknown_direction_is_neutral():
    m = score_macro_fit(idea(direction="hold"), REGIME_SUMMER_HIGH, SEASONS)
    assert m.label == "neutral"


def test_unmapped_asset_class_is_neutral():
    m = score_macro_fit(idea(asset_class="wombats"), REGIME_SUMMER_HIGH, SEASONS)
    assert m.label == "neutral"


def test_missing_conviction_defaults_to_medium():
    m = score_macro_fit(idea(), {"active_season": "summer"}, SEASONS)
    # medium weight 0.6 -> 50 + 0.6*40 = 74
    assert m.macro_fit_score == pytest.approx(74.0)


# ── ranking ─────────────────────────────────────────────────────────────────

def test_score_all_sorts_best_first():
    ideas = [
        idea(id="head", direction="short", asset_class="equity"),  # headwind
        idea(id="tail", direction="long", asset_class="equity"),   # tailwind
        idea(id="neut", direction="long", asset_class="fx"),       # neutral
    ]
    ranked = score_all(ideas, REGIME_SUMMER_HIGH, SEASONS)
    assert [m.idea_id for m in ranked] == ["tail", "neut", "head"]
    assert ranked[0].macro_fit_score >= ranked[1].macro_fit_score >= ranked[2].macro_fit_score


def test_macrofit_as_dict_roundtrips():
    m = score_macro_fit(idea(), REGIME_SUMMER_HIGH, SEASONS)
    d = m.as_dict()
    assert d["label"] == "tailwind"
    assert set(d) >= {"idea_id", "symbol", "macro_fit_score", "label", "rationale"}


def test_regime_season_recorded_for_supabase_row():
    # The persisted row must carry which season it was scored against.
    m = score_macro_fit(idea(), REGIME_SUMMER_HIGH, SEASONS)
    assert m.regime_season == "summer"
    assert m.as_dict()["regime_season"] == "summer"
    # No active season -> empty string, never None (keeps the DB column clean).
    m2 = score_macro_fit(idea(), REGIME_NONE, SEASONS)
    assert m2.regime_season == ""
