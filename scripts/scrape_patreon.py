#!/usr/bin/env python3
"""
Patreon scraper — robust, production-grade implementation for MoneyTrail.

Strategy (layered, most-reliable-first):
  Layer 1 — Bootstrap: Extract posts from window.patreon.bootstrap or
             window.__NEXT_DATA__ embedded in the page HTML. Zero extra
             requests, highest fidelity.
  Layer 2 — Direct API: Use Playwright's authenticated page.request client
             to call Patreon's internal /api/posts and /api/comments endpoints
             as clean JSON. Cursor-paginated — gets every comment, not just
             what fits on screen.
  Layer 3 — DOM fallback: Multi-selector chains for every field (4–6 selectors
             per element). Used when both API layers return nothing.

  Comment fetching mirrors this: API cursor-pagination first, DOM button-
  pumping second.

Resilience:
  - Login verification before scraping (expired cookies caught upfront)
  - Per-request retry with back-off (3 attempts, handles transient failures)
  - 429 / rate-limit detection with configurable sleep
  - 403 detection (post behind higher paywall tier — skipped cleanly)
  - Screenshot + page HTML saved to logs/ on any error (--debug)
  - Per-post error isolation: one bad post never kills the run
  - Configurable inter-request jitter to reduce bot-detection risk
  - CSRF token extraction for authenticated API calls
  - HTML→text conversion via BeautifulSoup (already in requirements)

Usage:
    python scripts/scrape_patreon.py --setup
    python scripts/scrape_patreon.py --creator investanswers
    python scripts/scrape_patreon.py --creator investanswers --comments
    python scripts/scrape_patreon.py --creator investanswers --comments --comment-days 2
    python scripts/scrape_patreon.py --creator investanswers --limit 5 --dry-run --debug

Cookie setup (one-time, cookies last ~30 days):
    1. python scripts/scrape_patreon.py --setup
    2. Browser opens — log in to Patreon.
    3. Press Enter. Cookies saved to secrets/patreon_cookies.json.

Patreon ToS: personal use only. Only scrape content you have paid for.
"""

import argparse
import hashlib
import html as _html_stdlib
import json
import logging
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"

log = logging.getLogger("patreon")

# ---------------------------------------------------------------------------
# Patreon internal API constants
# ---------------------------------------------------------------------------
API_BASE = "https://www.patreon.com/api"

# Fields to request from the posts endpoint
_POST_FIELDS = (
    "title,content,url,published_at,comment_count,like_count,"
    "post_type,embed,image,teaser_text,current_user_can_view,"
    "min_cents_pledged_to_view,is_paid"
)
_USER_FIELDS = "full_name,url,thumb_url"
_COMMENT_FIELDS = "body,created,is_by_patron,is_by_creator,vote_sum,deleted_at"

# ---------------------------------------------------------------------------
# Selector chains: try each in order, use first that matches.
# Patreon does heavy A/B testing so having 5-6 options per field is normal.
# ---------------------------------------------------------------------------
_SEL = {
    "post_title": [
        "h1[data-tag='post-title']",
        "h1[class*='sc-']",          # hashed CSS module class
        "div[data-tag='post-title'] h1",
        "div[class*='PostHeader'] h1",
        "h1",
    ],
    "post_body": [
        "[data-tag='post-content']",
        "div[data-tag='post-body']",
        "div[class*='PostContent']",
        "div[class*='post-content']",
        "div[class*='PostBody']",
        "article div[class*='body']",
        "article",
    ],
    "post_time": [
        "time[datetime]",
        "a time[datetime]",
        "span[class*='timestamp'] time",
        "div[class*='created-at'] time",
        "a[class*='timestamp'] time",
    ],
    "post_author": [
        "a[href*='/user?u=']",
        "a[href*='patreon.com/user']",
        "span[class*='CreatorName']",
        "div[class*='UserBadge'] a",
        "a[class*='creator-name']",
        "span[class*='creator']",
    ],
    "comment_container": [
        "[data-tag='comment']",
        "li[class*='Comment_comment']",
        "div[class*='CommentItem']",
        "div[class*='comment-item']",
        "li[class*='comment-']",
        "div[class*='Comment'][class*='container']",
    ],
    "comment_author": [
        "[data-tag='comment-author-name']",
        "span[class*='CommentAuthor']",
        "a[class*='patron-name']",
        "span[class*='author-name']",
        "a[class*='author']",
        "span[class*='author']",
    ],
    "comment_body": [
        "[data-tag='comment-body']",
        "div[class*='CommentBody']",
        "div[class*='comment-body']",
        "div[class*='CommentText']",
        "p[class*='body']",
        "div[class*='body']",
    ],
    "load_more_btn": [
        "[data-tag='load-more-comments-button']",
        "button[class*='LoadMoreButton']",
        "button:has-text('Load more comments')",
        "button:has-text('Load more')",
        "button:has-text('Show more')",
        "a:has-text('Load more comments')",
    ],
    "post_feed_links": [
        "a[data-tag='post-title']",
        "h2 a[href*='/posts/']",
        "a[href*='/posts/'][class*='title']",
        "a[href*='/posts/']",
    ],
    "login_indicator": [
        "[data-tag='user-menu-toggle']",
        "button[aria-label*='account' i]",
        "img[alt*='profile photo' i]",
        "a[href*='/settings']",
        "div[class*='UserMenu']",
        "nav a[href*='/logout']",
        "a[href*='/logout']",
    ],
    "logged_out_indicator": [
        "a[href='/login']",
        "button:has-text('Log in')",
        "a:has-text('Log in')",
        "a[href*='/login']",
    ],
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler()],
    )


