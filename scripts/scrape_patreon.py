#!/usr/bin/env python3
"""
Patreon scraper using Playwright (headless browser).

Patreon has no public API for patron content. This uses a saved browser
session (cookies) to scrape posts as an authenticated user.

Usage:
    python scripts/scrape_patreon.py --setup             # one-time cookie export
    python scripts/scrape_patreon.py --creator investanswers
    python scripts/scrape_patreon.py --creator realvision --limit 5 --dry-run

Cookie setup (run once, then cookies last ~30 days):
    1. Run: python scripts/scrape_patreon.py --setup
    2. The browser opens. Log in to Patreon manually.
    3. Press Enter in the terminal when logged in.
    4. Cookies are saved to secrets/patreon_cookies.json

Patreon ToS note:
    This scraper is for personal use only — accessing content you have
    legitimately paid for. Do not use to scrape content you don't have
    access to or redistribute scraped content.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_env() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "secrets" / ".env")


def setup_cookies() -> None:
    """Open a real browser so the user can log in, then save cookies."""
    from playwright.sync_api import sync_playwright

    cookies_path = ROOT / "secrets" / "patreon_cookies.json"
    print("Opening browser. Log in to Patreon, then press Enter here.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.patreon.com/login")
        input("Press Enter after logging in...")
        cookies = context.cookies()
        with open(cookies_path, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"Cookies saved to {cookies_path}")
        browser.close()


def scrape_creator(
    creator_url: str,
    cookies_path: Path,
    limit: int = 10,
    since_days: int = 2,
    dry_run: bool = False,
) -> list[dict]:
    """
    Scrape recent posts from a Patreon creator page.
    Returns a list of post dicts: {title, author, url, published_at, text, content_hash}
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    if not cookies_path.exists():
        raise FileNotFoundError(
            f"Cookie file not found: {cookies_path}\n"
            "Run: python scripts/scrape_patreon.py --setup"
        )

    with open(cookies_path) as f:
        cookies = json.load(f)

    since_dt = datetime.now(timezone.utc) - timedelta(days=since_days)
    posts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        context.add_cookies(cookies)
        page = context.new_page()

        # Navigate to creator posts feed
        posts_url = creator_url.rstrip("/") + "/posts"
        print(f"  Loading {posts_url}...")
        try:
            page.goto(posts_url, wait_until="networkidle", timeout=30_000)
        except PWTimeout:
            print("  Timeout loading page — partial content may be available")

        # Scroll to load more posts
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)

        # Extract post cards
        post_links = page.query_selector_all("a[href*='/posts/']")
        seen_urls: set[str] = set()
        post_urls: list[str] = []
        for link in post_links:
            href = link.get_attribute("href") or ""
            if "/posts/" in href and href not in seen_urls:
                full_url = (
                    href if href.startswith("http")
                    else "https://www.patreon.com" + href
                )
                seen_urls.add(href)
                post_urls.append(full_url)
            if len(post_urls) >= limit:
                break

        print(f"  Found {len(post_urls)} post URLs")

        for url in post_urls[:limit]:
            try:
                post = _scrape_post(page, url, since_dt, dry_run)
                if post:
                    posts.append(post)
            except Exception as exc:
                print(f"  Error scraping {url}: {exc}")
                continue

        browser.close()

    return posts


def _scrape_post(page, url: str, since_dt: datetime, dry_run: bool) -> dict | None:
    """Scrape a single Patreon post page."""
    page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    time.sleep(1)

    # Title
    title_el = page.query_selector("h1")
    title = title_el.inner_text().strip() if title_el else "Untitled"

    # Published date — look for datetime attributes
    time_el = page.query_selector("time[datetime]")
    published_at = None
    if time_el:
        dt_str = time_el.get_attribute("datetime") or ""
        try:
            published_at = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    if published_at and published_at < since_dt:
        return None  # too old, skip

    # Author
    author_el = page.query_selector("a[href*='/user?u=']")
    author = author_el.inner_text().strip() if author_el else "Unknown"

    # Content — grab all text paragraphs in the post body
    body_el = page.query_selector("[data-tag='post-content']") or page.query_selector("article")
    text = ""
    if body_el:
        text = body_el.inner_text()
    else:
        # Fallback: all paragraph text
        paras = page.query_selector_all("p")
        text = "\n\n".join(p.inner_text() for p in paras if len(p.inner_text()) > 20)

    if not text.strip():
        return None

    content_hash = hashlib.sha256(text.encode()).hexdigest()

    if dry_run:
        print(f"  [DRY RUN] Would collect: {title[:60]}... ({len(text)} chars)")
        return None

    return {
        "title": title,
        "author": author,
        "url": url,
        "published_at": published_at.isoformat() if published_at else None,
        "text": text,
        "content_hash": content_hash,
    }


def main() -> None:
    _load_env()

    parser = argparse.ArgumentParser(description="Patreon scraper for MoneyTrail")
    parser.add_argument("--setup", action="store_true", help="One-time cookie setup")
    parser.add_argument("--creator", help="Creator URL slug (e.g. investanswers)")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--since-days", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.setup:
        setup_cookies()
        return

    if not args.creator:
        parser.error("--creator is required unless --setup")

    cookies_path_env = os.getenv("PATREON_COOKIES_FILE", "secrets/patreon_cookies.json")
    cookies_path = ROOT / cookies_path_env

    creator_url = (
        args.creator if args.creator.startswith("http")
        else f"https://www.patreon.com/{args.creator}"
    )

    print(f"Scraping {creator_url} (limit={args.limit}, since={args.since_days}d)...")
    posts = scrape_creator(
        creator_url=creator_url,
        cookies_path=cookies_path,
        limit=args.limit,
        since_days=args.since_days,
        dry_run=args.dry_run,
    )

    print(f"Collected {len(posts)} posts.")
    if posts and not args.dry_run:
        # Save to knowledge/raw/patreon/
        out_dir = ROOT / "knowledge" / "raw" / args.creator.split("/")[-1]
        out_dir.mkdir(parents=True, exist_ok=True)
        for post in posts:
            safe_title = "".join(c for c in post["title"][:50] if c.isalnum() or c in " -_")
            fname = f"{datetime.now().strftime('%Y%m%d')}_{safe_title.replace(' ', '_')}.md"
            (out_dir / fname).write_text(
                f"# {post['title']}\n"
                f"Author: {post['author']}\n"
                f"URL: {post['url']}\n"
                f"Published: {post['published_at']}\n\n"
                f"{post['text']}\n"
            )
        print(f"Saved to {out_dir}/")


if __name__ == "__main__":
    main()
