#!/usr/bin/env python3
"""
Step 1 — Collect raw content from all enabled sources.
Delegates to source-specific collectors based on source type.

Implements: agents/source_collector.md
"""
import argparse
import datetime
import hashlib
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


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


def _load_sources():
    import yaml
    with open(ROOT / "config" / "sources.yaml") as f:
        cfg = yaml.safe_load(f)
    return [s for s in cfg.get("sources", []) if s.get("enabled")]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _already_seen(conn, content_hash: str) -> bool:
    row = conn.execute(
        "SELECT id FROM raw_content WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    return row is not None


def _store(conn, source_name: str, source_type: str, title: str, author: str,
           url: str, published_at: str, raw_text: str) -> str | None:
    ch = _content_hash(raw_text)
    if _already_seen(conn, ch):
        return None
    record_id = str(uuid.uuid4())
    out_dir = ROOT / "knowledge" / "raw" / source_name / datetime.date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{record_id}.md").write_text(raw_text)
    conn.execute(
        """INSERT INTO raw_content
           (id, source_name, source_type, title, author, url, published_at, collected_at, content_hash, raw_text)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (record_id, source_name, source_type, title, author, url,
         published_at, datetime.datetime.utcnow().isoformat(), ch, raw_text),
    )
    return record_id


def collect_local_folder(source: dict, conn, dry_run: bool) -> int:
    folder = ROOT / source.get("path", "knowledge/raw/drop/")
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    for fpath in sorted(folder.glob("*.md")) + sorted(folder.glob("*.txt")):
        text = fpath.read_text()
        if not text.strip():
            continue
        if dry_run:
            print(f"    [DRY RUN] Would ingest: {fpath.name}")
            continue
        record_id = _store(conn, source["name"], "local_folder",
                           fpath.stem, "local", str(fpath), None, text)
        if record_id:
            count += 1
    return count


def collect_patreon(source: dict, conn, dry_run: bool) -> int:
    cookies_env = os.getenv("PATREON_COOKIES_FILE", "secrets/patreon_cookies.json")
    cookies_path = ROOT / cookies_env
    if not cookies_path.exists():
        print(f"    Patreon cookies not found at {cookies_path}. Run --setup first.")
        return 0

    from scrape_patreon import scrape_creator
    posts = scrape_creator(
        creator_url=source["creator_url"],
        cookies_path=cookies_path,
        limit=source.get("max_posts_per_run", 10),
        since_days=source.get("poll_interval_hours", 24) // 24 + 1,
        dry_run=dry_run,
    )
    count = 0
    for post in posts:
        record_id = _store(conn, source["name"], "patreon",
                           post["title"], post["author"],
                           post["url"], post["published_at"], post["text"])
        if record_id:
            count += 1
    return count


def collect_youtube(source: dict, conn, dry_run: bool) -> int:
    # Requires: pip install youtube-transcript-api
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("    youtube-transcript-api not installed. Run: pip install youtube-transcript-api")
        return 0
    # TODO: fetch new video IDs from channel/playlist, get transcripts
    print("    YouTube collector: stub — implement video ID fetching")
    return 0


def collect_rss(source: dict, conn, dry_run: bool) -> int:
    # Requires: pip install feedparser
    try:
        import feedparser
    except ImportError:
        print("    feedparser not installed. Run: pip install feedparser")
        return 0
    url = source.get("url", "")
    if not url:
        return 0
    feed = feedparser.parse(url)
    count = 0
    for entry in feed.entries[:20]:
        text = f"# {entry.get('title', '')}\n\n{entry.get('summary', '')}"
        if dry_run:
            print(f"    [DRY RUN] Would ingest: {entry.get('title', '')[:60]}")
            continue
        record_id = _store(conn, source["name"], "rss",
                           entry.get("title", ""), entry.get("author", ""),
                           entry.get("link", ""), entry.get("published", None), text)
        if record_id:
            count += 1
    return count


COLLECTORS = {
    "local_folder": collect_local_folder,
    "patreon": collect_patreon,
    "youtube": collect_youtube,
    "rss": collect_rss,
}


def main():
    _load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source", help="Run only this source name")
    args = parser.parse_args()

    sources = _load_sources()
    if args.source:
        sources = [s for s in sources if s["name"] == args.source]

    conn = _get_conn()
    total = 0
    for source in sources:
        stype = source.get("type")
        collector = COLLECTORS.get(stype)
        if not collector:
            print(f"  [{source['name']}] Unknown type: {stype}")
            continue
        print(f"  Collecting {source['name']} ({stype})...")
        try:
            n = collector(source, conn, args.dry_run)
            total += n
            print(f"    {n} new records")
            if not args.dry_run:
                conn.commit()
        except Exception as exc:
            print(f"    ERROR: {exc}")
            conn.rollback()

    conn.close()
    print(f"[ingest_sources] Total new records: {total}")


if __name__ == "__main__":
    main()
