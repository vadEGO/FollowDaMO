"""Unit tests for the LLM extraction schema validation."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest


def get_validate():
    from scripts.extract_mentions import AssetMention, _validate_and_fix
    return AssetMention, _validate_and_fix


def test_valid_mention():
    _, validate = get_validate()
    raw = json.dumps([{
        "raw_mention": "SOL",
        "resolved_asset": "Solana",
        "symbol": "SOL",
        "asset_type": "crypto",
        "context_snippet": "SOL is a strong buy here",
        "investment_intent": "buy",
        "sentiment": "bullish",
        "confidence": "high",
        "needs_review": False,
    }])
    valid, errors = validate(raw, "patreon", {"SOL", "BTC"}, set())
    assert len(valid) == 1
    assert valid[0].symbol == "SOL"
    assert not errors


def test_float_confidence_coerced():
    AssetMention, _ = get_validate()
    m = AssetMention(raw_mention="BTC", confidence=0.95)
    assert m.confidence == "high"
    m2 = AssetMention(raw_mention="BTC", confidence=0.3)
    assert m2.confidence == "low"


def test_malformed_json_returns_error():
    _, validate = get_validate()
    valid, errors = validate("not json at all", "patreon", {"SOL"}, set())
    assert len(valid) == 0
    assert len(errors) > 0


def test_missing_required_field_goes_to_error():
    _, validate = get_validate()
    # Missing raw_mention
    raw = json.dumps([{"symbol": "BTC", "confidence": "high"}])
    valid, errors = validate(raw, "patreon", {"BTC"}, set())
    # raw_mention is required — should either fail or flag needs_review
    # Pydantic will raise ValidationError
    assert len(valid) == 0 or valid[0].needs_review


def test_comment_source_caps_confidence():
    _, validate = get_validate()
    raw = json.dumps([{
        "raw_mention": "SOL",
        "symbol": "SOL",
        "confidence": "high",
        "needs_review": False,
    }])
    valid, errors = validate(raw, "youtube_comments", {"SOL"}, set())
    assert valid[0].confidence == "medium"


def test_ambiguous_ticker_sets_needs_review():
    _, validate = get_validate()
    raw = json.dumps([{
        "raw_mention": "NEAR",
        "symbol": "NEAR",
        "confidence": "high",
        "needs_review": False,
    }])
    valid, errors = validate(raw, "patreon", {"NEAR"}, {"NEAR"})
    assert valid[0].needs_review is True


def test_unknown_symbol_sets_needs_review():
    _, validate = get_validate()
    raw = json.dumps([{
        "raw_mention": "FAKECOIN",
        "symbol": "FAKECOIN",
        "confidence": "high",
        "needs_review": False,
    }])
    valid, errors = validate(raw, "patreon", {"BTC", "SOL"}, set())
    assert valid[0].needs_review is True
