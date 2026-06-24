"""Tests for rating calculation and ordering."""
from __future__ import annotations
import uuid
from kestrel.models import Classification, ScoredItem
from kestrel.config import FilterConfig
from kestrel.pipeline import _rate


def _item(impact: float, trust: float, signal: float,
          sentiment: float, escalated: bool) -> ScoredItem:
    return ScoredItem(
        item_id=str(uuid.uuid4()),
        title="Test item",
        canonical_url="https://example.com",
        source_name="Test",
        published_at=None,
        snippet="",
        classification=Classification(
            kestrel_tags=[], domain_tags=[],
            impact_score=impact, kestrel_sentiment=sentiment, primary_section="policy",
        ),
        rating_total=0.0, rating_impact=0.0, rating_sentiment=0.0,
        trust_score=trust, signal_score=signal, escalated=escalated,
        confidence="medium",
    )


_f = FilterConfig()


def test_basic_rating():
    item = _item(impact=4.0, trust=4.0, signal=4.0, sentiment=1.0, escalated=False)
    rated = _rate(item, _f)
    # 0.4*4 + 0.2*4 + 0.2*4 + 0 + 0.2*1 = 1.6+0.8+0.8+0.2 = 3.4
    assert abs(rated.rating_total - 3.4) < 0.01


def test_escalation_boost():
    item_no_boost = _item(3.0, 3.0, 3.0, 0.0, False)
    item_boost = _item(3.0, 3.0, 3.0, 0.0, True)
    _rate(item_no_boost, _f)
    _rate(item_boost, _f)
    assert item_boost.rating_total == item_no_boost.rating_total + _f.escalation_boost


def test_negative_sentiment_still_contributes():
    """High-magnitude negative sentiment (major risk) should boost rating_total."""
    item_neut = _item(3.0, 3.0, 3.0, 0.0, False)
    item_neg = _item(3.0, 3.0, 3.0, -2.0, False)
    _rate(item_neut, _f)
    _rate(item_neg, _f)
    # abs(-2.0) > 0 so rating_total should be higher
    assert item_neg.rating_total > item_neut.rating_total


def test_ordering_by_rating():
    items = [
        _item(2.0, 2.0, 2.0, 0.0, False),
        _item(5.0, 5.0, 5.0, 2.0, True),
        _item(3.0, 3.0, 3.0, 1.0, False),
    ]
    for i in items:
        _rate(i, _f)
    ranked = sorted(items, key=lambda x: x.rating_total, reverse=True)
    assert ranked[0].classification.impact_score == 5.0
    assert ranked[-1].classification.impact_score == 2.0
