"""Collector protocol and shared utilities."""
from __future__ import annotations
from typing import Protocol

from kestrel.models import RawItem, Source, Window


class Collector(Protocol):
    def collect(self, source: Source, window: Window) -> list[RawItem]: ...


def parse_notes_hint(notes: str, key: str) -> str:
    """Extract 'key: value' from the Notes field. Returns '' if not found."""
    import re
    m = re.search(rf"(?i){re.escape(key)}:\s*(.+?)(?:,|$)", notes)
    return m.group(1).strip() if m else ""
