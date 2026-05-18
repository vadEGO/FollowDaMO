#!/usr/bin/env python3
"""
Step 1 — Collect raw content from all enabled sources.
Delegates to source-specific collectors based on source type.

Implements: agents/source_collector.md
"""
import argparse
import datetime
import hashlib
import json
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


def _apply_migration(conn) -> None:
    """Ensure migration 002 tables exist (idempotent)."""
    migration_path = ROOT / "migrations" / "002_patreon_comments.sql"
    if not migration_path.exists():
        return
    already = conn.execute(
        "SELECT 1 FROM schema_version WHERE version = 2"
    ).fetchone()
    if already:
        return
    sql = migration_path.read_text()
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # CREATE IF NOT EXISTS — safe to ignore duplicates


def _store_comments(conn, post_url: str, source_name: str,
                    post_title: str, comments: list[dict]) -> int:
    """
    Persist comments to patreon_comments, deduplicated by content_hash.
    Updates patreon_scrape_state with the latest scrape timestamp.
    Returns number of new comments stored.
    """
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO patreon_scrape_state
               (post_url, source_name, post_title, comments_last_scraped_at, comment_count)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(post_url) DO UPDATE SET
               comments_last_scraped_at = excluded.comments_last_scraped_at,
               comment_count = excluded.comment_count""",
        (post_url, source_name, post_title, now, len(comments)),
    )
    new_count = 0
    for c in comments:
        existing = conn.execute(
            "SELECT id FROM patreon_comments WHERE content_hash = ?",
            (c["content_hash"],),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """INSERT INTO patreon_comments
                   (id, post_url, source_name, author, comment_text,
                    published_at, content_hash, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                post_url,
                source_name,
                c["author"],
                c["text"],
                c.get("published_at"),
                c["content_hash"],
                now,
            ),
        )
        new_count += 1
    return new_count


def _append_comments_to_knowledge_file(
    source_name: str, post: dict
) -> None:
    """
    Append any new comments to the post's knowledge-base Markdown file.
    Looks for the most-recently-written file for this post URL.
    """
    if not post.get("comments"):
        return
    safe_title = "".join(
        c for c in post["title"][:50] if c.isalnum() or c in " -_"
    )
    creator_slug = post["url"].split("/")[4] if post["url"].count("/") >= 4 else source_name
    kb_dir = ROOT / "knowledge" / "raw" / creator_slug
    if not kb_dir.exists():
        return
    # Find the file that was written for this post today (or any date)
    candidates = sorted(kb_dir.glob(f"*{safe_title.replace(' ', '_')}*.md"), reverse=True)
    if not candidates:
        return
    target = candidates[0]
    existing = target.read_text()
    comment_header = "\n---\n## Comments"
    # Strip old comment section if present so we don't double-append
    if comment_header in existing:
        existing = existing[: existing.index(comment_header)]
    lines = [existing.rstrip(), "", "---", f"## Comments ({len(post['comments'])})", ""]
    for c in post["comments"]:
        ts = f" — {c['published_at']}" if c.get("published_at") else ""
        lines.append(f"**{c['author']}**{ts}")
        lines.append(c["text"])
        lines.append("")
    target.write_text("\n".join(lines))


def collect_patreon(source: dict, conn, dry_run: bool) -> int:
    _apply_migration(conn)

    cookies_env = os.getenv("PATREON_COOKIES_FILE", "secrets/patreon_cookies.json")
    cookies_path = ROOT / cookies_env
    if not cookies_path.exists():
        print(f"    Patreon cookies not found at {cookies_path}. Run --setup first.")
        return 0

    from scrape_patreon import scrape_creator
    include_comments = source.get("include_comments", False)
    comment_days = source.get("comment_days", 2)

    posts = scrape_creator(
        creator_url=source["creator_url"],
        cookies_path=cookies_path,
        limit=source.get("max_posts_per_run", 10),
        since_days=source.get("poll_interval_hours", 24) // 24 + 1,
        dry_run=dry_run,
        include_comments=include_comments,
        comment_days=comment_days,
    )
    count = 0
    for post in posts:
        # Build the full Markdown document (post body + comments) once.
        # This is what gets stored in both the DB and the knowledge file.
        from scrape_patreon import _format_post_md
        full_md = _format_post_md(post)

        record_id = _store(conn, source["name"], "patreon",
                           post["title"], post["author"],
                           post["url"], post["published_at"], full_md)
        if record_id:
            count += 1
        elif not dry_run and post.get("comments"):
            # Post already seen but comments may be new — update the file
            _append_comments_to_knowledge_file(source["name"], post)

        # Persist individual comments to the comments table for querying
        if not dry_run and post.get("comments"):
            new_comments = _store_comments(
                conn, post["url"], source["name"], post["title"], post["comments"]
            )
            if new_comments:
                print(f"      +{new_comments} new comments for: {post['title'][:50]}")

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


