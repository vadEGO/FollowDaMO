"""Unit tests for the technical scorer (scripts/score_technical.py).

Pure indicator math + composite scoring. No network/DB.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from scripts.score_technical import (
    sma, rsi, range_position,
    score_technical, TechnicalScore,
    NEUTRAL_SCORE, SMA_FAST,
)


# ── SMA ──────────────────────────────────────────────────────────────────────

def test_sma_basic():
    assert sma([1, 2, 3, 4, 5], 5) == pytest.approx(3.0)
    assert sma([1, 2, 3, 4, 5], 2) == pytest.approx(4.5)  # last 2 = (4+5)/2


def test_sma_too_few_returns_none():
    assert sma([1, 2], 5) is None
    assert sma([], 3) is None


# ── RSI ──────────────────────────────────────────────────────────────────────

def test_rsi_all_gains_is_100():
    closes = list(range(1, 20))  # strictly increasing
    assert rsi(closes) == pytest.approx(100.0)


def test_rsi_all_losses_is_low():
    closes = list(range(20, 1, -1))  # strictly decreasing
    assert rsi(closes) == pytest.approx(0.0, abs=1e-6)


def test_rsi_flat_series_is_50():
    # No gains and no losses -> neutral 50 (avg_loss==0, avg_gain==0 branch).
    assert rsi([100.0] * 20) == pytest.approx(50.0)


def test_rsi_insufficient_data_none():
    assert rsi([1, 2, 3], period=14) is None


def test_rsi_known_value():
    # Classic alternating/mixed series stays mid-range, not at extremes.
    closes = [44, 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
              45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    val = rsi(closes, period=14)
    assert val is not None
    assert 60 <= val <= 80  # uptrending sample -> elevated but not pinned


# ── range position ────────────────────────────────────────────────────────────

def test_range_position_at_high_and_low():
    assert range_position([10, 20, 30], lookback=30) == pytest.approx(1.0)   # close == high
    assert range_position([30, 20, 10], lookback=30) == pytest.approx(0.0)   # close == low


def test_range_position_flat_is_none():
    assert range_position([5, 5, 5]) is None


# ── composite scoring ─────────────────────────────────────────────────────────

def _trend_series(n, start, step):
    return [start + i * step for i in range(n)]


def test_strong_uptrend_scores_bullish():
    s = score_technical("UP", _trend_series(60, 100, 1.0))  # steady climb
    assert s.trend == "up"
    assert s.technical_score > 60
    assert s.label in ("bullish", "strong")
    assert s.rsi is not None and s.rsi > 50


def test_strong_downtrend_scores_bearish():
    s = score_technical("DOWN", _trend_series(60, 160, -1.0))  # steady decline
    assert s.trend == "down"
    assert s.technical_score < 40
    assert s.label in ("bearish", "weak")


def test_insufficient_data_is_neutral_and_safe():
    s = score_technical("NEW", [100, 101, 102])  # < SMA_FAST+1
    assert s.label == "insufficient_data"
    assert s.technical_score == pytest.approx(NEUTRAL_SCORE)
    assert s.trend == "n/a"
    assert s.n_candles == 3


def test_score_bounded_0_100():
    for series in (_trend_series(80, 100, 5.0), _trend_series(80, 500, -5.0)):
        s = score_technical("X", series)
        assert 0.0 <= s.technical_score <= 100.0


def test_real_sol_series_runs():
    # The actual SOL closes pulled from market_candles (ascending) — must
    # produce a finite score and a real label, whatever the direction.
    sol = [86.3192, 89.145, 88.4048, 91.9498, 93.1455, 96.427, 97.3502,
           94.2843, 91.0855, 92.1487, 89.2004, 86.5365]
    # pad to enough candles by prepending a gentle ramp
    series = _trend_series(40, 70, 0.5) + sol
    s = score_technical("SOL", series)
    assert s.label != "insufficient_data"
    assert 0.0 <= s.technical_score <= 100.0
    assert s.price == pytest.approx(86.5365)


def test_as_dict_has_persistence_fields():
    d = score_technical("UP", _trend_series(60, 100, 1.0)).as_dict()
    assert set(d) >= {"symbol", "technical_score", "label", "trend", "rsi", "price", "rationale"}
