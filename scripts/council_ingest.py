#!/usr/bin/env python3
"""
Council, step 3 of 3 — INGEST.

Validates the deliberation the agent produced (knowledge/council_results/<SLUG>.json)
and upserts it to Supabase `council_runs` + `persona_positions` — the tables the
dashboard's /research page reads (public_latest_council_runs / public_persona_positions).
No LLM call: deterministic validate-and-store.

Usage:
    python scripts/council_ingest.py --topic "Bitcoin liquidity through year-end"
    python scripts/council_ingest.py --topic BTC --dry-run   # validate only, no write
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

RESULT_DIR = ROOT / "knowledge" / "council_results"
COUNCIL_YAML = ROOT / "config" / "council.yaml"

# Reuse the Supabase env loader the other scorers use (secrets/.env.supabase).
import score_technical as st

try:
    from pydantic import BaseModel, field_validator, ValidationError
except ImportError:
    print("pydantic not installed. Run: pip install pydantic", file=sys.stderr)
    sys.exit(1)


def slugify(topic: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    return s[:60] or "topic"


def _allowed_states() -> set[str]:
    try:
        import yaml
        data = yaml.safe_load(COUNCIL_YAML.read_text()) or {}
        return set(data.get("decision_states", [])) or {"research_further"}
    except Exception:
        return {"research_further"}


def _clamp01(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


class PersonaPosition(BaseModel):
    persona: str
    thesis: str = ""
    supporting_evidence: list[str] = []
    counterpoints: list[str] = []
    risks: list[str] = []
    investment_implications: str = ""
    what_would_change_my_mind: list[str] = []
    confidence: float = 0.0

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v):
        return _clamp01(v)

    @field_validator("supporting_evidence", "counterpoints", "risks",
                     "what_would_change_my_mind", mode="before")
    @classmethod
    def _list(cls, v):
        if v is None:
            return []
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]


class CouncilResult(BaseModel):
    topic: str
    decision_state: str = "research_further"
    confidence: float = 0.0
    consensus_view: str = ""
    recommended_next_step: str = ""
    agreements: list[str] = []
    disagreements: list[str] = []
    most_important_uncertainties: list[str] = []
    what_would_change_our_mind: list[str] = []
    personal_constraints_public: list[str] = []
    personas: list[PersonaPosition] = []

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v):
        return _clamp01(v)

    @field_validator("agreements", "disagreements", "most_important_uncertainties",
                     "what_would_change_our_mind", "personal_constraints_public", mode="before")
    @classmethod
    def _list(cls, v):
        if v is None:
            return []
        return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def _supabase_upsert(table: str, rows: list[dict], url: str, key: str) -> bool:
    if not rows:
        return True
    try:
        import httpx
    except ImportError:
        print("  httpx not installed (pip install httpx) — cannot write.", file=sys.stderr)
        return False
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    try:
        r = httpx.post(f"{url}/rest/v1/{table}", headers=headers, json=rows, timeout=30)
    except httpx.HTTPError as e:
        print(f"  ERROR upserting to {table}: {e}", file=sys.stderr)
        return False
    if r.status_code not in (200, 201):
        print(f"  ERROR upserting to {table}: {r.status_code} {r.text[:300]}", file=sys.stderr)
        return False
    return True


def ingest(topic: str, dry_run: bool) -> bool:
    import json
    slug = slugify(topic)
    result_path = RESULT_DIR / f"{slug}.json"
    if not result_path.exists():
        print(f"[council_ingest] no result file at {result_path.relative_to(ROOT)} — "
              f"run council_prepare.py and have the agent deliberate first.", file=sys.stderr)
        return False

    try:
        result = CouncilResult(**json.loads(result_path.read_text()))
    except (json.JSONDecodeError, ValidationError) as e:
        print(f"[council_ingest] invalid result file: {e}", file=sys.stderr)
        return False

    # Coerce decision_state to the allowed set.
    if result.decision_state not in _allowed_states():
        print(f"  note: decision_state '{result.decision_state}' not in config; "
              f"storing as 'research_further'.")
        result.decision_state = "research_further"

    print(f"[council_ingest] {topic}: {result.decision_state} "
          f"(confidence {result.confidence:.2f}, {len(result.personas)} personas)")

    if dry_run:
        print("  [DRY RUN] validated; not writing to Supabase.")
        return True

    url, key = st._load_env_supabase()
    if not url or not key:
        print("  SUPABASE creds not set (secrets/.env.supabase) — skipping write.", file=sys.stderr)
        return False

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    run_id = f"moneytrail_{slug}"

    council_row = {
        "id": run_id,
        "topic_pack_id": None,
        "topic": result.topic or topic,
        "decision_state": result.decision_state,
        "confidence": result.confidence,
        "consensus_view": result.consensus_view,
        "recommended_next_step": result.recommended_next_step,
        # NOT-NULL array columns — always a list
        "agreements": result.agreements,
        "disagreements": result.disagreements,
        "most_important_uncertainties": result.most_important_uncertainties,
        "what_would_change_our_mind": result.what_would_change_our_mind,
        "personal_constraints_public": result.personal_constraints_public,
        "reasoning_mode": "agent_synthesized",
        "llm_model": "claude-code-agent",
        "created_at": now,
    }
    persona_rows = [{
        "id": f"{run_id}_{p.persona}",
        "council_run_id": run_id,
        "persona": p.persona,
        "thesis": p.thesis,
        "supporting_evidence": p.supporting_evidence,
        "counterpoints": p.counterpoints,
        "risks": p.risks,
        "investment_implications": p.investment_implications,
        "what_would_change_my_mind": p.what_would_change_my_mind,
        "confidence": p.confidence,
        "reasoning_mode": "agent_synthesized",
        "created_at": now,
    } for p in result.personas]

    if not _supabase_upsert("council_runs", [council_row], url, key):
        return False
    if not _supabase_upsert("persona_positions", persona_rows, url, key):
        print("  WARNING: council run stored but persona positions failed.", file=sys.stderr)
        return False
    print(f"  → council_runs ({run_id}) + {len(persona_rows)} persona_positions")
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate + store the agent's council deliberation")
    parser.add_argument("--topic", required=True, help="Topic or asset symbol")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    ok = ingest(args.topic, args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
