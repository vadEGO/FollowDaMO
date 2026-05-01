#!/usr/bin/env python3
"""
Step 2 — Extract investable asset mentions from raw content.
All LLM output is validated via Pydantic before any database write.

Implements: agents/asset_extractor.md
"""
import argparse
import datetime
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from pydantic import BaseModel, field_validator, ValidationError
except ImportError:
    print("pydantic not installed. Run: pip install pydantic")
    sys.exit(1)


class AssetMention(BaseModel):
    raw_mention: str
    resolved_asset: str | None = None
    symbol: str | None = None
    asset_type: str | None = None
    context_snippet: str | None = None
    investment_intent: str | None = None
    sentiment: str | None = None
    time_horizon: str | None = None
    confidence: Literal["high", "medium", "low"] = "low"
    needs_review: bool = True
    reason: str | None = None
    raw_llm_response: str | None = None  # set by caller, not LLM

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v):
        if isinstance(v, float):
            if v >= 0.7:
                return "high"
            elif v >= 0.4:
                return "medium"
            return "low"
        if isinstance(v, str) and v.lower() in ("high", "medium", "low"):
            return v.lower()
        return "low"


def _load_env():
    from dotenv import load_dotenv
    load_dotenv(ROOT / "secrets" / ".env")


def _get_conn():
    import sqlite3
    conn = sqlite3.connect(ROOT / "data" / "moneytrail.sqlite")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _load_known_assets() -> tuple[set[str], set[str]]:
    """Returns (valid_symbols, ambiguous_symbols)."""
    import yaml
    with open(ROOT / "config" / "assets.yaml") as f:
        cfg = yaml.safe_load(f)
    valid = set()
    for section in ("crypto", "equities", "etfs"):
        for asset in cfg.get(section, []):
            valid.add(asset["symbol"].upper())
    ambiguous = {s.upper() for s in cfg.get("ambiguous_tickers", [])}
    return valid, ambiguous


def _call_llm(content: str, prompt_template: str) -> str:
    """Call the configured LLM with the extraction prompt."""
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("No LLM API key found in secrets/.env")

    prompt = prompt_template.replace("{{CONTENT}}", content)

    if os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",   # fast + cheap for extraction
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    else:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
        )
        return response.choices[0].message.content


def _validate_and_fix(raw_response: str, source_type: str,
                      valid_symbols: set[str], ambiguous_symbols: set[str]
                      ) -> tuple[list[AssetMention], list[str]]:
    """
    Parse and validate the LLM response. Returns (valid_mentions, error_messages).
    Invalid items go to resolution_queue, not asset_mentions.
    """
    errors = []
    try:
        # Find JSON array in response (LLM may include prose before/after)
        start = raw_response.find("[")
        end = raw_response.rfind("]") + 1
        if start == -1 or end == 0:
            errors.append(f"No JSON array found in response")
            return [], errors
        data = json.loads(raw_response[start:end])
    except json.JSONDecodeError as e:
        errors.append(f"JSON decode error: {e}")
        return [], errors

    if not isinstance(data, list):
        errors.append("LLM returned non-array JSON")
        return [], errors

    valid = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"Item {i} is not a dict")
            continue
        try:
            mention = AssetMention(**item)
        except ValidationError as e:
            errors.append(f"Item {i} validation error: {e}")
            continue

        # Cap confidence for comment sources
        if "comment" in source_type.lower():
            if mention.confidence == "high":
                mention.confidence = "medium"

        # Force needs_review for ambiguous tickers
        if mention.symbol and mention.symbol.upper() in ambiguous_symbols:
            mention.needs_review = True

        # Reject unrecognised symbols (not null, not in registry)
        if mention.symbol and mention.symbol.upper() not in valid_symbols:
            mention.needs_review = True  # goes to resolution queue

        valid.append(mention)

    return valid, errors


def main():
    _load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    prompt_path = ROOT / "prompts" / "extraction_prompt.md"
    prompt_template = prompt_path.read_text()

    conn = _get_conn()
    valid_symbols, ambiguous_symbols = _load_known_assets()

    # Load unprocessed content
    already_extracted = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT content_id FROM asset_mentions"
        ).fetchall()
    }
    rows = conn.execute("SELECT id, source_type, raw_text FROM raw_content").fetchall()
    unprocessed = [r for r in rows if r["id"] not in already_extracted]

    print(f"[extract_mentions] {len(unprocessed)} unprocessed content items")
    total_mentions = 0
    total_queued = 0

    for row in unprocessed:
        content_id = row["id"]
        source_type = row["source_type"]
        text = row["raw_text"] or ""

        if not text.strip():
            continue

        # Chunk to 2000 tokens approx (rough: 4 chars / token)
        chunks = [text[i:i+8000] for i in range(0, len(text), 8000)]

        for chunk in chunks:
            try:
                raw_response = _call_llm(chunk, prompt_template)
            except Exception as exc:
                print(f"  LLM error for {content_id}: {exc}")
                continue

            mentions, errors = _validate_and_fix(
                raw_response, source_type, valid_symbols, ambiguous_symbols
            )

            if errors:
                # Store failed validation in resolution_queue
                for err in errors:
                    if not args.dry_run:
                        conn.execute(
                            """INSERT INTO resolution_queue
                               (id, raw_mention, candidate_resolutions, context_snippet, source_name, created_at)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (str(uuid.uuid4()), "VALIDATION_ERROR",
                             json.dumps({"error": err, "raw": raw_response[:500]}),
                             chunk[:200], source_type,
                             datetime.datetime.utcnow().isoformat()),
                        )
                        total_queued += 1

            for mention in mentions:
                if args.dry_run:
                    print(f"  [DRY RUN] {mention.symbol or mention.raw_mention}: {mention.confidence}, needs_review={mention.needs_review}")
                    continue

                if mention.needs_review:
                    # Route to resolution_queue
                    conn.execute(
                        """INSERT INTO resolution_queue
                           (id, raw_mention, candidate_resolutions, context_snippet, source_name, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (str(uuid.uuid4()), mention.raw_mention,
                         json.dumps([mention.symbol] if mention.symbol else []),
                         mention.context_snippet, source_type,
                         datetime.datetime.utcnow().isoformat()),
                    )
                    total_queued += 1
                else:
                    conn.execute(
                        """INSERT INTO asset_mentions
                           (id, content_id, raw_mention, resolved_asset, symbol, asset_type,
                            confidence, context_snippet, sentiment, intent, time_horizon,
                            needs_review, raw_llm_response, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (str(uuid.uuid4()), content_id, mention.raw_mention,
                         mention.resolved_asset, mention.symbol, mention.asset_type,
                         mention.confidence, mention.context_snippet,
                         mention.sentiment, mention.investment_intent,
                         mention.time_horizon, 0, raw_response[:2000],
                         datetime.datetime.utcnow().isoformat()),
                    )
                    total_mentions += 1

        if not args.dry_run:
            conn.commit()

    conn.close()
    print(f"[extract_mentions] Stored {total_mentions} mentions, queued {total_queued} for review")


if __name__ == "__main__":
    main()
