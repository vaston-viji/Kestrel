"""Google News RSS collector — fallback for JS-rendered and robots-blocked sources.

Queries Google News RSS search (news.google.com/rss/search), which returns items
from Google's index rather than fetching the source directly. This bypasses robots.txt
and JavaScript rendering entirely.

Collector is invoked in two ways:
  1. Notes field contains 'gnews: <custom query>' → use that query directly.
  2. Auto-generated: 'site:<domain>' derived from the source URL.
"""
from __future__ import annotations
import calendar
import logging
import re
import time as time_mod
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx

from kestrel.models import RawItem, Source, Window
from kestrel.collectors.protocol import parse_notes_hint

log = logging.getLogger(__name__)

GNEWS_BASE = "https://news.google.com/rss/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-AU,en;q=0.9",
}


def _build_url(query: str) -> str:
    return f"{GNEWS_BASE}?q={quote_plus(query)}&hl=en-AU&gl=AU&ceid=AU:en"


def _auto_query(source: Source) -> str:
    domain = urlparse(source.url).netloc.lstrip("www.")
    return f"site:{domain}"


def _to_utc(raw_pub) -> datetime | None:
    if not raw_pub:
        return None
    try:
        if isinstance(raw_pub, time_mod.struct_time):
            return datetime.fromtimestamp(calendar.timegm(raw_pub), tz=timezone.utc)
        if isinstance(raw_pub, datetime):
            return raw_pub.astimezone(timezone.utc)
    except Exception:
        pass
    return None


class GoogleNewsCollector:
    def __init__(self, timeout: int = 20) -> None:
        self._timeout = timeout

    def collect(self, source: Source, window: Window) -> list[RawItem]:
        hint = parse_notes_hint(source.notes, "gnews")
        query = hint or _auto_query(source)
        url = _build_url(query)

        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = httpx.get(url, headers=HEADERS, timeout=self._timeout,
                              follow_redirects=True, verify=False)
            if r.status_code != 200:
                log.debug("Google News HTTP %d for %s", r.status_code, source.name)
                return []
            content = r.content
        except Exception as exc:
            log.warning("Google News fetch error for %s: %s", source.name, exc)
            return []

        try:
            feed = feedparser.parse(content)
        except Exception as exc:
            log.warning("Google News parse error for %s: %s", source.name, exc)
            return []

        items = []
        for entry in feed.entries:
            pub = _to_utc(entry.get("published_parsed") or entry.get("updated_parsed"))
            if pub and pub < window.start:
                continue

            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            snippet = re.sub(r"<[^>]+>", " ", entry.get("summary", "")).strip()[:500]
            # Capture the publisher homepage URL so article_fetcher can locate
            # the article on the source site when the GNews redirect is opaque.
            gnews_source_href = entry.get("source", {}).get("href", "")

            items.append(RawItem(
                title=title,
                url=link,
                source_name=source.name,
                published_at=pub,
                snippet=snippet,
                raw_meta={"gnews_query": query, "gnews_source_href": gnews_source_href},
            ))

        log.info("GoogleNews %s (q=%r) -> %d items", source.name, query, len(items))
        return items
