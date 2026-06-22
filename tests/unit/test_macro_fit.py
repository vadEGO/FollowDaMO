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
    liquidity_tilt,
    score_macro_fit,
    score_all,
    NEUTRAL_SCORE,
    LIQUIDITY_MAX_TILT,
    SCORE_CEIL,
    SCORE_FLOOR,
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


# ── liquidity axis ──────────────────────────────────────────────────────────

# Same season/conviction, plus a liquidity overlay.
REGIME_SUMMER_HIGH_LIQ_EXP = {
    "active_season": "summer", "season_conviction": "high",
    "liquidity_regime": "expanding", "liquidity_conviction": "high",
}
REGIME_SUMMER_HIGH_LIQ_CON = {
    "active_season": "summer", "season_conviction": "high",
    "liquidity_regime": "contracting", "liquidity_conviction": "high",
}
# A low-conviction season so liquidity can flip the sign.
REGIME_SUMMER_LOW_LIQ_CON = {
    "active_season": "summer", "season_conviction": "low",
    "liquidity_regime": "contracting", "liquidity_conviction": "high",
}


def test_liquidity_tilt_only_moves_sensitive_classes():
    # crypto/equities are liquidity-sensitive; fx/bonds/commodities are not.
    assert liquidity_tilt("crypto", "long", "expanding", "high") == pytest.approx(LIQUIDITY_MAX_TILT)
    assert liquidity_tilt("equities", "long", "expanding", "high") == pytest.approx(LIQUIDITY_MAX_TILT)
    assert liquidity_tilt("bonds", "long", "expanding", "high") == 0.0
    assert liquidity_tilt("fx", "long", "expanding", "high") == 0.0


def test_liquidity_tilt_signs_and_neutral():
    # Expanding rewards longs, penalises shorts; contracting inverts; neutral = 0.
    assert liquidity_tilt("crypto", "short", "expanding", "high") == pytest.approx(-LIQUIDITY_MAX_TILT)
    assert liquidity_tilt("crypto", "long", "contracting", "high") == pytest.approx(-LIQUIDITY_MAX_TILT)
    assert liquidity_tilt("crypto", "short", "contracting", "high") == pytest.approx(LIQUIDITY_MAX_TILT)
    assert liquidity_tilt("crypto", "long", "neutral", "high") == 0.0
    assert liquidity_tilt("crypto", "long", None, "high") == 0.0


def test_expanding_liquidity_reinforces_a_season_tailwind():
    base = score_macro_fit(idea(asset_class="crypto", direction="long"), REGIME_SUMMER_HIGH, SEASONS)
    boosted = score_macro_fit(idea(asset_class="crypto", direction="long"), REGIME_SUMMER_HIGH_LIQ_EXP, SEASONS)
    assert boosted.macro_fit_score > base.macro_fit_score
    assert boosted.label == "tailwind"
    assert boosted.liquidity_tilt == pytest.approx(LIQUIDITY_MAX_TILT)
    assert boosted.liquidity_regime == "expanding"


def test_contracting_liquidity_opposes_a_season_tailwind():
    # Summer favours crypto-long (tailwind), but a liquidity drain weighs on it.
    base = score_macro_fit(idea(asset_class="crypto", direction="long"), REGIME_SUMMER_HIGH, SEASONS)
    drained = score_macro_fit(idea(asset_class="crypto", direction="long"), REGIME_SUMMER_HIGH_LIQ_CON, SEASONS)
    assert drained.macro_fit_score < base.macro_fit_score
    assert drained.liquidity_tilt == pytest.approx(-LIQUIDITY_MAX_TILT)


def test_liquidity_can_flip_a_weak_season_tailwind_to_headwind():
    # Low-conviction summer tailwind (+0.3*40 = +12) overwhelmed by a high-conviction
    # liquidity drain (-20) -> net -8 -> headwind. This is the orthogonality payoff.
    m = score_macro_fit(idea(asset_class="crypto", direction="long"), REGIME_SUMMER_LOW_LIQ_CON, SEASONS)
    assert m.label == "headwind"
    assert m.macro_fit_score < NEUTRAL_SCORE


def test_liquidity_moves_a_season_neutral_class_off_neutral():
    # SEASONS has no 'commodities' in winter; use a class the season is silent on
    # but that's liquidity-sensitive. equities in a season-neutral stance:
    seasons_neutral_eq = {"summer": {"asset_playbook": {"equities": "neutral", "crypto": "up"}}}
    m = score_macro_fit(idea(asset_class="equity", direction="long"),
                        REGIME_SUMMER_HIGH_LIQ_EXP, seasons_neutral_eq)
    # season contributes 0, liquidity lifts it -> tailwind despite neutral season.
    assert m.label == "tailwind"
    assert m.macro_fit_score == pytest.approx(NEUTRAL_SCORE + LIQUIDITY_MAX_TILT)


def test_combined_extreme_is_clamped_into_band():
    # High season tailwind (+40) + high expanding liquidity (+20) = +60, but the
    # score clamps at SCORE_CEIL rather than 110.
    m = score_macro_fit(idea(asset_class="crypto", direction="long"), REGIME_SUMMER_HIGH_LIQ_EXP, SEASONS)
    assert m.macro_fit_score == pytest.approx(SCORE_CEIL)
    assert m.macro_fit_score <= 100.0


def test_liquidity_ignored_on_degraded_neutral_paths():
    # No season -> stays a hard neutral 50, liquidity never applies.
    m = score_macro_fit(idea(asset_class="crypto"), {"liquidity_regime": "expanding",
                                                     "liquidity_conviction": "high"}, SEASONS)
    assert m.label == "neutral"
    assert m.macro_fit_score == pytest.approx(NEUTRAL_SCORE)
    assert m.liquidity_tilt == 0.0


def test_liquidity_fields_persist_in_row():
    m = score_macro_fit(idea(asset_class="crypto", direction="long"), REGIME_SUMMER_HIGH_LIQ_CON, SEASONS)
    d = m.as_dict()
    assert d["liquidity_regime"] == "contracting"
    assert d["liquidity_tilt"] == pytest.approx(-LIQUIDITY_MAX_TILT)
