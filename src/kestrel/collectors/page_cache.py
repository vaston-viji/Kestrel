"""Per-URL HTTP cache for conditional requests.

Stores ETag, Last-Modified, and a content hash for every URL fetched.
On subsequent runs:
  - Sends If-None-Match / If-Modified-Since headers so the server can return 304
  - Falls back to content-hash comparison for servers that ignore caching headers

Usage:
    from kestrel.collectors.page_cache import init_cache, get_cache
    init_cache(Path("data/page_cache.db"))   # call once at startup
    cache = get_cache()                       # returns PageCache | None
"""
from __future__ import annotations
import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_cache: "PageCache | None" = None


def init_cache(path: Path) -> None:
    global _cache
    _cache = PageCache(path)


def get_cache() -> "PageCache | None":
    return _cache


class PageCache:
    _DDL = """
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS page_cache (
        url_hash      TEXT PRIMARY KEY,
        url           TEXT NOT NULL,
        etag          TEXT,
        last_modified TEXT,
        content_hash  TEXT NOT NULL DEFAULT '',
        last_fetched  TEXT NOT NULL
    );
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(self._DDL)
        self._conn.commit()

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()

    def get(self, url: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT etag, last_modified, content_hash FROM page_cache WHERE url_hash=?",
                (self._key(url),),
            ).fetchone()
        if row:
            return {"etag": row[0] or "", "last_modified": row[1] or "", "content_hash": row[2] or ""}
        return None

    def set(self, url: str, etag: str, last_modified: str, content_hash: str) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO page_cache "
                "(url_hash, url, etag, last_modified, content_hash, last_fetched) "
                "VALUES (?,?,?,?,?,?)",
                (self._key(url), url, etag or None, last_modified or None, content_hash, now),
            )
            self._conn.commit()

    @staticmethod
    def hash_content(content: bytes) -> str:
        return hashlib.md5(content).hexdigest()
