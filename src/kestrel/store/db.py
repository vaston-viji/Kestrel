"""SQLite archive — WAL mode, stable past 12 months of data."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from kestrel.models import BriefItem, Brief, ScoredItem

DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    slot        TEXT NOT NULL,
    run_date    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    late        INTEGER NOT NULL DEFAULT 0,
    item_count  INTEGER,
    status      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    item_id          TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL REFERENCES runs(run_id),
    headline         TEXT NOT NULL,
    canonical_url    TEXT NOT NULL,
    source_name      TEXT NOT NULL,
    published_at     TEXT,
    section          TEXT,
    summary          TEXT,
    why_it_matters   TEXT,
    kpmg_angle       TEXT,
    confidence       TEXT,
    rating_total     REAL,
    rating_impact    REAL,
    rating_sentiment REAL,
    kpmg_tags        TEXT,
    domain_tags      TEXT,
    escalated        INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_sources (
    item_id     TEXT NOT NULL REFERENCES items(item_id),
    source_name TEXT NOT NULL,
    url         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS url_seen (
    url_hash    TEXT PRIMARY KEY,
    first_seen  TEXT NOT NULL,
    headline    TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_run      ON items(run_id);
CREATE INDEX IF NOT EXISTS idx_items_date     ON items(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_date_slot ON runs(run_date, slot);
"""


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class KestrelDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(DDL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def start_run(self, run_id: str, slot: str, run_date: str, started_at: datetime,
                  late: bool) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, slot, run_date, started_at, late, status) "
            "VALUES (?, ?, ?, ?, ?, 'running')",
            (run_id, slot, run_date, started_at.isoformat(), int(late)),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, finished_at: datetime, item_count: int,
                   status: str = "ok") -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at=?, item_count=?, status=? WHERE run_id=?",
            (finished_at.isoformat(), item_count, status, run_id),
        )
        self._conn.commit()

    def has_completed_run(self, slot: str, run_date: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM runs WHERE slot=? AND run_date=? AND status IN ('ok','partial')",
            (slot, run_date),
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    def persist_brief(self, brief: Brief, run_id: str) -> None:
        all_items: list[BriefItem] = (
            brief.priority_items
            + brief.policy_items
            + brief.market_items
            + brief.tech_items
        )
        now = datetime.utcnow().isoformat()
        for bi in all_items:
            si = bi.scored
            self._conn.execute(
                """INSERT OR REPLACE INTO items
                   (item_id, run_id, headline, canonical_url, source_name,
                    published_at, section, summary, why_it_matters, kpmg_angle,
                    confidence, rating_total, rating_impact, rating_sentiment,
                    kpmg_tags, domain_tags, escalated, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    si.item_id, run_id, si.title, si.canonical_url, si.source_name,
                    si.published_at.isoformat() if si.published_at else None,
                    bi.section,
                    bi.narrative.what_happened, bi.narrative.why_it_matters,
                    bi.narrative.kpmg_angle, si.confidence,
                    si.rating_total, si.rating_impact, si.rating_sentiment,
                    json.dumps(si.classification.kpmg_tags),
                    json.dumps(si.classification.domain_tags),
                    int(si.escalated), now,
                ),
            )
            for src_name, src_url in si.corroborating_sources:
                self._conn.execute(
                    "INSERT INTO item_sources (item_id, source_name, url) VALUES (?,?,?)",
                    (si.item_id, src_name, src_url),
                )
        self._conn.commit()

    # ------------------------------------------------------------------
    # URL dedup / suppression
    # ------------------------------------------------------------------

    def is_url_seen(self, url: str, suppression_days: int) -> bool:
        h = _url_hash(url)
        row = self._conn.execute(
            "SELECT first_seen FROM url_seen WHERE url_hash=?", (h,)
        ).fetchone()
        if row is None:
            return False
        first = datetime.fromisoformat(row[0])
        age = (datetime.utcnow() - first).days
        return age < suppression_days

    def mark_url_seen(self, url: str, headline: str) -> None:
        h = _url_hash(url)
        self._conn.execute(
            "INSERT OR IGNORE INTO url_seen (url_hash, first_seen, headline) VALUES (?,?,?)",
            (h, datetime.utcnow().isoformat(), headline),
        )
        self._conn.commit()

    def mark_urls_seen_bulk(self, items: list[ScoredItem]) -> None:
        now = datetime.utcnow().isoformat()
        self._conn.executemany(
            "INSERT OR IGNORE INTO url_seen (url_hash, first_seen, headline) VALUES (?,?,?)",
            [(_url_hash(i.canonical_url), now, i.title) for i in items],
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Source health check
    # ------------------------------------------------------------------

    def source_zero_yield_streak(self, source_name: str, current_run_id: str,
                                 previous_run_ids: list[str]) -> int:
        """Return count of consecutive recent runs (including current) with no items from source."""
        check_runs = previous_run_ids[-1:] + [current_run_id]
        streak = 0
        for rid in reversed(check_runs):
            count = self._conn.execute(
                "SELECT COUNT(*) FROM items WHERE run_id=? AND source_name=?",
                (rid, source_name),
            ).fetchone()[0]
            if count == 0:
                streak += 1
            else:
                break
        return streak

    def recent_run_ids(self, slot: str, limit: int = 2) -> list[str]:
        rows = self._conn.execute(
            "SELECT run_id FROM runs WHERE slot=? AND status IN ('ok','partial') "
            "ORDER BY started_at DESC LIMIT ?",
            (slot, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def last_finished_at(self, slot: str) -> Optional[datetime]:
        """Return the finished_at timestamp of the most recent completed run for this slot."""
        row = self._conn.execute(
            "SELECT finished_at FROM runs WHERE slot=? AND status IN ('ok','partial') "
            "AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1",
            (slot,),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])
