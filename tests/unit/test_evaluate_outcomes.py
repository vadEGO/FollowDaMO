"""Unit tests for the self-evolving feedback loop (scripts/evaluate_outcomes.py).

Covers the outcome-scoring math, source calibration nudge + bounds, and the
zero-data bootstrap path.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from scripts.evaluate_outcomes import (
    outcome_score, calibrate_sources, score_outcomes,
    LEARNING_RATE, WEIGHT_FLOOR, WEIGHT_CEIL,
)


# ── outcome_score ─────────────────────────────────────────────────────────────

def test_flat_outcome_is_50():
    assert outcome_score(100, price_30d=100, price_90d=100, max_drawdown_90d=0) == pytest.approx(50.0)


def test_gain_scores_above_50():
    # +20% blended, no drawdown -> 50 + 20 = 70
    s = outcome_score(100, price_30d=120, price_90d=120, max_drawdown_90d=0)
    assert s == pytest.approx(70.0)


def test_loss_scores_below_50():
    s = outcome_score(100, price_30d=80, price_90d=80, max_drawdown_90d=0)
    assert s == pytest.approx(30.0)


def test_drawdown_penalises_a_gain():
    # +20% gain but 20% max drawdown -> risk-adjusted 0 -> 50
    s = outcome_score(100, price_30d=120, price_90d=120, max_drawdown_90d=0.20)
    assert s == pytest.approx(50.0)


def test_horizon_blend_weights_90d_more():
    # 30d flat, 90d +50%. Blend = 0.4*0 + 0.6*0.5 = 0.30 -> 80
    s = outcome_score(100, price_30d=100, price_90d=150, max_drawdown_90d=0)
    assert s == pytest.approx(80.0)


def test_score_clamped_0_100():
    assert outcome_score(100, price_30d=1000, price_90d=1000, max_drawdown_90d=0) == 100.0
    assert outcome_score(100, price_30d=1, price_90d=1, max_drawdown_90d=0) == 0.0


def test_missing_prices_returns_none():
    assert outcome_score(100, price_30d=None, price_90d=None, max_drawdown_90d=0) is None


def test_zero_entry_returns_none():
    assert outcome_score(0, price_30d=100, price_90d=100, max_drawdown_90d=0) is None


def test_partial_horizon_uses_what_exists():
    # only 30d present -> uses 30d alone
    s = outcome_score(100, price_30d=110, price_90d=None, max_drawdown_90d=0)
    assert s == pytest.approx(60.0)


# ── calibration ───────────────────────────────────────────────────────────────

def make_conn_with_source(weight=0.70):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE source_scores (
        source_name TEXT PRIMARY KEY, source_type TEXT, base_credibility REAL,
        historical_accuracy REAL, signal_weight REAL, hype_tendency REAL,
        late_cycle_tendency REAL, notes TEXT)""")
    conn.execute("INSERT INTO source_scores (source_name, signal_weight) VALUES (?, ?)",
                 ("src_a", weight))
    return conn


def test_calibration_nudges_toward_realized():
    conn = make_conn_with_source(weight=0.70)
    # realized accuracy 0.90 (all great outcomes) -> weight should move UP toward it
    cals = calibrate_sources(conn, {"src_a": [90.0, 90.0]})
    c = cals[0]
    expected = 0.70 + LEARNING_RATE * (0.90 - 0.70)
    assert c.new_signal_weight == pytest.approx(round(expected, 4))
    assert c.new_signal_weight > c.old_signal_weight
    assert c.delta > 0


def test_calibration_moves_down_on_bad_outcomes():
    conn = make_conn_with_source(weight=0.80)
    cals = calibrate_sources(conn, {"src_a": [20.0]})  # realized 0.20
    assert cals[0].new_signal_weight < 0.80
    assert cals[0].delta < 0


def test_calibration_respects_floor():
    conn = make_conn_with_source(weight=WEIGHT_FLOOR + 0.01)
    # terrible realized accuracy repeatedly can't push below the floor
    cals = calibrate_sources(conn, {"src_a": [0.0]})
    assert cals[0].new_signal_weight >= WEIGHT_FLOOR


def test_calibration_respects_ceiling():
    conn = make_conn_with_source(weight=WEIGHT_CEIL - 0.001)
    cals = calibrate_sources(conn, {"src_a": [100.0]})
    assert cals[0].new_signal_weight <= WEIGHT_CEIL


def test_unknown_source_skipped():
    conn = make_conn_with_source()
    cals = calibrate_sources(conn, {"not_in_table": [80.0]})
    assert cals == []


def test_gradual_evolution_not_lurch():
    # A single great outcome must NOT slam the weight to 1.0 — it evolves.
    conn = make_conn_with_source(weight=0.70)
    cals = calibrate_sources(conn, {"src_a": [100.0]})
    assert cals[0].new_signal_weight < 0.80  # moved up but bounded by learning rate


# ── bootstrap (zero outcomes) ─────────────────────────────────────────────────

def test_score_outcomes_empty_table_is_empty():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE model_decision_outcomes (
        id TEXT, asset TEXT, initial_decision TEXT, decision_date TEXT,
        entry_price REAL, price_7d REAL, price_30d REAL, price_90d REAL,
        max_drawdown_90d REAL, outcome_score REAL)""")
    assert score_outcomes(conn) == []
