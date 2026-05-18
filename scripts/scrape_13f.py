#!/usr/bin/env python3
"""
SEC 13F filing scraper for MoneyTrail.

Monitors institutional 13F filings for target fund managers. Detects new
positions, increases, decreases, and exits vs the prior quarter.

Data source strategy (layered):
  Layer 1 — SEC EDGAR (primary): free, no credentials, official source.
             Uses the EDGAR full-text search API + XML filing parser.
             Requires a declared User-Agent header (EDGAR_USER_AGENT env var).
  Layer 2 — WhaleWisdom API (optional): pre-parsed JSON, holdings_comparison
             endpoint does the diff automatically. Requires API keys.

13F signal characteristics:
  - High data accuracy (regulatory disclosure)
  - 45–135 day lag (filed up to 45 days after quarter end)
  - Quarterly cadence — fires 4 times per year per filer
  - Confirmation signal, NOT discovery signal — use to validate existing theses

Usage:
    python scripts/scrape_13f.py --setup                         # find CIK for a filer
    python scripts/scrape_13f.py --filer situational-awareness-lp --dry-run
    python scripts/scrape_13f.py --filer situational-awareness-lp
    python scripts/scrape_13f.py --filer 0001802256              # by CIK

Required env vars:
    EDGAR_USER_AGENT=YourName/MoneyTrail your@email.com

Optional env vars (WhaleWisdom):
    WHALEWISDOM_ACCESS_KEY=...
    WHALEWISDOM_SECRET_KEY=...
"""

import argparse
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

ROOT = Path(__file__).parent.parent
log = logging.getLogger("13f")

# EDGAR API endpoints
EDGAR_BASE        = "https://data.sec.gov"
EDGAR_SEARCH      = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
EDGAR_RATE_LIMIT  = 10   # SEC guideline: max 10 req/sec; we stay well below

# WhaleWisdom API
WW_BASE = "https://whalewisdom.com/shell/command"


# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logging(debug: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


# ── Environment ───────────────────────────────────────────────────────────────

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "secrets" / ".env")
    except ImportError:
        pass


def _edgar_headers() -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "")
    if not ua:
        log.error(
            "EDGAR_USER_AGENT not set.\n"
            "  SEC requires a declared User-Agent to avoid being blocked.\n"
            "  Add to secrets/.env:\n"
            "  EDGAR_USER_AGENT=YourName/MoneyTrail your@email.com"
        )
        sys.exit(1)
    return {
        "User-Agent":    ua,
        "Accept":        "application/json",
        "Cache-Control": "no-cache",
    }


# ── HTTP with rate-limit handling ─────────────────────────────────────────────

