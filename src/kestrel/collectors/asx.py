"""ASX announcements collector.

Uses the ASX JSON endpoint. Note: ASX migrated to a Vue.js SPA in 2024/2025
and the public API now returns 404. Sources should be migrated to individual
company IR pages in the source registry.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import httpx
from dateutil.parser import parse as parse_date

from kestrel.models import RawItem, Source, Window

log = logging.getLogger(__name__)

UA = "Kestrel/1.0 (Australian Defence Brief; contact product@quantrim.com)"
HEADERS = {"User-Agent": UA, "Accept": "application/json, text/html"}

# ASX's internal JSON endpoint — NOTE: this API was shut down by ASX when they
# migrated to a Vue.js SPA in 2024/2025. Both this and the old HTML page return 404.
# TODO: replace with individual company IR-page sources in the source registry.
_ASX_JSON = "https://www.asx.com.au/asx/1/company/{ticker}/announcements?count=20&market_sensitive=false"


def _parse_json(data: dict, ticker: str, source_name: str, window: Window) -> list[RawItem]:
    items = []
    for ann in data.get("data", []):
        title = ann.get("header", "").strip()
        url = ann.get("url", "").strip()
        if not url:
            doc_date = ann.get("document_date", "")
            url = f"https://www.asx.com.au/asxpdf/{doc_date[:8].replace('-','')}/{ticker.lower()}.htm"
        price_sensitive = bool(ann.get("price_sensitive"))
        try:
            pub = parse_date(ann.get("document_date", "")).astimezone(timezone.utc)
        except Exception:
            pub = None

        if pub and pub < window.start:
            continue
        if not title:
            continue

        snippet = f"[ASX:{ticker}] {ann.get('document_type', '')}".strip()
        if price_sensitive:
            snippet += " [PRICE SENSITIVE]"

        items.append(RawItem(
            title=title,
            url=f"https://www.asx.com.au{url}" if url.startswith("/") else url,
            source_name=source_name,
            published_at=pub,
            snippet=snippet,
            raw_meta={"asx_ticker": ticker, "price_sensitive": price_sensitive,
                      "doc_type": ann.get("document_type", "")},
        ))
    return items


class ASXCollector:
    def __init__(self, timeout: int = 20) -> None:
        self._timeout = timeout

    def collect(self, source: Source, window: Window) -> list[RawItem]:
        ticker = source.asx_ticker.strip().upper()
        if not ticker:
            log.warning("ASX source %s has no ticker", source.name)
            return []

        # Try JSON endpoint (NOTE: returns 404 since ASX migrated to Vue.js SPA)
        try:
            resp = httpx.get(
                _ASX_JSON.format(ticker=ticker),
                headers=HEADERS,
                timeout=self._timeout,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = _parse_json(data, ticker, source.name, window)
                log.info("ASX JSON %s -> %d items", ticker, len(items))
                return items
            if resp.status_code == 404:
                log.warning(
                    "ASX API deprecated for %s (404) — update source registry to use company IR page",
                    ticker,
                )
                return []
        except Exception as exc:
            log.warning("ASX JSON endpoint failed for %s: %s", ticker, exc)

        return []