def _html_to_text(html_content: str) -> str:
    """Convert HTML to readable plain text via BeautifulSoup."""
    if not html_content:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        # Preserve paragraph breaks
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for p in soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "blockquote"]):
            p.append("\n")
        text = soup.get_text(separator="")
        lines = [l.strip() for l in text.splitlines()]
        lines = [l for l in lines if l]
        return "\n\n".join(lines)
    except ImportError:
        # stdlib fallback: strip tags
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = _html_stdlib.unescape(text)
        return re.sub(r"[ \t]+", " ", text).strip()


def _parse_dt(s: str) -> datetime | None:
    """Parse ISO-8601 datetime string, tolerating several formats."""
    if not s:
        return None
    candidates = [
        lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")),
        lambda x: datetime.strptime(x, "%Y-%m-%dT%H:%M:%S.%f%z"),
        lambda x: datetime.strptime(x, "%Y-%m-%dT%H:%M:%S%z"),
        lambda x: datetime.strptime(x, "%Y-%m-%d"),
    ]
    for fn in candidates:
        try:
            return fn(s)
        except Exception:
            pass
    return None


def _first(node, key: str):
    """Return first matching element from selector chain, or None."""
    for sel in _SEL.get(key, []):
        try:
            el = node.query_selector(sel)
            if el:
                return el
        except Exception:
            continue
    return None


def _all(node, key: str) -> list:
    """Return first non-empty list from selector chain."""
    for sel in _SEL.get(key, []):
        try:
            els = node.query_selector_all(sel)
            if els:
                return els
        except Exception:
            continue
    return []


def _save_diagnostic(page, label: str) -> None:
    """Save screenshot + HTML to logs/ for offline debugging."""
    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^\w]", "_", label)[:40]
    try:
        page.screenshot(
            path=str(LOGS_DIR / f"diag_{ts}_{safe}.png"), full_page=True
        )
        (LOGS_DIR / f"diag_{ts}_{safe}.html").write_text(
            page.content(), encoding="utf-8"
        )
        log.debug(f"Diagnostic saved: logs/diag_{ts}_{safe}.*")
    except Exception as e:
        log.debug(f"Could not save diagnostic: {e}")