def _get(url: str, params: dict | None = None, headers: dict | None = None,
         retries: int = 3) -> dict | list | str | None:
    """GET with exponential backoff on 429/5xx. Returns parsed JSON or raw text."""
    import requests

    h = headers or _edgar_headers()
    full_url = f"{url}?{urlencode(params)}" if params else url

    for attempt in range(retries):
        try:
            r = requests.get(full_url, headers=h, timeout=20)

            if r.status_code == 200:
                ct = r.headers.get("Content-Type", "")
                if "json" in ct:
                    return r.json()
                return r.text

            if r.status_code == 429:
                wait = (2 ** attempt) * 10 + 5  # 15s, 25s, 45s
                log.warning(f"Rate limited (429) — sleeping {wait}s")
                time.sleep(wait)
                continue

            if r.status_code in (403, 404):
                log.debug(f"HTTP {r.status_code} for {url}")
                return None

            if r.status_code >= 500:
                wait = (2 ** attempt) * 5
                log.warning(f"Server error {r.status_code} — retry in {wait}s")
                time.sleep(wait)
                continue

            log.warning(f"HTTP {r.status_code} for {url}")
            return None

        except Exception as e:
            log.warning(f"Request error (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    return None


# ── Quarter utilities ─────────────────────────────────────────────────────────

def _normalize_quarter(q: str) -> str | None:
    """Normalize various quarter formats to YYYY-QN."""
    if re.match(r"^\d{4}-Q[1-4]$", q):
        return q
    # YYYY-MM-DD period end dates
    m = re.match(r"^(\d{4})-(\d{2})-\d{2}$", q)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        qn = (month - 1) // 3 + 1
        return f"{year}-Q{qn}"
    # Q1YYYY or Q12026 style
    m = re.match(r"^Q([1-4])(\d{4})$", q)
    if m:
        return f"{m.group(2)}-Q{m.group(1)}"
    return None


def _quarters_are_consecutive(q1: str, q2: str) -> bool:
    """Return True if q1 is immediately followed by q2."""
    try:
        y1, n1 = int(q1[:4]), int(q1[-1])
        y2, n2 = int(q2[:4]), int(q2[-1])
        if n1 == 4:
            return y2 == y1 + 1 and n2 == 1
        return y2 == y1 and n2 == n1 + 1
    except (ValueError, IndexError):
        return False


def _current_expected_quarter() -> str:
    """Return the most recent quarter that would have a filed 13F (45-day lag)."""
    now = datetime.now(timezone.utc)
    year = now.year
    # Filing deadlines: Q4 → mid-Feb, Q1 → mid-May, Q2 → mid-Aug, Q3 → mid-Nov
    deadlines = [
        (2, 15, f"{year-1}-Q4"),
        (5, 15, f"{year}-Q1"),
        (8, 15, f"{year}-Q2"),
        (11, 15, f"{year}-Q3"),
    ]
    latest = f"{year-1}-Q4"
    for month, day, quarter in deadlines:
        if (now.month, now.day) >= (month, day):
            latest = quarter
    return latest


# ── EDGAR: CIK lookup ─────────────────────────────────────────────────────────

def find_cik(filer_name: str) -> str | None:
    """Search EDGAR for a filer and return their CIK number."""
    # Try the EDGAR company search API
    data = _get(
        "https://efts.sec.gov/LATEST/search-index",
        params={"q": filer_name, "forms": "13F-HR"},
    )
    if isinstance(data, dict):
        hits = data.get("hits", {}).get("hits", [])
        if hits:
            src = hits[0].get("_source", {})
            cik = src.get("ciks", [None])[0] or src.get("entity_id")
            if cik:
                return str(cik).lstrip("0").zfill(10)

    # Try EDGAR full-text company search
    data2 = _get(
        "https://www.sec.gov/cgi-bin/browse-edgar",
        params={
            "company":     filer_name,
            "CIK":         "",
            "type":        "13F-HR",
            "dateb":       "",
            "owner":       "include",
            "count":       "5",
            "search_text": "",
            "action":      "getcompany",
            "output":      "atom",
        },
    )
    if isinstance(data2, str) and data2:
        m = re.search(r"CIK=(\d+)", data2)
        if m:
            return m.group(1).zfill(10)

    return None


# ── EDGAR: filing discovery ───────────────────────────────────────────────────

def get_latest_filings(cik: str, count: int = 2) -> list[dict]:
    """
    Fetch the N most recent 13F-HR filings for a CIK.
    Returns list of {accession_number, filing_date, period_of_report, quarter}.
    """
    cik_padded = cik.zfill(10)
    data = _get(f"{EDGAR_SUBMISSIONS}/CIK{cik_padded}.json")
    if not isinstance(data, dict):
        log.warning(f"Could not fetch submission data for CIK {cik}")
        return []

    filings = data.get("filings", {}).get("recent", {})
    forms        = filings.get("form", [])
    accessions   = filings.get("accessionNumber", [])
    dates        = filings.get("filingDate", [])
    periods      = filings.get("reportDate", [])

    results = []
    for form, acc, date, period in zip(forms, accessions, dates, periods):
        if form in ("13F-HR", "13F-HR/A"):
            q = _normalize_quarter(period) or period
            results.append({
                "accession_number": acc,
                "filing_date":      date,
                "period_of_report": period,
                "quarter":          q,
                "is_amendment":     form.endswith("/A"),
            })
        if len(results) >= count:
            break

    return results


# ── EDGAR: XML holdings parser ────────────────────────────────────────────────

def parse_holdings_xml(accession_number: str, cik: str) -> list[dict]:
    """
    Download and parse the InfoTable XML from an EDGAR 13F filing.
    Returns list of position dicts.

    EDGAR filing structure: directory listing at
    https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/
    We parse the HTML directory listing to find the InfoTable XML file.
    """
    cik_int   = str(int(cik))           # strip leading zeros for URL path
    acc_clean = accession_number.replace("-", "")
    dir_url   = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/"

    dir_html = _get(dir_url, headers={**_edgar_headers(), "Accept": "text/html"})
    if not isinstance(dir_html, str):
        log.warning(f"Could not fetch filing directory: {dir_url}")
        return []

    # Find InfoTable XML — named variously: infotable.xml, *13F*.xml, *holdings*.xml
    # Fall back to any .xml that isn't the primary_doc wrapper
    xml_filename = None
    for pattern in [
        r'href="(/Archives/edgar/data/[^"]+infotable[^"]+\.xml)"',
        r'href="(/Archives/edgar/data/[^"]+13[fF][^"]+\.xml)"',
        r'href="(/Archives/edgar/data/[^"]+hold[^"]+\.xml)"',
        r'href="(/Archives/edgar/data/[^"]+\.xml)"',
    ]:
        matches = re.findall(pattern, dir_html, re.I)
        # Skip the primary_doc.xml wrapper — it's metadata, not holdings
        for m in matches:
            if "primary_doc" not in m.lower():
                xml_filename = m
                break
        if xml_filename:
            break

    if not xml_filename:
        log.warning(f"No InfoTable XML found in {dir_url}")
        return []

    log.debug(f"InfoTable XML: {xml_filename}")
    time.sleep(0.2)  # stay well under 10 req/sec EDGAR limit
    xml_url = f"https://www.sec.gov{xml_filename}"
    xml_text = _get(xml_url, headers={**_edgar_headers(), "Accept": "text/xml,application/xml"})
    if not isinstance(xml_text, str):
        return []

    return _parse_infotable_xml(xml_text)


def _parse_infotable_xml(xml_text: str) -> list[dict]:
    """Parse SEC 13F InfoTable XML into position dicts."""
    positions = []
    try:
        # Strip all namespace declarations and prefixes for simple tag access
        xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', "", xml_text)
        xml_clean = re.sub(r"<(\w+):([^>\s/]+)", r"<\2", xml_clean)
        xml_clean = re.sub(r"</(\w+):([^>]+)>", r"</\2>", xml_clean)

        root = ET.fromstring(xml_clean)

        for info in root.iter("infoTable"):
            def _t(tag: str) -> str:
                el = info.find(tag)
                return (el.text or "").strip() if el is not None else ""

            # EDGAR InfoTable has no ticker field — only CUSIP and company name.
            # We store the company name as company_name and leave ticker blank.
            # A future step can resolve CUSIP → ticker via a lookup API.
            cusip  = _t("cusip")
            name   = _t("nameOfIssuer")
            # shares are nested: <shrsOrPrnAmt><sshPrnamt>N</sshPrnamt>...
            shr_el = info.find("shrsOrPrnAmt")
            shares_str = ""
            if shr_el is not None:
                sph = shr_el.find("sshPrnamt")
                if sph is not None:
                    shares_str = (sph.text or "").strip()
            value_str  = _t("value")

            try:
                shares = float(shares_str) if shares_str else None
            except ValueError:
                shares = None
            try:
                # EDGAR value field is in dollars (not thousands — despite old docs saying thousands,
                # modern 13F-HR filings use whole dollars; verify: APLD position = ~$278M matches real data)
                market_value = float(value_str) if value_str else None
            except ValueError:
                market_value = None

            positions.append({
                "ticker":          None,       # EDGAR InfoTable has no ticker; use company_name
                "cusip":           cusip or None,
                "company_name":    name,
                "shares":          shares,
                "market_value_usd": market_value,
                "portfolio_pct":   None,   # computed after summing total portfolio
                "sector":          None,
                "industry":        None,
                "avg_price":       None,
                "quarter_first_owned": None,
            })

    except ET.ParseError as e:
        log.error(f"XML parse error: {e}")

    # Compute portfolio percentages
    total_value = sum(p["market_value_usd"] for p in positions if p["market_value_usd"])
    if total_value > 0:
        for p in positions:
            if p["market_value_usd"] is not None:
                p["portfolio_pct"] = round(p["market_value_usd"] / total_value * 100, 4)

    return positions


# ── WhaleWisdom API client (optional) ────────────────────────────────────────

def _ww_sign(access_key: str, secret_key: str, args_str: str) -> tuple[str, str]:
    """Generate WhaleWisdom HMAC-SHA1 signature."""
    timestamp = str(int(time.time()))
    message   = f"{args_str}\n{timestamp}"
    sig = hmac.new(
        secret_key.encode(), message.encode(), "sha1"
    ).hexdigest()
    return sig, timestamp


def fetch_ww_holdings(
    filer_slug: str,
    quarter: str | None = None,
    compare_quarter: str | None = None,
) -> list[dict] | None:
    """
    Fetch holdings (or holdings comparison) from WhaleWisdom.
    Returns None if credentials not set or request fails.
    """
    access_key = os.getenv("WHALEWISDOM_ACCESS_KEY", "")
    secret_key = os.getenv("WHALEWISDOM_SECRET_KEY", "")
    if not access_key or not secret_key:
        return None

    import requests

    command = "holdings_comparison" if compare_quarter else "holdings"
    args = {
        "command":     command,
        "filer_slug":  filer_slug,
        "output":      "json",
    }
    if quarter:
        args["quarter"] = quarter
    if compare_quarter:
        args["compare_quarter"] = compare_quarter

    args_str = urlencode(sorted(args.items()))
    sig, ts  = _ww_sign(access_key, secret_key, args_str)

    params = dict(args)
    params["access_key"] = access_key
    params["signature"]  = sig
    params["timestamp"]  = ts

    try:
        r = requests.get(WW_BASE, params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
        log.debug(f"WhaleWisdom {r.status_code}: {r.text[:100]}")
    except Exception as e:
        log.debug(f"WhaleWisdom request failed: {e}")

    return None


# ── Diff computation ──────────────────────────────────────────────────────────

def compute_diff(
    current: list[dict],
    prior: list[dict],
) -> list[dict]:
    """
    Compare current vs prior quarter positions.
    Returns current positions with change_type and shares_change filled in.
    """
    prior_by_ticker = {
        p["ticker"]: p for p in prior if p.get("ticker")
    }
    prior_by_cusip = {
        p["cusip"]: p for p in prior if p.get("cusip") and not p.get("ticker")
    }

    result = []
    for pos in current:
        ticker = pos.get("ticker")
        cusip  = pos.get("cusip")

        prior_pos = prior_by_ticker.get(ticker) or prior_by_cusip.get(cusip)

        if prior_pos is None:
            pos["change_type"]   = "new"
            pos["shares_change"] = None
        else:
            curr_shares  = pos.get("shares") or 0
            prior_shares = prior_pos.get("shares") or 0
            delta        = curr_shares - prior_shares

            if abs(delta) < 0.5:
                pos["change_type"]   = "unchanged"
                pos["shares_change"] = 0
            elif delta > 0:
                pos["change_type"]   = "increased"
                pos["shares_change"] = delta
            else:
                pos["change_type"]   = "decreased"
                pos["shares_change"] = delta

        result.append(pos)

    # Find exited positions (in prior but not in current)
    current_tickers = {p.get("ticker") for p in current if p.get("ticker")}
    current_cusips  = {p.get("cusip")  for p in current if p.get("cusip")}
    for prior_pos in prior:
        t = prior_pos.get("ticker")
        c = prior_pos.get("cusip")
        if t and t not in current_tickers:
            exited = dict(prior_pos)
            exited["change_type"]   = "exited"
            exited["shares_change"] = -(prior_pos.get("shares") or 0)
            exited["shares"]        = 0
            exited["market_value_usd"] = 0
            exited["portfolio_pct"]    = 0
            result.append(exited)
        elif c and c not in current_cusips and not t:
            exited = dict(prior_pos)
            exited["change_type"]   = "exited"
            exited["shares_change"] = -(prior_pos.get("shares") or 0)
            exited["shares"]        = 0
            result.append(exited)

    return result


# ── Markdown formatter ────────────────────────────────────────────────────────

def _fmt_shares(n: float | None) -> str:
    if n is None:
        return "—"
    return f"{abs(n):,.0f}"


def _fmt_money(n: float | None) -> str:
    if n is None:
        return "—"
    if abs(n) >= 1e9:
        return f"${n/1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"${n/1e6:.1f}M"
    return f"${n:,.0f}"


def format_digest(
    filer_name: str,
    quarter: str,
    positions: list[dict],
    max_positions: int = 50,
    include_unchanged: bool = False,
) -> str:
    """Format a quarterly 13F diff as Markdown for the knowledge base."""
    new_pos        = [p for p in positions if p.get("change_type") == "new"]
    increased      = [p for p in positions if p.get("change_type") == "increased"]
    decreased      = [p for p in positions if p.get("change_type") == "decreased"]
    exited         = [p for p in positions if p.get("change_type") == "exited"]
    unchanged      = [p for p in positions if p.get("change_type") == "unchanged"]
    gap_unknown    = [p for p in positions if p.get("change_type") == "gap_unknown"]

    # Sort by portfolio % descending
    for group in (new_pos, increased, decreased, exited, unchanged):
        group.sort(key=lambda p: -(p.get("portfolio_pct") or 0))

    total_value = sum(
        p.get("market_value_usd") or 0 for p in positions
        if p.get("change_type") != "exited"
    )
    total_positions = len([p for p in positions if p.get("change_type") != "exited"])

    lines = [
        f"# 13F Filing: {filer_name} — {quarter}",
        f"",
        f"Source: SEC EDGAR (13F-HR regulatory disclosure)",
        f"Quarter: {quarter} | Total active positions: {total_positions} | Portfolio value: {_fmt_money(total_value)}",
        f"Signal type: CONFIRMATION (45-135 day lag — use to validate theses, not initiate positions)",
        f"",
    ]

    if gap_unknown:
        lines += [
            f"⚠️ WARNING: Non-consecutive quarters detected. Changes below may be unreliable.",
            f"",
        ]

    def _pos_line(p: dict, show_change: bool = False) -> str:
        name   = p.get("company_name", "")
        ticker = p.get("ticker")
        # Use company name as primary label; show ticker if available, else CUSIP
        if ticker:
            label = f"**{ticker}** ({name})" if name else f"**{ticker}**"
        else:
            label = f"**{name}**" if name else f"CUSIP:{p.get('cusip', '?')}"
        shares = _fmt_shares(p.get("shares"))
        value  = _fmt_money(p.get("market_value_usd"))
        pct    = f"{p.get('portfolio_pct') or 0:.2f}%"

        if show_change and p.get("shares_change") is not None:
            chg = p["shares_change"]
            sign = "+" if chg >= 0 else ""
            return f"- {label} — {sign}{_fmt_shares(chg)} shares change, now {shares} ({value}, {pct})"
        return f"- {label} — {shares} shares ({value}, {pct})"

    if new_pos:
        lines += [f"## New Positions ({len(new_pos)})", ""]
        for p in new_pos[:max_positions]:
            lines.append(_pos_line(p))
        lines.append("")

    if increased:
        lines += [f"## Increased Positions ({len(increased)})", ""]
        for p in increased[:max_positions]:
            lines.append(_pos_line(p, show_change=True))
        lines.append("")

    if decreased:
        lines += [f"## Decreased Positions ({len(decreased)})", ""]
        for p in decreased[:max_positions]:
            lines.append(_pos_line(p, show_change=True))
        lines.append("")

    if exited:
        lines += [f"## Exited Positions ({len(exited)})", ""]
        for p in exited[:max_positions]:
            name   = p.get("company_name", "")
            ticker = p.get("ticker")
            label  = f"**{ticker}** ({name})" if ticker else (f"**{name}**" if name else f"CUSIP:{p.get('cusip', '?')}")
            lines.append(f"- {label}")
        lines.append("")

    if include_unchanged and unchanged:
        lines += [f"## Unchanged Top Holdings ({len(unchanged)})", ""]
        for p in unchanged[:10]:
            lines.append(_pos_line(p))
        lines.append("")

    return "\n".join(lines)


# ── Main scraper class ────────────────────────────────────────────────────────

class Filing13FScraper:
    """
    Scrapes 13F filings for one filer. Tracks scrape state for incremental runs.
    """

    def __init__(self, debug: bool = False):
        self.debug = debug

    def scrape_filer(
        self,
        filer_slug: str,
        filer_cik: str | None = None,
        max_positions: int = 50,
        include_unchanged: bool = False,
        dry_run: bool = False,
    ) -> list[dict]:
        """
        Fetch and diff the latest 13F for a filer.
        Returns list of post dicts for MoneyTrail raw_content.
        """
        # Resolve CIK
        cik = filer_cik
        if not cik:
            log.info(f"Looking up CIK for: {filer_slug}")
            cik = find_cik(filer_slug)
            if not cik:
                log.error(f"Could not find CIK for '{filer_slug}'")
                return []
            log.info(f"CIK: {cik}")
            time.sleep(0.5)

        # Get latest 2 filings (current + prior for diff)
        log.info(f"Fetching recent 13F filings for CIK {cik}...")
        filings = get_latest_filings(cik, count=2)
        if not filings:
            log.warning(f"No 13F filings found for CIK {cik}")
            return []

        current_filing = filings[0]
        prior_filing   = filings[1] if len(filings) > 1 else None

        current_quarter = current_filing["quarter"]
        log.info(f"Latest filing: {current_quarter} (filed {current_filing['filing_date']})")

        if dry_run:
            log.info(f"[DRY RUN] Would process {current_quarter} filing")
            return []

        # Parse current quarter holdings
        log.info(f"Parsing holdings XML for {current_quarter}...")
        time.sleep(0.5)
        current_positions = parse_holdings_xml(
            current_filing["accession_number"], cik
        )
        if not current_positions:
            log.warning(f"No positions parsed from {current_quarter} filing")
            return []
        log.info(f"  {len(current_positions)} positions")

        # Parse prior quarter for diff
        prior_positions = []
        consecutive = True
        if prior_filing:
            prior_quarter = prior_filing["quarter"]
            consecutive = _quarters_are_consecutive(prior_quarter, current_quarter)
            if not consecutive:
                log.warning(
                    f"Non-consecutive quarters: {prior_quarter} → {current_quarter}. "
                    "Diff may be unreliable; marking as gap_unknown."
                )
            time.sleep(0.5)
            prior_positions = parse_holdings_xml(
                prior_filing["accession_number"], cik
            )

        # Compute diff
        positions_with_diff = compute_diff(current_positions, prior_positions)
        if not consecutive:
            for p in positions_with_diff:
                if p.get("change_type") not in ("exited",):
                    p["change_type"] = "gap_unknown"

        # Build Markdown digest
        filer_name = filer_slug.replace("-", " ").title()
        text = format_digest(
            filer_name=filer_name,
            quarter=current_quarter,
            positions=positions_with_diff,
            max_positions=max_positions,
            include_unchanged=include_unchanged,
        )

        content_hash = hashlib.sha256(text.encode()).hexdigest()
        filed_dt     = current_filing.get("filing_date", "")

        return [{
            "title":        f"13F: {filer_name} — {current_quarter}",
            "author":       f"sec_edgar/{filer_slug}",
            "url":          (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={cik}&type=13F-HR&dateb=&owner=include&count=1"
            ),
            "published_at": f"{filed_dt}T00:00:00+00:00" if filed_dt else None,
            "text":         text,
            "content_hash": content_hash,
            "quarter":      current_quarter,
            "cik":          cik,
            "filer_slug":   filer_slug,
            "position_count": len([p for p in positions_with_diff if p.get("change_type") != "exited"]),
            "raw_snapshot": json.dumps([
                {k: v for k, v in p.items()}
                for p in current_positions
            ]),
        }]


# ── Public API (called by ingest_sources.py) ──────────────────────────────────

def scrape_filer(
    filer_slug: str,
    filer_cik: str | None = None,
    max_positions: int = 50,
    include_unchanged: bool = False,
    dry_run: bool = False,
    debug: bool = False,
) -> list[dict]:
    """Entry point for ingest_sources.py collect_sec13f()."""
    _setup_logging(debug)
    scraper = Filing13FScraper(debug=debug)
    return scraper.scrape_filer(
        filer_slug=filer_slug,
        filer_cik=filer_cik,
        max_positions=max_positions,
        include_unchanged=include_unchanged,
        dry_run=dry_run,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    _load_env()
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="SEC 13F filing scraper for MoneyTrail",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--setup",    action="store_true", help="Look up CIK for a filer name")
    parser.add_argument("--filer",    help="Filer slug or CIK number")
    parser.add_argument("--cik",      help="SEC CIK number (10 digits)")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--debug",    action="store_true")
    parser.add_argument("--max",      type=int, default=50, help="Max positions per section (default 50)")
    parser.add_argument("--unchanged",action="store_true", help="Include unchanged positions")
    args = parser.parse_args()

    if args.debug:
        _setup_logging(debug=True)

    if args.setup:
        if not args.filer:
            parser.error("--filer required with --setup")
        ua = os.getenv("EDGAR_USER_AGENT", "")
        if not ua:
            print("ERROR: Set EDGAR_USER_AGENT in secrets/.env first")
            print("Format: YourName/MoneyTrail your@email.com")
            sys.exit(1)
        print(f"Searching EDGAR for: {args.filer}")
        cik = find_cik(args.filer)
        if cik:
            print(f"CIK: {cik}")
            print(f"  EDGAR link: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=13F-HR")
        else:
            print("Not found. Try a different name or search manually at sec.gov/cgi-bin/browse-edgar")
        return

    if not args.filer:
        parser.error("--filer required")

    posts = scrape_filer(
        filer_slug=args.filer,
        filer_cik=args.cik,
        max_positions=args.max,
        include_unchanged=args.unchanged,
        dry_run=args.dry_run,
        debug=args.debug,
    )

    if args.dry_run or not posts:
        return

    out_dir = ROOT / "knowledge" / "raw" / "sec_13f" / args.filer
    out_dir.mkdir(parents=True, exist_ok=True)
    for post in posts:
        fname = f"{datetime.now().strftime('%Y%m%d')}_{post['quarter']}.md"
        (out_dir / fname).write_text(post["text"], encoding="utf-8")
        print(f"Saved: {out_dir / fname}")
        print(f"  {post['position_count']} positions in {post['quarter']}")


if __name__ == "__main__":
    main()
