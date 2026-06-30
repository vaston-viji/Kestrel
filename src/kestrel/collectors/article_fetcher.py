"""Enrich thin snippets for priority items by fetching article body text.

Called as Stage 8.5 in the pipeline — after allocation, before synthesis.
Only processes items where the snippet adds nothing beyond the headline
(the common case for Google News RSS, which returns only title + source name).

Two strategies are tried in order:
1. Direct fetch — for items with a real article URL, fetch and extract body text.
2. GNews source-homepage fallback — for opaque Google News URLs, fetch the
   publisher homepage (stored in raw_meta["gnews_source_href"]), find the
   article link by fuzzy title matching, then fetch and extract that article.

All failures degrade gracefully — the item keeps its original (thin) snippet
and the synthesis prompt guard provides a structured placeholder.
"""
from __future__ import annotations
import logging
import re
import warnings
from urllib.parse import urljoin, urlparse

import httpx
from rapidfuzz import fuzz
from selectolax.parser import HTMLParser

from kestrel.models import ScoredItem
from kestrel.collectors.page_cache import get_cache, PageCache

log = logging.getLogger(__name__)

_GNEWS_HOST = "news.google.com"
_FETCH_TIMEOUT = 8          # seconds per request — keep the stage fast
_MAX_SNIPPET_CHARS = 600
_MIN_PARA_CHARS = 40        # shorter paragraphs are nav/label noise
_TITLE_MATCH_THRESHOLD = 75  # rapidfuzz token_set_ratio score to accept as same article

_UA = "Kestrel/1.0 (Australian Defence Brief; contact product@quantrim.com)"
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-AU,en;q=0.9",
}

# Tried in priority order — first selector returning ≥1 qualifying paragraph wins
_BODY_SELECTORS = [
    "article p",
    "[class*='article'] p",
    "[class*='post-content'] p",
    "[class*='entry-content'] p",
    "[class*='story-body'] p",
    "[class*='body-text'] p",
    "main p",
    "p",
]


def is_thin(snippet: str | None, title: str) -> bool:
    """Return True when the snippet adds no meaningful content beyond the headline.

    Catches three shapes:
    - Empty / missing snippet
    - Snippet not materially longer than the title (headline-only from GNews RSS)
    - Snippet whose non-title remainder is trivially short (title + source name)
    """
    s = (snippet or "").strip()
    t = (title or "").strip()
    if not s:
        return True
    if len(s) < len(t) + 30:
        return True
    remainder = re.sub(re.escape(t), "", s, flags=re.IGNORECASE).strip()
    return len(remainder) < 30


def _extract_body(html: str) -> str:
    """Extract article body paragraphs from HTML, up to _MAX_SNIPPET_CHARS."""
    tree = HTMLParser(html)
    for el in tree.css("nav, header, footer, aside, script, style, "
                       "[class*='nav'], [class*='menu'], [class*='sidebar']"):
        el.decompose()
    for selector in _BODY_SELECTORS:
        paras = [
            re.sub(r"\s+", " ", p.text(strip=True))
            for p in tree.css(selector)
            if len(p.text(strip=True)) >= _MIN_PARA_CHARS
        ]
        if paras:
            return " ".join(paras)[:_MAX_SNIPPET_CHARS]
    return ""


def _fetch(url: str, timeout: int) -> tuple[str, str | None]:
    """GET url with redirect following. Returns (final_url, html) or (url, None).

    Attaches conditional request headers from page cache; updates cache on 200.
    """
    cache = get_cache()
    req_headers = dict(_HEADERS)
    if cache:
        cached = cache.get(url)
        if cached:
            if cached.get("etag"):
                req_headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                req_headers["If-Modified-Since"] = cached["last_modified"]

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = httpx.get(
                url, headers=req_headers, timeout=timeout,
                follow_redirects=True, verify=False,
            )
        final_url = str(r.url)

        if r.status_code == 304:
            return final_url, None
        if r.status_code == 200:
            if cache:
                cache.set(url, r.headers.get("etag", ""),
                          r.headers.get("last-modified", ""),
                          PageCache.hash_content(r.content))
            return final_url, r.text

        log.debug("HTTP %d for %s", r.status_code, url[:80])
        return final_url, None

    except Exception as exc:
        log.debug("fetch failed for %s: %s", url[:80], exc)
        return url, None


def _find_article_on_homepage(source_href: str, title: str,
                              timeout: int) -> tuple[str, str] | None:
    """Fetch the publisher homepage, find the link matching title, return (article_url, body).

    Uses rapidfuzz token_set_ratio so minor headline truncation doesn't break matching.
    Returns None if no match is found or the article fetch fails.
    """
    _, homepage_html = _fetch(source_href, timeout)
    if not homepage_html:
        return None

    tree = HTMLParser(homepage_html)
    best_score = 0
    best_href = ""

    for a in tree.css("a"):
        link_text = a.text(strip=True)
        if len(link_text) < 10:
            continue
        score = fuzz.token_set_ratio(link_text.lower(), title.lower())
        if score > best_score:
            best_score = score
            best_href = a.attributes.get("href", "")

    if best_score < _TITLE_MATCH_THRESHOLD or not best_href:
        log.debug("no title match on homepage %s (best=%d)", source_href[:60], best_score)
        return None

    article_url = urljoin(source_href, best_href)
    log.info("matched article link (score=%d): %s", best_score, article_url[:80])

    final_url, article_html = _fetch(article_url, timeout)
    if not article_html or _GNEWS_HOST in urlparse(final_url).netloc:
        return None

    body = _extract_body(article_html)
    return (final_url, body) if body else None


def enrich_snippets(items: list[ScoredItem], timeout: int = _FETCH_TIMEOUT) -> None:
    """Mutate thin-snippet ScoredItems in-place with fetched article body text.

    Strategy 1 — direct fetch: for non-GNews URLs, GET the article and extract
    body paragraphs. Updates canonical_url to the final redirect destination.

    Strategy 2 — GNews homepage fallback: when the canonical URL is an opaque
    Google News URL, fetch the publisher homepage (raw_meta["gnews_source_href"]),
    fuzzy-match the article title to find the real article link, then fetch and
    extract that article. Updates canonical_url to the real article URL.

    Gracefully skips items where enrichment fails — the synthesis prompt guard
    handles the remaining thin-snippet cases.
    """
    for item in items:
        if not is_thin(item.snippet, item.title):
            continue

        url = item.canonical_url
        is_gnews = _GNEWS_HOST in urlparse(url).netloc

        if not is_gnews:
            # Strategy 1: direct fetch
            final_url, html = _fetch(url, timeout)
            if html and _GNEWS_HOST not in urlparse(final_url).netloc:
                body = _extract_body(html)
                if body:
                    log.info("snippet enriched (direct, %d chars): %s",
                             len(body), item.title[:60])
                    item.snippet = body
                    if final_url != url:
                        item.canonical_url = final_url
                    continue
            log.info("enrichment skipped (direct fetch no body): %s", item.title[:60])
            continue

        # Strategy 2: GNews homepage fallback
        source_href = item.raw_meta.get("gnews_source_href", "")
        if not source_href:
            log.info("enrichment skipped (no gnews_source_href): %s", item.title[:60])
            continue

        log.info("trying GNews homepage fallback for: %s", item.title[:60])
        result = _find_article_on_homepage(source_href, item.title, timeout)
        if result:
            article_url, body = result
            log.info("snippet enriched (homepage, %d chars): %s",
                     len(body), item.title[:60])
            item.snippet = body
            item.canonical_url = article_url
        else:
            log.info("enrichment skipped (homepage fallback failed): %s", item.title[:60])
