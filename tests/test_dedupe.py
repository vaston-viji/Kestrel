"""Tests for deduplication logic."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from kestrel.models import RawItem, Source
from kestrel.pipeline import _dedupe


def _raw(title: str, url: str, source: str = "Test") -> RawItem:
    return RawItem(title=title, url=url, source_name=source,
                   published_at=datetime.now(tz=timezone.utc), snippet="", raw_meta={})


def _src(name: str, official: str = "Independent", trust: float = 3.0) -> Source:
    return Source(
        name=name, type="Media", sector="Defence", adjacent_domain="",
        active=True, url="", linkedin_url="", asx_ticker="",
        primary_or_secondary="Primary" if official == "Official" else "Secondary",
        official_status=official, trust_score=trust, signal_score=trust,
        noise_score=2.0, priority_tier=2, include_morning=True, include_afternoon=True,
        notes="",
    )


def test_exact_url_dedupe():
    items = [
        _raw("AUKUS deal signed", "https://example.com/aukus", "Reuters"),
        _raw("AUKUS deal confirmed", "https://example.com/aukus", "ABC"),
    ]
    sources = {"Reuters": _src("Reuters"), "ABC": _src("ABC")}
    result = _dedupe(items, 0.82, sources)
    assert len(result) == 1


def test_title_similarity_dedupe():
    items = [
        _raw("Australia signs major AUKUS submarine deal with US", "https://a.com/1", "ABC"),
        _raw("Australia signs AUKUS submarine deal with United States", "https://b.com/2", "Reuters"),
    ]
    sources = {"ABC": _src("ABC"), "Reuters": _src("Reuters")}
    result = _dedupe(items, 0.82, sources)
    assert len(result) == 1
    # Should have corroborating source
    assert len(result[0].corroborating_sources) == 1


def test_different_stories_not_deduped():
    items = [
        _raw("AUKUS submarine deal confirmed", "https://a.com/1", "ABC"),
        _raw("Defence budget increased by $10 billion", "https://b.com/2", "Reuters"),
    ]
    sources = {"ABC": _src("ABC"), "Reuters": _src("Reuters")}
    result = _dedupe(items, 0.82, sources)
    assert len(result) == 2


def test_official_preferred_as_canonical():
    items = [
        _raw("Defence Minister announces new base", "https://media.com/1", "The Australian"),
        _raw("Defence Minister announces new base", "https://defence.gov.au/1", "DoD"),
    ]
    sources = {
        "The Australian": _src("The Australian", "Independent", 4.0),
        "DoD": _src("DoD", "Official", 5.0),
    }
    result = _dedupe(items, 0.82, sources)
    assert len(result) == 1
    assert result[0].source_name == "DoD"
    assert result[0].canonical_url == "https://defence.gov.au/1"


def test_higher_trust_preferred_when_no_official():
    items = [
        _raw("New frigates ordered", "https://low.com/1", "Trade Rag"),
        _raw("New frigates ordered for RAN", "https://high.com/2", "ASPI"),
    ]
    sources = {
        "Trade Rag": _src("Trade Rag", "Independent", 2.0),
        "ASPI": _src("ASPI", "Independent", 4.0),
    }
    result = _dedupe(items, 0.82, sources)
    assert len(result) == 1
    assert result[0].source_name == "ASPI"
