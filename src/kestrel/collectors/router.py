"""Route each source to its collector strategy; collect all sources concurrently."""
from __future__ import annotations
import concurrent.futures
import logging
import threading
from datetime import datetime, timezone

from kestrel.models import RawItem, Source, Window
from kestrel.collectors.asx import ASXCollector
from kestrel.collectors.austender import AusTenderCollector
from kestrel.collectors.bing_news import BingNewsCollector
from kestrel.collectors.data_gov_au import DataGovAuCollector
from kestrel.collectors.google_news import GoogleNewsCollector
from kestrel.collectors.protocol import parse_notes_hint
from kestrel.collectors.rss import RSSCollector
from kestrel.collectors.scrape import HTMLScrapeCollector

log = logging.getLogger(__name__)

_LINKEDIN_SKIP_MSG = "skipped_linkedin"
_DEADLINE_MSG = "deadline_exceeded"
_WORKERS = 20

# Cap concurrent Google News requests — hitting news.google.com with 20 threads
# simultaneously triggers WinError 10054 (connection forcibly closed). Bing is
# used as a 4th-tier fallback and tolerates higher concurrency.
_GNEWS_SEMAPHORE = threading.Semaphore(3)


def collect_source(source: Source, window: Window, timeout: int) -> tuple[list[RawItem], str | None]:
    """Return (items, error_msg). error_msg is None on success."""
    if source.type.lower() == "linkedin":
        log.info("Skipping LinkedIn source: %s", source.name)
        return [], _LINKEDIN_SKIP_MSG

    if source.type.upper() == "ASX":
        collector: object = ASXCollector(timeout=timeout)
        try:
            items = collector.collect(source, window)
            return items, None
        except Exception as exc:
            log.warning("Collect error for %s: %s", source.name, exc)
            return [], f"collect_error: {exc}"
    elif source.type.upper() == "AUSTENDER":
        collector = AusTenderCollector(timeout=timeout)
        try:
            items = collector.collect(source, window)
            return items, None
        except Exception as exc:
            log.warning("Collect error for %s: %s", source.name, exc)
            return [], f"collect_error: {exc}"
    elif parse_notes_hint(source.notes, "ckan"):
        collector = DataGovAuCollector(timeout=timeout)
        try:
            items = collector.collect(source, window)
            return items, None
        except Exception as exc:
            log.warning("Collect error for %s: %s", source.name, exc)
            return [], f"collect_error: {exc}"
    elif parse_notes_hint(source.notes, "gnews"):
        # Explicit Google News query — throttled to avoid rate limits
        try:
            with _GNEWS_SEMAPHORE:
                items = GoogleNewsCollector(timeout=timeout).collect(source, window)
            if items:
                return items, None
        except Exception as exc:
            log.warning("Google News collect error for %s: %s", source.name, exc)
        # Fall through to Bing if GNews returns nothing or errors
        try:
            items = BingNewsCollector(timeout=timeout).collect(source, window)
            return items, None
        except Exception as exc:
            log.warning("Bing News fallback error for %s: %s", source.name, exc)
            return [], f"collect_error: {exc}"
    else:
        return _rss_scrape_gnews(source, window, timeout)


def _rss_scrape_gnews(
    source: Source, window: Window, timeout: int
) -> tuple[list[RawItem], str | None]:
    """RSS → scrape → Google News fallback chain."""
    method_hint = parse_notes_hint(source.notes, "method").lower()

    # RSS (skip if Notes says method:scrape)
    if method_hint != "scrape":
        try:
            items = RSSCollector(timeout=timeout).collect(source, window)
            if items:
                return items, None
        except Exception as exc:
            log.warning("RSS failed for %s: %s", source.name, exc)

    # HTML scrape
    try:
        items = HTMLScrapeCollector(timeout=timeout).collect(source, window)
        if items:
            return items, None
    except Exception as exc:
        log.warning("Scrape failed for %s: %s", source.name, exc)

    # Google News (throttled — max 3 concurrent)
    try:
        with _GNEWS_SEMAPHORE:
            items = GoogleNewsCollector(timeout=timeout).collect(source, window)
        if items:
            return items, None
    except Exception as exc:
        log.warning("Google News fallback failed for %s: %s", source.name, exc)

    # Bing News (final fallback — more rate-limit-tolerant than Google News)
    try:
        items = BingNewsCollector(timeout=timeout).collect(source, window)
        return items, None
    except Exception as exc:
        log.warning("Bing News fallback failed for %s: %s", source.name, exc)
        return [], f"collect_error: {exc}"


def collect_all(
    sources: list[Source],
    window: Window,
    per_source_timeout: int,
    global_deadline: datetime,
) -> tuple[list[RawItem], list[str], list[str]]:
    """Collect from all sources concurrently, respecting the global time budget.

    Returns (all_raw_items, zero_yield_sources, linkedin_sources).
    Up to _WORKERS sources run in parallel; the global deadline cancels remaining work.
    """
    all_items: list[RawItem] = []
    zero_yield: list[str] = []
    linkedin: list[str] = []
    _items_lock = threading.Lock()

    def _one(source: Source) -> tuple[str, list[RawItem], str | None]:
        if datetime.now(tz=timezone.utc) > global_deadline:
            return source.name, [], _DEADLINE_MSG
        items, err = collect_source(source, window, per_source_timeout)
        return source.name, items, err

    with concurrent.futures.ThreadPoolExecutor(max_workers=_WORKERS) as executor:
        future_map = {executor.submit(_one, s): s for s in sources}

        for future in concurrent.futures.as_completed(future_map):
            if datetime.now(tz=timezone.utc) > global_deadline:
                log.warning("Global time budget exhausted; cancelling remaining collection")
                for f in future_map:
                    f.cancel()
                break

            try:
                src_name, items, err = future.result()
            except Exception as exc:
                src = future_map[future]
                log.warning("Unhandled thread error for %s: %s", src.name, exc)
                with _items_lock:
                    zero_yield.append(src.name)
                continue

            if err == _LINKEDIN_SKIP_MSG:
                with _items_lock:
                    linkedin.append(src_name)
                continue
            if err == _DEADLINE_MSG:
                continue
            if err:
                log.warning("Source %s: %s", src_name, err)

            with _items_lock:
                if not items:
                    zero_yield.append(src_name)
                else:
                    all_items.extend(items)

    return all_items, zero_yield, linkedin