def _post_id_from_url(url: str) -> str | None:
    """Extract numeric post ID from a Patreon post URL."""
    m = re.search(r"/posts/(?:[^/]+-)?(\d+)(?:[/?#]|$)", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# PatreonScraper — context manager, one browser session per scrape run
# ---------------------------------------------------------------------------

class PatreonScraper:
    """
    Manages a Playwright browser context for one scraping run.
    Use as a context manager: `with PatreonScraper(cookies_path) as s: ...`
    """

    def __init__(
        self,
        cookies_path: Path,
        debug: bool = False,
        request_delay: float = 1.5,
        jitter: float = 0.8,
    ):
        self.cookies_path = cookies_path
        self.debug = debug
        self.request_delay = request_delay
        self.jitter = jitter
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._csrf: str | None = None
        self._intercepted: list[dict] = []   # API responses captured during navigation

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        with open(self.cookies_path) as f:
            self._context.add_cookies(json.load(f))
        self._page = self._context.new_page()
        self._page.on("response", self._capture_api_response)
        return self

    def __exit__(self, *_):
        for obj in (self._browser, self._pw):
            try:
                if obj:
                    obj.close() if hasattr(obj, "close") else obj.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # API interception (backup data collected during navigation)
    # ------------------------------------------------------------------

    def _capture_api_response(self, response) -> None:
        if "patreon.com/api/" not in response.url:
            return
        if response.status != 200:
            return
        try:
            self._intercepted.append({
                "url": response.url,
                "data": response.json(),
            })
            log.debug(f"Intercepted: {response.url[:80]}")
        except Exception:
            pass

    def _intercepted_for(self, fragment: str) -> dict | None:
        for item in reversed(self._intercepted):
            if fragment in item["url"]:
                return item["data"]
        return None

    # ------------------------------------------------------------------
    # Authenticated API calls via Playwright's request context
    # ------------------------------------------------------------------

    def _api_get(self, path: str, params: dict | None = None) -> dict | None:
        """
        Call Patreon's internal API using the browser's cookie jar.
        Handles 401, 403, 429 and 5xx with retries + back-off.
        Returns parsed JSON or None.
        """
        url = f"{API_BASE}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.patreon.com/",
            "X-Requested-With": "XMLHttpRequest",
        }
        if self._csrf:
            headers["X-CSRF-Signature"] = self._csrf

        for attempt in range(3):
            try:
                resp = self._page.request.get(url, headers=headers, timeout=25_000)
                status = resp.status

                if status == 200:
                    return resp.json()

                if status == 401:
                    log.error(
                        "Session expired (401). "
                        "Run: python scripts/scrape_patreon.py --setup"
                    )
                    return None

                if status == 403:
                    log.debug(f"403 for {path} — paywall or access restricted")
                    return None

                if status == 429:
                    wait = 30 + attempt * 30
                    log.warning(f"Rate limited (429). Sleeping {wait}s …")
                    time.sleep(wait)
                    continue

                if status >= 500:
                    log.warning(f"Server error {status} for {path} (attempt {attempt+1}/3)")
                    time.sleep(5 * (attempt + 1))
                    continue

                log.debug(f"Unexpected status {status} for {path}")
                return None

            except Exception as e:
                log.warning(f"API request failed ({attempt+1}/3): {e}")
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))

        return None

    def _throttle(self) -> None:
        time.sleep(self.request_delay + random.uniform(0, self.jitter))

    def _extract_csrf(self) -> None:
        """Pull CSRF token from cookies or meta tags."""
        try:
            for c in self._context.cookies():
                if "csrf" in c["name"].lower():
                    self._csrf = c["value"]
                    log.debug(f"CSRF from cookie: {c['name']}")
                    return
            meta = self._page.query_selector("meta[name*='csrf' i]")
            if meta:
                self._csrf = meta.get_attribute("content")
                log.debug("CSRF from meta tag")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Session verification
    # ------------------------------------------------------------------

    def verify_login(self) -> bool:
        """
        Navigate to patreon.com and confirm the session is authenticated.
        Returns True if logged in.
        """
        log.info("Verifying Patreon session …")
        try:
            self._page.goto(
                "https://www.patreon.com/",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            time.sleep(2)
            self._extract_csrf()
        except Exception as e:
            log.error(f"Could not reach patreon.com: {e}")
            return False

        for sel in _SEL["logged_out_indicator"]:
            try:
                if self._page.query_selector(sel):
                    log.error(
                        "Not logged in — cookies expired or invalid.\n"
                        "  Fix: python scripts/scrape_patreon.py --setup"
                    )
                    return False
            except Exception:
                pass

        for sel in _SEL["login_indicator"]:
            try:
                if self._page.query_selector(sel):
                    log.info("Session OK — logged in.")
                    return True
            except Exception:
                pass

        # Ambiguous: no explicit indicator found; check redirect
        if "/login" in self._page.url:
            log.error("Redirected to login page — session expired.")
            return False

        log.warning("Login indicator not found — proceeding cautiously.")
        return True  # treat as ok; will fail naturally if not authed

    # ------------------------------------------------------------------
    # Campaign / post discovery helpers
    # ------------------------------------------------------------------

    def _bootstrap_data(self) -> dict | None:
        """Extract JSON embedded by Patreon's React app in the page."""
        try:
            raw = self._page.evaluate("""() => {
                if (window.patreon && window.patreon.bootstrap)
                    return JSON.stringify(window.patreon.bootstrap);
                if (window.__NEXT_DATA__)
                    return JSON.stringify(window.__NEXT_DATA__);
                for (const s of document.querySelectorAll('script[type="application/json"]')) {
                    if (s.textContent.includes('"campaign"'))
                        return s.textContent;
                }
                return null;
            }""")
            if raw:
                return json.loads(raw)
        except Exception as e:
            log.debug(f"Bootstrap extraction: {e}")
        return None

    def _find_campaign_id(self, creator_url: str) -> str | None:
        """
        Discover the numeric Patreon campaign ID from:
          1. Intercepted API responses
          2. Bootstrap JSON
          3. Page source regex
        """
        # From intercepted responses
        for item in self._intercepted:
            data = item["data"]
            try:
                for post in data.get("data", []):
                    if post.get("type") == "post":
                        cid = (
                            post.get("relationships", {})
                            .get("campaign", {})
                            .get("data", {})
                            .get("id")
                        )
                        if cid:
                            return str(cid)
                for inc in data.get("included", []):
                    if inc.get("type") == "campaign":
                        return str(inc["id"])
            except Exception:
                pass

        # From bootstrap
        bs = self._bootstrap_data()
        if bs:
            for path in [
                ["campaign"],
                ["props", "pageProps", "campaign"],
                ["bootstrapData", "campaign"],
            ]:
                try:
                    obj = bs
                    for key in path:
                        obj = obj[key]
                    cid = obj.get("id") or obj.get("data", {}).get("id")
                    if cid:
                        return str(cid)
                except (KeyError, TypeError):
                    pass

        # From raw HTML
        try:
            html = self._page.content()
            for pattern in [
                r'"campaign_id"\s*:\s*"?(\d+)"?',
                r'"campaignId"\s*:\s*"?(\d+)"?',
                r'/api/campaigns/(\d+)',
                r'"id"\s*:\s*"(\d+)".*?"type"\s*:\s*"campaign"',
            ]:
                m = re.search(pattern, html)
                if m:
                    return m.group(1)
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Posts — Layer 1: Bootstrap
    # ------------------------------------------------------------------

    def _posts_from_bootstrap(
        self, since_dt: datetime | None, limit: int
    ) -> list[dict]:
        bs = self._bootstrap_data()
        if not bs:
            return []
        try:
            # Find posts array in bootstrap
            posts_raw = None
            for candidate in [
                bs.get("posts"),
                bs.get("props", {}).get("pageProps", {}).get("posts"),
                bs.get("bootstrapData", {}).get("posts"),
            ]:
                if isinstance(candidate, list) and candidate:
                    posts_raw = candidate
                    break
                if isinstance(candidate, dict) and candidate.get("data"):
                    posts_raw = candidate["data"]
                    break

            if not posts_raw:
                return []

            log.debug(f"Bootstrap: found {len(posts_raw)} post candidates")
            return self._parse_posts_list(posts_raw, {}, since_dt, limit)
        except Exception as e:
            log.debug(f"Bootstrap parse error: {e}")
        return []

    # ------------------------------------------------------------------
    # Posts — Layer 2: Direct API
    # ------------------------------------------------------------------

    def _posts_from_api(
        self, creator_url: str, since_dt: datetime | None, limit: int
    ) -> list[dict]:
        # Approach A: filter by campaign URL
        base_params = {
            "fields[post]": _POST_FIELDS,
            "fields[user]": _USER_FIELDS,
            "include": "user",
            "sort": "-published_at",
            "page[count]": str(min(limit + 2, 20)),
            "filter[is_draft]": "false",
        }
        params_a = dict(base_params)
        params_a["filter[campaign.url]"] = creator_url.rstrip("/")
        result = self._api_get("/posts", params_a)
        if result and result.get("data"):
            log.debug(f"API (campaign.url filter): {len(result['data'])} posts")
            return self._parse_posts_response(result, since_dt, limit)

        # Approach B: filter by campaign ID
        campaign_id = self._find_campaign_id(creator_url)
        if campaign_id:
            params_b = dict(base_params)
            params_b["filter[campaign_id]"] = campaign_id
            result2 = self._api_get("/posts", params_b)
            if result2 and result2.get("data"):
                log.debug(f"API (campaign_id filter): {len(result2['data'])} posts")
                return self._parse_posts_response(result2, since_dt, limit)

        # Approach C: use intercepted response from navigation
        intercepted = self._intercepted_for("/posts")
        if intercepted and intercepted.get("data"):
            log.debug(f"Using intercepted posts data: {len(intercepted['data'])} items")
            return self._parse_posts_response(intercepted, since_dt, limit)

        return []

    def _parse_posts_response(
        self, data: dict, since_dt: datetime | None, limit: int
    ) -> list[dict]:
        users = {
            inc["id"]: inc.get("attributes", {}).get("full_name", "Unknown")
            for inc in data.get("included", [])
            if inc.get("type") == "user"
        }
        return self._parse_posts_list(
            data.get("data", []), users, since_dt, limit
        )

    def _parse_posts_list(
        self,
        items: list,
        users: dict,
        since_dt: datetime | None,
        limit: int,
    ) -> list[dict]:
        posts = []
        for item in items:
            if len(posts) >= limit:
                break
            if not isinstance(item, dict):
                continue
            if item.get("type") not in ("post", None):
                # Some bootstrap formats have flat dicts without type
                if item.get("type") and item["type"] != "post":
                    continue

            attrs = item.get("attributes") or item  # flat or nested
            published_at = _parse_dt(attrs.get("published_at", ""))
            if since_dt and published_at and published_at < since_dt:
                continue

            # Author
            rels = item.get("relationships", {})
            author_id = rels.get("user", {}).get("data", {}).get("id", "")
            author = users.get(author_id) or attrs.get("creator_name") or "Unknown"

            # Content
            content_html = attrs.get("content") or attrs.get("teaser_text") or ""
            text = _html_to_text(content_html)

            # Embedded content (video/audio posts)
            if not text.strip() and attrs.get("embed"):
                embed = attrs["embed"]
                text = "\n".join(filter(None, [
                    f"[Embedded: {embed.get('subject', '')}]",
                    embed.get("description", ""),
                    embed.get("url", ""),
                ]))

            if not text.strip():
                continue

            post_url = attrs.get("url", "")
            post_id = str(item.get("id", "")) or _post_id_from_url(post_url)
            if not post_url and post_id:
                post_url = f"https://www.patreon.com/posts/{post_id}"

            posts.append({
                "id": post_id,
                "title": (attrs.get("title") or "Untitled").strip(),
                "author": author,
                "url": post_url,
                "published_at": published_at.isoformat() if published_at else None,
                "text": text,
                "content_html": content_html,
                "comment_count": int(attrs.get("comment_count") or 0),
                "post_type": attrs.get("post_type", "text_only"),
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                "comments": [],
            })

        return posts

    # ------------------------------------------------------------------
    # Posts — Layer 3: DOM fallback
    # ------------------------------------------------------------------

    def _posts_from_dom(
        self, since_dt: datetime | None, limit: int
    ) -> list[dict]:
        """
        Extract post URLs from the feed page DOM, then scrape each individually.
        The feed page should already be loaded.
        """
        log.info("DOM fallback: collecting post URLs from feed …")
        seen: set[str] = set()
        post_urls: list[str] = []

        for link in _all(self._page, "post_feed_links"):
            href = link.get_attribute("href") or ""
            if not href or href in seen:
                continue
            seen.add(href)
            full = href if href.startswith("http") else "https://www.patreon.com" + href
            if "/posts/" in full:
                post_urls.append(full)
            if len(post_urls) >= limit:
                break

        log.info(f"DOM: found {len(post_urls)} post URLs")
        posts = []
        for url in post_urls:
            try:
                post = self._scrape_post_dom(url, since_dt)
                if post:
                    posts.append(post)
                self._throttle()
            except Exception as e:
                log.error(f"DOM scrape failed {url}: {e}")
                if self.debug:
                    _save_diagnostic(self._page, f"post_{url.split('/')[-1][:30]}")
        return posts

    def _scrape_post_dom(
        self, url: str, since_dt: datetime | None
    ) -> dict | None:
        log.debug(f"DOM scraping: {url}")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            # Wait for title
            try:
                self._page.wait_for_selector(
                    ", ".join(_SEL["post_title"]), timeout=8_000
                )
            except Exception:
                pass
        except Exception as e:
            log.warning(f"Failed to load {url}: {e}")
            return None

        title_el = _first(self._page, "post_title")
        title = title_el.inner_text().strip() if title_el else "Untitled"

        time_el = _first(self._page, "post_time")
        published_at = None
        if time_el:
            published_at = _parse_dt(time_el.get_attribute("datetime") or "")
        if since_dt and published_at and published_at < since_dt:
            return None

        author_el = _first(self._page, "post_author")
        author = author_el.inner_text().strip() if author_el else "Unknown"

        body_el = _first(self._page, "post_body")
        if body_el:
            try:
                text = _html_to_text(body_el.inner_html())
            except Exception:
                text = body_el.inner_text()
        else:
            paras = self._page.query_selector_all("p")
            text = "\n\n".join(
                p.inner_text() for p in paras
                if len(p.inner_text().strip()) > 20
            )

        if not text.strip():
            log.debug(f"No content in DOM for {url}")
            return None

        post_id = _post_id_from_url(url)
        return {
            "id": post_id,
            "title": title,
            "author": author,
            "url": url,
            "published_at": published_at.isoformat() if published_at else None,
            "text": text,
            "content_html": "",
            "comment_count": 0,
            "post_type": "text_only",
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            "comments": [],
        }

    # ------------------------------------------------------------------
    # Comments — API (cursor-paginated, gets everything)
    # ------------------------------------------------------------------

    def _comments_from_api(
        self, post_id: str, max_comments: int = 500
    ) -> list[dict]:
        all_comments: list[dict] = []
        cursor: str | None = None
        max_pages = max(1, (max_comments // 50) + 2)

        for page_num in range(max_pages):
            params = {
                "fields[comment]": _COMMENT_FIELDS,
                "fields[user]": _USER_FIELDS,
                "include": "commenter.campaign,parent,commenter",
                "page[count]": "50",
            }
            if cursor:
                params["page[cursor]"] = cursor

            data = self._api_get(f"/posts/{post_id}/comments", params)
            if not data:
                break

            batch = self._parse_comments_response(data, post_id)
            all_comments.extend(batch)
            log.debug(
                f"Comments page {page_num+1}: {len(batch)} new "
                f"(total {len(all_comments)})"
            )

            # Advance cursor
            try:
                next_cursor = (
                    data.get("meta", {})
                    .get("pagination", {})
                    .get("cursors", {})
                    .get("next")
                )
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
            except Exception:
                break

            if len(all_comments) >= max_comments:
                break
            self._throttle()

        return all_comments

    def _parse_comments_response(self, data: dict, post_id: str) -> list[dict]:
        users = {
            inc["id"]: inc.get("attributes", {}).get("full_name", "Unknown")
            for inc in data.get("included", [])
            if inc.get("type") == "user"
        }
        comments = []
        for item in data.get("data", []):
            if item.get("type") != "comment":
                continue
            attrs = item.get("attributes", {})
            if attrs.get("deleted_at"):
                continue
            body = (attrs.get("body") or "").strip()
            if not body:
                continue
            author_id = (
                item.get("relationships", {})
                .get("commenter", {})
                .get("data", {})
                .get("id", "")
            )
            author = users.get(author_id, "Unknown")
            published_at = _parse_dt(attrs.get("created", ""))
            comments.append({
                "author": author,
                "text": body,
                "published_at": published_at.isoformat() if published_at else None,
                "content_hash": hashlib.sha256(
                    f"{post_id}:{author}:{body}".encode()
                ).hexdigest(),
            })
        return comments

    # ------------------------------------------------------------------
    # Comments — DOM fallback (button pumping)
    # ------------------------------------------------------------------

    def _comments_from_dom(self, post_url: str) -> list[dict]:
        log.debug(f"DOM comment fallback: {post_url}")
        try:
            if self._page.url != post_url:
                self._page.goto(
                    post_url, wait_until="domcontentloaded", timeout=25_000
                )
                time.sleep(1.5)
        except Exception as e:
            log.warning(f"Cannot load post for DOM comments: {e}")
            return []

        # Scroll to load the comment section
        for i in range(4):
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.8 + i * 0.2)

        # Pump "Load more" button until gone
        for _ in range(30):
            btn = None
            for sel in _SEL["load_more_btn"]:
                try:
                    b = self._page.query_selector(sel)
                    if b and b.is_visible():
                        btn = b
                        break
                except Exception:
                    continue
            if not btn:
                break
            try:
                btn.scroll_into_view_if_needed()
                time.sleep(0.3)
                btn.click()
                time.sleep(1.5)
            except Exception:
                break

        comment_nodes = _all(self._page, "comment_container")
        log.debug(f"DOM: {len(comment_nodes)} comment nodes")

        comments = []
        for node in comment_nodes:
            author_el = _first(node, "comment_author")
            author = author_el.inner_text().strip() if author_el else "Unknown"

            body_el = _first(node, "comment_body")
            if not body_el:
                continue
            text = body_el.inner_text().strip()
            if not text:
                continue

            time_el = node.query_selector("time[datetime]")
            published_at = None
            if time_el:
                dt = _parse_dt(time_el.get_attribute("datetime") or "")
                published_at = dt.isoformat() if dt else None

            comments.append({
                "author": author,
                "text": text,
                "published_at": published_at,
                "content_hash": hashlib.sha256(
                    f"{post_url}:{author}:{text}".encode()
                ).hexdigest(),
            })

        return comments

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def scrape_creator(
        self,
        creator_url: str,
        limit: int = 10,
        since_days: int = 2,
        include_comments: bool = False,
        comment_days: int = 2,
        dry_run: bool = False,
    ) -> list[dict]:
        """
        Scrape posts (and optionally comments) from a Patreon creator.
        Uses layered strategy: bootstrap → API → DOM for both posts and comments.
        """
        since_dt = datetime.now(timezone.utc) - timedelta(days=since_days)
        comment_cutoff = datetime.now(timezone.utc) - timedelta(days=comment_days)

        if not self.verify_login():
            raise RuntimeError(
                "Patreon session not authenticated. "
                "Run: python scripts/scrape_patreon.py --setup"
            )

        # Navigate to creator posts page
        posts_url = creator_url.rstrip("/") + "/posts"
        log.info(f"Loading {posts_url} …")
        self._intercepted.clear()
        try:
            self._page.goto(posts_url, wait_until="networkidle", timeout=40_000)
        except Exception as e:
            log.warning(f"Page load issue: {e} — continuing with partial content")

        # Scroll to trigger lazy loading and fire API calls
        for _ in range(3):
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.0)

        # Layer 1: Bootstrap
        posts = self._posts_from_bootstrap(since_dt, limit)
        if posts:
            log.info(f"Bootstrap: {len(posts)} posts")
        else:
            # Layer 2: Direct API
            log.debug("Bootstrap empty — trying API …")
            posts = self._posts_from_api(creator_url, since_dt, limit)
            if posts:
                log.info(f"API: {len(posts)} posts")
            else:
                # Layer 3: DOM
                log.warning("API empty — DOM fallback …")
                posts = self._posts_from_dom(since_dt, limit)
                log.info(f"DOM: {len(posts)} posts")

        if not posts:
            log.warning("No posts found via any method")
            return []

        # For posts where content is empty (paywall), try fetching individually
        for post in posts:
            if not post["text"].strip() and post.get("id"):
                log.debug(f"Empty content, trying individual fetch: {post['url']}")
                self._throttle()
                result = self._api_get(
                    f"/posts/{post['id']}",
                    {
                        "fields[post]": _POST_FIELDS,
                        "fields[user]": _USER_FIELDS,
                        "include": "user",
                    },
                )
                if result and result.get("data"):
                    attrs = result["data"].get("attributes", {})
                    html = attrs.get("content") or attrs.get("teaser_text") or ""
                    text = _html_to_text(html)
                    if text:
                        post["text"] = text
                        post["content_hash"] = hashlib.sha256(text.encode()).hexdigest()

        if dry_run:
            for p in posts:
                nc = p.get("comment_count", 0)
                print(
                    f"  [DRY RUN] {p['title'][:60]} "
                    f"({len(p['text'])} chars, {nc} comments)"
                )
            return []

        # Fetch comments
        if include_comments:
            for post in posts:
                pub = _parse_dt(post.get("published_at") or "")
                in_window = pub is None or pub >= comment_cutoff
                if not in_window:
                    log.debug(f"Comments skipped (too old): {post['title'][:50]}")
                    continue

                log.info(f"  Comments: {post['title'][:50]} …")
                self._throttle()
                try:
                    if post.get("id"):
                        comments = self._comments_from_api(post["id"])
                    else:
                        comments = []
                    if not comments:
                        log.debug("API returned no comments — DOM fallback")
                        comments = self._comments_from_dom(post["url"])
                    post["comments"] = comments
                    log.info(f"  → {len(comments)} comments")
                except Exception as e:
                    log.error(f"Comment fetch failed {post['url']}: {e}")
                    if self.debug:
                        _save_diagnostic(
                            self._page,
                            f"comments_{post.get('id', 'unknown')}",
                        )
                    post["comments"] = []

        return posts


# ---------------------------------------------------------------------------
# Public module API (called by ingest_sources.py)
# ---------------------------------------------------------------------------

def setup_cookies() -> None:
    """Open a visible browser so the user can log in, then save cookies."""
    from playwright.sync_api import sync_playwright

    cookies_path = ROOT / "secrets" / "patreon_cookies.json"
    cookies_path.parent.mkdir(exist_ok=True)
    print("Opening browser. Log in to Patreon, then press Enter here.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.patreon.com/login")
        input("Press Enter after logging in …")
        with open(cookies_path, "w") as f:
            json.dump(context.cookies(), f, indent=2)
        print(f"✓ Cookies saved to {cookies_path}")
        browser.close()


def scrape_creator(
    creator_url: str,
    cookies_path: Path,
    limit: int = 10,
    since_days: int = 2,
    dry_run: bool = False,
    include_comments: bool = False,
    comment_days: int = 2,
    debug: bool = False,
) -> list[dict]:
    """
    Primary entry point used by ingest_sources.py.
    Returns list of post dicts: {id, title, author, url, published_at,
    text, content_hash, comments, comment_count, post_type}.
    """
    _setup_logging(debug)
    if not cookies_path.exists():
        raise FileNotFoundError(
            f"Cookie file not found: {cookies_path}\n"
            "Run: python scripts/scrape_patreon.py --setup"
        )
    with PatreonScraper(cookies_path, debug=debug) as scraper:
        return scraper.scrape_creator(
            creator_url=creator_url,
            limit=limit,
            since_days=since_days,
            include_comments=include_comments,
            comment_days=comment_days,
            dry_run=dry_run,
        )


def _format_post_md(post: dict) -> str:
    """Render a post + comments as a Markdown file for the knowledge base."""
    lines = [
        f"# {post['title']}",
        f"Author: {post['author']}",
        f"URL: {post['url']}",
        f"Published: {post['published_at']}",
        f"Type: {post.get('post_type', 'text_only')}",
        "",
        post["text"],
    ]
    comments = post.get("comments") or []
    if comments:
        lines += ["", "---", f"## Comments ({len(comments)})", ""]
        for c in comments:
            ts = f" — {c['published_at']}" if c.get("published_at") else ""
            lines.append(f"**{c['author']}**{ts}")
            lines.append(c["text"])
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "secrets" / ".env")

    parser = argparse.ArgumentParser(
        description="Patreon scraper for MoneyTrail",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--setup", action="store_true",
                        help="One-time browser login to save cookies")
    parser.add_argument("--creator",
                        help="Creator slug or full URL (e.g. investanswers)")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max posts to collect (default 10)")
    parser.add_argument("--since-days", type=int, default=2,
                        help="Only posts from the last N days (default 2)")
    parser.add_argument("--comments", action="store_true",
                        help="Scrape comments on each post")
    parser.add_argument("--comment-days", type=int, default=2,
                        help="Scrape comments on posts from the last N days (default 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be collected without saving")
    parser.add_argument("--debug", action="store_true",
                        help="Verbose logging + save screenshots on errors")
    args = parser.parse_args()

    _setup_logging(args.debug)

    if args.setup:
        setup_cookies()
        return

    if not args.creator:
        parser.error("--creator is required (unless --setup)")

    cookies_env = os.getenv("PATREON_COOKIES_FILE", "secrets/patreon_cookies.json")
    cookies_path = ROOT / cookies_env

    creator_url = (
        args.creator if args.creator.startswith("http")
        else f"https://www.patreon.com/{args.creator}"
    )

    posts = scrape_creator(
        creator_url=creator_url,
        cookies_path=cookies_path,
        limit=args.limit,
        since_days=args.since_days,
        dry_run=args.dry_run,
        include_comments=args.comments,
        comment_days=args.comment_days,
        debug=args.debug,
    )

    if args.dry_run or not posts:
        return

    creator_slug = args.creator.split("/")[-1].split("?")[0]
    out_dir = ROOT / "knowledge" / "raw" / creator_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    for post in posts:
        safe = "".join(
            c for c in post["title"][:50] if c.isalnum() or c in " -_"
        ).strip().replace(" ", "_")
        fname = f"{datetime.now().strftime('%Y%m%d')}_{safe}.md"
        (out_dir / fname).write_text(_format_post_md(post), encoding="utf-8")

    print(f"\n✓ {len(posts)} posts saved to {out_dir}/")
    for post in posts:
        nc = len(post.get("comments") or [])
        suffix = f"  ({nc} comments)" if nc else ""
        print(f"  {post['title'][:60]}{suffix}")


if __name__ == "__main__":
    main()
