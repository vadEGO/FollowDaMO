"""Regression tests for thesis-score normalization (scripts/update_thesis_memory.py).

The bug this guards against: research-backed assets had `score` normalised to a
0-1 scale but `conviction_score` left on the raw 0-100 scale, so the two fields
disagreed on units. Both must now agree on the 0-1 scale.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from scripts.update_thesis_memory import upsert_thesis_scores, DEFAULT_SCORE


def make_conn() -> sqlite3.Connection:
    """Minimal in-memory asset_thesis_scores table matching the writer's columns."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE asset_thesis_scores (
            id TEXT PRIMARY KEY, asset TEXT, thesis TEXT, score REAL,
            primary_thesis INTEGER, portfolio_role TEXT, best_expression_rank INTEGER,
            lifecycle_stage TEXT, conviction_score REAL, invalidation_conditions TEXT,
            add_conditions TEXT, trim_conditions TEXT, last_reviewed TEXT,
            version INTEGER, is_placeholder INTEGER NOT NULL DEFAULT 1
        )
    """)
    return conn


ASSETS = [
    {"symbol": "BTC", "name": "Bitcoin", "primary_thesis": "scarce_assets"},
    {"symbol": "NVDA", "name": "NVIDIA", "primary_thesis": "ai_growth"},
]


def rows_by_symbol(conn):
    return {r["asset"]: r for r in conn.execute("SELECT * FROM asset_thesis_scores").fetchall()}


def test_placeholder_uses_default_score_on_0_1_scale():
    conn = make_conn()
    upsert_thesis_scores(conn, ASSETS, research_scores={}, dry_run=False)
    rows = rows_by_symbol(conn)
    btc = rows["Bitcoin"]
    assert btc["score"] == pytest.approx(DEFAULT_SCORE)   # 0.75, on 0-1 scale
    assert btc["is_placeholder"] == 1
    assert btc["conviction_score"] is None                # placeholders carry no conviction


def test_research_backed_score_and_conviction_share_units():
    # thesis_fit_score arrives on a 0-100 scale (e.g. 80 = "strong").
    conn = make_conn()
    upsert_thesis_scores(conn, ASSETS, research_scores={"NVDA": 80.0}, dry_run=False)
    nvda = rows_by_symbol(conn)["NVIDIA"]
    assert nvda["is_placeholder"] == 0
    # Both fields must be on the SAME 0-1 scale — this is the regression.
    assert nvda["score"] == pytest.approx(0.80)
    assert nvda["conviction_score"] == pytest.approx(0.80)
    assert nvda["score"] == nvda["conviction_score"]


def test_already_normalised_research_score_passthrough():
    # If a research score is already <= 1 it must not be divided again.
    conn = make_conn()
    upsert_thesis_scores(conn, ASSETS, research_scores={"NVDA": 0.65}, dry_run=False)
    nvda = rows_by_symbol(conn)["NVIDIA"]
    assert nvda["score"] == pytest.approx(0.65)
    assert nvda["conviction_score"] == pytest.approx(0.65)


def test_all_scores_within_unit_range():
    conn = make_conn()
    upsert_thesis_scores(conn, ASSETS, research_scores={"BTC": 92.0, "NVDA": 55.0}, dry_run=False)
    for r in conn.execute("SELECT score, conviction_score FROM asset_thesis_scores").fetchall():
        assert 0.0 <= r["score"] <= 1.0
        if r["conviction_score"] is not None:
            assert 0.0 <= r["conviction_score"] <= 1.0
