"""Tests for MECE section allocation."""
from __future__ import annotations
import uuid
from kestrel.models import Classification, ScoredItem
from kestrel.config import FilterConfig
from kestrel.pipeline import _allocate


def _item(section: str, rating: float, escalated: bool = False) -> ScoredItem:
    return ScoredItem(
        item_id=str(uuid.uuid4()),
        title=f"Item {rating}",
        canonical_url=f"https://example.com/{uuid.uuid4()}",
        source_name="Test",
        published_at=None,
        snippet="",
        classification=Classification(
            kpmg_tags=[], domain_tags=[],
            impact_score=3.0, kpmg_sentiment=0.0, primary_section=section,
        ),
        rating_total=rating, rating_impact=0.0, rating_sentiment=0.0,
        trust_score=3.0, signal_score=3.0, escalated=escalated,
        confidence="medium",
    )


_f = FilterConfig(min_rating_to_include=0.0)  # no floor for testing
_escalation_rules: list = []


def test_items_appear_in_exactly_one_section():
    items = (
        [_item("policy", 4.0) for _ in range(3)]
        + [_item("market", 3.5) for _ in range(3)]
        + [_item("tech", 3.0) for _ in range(3)]
    )
    priority, policy, market, tech = _allocate(items, _f, _escalation_rules)
    all_ids = (
        [i.item_id for i in priority]
        + [i.item_id for i in policy]
        + [i.item_id for i in market]
        + [i.item_id for i in tech]
    )
    assert len(all_ids) == len(set(all_ids)), "Duplicate item across sections"


def test_escalated_items_go_to_priority_first():
    items = [_item("policy", 3.0, escalated=True)] + [_item("market", 5.0, escalated=False)] * 3
    priority, policy, market, tech = _allocate(items, _f, _escalation_rules)
    priority_ids = {i.item_id for i in priority}
    escalated_ids = {i.item_id for i in items if i.escalated}
    assert escalated_ids.issubset(priority_ids)


def test_body_section_cap_respected():
    f = FilterConfig(min_rating_to_include=0.0, max_per_body_subsection=3,
                     max_body_headlines_total=9, max_priority_items=0)
    items = [_item("policy", 4.0)] * 10
    priority, policy, market, tech = _allocate(items, f, _escalation_rules)
    assert len(policy) <= 3


def test_min_rating_filter():
    f = FilterConfig(min_rating_to_include=3.0, max_priority_items=7)
    items = [_item("policy", 4.0), _item("market", 1.0), _item("tech", 2.0)]
    priority, policy, market, tech = _allocate(items, f, _escalation_rules)
    all_items = priority + policy + market + tech
    for i in all_items:
        assert i.rating_total >= 3.0
