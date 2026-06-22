"""Resilient HTML scrape collector with robots.txt respect."""
from __future__ import annotations
import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import threading

import httpx
from selectolax.parser import HTMLParser

from kestrel.models import RawItem, Source, Window
from kestrel.collectors.protocol import parse_notes_hint
from kestrel.collectors.page_cache import get_cache, PageCache

log = logging.getLogger(__name__)

UA = "Kestrel/1.0 (Australian Defence Brief; contact viji.john@quantrim.com)"
HEADERS = {"User-Agent": UA}
_robots_cache: dict[str, RobotFileParser] = {}
_robots_lock = threading.Lock()
_last_request: dict[str, float] = {}
_last_request_lock = threading.Lock()
POLITE_DELAY = 1.5  # seconds between requests to same host

# Sentinel: returned by _polite_get when server confirms nothing has changed
_NOT_MODIFIED = object()


def _robots(base_url: str, timeout: int) -> RobotFileParser:
    """Load robots.txt via httpx (SSL-tolerant) and parse it. Thread-safe."""
    parsed = urlparse(base_url)
    host = f"{parsed.scheme}://{parsed.netloc}"
    with _robots_lock:
        if host in _robots_cache:
            return _robots_cache[host]
    # Fetch outside the lock so other threads aren't blocked waiting on I/O
    rp = RobotFileParser()
    robots_url = host + "/robots.txt"
    rp.set_url(robots_url)
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = httpx.get(robots_url, headers=HEADERS, timeout=timeout,
                          follow_redirects=True, verify=False)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
    except Exception:
        pass
    with _robots_lock:
        _robots_cache.setdefault(host, rp)
        return _robots_cache[host]


def _polite_get(url: str, client: httpx.Client, timeout: int):
    """Fetch URL with politeness delay and HTTP conditional request support.

    Returns:
        httpx.Response  — new content received (200)
        _NOT_MODIFIED   — server or hash confirms nothing changed (304 / same hash)
        None            — request failed
    """
    host = urlparse(url).netloc
    with _last_request_lock:
        since = time.time() - _last_request.get(host, 0.0)
        wait = POLITE_DELAY - since
    if wait > 0:
        time.sleep(wait)

    # Attach conditional headers if we have a cached entry for this URL
    cache = get_cache()
    req_headers = dict(HEADERS)
    cached = cache.get(url) if cache else None
    if cached:
        if cached["etag"]:
            req_headers["If-None-Match"] = cached["etag"]
        if cached["last_modified"]:
            req_headers["If-Modified-Since"] = cached["last_modified"]

    resp = None
    try:
        resp = client.get(url, headers=req_headers, timeout=timeout, follow_redirects=True)
        with _last_request_lock:
            _last_request[host] = time.time()
    except Exception as exc:
        exc_str = str(exc).lower()
        if "ssl" in exc_str or "certificate" in exc_str:
            import warnings
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    resp = httpx.get(url, headers=req_headers, timeout=timeout,
                                     follow_redirects=True, verify=False)
                with _last_request_lock:
                    _last_request[host] = time.time()
                log.debug("SSL fallback succeeded for %s", url)
            except Exception:
                log.warning("GET %s failed: %s", url, exc)
                return None
        else:
            log.warning("GET %s failed: %s", url, exc)
            return None

    if resp.status_code == 304:
        log.debug("304 Not Modified: %s", url)
        return _NOT_MODIFIED

    if resp.status_code == 200 and cache:
        content_hash = PageCache.hash_content(resp.content)
        if cached and cached["content_hash"] and cached["content_hash"] == content_hash:
            log.debug("Content hash unchanged: %s", url)
            return _NOT_MODIFIED
        cache.set(
            url,
            resp.headers.get("etag", ""),
            resp.headers.get("last-modified", ""),
            content_hash,
        )

    return resp


def _parse_date(tag) -> datetime | None:
    for attr in ("datetime", "content"):
        val = tag.attributes.get(attr, "")
        if val:
            try:
                from dateutil.parser import parse as dp
                return dp(val).astimezone(timezone.utc).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _heuristic_items(tree: HTMLParser, base_url: str, window: Window) -> list[dict]:
    """Generic extraction: articles / h2-h3 links near <time> elements."""
    results = []
    # Prefer <article> containers
    containers = tree.css("article") or []
    if not containers:
        # Fall back to main/body
        containers = tree.css("main, .content, #content, body")

    for container in containers:
        for tag in container.css("h1, h2, h3"):
            a = tag.css_first("a") or (tag.parent.css_first("a") if tag.parent else None)
            if not a:
                continue
            href = a.attributes.get("href", "")
            if not href or href.startswith("#") or href.startswith("javascript"):
                continue
            link = urljoin(base_url, href)
            title = a.text(strip=True) or tag.text(strip=True)
            if len(title) < 10:
                continue

            # Find adjacent <time> or meta date
            pub = None
            parent = tag.parent
            for _ in range(4):
                if parent is None:
                    break
                t = parent.css_first("time")
                if t:
                    pub = _parse_date(t)
                    break
                parent = parent.parent

            # snippet: next sibling <p>
            snippet = ""
            if tag.parent:
                for sib in tag.parent.css("p"):
                    snippet = sib.text(strip=True)[:300]
                    if snippet:
                        break

            results.append({"title": title, "url": link, "pub": pub, "snippet": snippet})

    return results


class HTMLScrapeCollector:
    def __init__(self, timeout: int = 20) -> None:
        self._timeout = timeout

    def collect(self, source: Source, window: Window) -> list[RawItem]:
        rp = _robots(source.url, self._timeout)
        if not rp.can_fetch(UA, source.url):
            log.info("robots.txt disallows %s for %s", source.url, source.name)
            return []

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with httpx.Client(verify=False) as client:
                resp = _polite_get(source.url, client, self._timeout)
        if resp is _NOT_MODIFIED:
            log.debug("Scrape skipped (unchanged): %s", source.name)
            return []
        if resp is None or resp.status_code >= 400:
            log.warning("Scrape failed for %s (status %s)",
                        source.name, getattr(resp, "status_code", "err"))
            return []

        tree = HTMLParser(resp.text)

        # Check Notes for CSS selector hint
        selector = parse_notes_hint(source.notes, "selector")
        if selector:
            candidates = []
            for node in tree.css(selector):
                a = node if node.tag == "a" else node.css_first("a")
                if not a:
                    continue
                href = urljoin(source.url, a.attributes.get("href", ""))
                # Prefer aria-label (clean title without nested nav text) then text content
                title = (a.attributes.get("aria-label", "").strip()
                         or a.text(strip=True)
                         or node.text(strip=True))
                # Skip very short titles (nav labels like "Land", "Latest")
                if title and href and len(title) >= 10:
                    candidates.append({"title": title, "url": href, "pub": None, "snippet": ""})
        else:
            candidates = _heuristic_items(tree, source.url, window)

        items = []
        for c in candidates:
            pub: datetime | None = c.get("pub")
            if pub and pub < window.start:
                continue
            title = re.sub(r"\s+", " ", c["title"]).strip()
            if not title:
                continue
            items.append(RawItem(
                title=title,
                url=c["url"],
                source_name=source.name,
                published_at=pub,
                snippet=c.get("snippet", ""),
                raw_meta={"scrape_url": source.url},
            ))

        log.info("Scrape %s -> %d items", source.name, len(items))
        return items
