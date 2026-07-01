"""ASX announcements collector.

Scrapes the ASX v2 announcements page per company ticker. Filters out routine
administrative filings (director interest notices, capital quotations, substantial
holder changes) and returns only substantive announcements within the collection
window. Price-sensitive announcements always pass the filter.
"""
from __future__ import annotations
import logging
import re
import zoneinfo
from datetime import datetime, timezone

import httpx

from kestrel.models import RawItem, Source, Window

log = logging.getLogger(__name__)

_SYDNEY_TZ = zoneinfo.ZoneInfo("Australia/Sydney")

_ANNOUNCEMENTS_URL = (
    "https://www.asx.com.au/asx/v2/statistics/announcements.do"
    "?by=asxCode&asxCode={ticker}&timeframe=D&period=M"
)
_VIEWER_URL = (
    "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do"
    "?display=pdf&idsId={ids_id}"
)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Headline substrings that mark routine admin filings — excluded unless price-sensitive
_ADMIN_PATTERNS = re.compile(
    r"change of director.s interest|"
    r"notification regarding unquoted|"
    r"application for quotation of securities|"
    r"becoming a substantial holder|"
    r"ceasing to be a substantial holder|"
    r"notification of cessation|"
    r"change in substantial holding|"
    r"appendix 3[by]|"
    r"top [12]00 security holders",
    re.IGNORECASE,
)


def _parse_sydney_date(raw: str) -> datetime | None:
    """Parse ASX date string like '29/06/2026 5:22 pm' as Sydney time → UTC."""
    raw = re.sub(r"\s+", " ", raw).strip()
    for fmt in ("%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M"):
        try:
            naive = datetime.strptime(raw[:19], fmt)
            return naive.replace(tzinfo=_SYDNEY_TZ).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _scrape(ticker: str, timeout: int) -> list[dict]:
    """Fetch and parse the announcements.do page, returning raw dicts."""
    try:
        r = httpx.get(
            _ANNOUNCEMENTS_URL.format(ticker=ticker),
            headers={"User-Agent": _UA},
            timeout=timeout,
            follow_redirects=True,
        )
        if r.status_code != 200:
            log.warning("ASX announcements.do HTTP %d for %s", r.status_code, ticker)
            return []
    except Exception as exc:
        log.warning("ASX announcements.do request failed for %s: %s", ticker, exc)
        return []

    html = r.text
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    results = []
    for row in rows:
        ids_m = re.search(r"idsId=(\w+)", row)
        if not ids_m:
            continue
        ids_id = ids_m.group(1)

        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) < 2:
            continue

        is_sensitive = "icon-price-sensitive" in row

        date_raw = re.sub(r"<[^>]+>", " ", cells[0])
        date_str = re.sub(r"\s+", " ", date_raw).strip()

        # Headline is the anchor text in the last meaningful cell
        hl_m = re.search(r'text-decoration:\s*none[^>]*>([^<]+)', row)
        if not hl_m:
            hl_m = re.search(r'<a\s[^>]+>([^<]+)', row)
        headline = re.sub(r"\s+", " ", hl_m.group(1)).strip() if hl_m else ""

        if not headline or not ids_id:
            continue

        results.append({
            "date_str": date_str,
            "headline": headline,
            "sensitive": is_sensitive,
            "ids_id": ids_id,
        })
    return results


class ASXCollector:
    def __init__(self, timeout: int = 20) -> None:
        self._timeout = timeout

    def collect(self, source: Source, window: Window) -> list[RawItem]:
        ticker = (source.asx_ticker or "").strip().upper()
        if not ticker:
            log.warning("ASX source %s has no ticker", source.name)
            return []

        raw = _scrape(ticker, self._timeout)
        if not raw:
            return []

        items: list[RawItem] = []
        for ann in raw:
            pub = _parse_sydney_date(ann["date_str"])

            # Window filter
            if pub and pub < window.start:
                continue
            if pub and pub > window.end:
                continue

            headline = ann["headline"]
            is_sensitive = ann["sensitive"]

            # Skip routine admin filings unless price-sensitive
            if not is_sensitive and _ADMIN_PATTERNS.search(headline):
                log.debug("ASX %s: skipping admin announcement: %s", ticker, headline[:60])
                continue

            url = _VIEWER_URL.format(ids_id=ann["ids_id"])
            snippet = f"[ASX:{ticker}]"
            if is_sensitive:
                snippet += " [PRICE SENSITIVE]"

            items.append(RawItem(
                title=headline,
                url=url,
                source_name=source.name,
                published_at=pub,
                snippet=snippet,
                raw_meta={
                    "asx_ticker": ticker,
                    "price_sensitive": is_sensitive,
                    "ids_id": ann["ids_id"],
                },
            ))

        log.info("ASX %s: %d substantive announcements in window (from %d total)",
                 ticker, len(items), len(raw))
        return items