def collect_sec13f(source: dict, conn, dry_run: bool) -> int:
    """
    Collect SEC 13F institutional filings for configured filers.
    Uses SEC EDGAR as primary source (free); WhaleWisdom as optional enhancement.

    Required source config fields:
      filer_slug      — fund name slug matching EDGAR (e.g. situational-awareness-lp)
      filer_cik       — SEC CIK number (auto-discovered if blank)
      edgar_user_agent — required: "YourName/App email@example.com"

    Optional:
      max_positions_per_digest — default 50; caps positions per Markdown section
      include_unchanged        — default false; skip unchanged positions
    """
    from scrape_13f import scrape_filer as scrape_13f

    filer_slug = source.get("filer_slug", "")
    if not filer_slug:
        print(f"    [{source['name']}] No filer_slug configured — skipping")
        return 0

    # edgar_user_agent can be in source config or env
    user_agent = source.get("edgar_user_agent", "") or os.getenv("EDGAR_USER_AGENT", "")
    if not user_agent:
        print(
            f"    [{source['name']}] EDGAR_USER_AGENT not set.\n"
            "      Add to secrets/.env: EDGAR_USER_AGENT=YourName/MoneyTrail your@email.com"
        )
        return 0
    os.environ["EDGAR_USER_AGENT"] = user_agent

    posts = scrape_13f(
        filer_slug=filer_slug,
        filer_cik=source.get("filer_cik") or None,
        max_positions=source.get("max_positions_per_digest", 50),
        include_unchanged=source.get("include_unchanged", False),
        dry_run=dry_run,
    )

    count = 0
    for post in posts:
        record_id = _store(
            conn, source["name"], "sec_13f",
            post["title"], post["author"],
            post["url"], post.get("published_at"), post["text"],
        )
        if record_id:
            count += 1
            # Persist structured positions to sec_13f_positions table
            if not dry_run:
                _store_13f_positions(conn, post)
                _update_13f_state(conn, post)
            print(f"      + {post['title']}")

    return count


def _store_13f_positions(conn, post: dict) -> None:
    """Upsert structured position rows into sec_13f_positions."""
    snapshot = post.get("raw_snapshot")
    if not snapshot:
        return
    try:
        positions = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
    except Exception:
        return

    now = datetime.datetime.utcnow().isoformat()
    filer_slug = post.get("filer_slug", "")
    quarter    = post.get("quarter", "")

    for pos in positions:
        conn.execute(
            """INSERT OR IGNORE INTO sec_13f_positions
               (id, filer_slug, filer_name, quarter, ticker, cusip, company_name,
                shares, market_value_usd, portfolio_pct, shares_change, change_type,
                sector, industry, avg_price, quarter_first_owned, scraped_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                filer_slug,
                post.get("author", "").split("/")[-1].replace("-", " ").title(),
                quarter,
                pos.get("ticker"),
                pos.get("cusip"),
                pos.get("company_name"),
                pos.get("shares"),
                pos.get("market_value_usd"),
                pos.get("portfolio_pct"),
                pos.get("shares_change"),
                pos.get("change_type"),
                pos.get("sector"),
                pos.get("industry"),
                pos.get("avg_price"),
                pos.get("quarter_first_owned"),
                now,
            ),
        )


def _update_13f_state(conn, post: dict) -> None:
    """Update sec_13f_scrape_state after a successful scrape."""
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO sec_13f_scrape_state
               (filer_slug, filer_name, filer_cik, last_quarter, last_raw_snapshot,
                last_scraped_at, position_count, consecutive_failures)
           VALUES (?,?,?,?,?,?,?,0)
           ON CONFLICT(filer_slug) DO UPDATE SET
               filer_cik          = excluded.filer_cik,
               last_quarter       = excluded.last_quarter,
               last_raw_snapshot  = excluded.last_raw_snapshot,
               last_scraped_at    = excluded.last_scraped_at,
               position_count     = excluded.position_count,
               last_error         = NULL,
               consecutive_failures = 0""",
        (
            post.get("filer_slug", ""),
            post.get("author", "").split("/")[-1].replace("-", " ").title(),
            post.get("cik"),
            post.get("quarter"),
            post.get("raw_snapshot"),
            now,
            post.get("position_count", 0),
        ),
    )


COLLECTORS = {
    "local_folder": collect_local_folder,
    "patreon":      collect_patreon,
    "youtube":      collect_youtube,
    "rss":          collect_rss,
    "sec_13f":      collect_sec13f,
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
