"""data.gov.au CKAN dataset collector.

Queries the Australian Government open data portal (CKAN) for recently updated
datasets matching source-specific keywords. Most useful for AusTender bulk data
and statistical/procurement releases.

Notes field hint (required):
  ckan: <search terms>

Example:
  ckan: defence contracts procurement tenders
"""
from __future__ import annotations
import logging
from datetime import timezone
from urllib.parse import urlencode

import httpx
from dateutil.parser import parse as _parse_date

from kestrel.models import RawItem, Source, Window
from kestrel.collectors.protocol import parse_notes_hint

log = logging.getLogger(__name__)

CKAN_SEARCH = "https://data.gov.au/api/3/action/package_search"
HEADERS = {"User-Agent": "Kestrel/1.0 (Australian Defence Brief; contact product@quantrim.com)"}


class DataGovAuCollector:
    def __init__(self, timeout: int = 20) -> None:
        self._timeout = timeout

    def collect(self, source: Source, window: Window) -> list[RawItem]:
        query = parse_notes_hint(source.notes, "ckan")
        if not query:
            log.warning("DataGovAu: no 'ckan:' hint in Notes for %s", source.name)
            return []

        params = {"q": query, "sort": "metadata_modified desc", "rows": 20}
        url = f"{CKAN_SEARCH}?{urlencode(params)}"

        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = httpx.get(url, headers=HEADERS, timeout=self._timeout,
                              follow_redirects=True, verify=False)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.warning("DataGovAu fetch error for %s: %s", source.name, exc)
            return []

        results = data.get("result", {}).get("results", [])
        items = []
        for pkg in results:
            pub = None
            modified_str = pkg.get("metadata_modified", "")
            if modified_str:
                try:
                    pub = _parse_date(modified_str).replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            if pub and pub < window.start:
                continue

            title = pkg.get("title", "").strip()
            pkg_name = pkg.get("name", "")
            link = f"https://data.gov.au/dataset/{pkg_name}"
            notes_text = pkg.get("notes", "").strip()[:300]
            org = (pkg.get("organization") or {}).get("title", "")
            snippet = f"{org}: {notes_text}".strip(": ")

            if not title:
                continue

            items.append(RawItem(
                title=title,
                url=link,
                source_name=source.name,
                published_at=pub,
                snippet=snippet,
                raw_meta={"ckan_id": pkg.get("id", ""), "org": org},
            ))

        log.info("DataGovAu %s -> %d datasets", source.name, len(items))
        return items
