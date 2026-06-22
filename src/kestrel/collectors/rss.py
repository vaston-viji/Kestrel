"""RSS/Atom collector with feed auto-discovery."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from kestrel.models import RawItem, Source, Window
from kestrel.collectors.protocol import parse_notes_hint
from kestrel.collectors.page_cache import get_cache, PageCache

log = logging.getLogger(__name__)

_FEED_NOT_MODIFIED = b""  # sentinel: feed bytes indicating nothing changed

FEED_PATHS = ["/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml",
              "/news.xml", "/news/feed", "/feed/rss", "/blog/feed"]
HEADERS = {"User-Agent": "Kestrel/1.0 (Australian Defence Brief; contact vjohn1@kpmg.com.au)"}


def _fetch_feed_bytes(url: str, timeout: int) -> bytes | None:
    """Fetch feed bytes with conditional request support.

    Returns:
        bytes           — new feed content
        _FEED_NOT_MODIFIED (b"") — feed unchanged since last fetch (304 or same hash)
        None            — fetch failed
    """
    import warnings as _w

    cache = get_cache()
    req_headers = dict(HEADERS)
    cached = cache.get(url) if cache else None
    if cached:
        if cached["etag"]:
            req_headers["If-None-Match"] = cached["etag"]
        if cached["last_modified"]:
            req_headers["If-Modified-Since"] = cached["last_modified"]

    r = None
    try:
        r = httpx.get(url, headers=req_headers, timeout=timeout, follow_redirects=True)
    except Exception as exc:
        exc_str = str(exc).lower()
        if "ssl" in exc_str or "certificate" in exc_str:
            try:
                with _w.catch_warnings():
                    _w.simplefilter("ignore")
                    r = httpx.get(url, headers=req_headers, timeout=timeout,
                                  follow_redirects=True, verify=False)
                log.debug("SSL fallback succeeded for %s", url)
            except Exception:
                pass
    if r is None:
        return None

    if r.status_code == 304:
        log.debug("Feed 304 Not Modified: %s", url)
        return _FEED_NOT_MODIFIED

    if r.status_code == 200:
        content = _repair_feed(r.content)
        if cache:
            content_hash = PageCache.hash_content(content)
            if cached and cached["content_hash"] and cached["content_hash"] == content_hash:
                log.debug("Feed content hash unchanged: %s", url)
                return _FEED_NOT_MODIFIED
            cache.set(url, r.headers.get("etag", ""), r.headers.get("last-modified", ""), content_hash)
        return content

    return None


def _repair_feed(content: bytes) -> bytes:
    """Fix known broken feed patterns before handing to feedparser.

    Some WordPress/CMS installations emit '<link/>URL' (self-closing with
    the URL outside the tag) instead of '<link>URL</link>'.
    """
    import re as _re
    try:
        text = content.decode("utf-8", errors="replace")
        # Fix <link/>URL -> <link>URL</link>
        text = _re.sub(
            r"<link/>(https?://[^\s<]+)",
            r"<link>\1</link>",
            text,
        )
        return text.encode("utf-8")
    except Exception:
        return content


def _to_utc(ts) -> datetime | None:
    if not ts:
        return None
    try:
        import calendar, time as time_mod
        # feedparser returns time.struct_time for published_parsed
        if isinstance(ts, time_mod.struct_time):
            return datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc)
        # datetime objects
        if isinstance(ts, datetime):
            return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        # RFC 2822 / string fallback
        return parsedate_to_datetime(str(ts)).astimezone(timezone.utc)
    except Exception:
        return None


def _discover_feed(base_url: str, timeout: int) -> str | None:
    """Try to find feed URL by probing known paths."""
    from urllib.parse import urlparse, urljoin
    import warnings
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = httpx.get(base_url, headers=HEADERS, timeout=timeout,
                             follow_redirects=True, verify=False)
        # Check <link rel="alternate"> in HTML
        import re
        for m in re.finditer(
            r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/(rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']',
            resp.text, re.I
        ):
            href = m.group(2)
            return urljoin(base_url, href)
        for m in re.finditer(
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]+type=["\']application/(rss|atom)\+xml["\']',
            resp.text, re.I
        ):
            href = m.group(1)
            return urljoin(base_url, href)
    except Exception:
        pass

    # Probe known paths — use a short timeout so slow servers (e.g. WAFs that
    # always return 200 but take 10s per HEAD) don't burn the global budget.
    head_timeout = min(timeout, 2)
    for path in FEED_PATHS:
        url = root + path
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = httpx.head(url, headers=HEADERS, timeout=head_timeout,
                               follow_redirects=True, verify=False)
            ct = r.headers.get("content-type", "")
            if r.status_code == 200 and ("xml" in ct or "rss" in ct or "atom" in ct):
                return url
        except Exception:
            continue
    return None


class RSSCollector:
    def __init__(self, timeout: int = 20) -> None:
        self._timeout = timeout

    def collect(self, source: Source, window: Window) -> list[RawItem]:
        # Check for hardcoded feed URL in Notes
        feed_url = parse_notes_hint(source.notes, "feed") or _discover_feed(source.url, self._timeout)
        if not feed_url:
            log.warning("No feed found for %s", source.name)
            return []

        content = _fetch_feed_bytes(feed_url, self._timeout)
        if content is _FEED_NOT_MODIFIED:
            log.debug("Feed unchanged, skipping: %s", source.name)
            return []
        if content is None:
            log.warning("Could not fetch feed for %s: %s", source.name, feed_url)
            return []
        try:
            feed = feedparser.parse(content)
        except Exception as exc:
            log.warning("RSS parse error for %s: %s", source.name, exc)
            return []

        items = []
        for entry in feed.entries:
            pub = _to_utc(entry.get("published_parsed") or entry.get("updated_parsed"))
            if pub and pub < window.start:
                continue

            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()
            if not title or not url:
                continue
            snippet = (
                entry.get("summary", "")
                or entry.get("description", "")
                or ""
            )
            # strip HTML from snippet
            import re
            snippet = re.sub(r"<[^>]+>", " ", snippet).strip()[:500]

            items.append(RawItem(
                title=title,
                url=url,
                source_name=source.name,
                published_at=pub,
                snippet=snippet,
                raw_meta={"feed_url": feed_url},
            ))

        log.info("RSS %s -> %d items", source.name, len(items))
        return items
