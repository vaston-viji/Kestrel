"""Tests for fallback rendering — file outputs and HTML self-containment."""
from __future__ import annotations
import base64
import re
from datetime import datetime, timezone
from pathlib import Path
import uuid

import pytest

from kestrel.models import (
    Brief, BriefItem, Classification, ItemNarrative, ScoredItem,
)
from kestrel.render.html import render_html
from kestrel.render.text import render_text
from kestrel.render.subject import make_subject


def _make_scored(title: str = "Test headline") -> ScoredItem:
    return ScoredItem(
        item_id=str(uuid.uuid4()),
        title=title,
        canonical_url="https://defence.gov.au/news/1",
        source_name="DoD AU",
        published_at=datetime.now(tz=timezone.utc),
        snippet="A test snippet about Australian defence.",
        classification=Classification(
            kpmg_tags=["Strategy"], domain_tags=["AUKUS"],
            impact_score=4.0, kpmg_sentiment=0.5, primary_section="policy",
        ),
        rating_total=4.2, rating_impact=1.6, rating_sentiment=0.1,
        trust_score=5.0, signal_score=5.0, escalated=False, confidence="high",
    )


def _make_brief(is_late: bool = False) -> Brief:
    scored = _make_scored()
    bi = BriefItem(
        scored=scored,
        narrative=ItemNarrative(
            what_happened="Defence confirmed new program.",
            why_it_matters="[[PASTE FROM CLAUDE]]",
            kpmg_angle="[[PASTE FROM CLAUDE]]",
        ),
        section="priority",
    )
    return Brief(
        slot="morning",
        run_date="2026-06-17",
        is_late=is_late,
        generated_at=datetime.now(tz=timezone.utc),
        top_line=["- **DoD AU** — confirmed new program", "- **AUKUS** — submarine milestone"],
        quote=("In preparing for battle I have always found that plans are useless, "
               "but planning is indispensable.", "Dwight D. Eisenhower"),
        priority_items=[bi],
        policy_items=[],
        market_items=[],
        tech_items=[],
        watchpoints=["- Watch for follow-on announcements from Defence."],
        digest_md="# Digest placeholder",
        subject="D&DI Morning Brief Tue 17-Jun-26 [Kestrel]",
    )


def test_subject_line_format():
    dt = datetime(2026, 6, 17, 7, 0, tzinfo=timezone.utc)
    subject = make_subject("morning", dt)
    assert "Morning Brief" in subject
    assert "Kestrel" in subject
    assert "17-Jun-26" in subject


def test_subject_afternoon():
    dt = datetime(2026, 6, 17, 11, 30, tzinfo=timezone.utc)
    subject = make_subject("afternoon", dt)
    assert "Afternoon Brief" in subject


def test_html_render_produces_content(tmp_path):
    brief = _make_brief()
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    html = render_html(brief, assets_dir, "light", tmp_path)
    assert "<!DOCTYPE html>" in html
    assert "KESTREL" in html.upper() or "kestrel" in html.lower()
    assert "DoD AU" in html
    assert "PASTE FROM CLAUDE" in html


def test_html_is_self_contained_when_assets_present(tmp_path):
    """With a real PNG present, the HTML should embed base64."""
    brief = _make_brief()
    assets_dir = tmp_path / "assets"
    brand_dir = assets_dir / "brand" / "kestrel_brand_pack" / "headers" / "light"
    brand_dir.mkdir(parents=True)
    # Write a minimal 1×1 PNG
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    (brand_dir / "kestrel_email_header_1200x300_light.png").write_bytes(tiny_png)

    html = render_html(brief, assets_dir, "light", tmp_path)
    assert "data:image/png;base64," in html
    # Must not reference external image files
    assert 'src="http' not in html


def test_html_late_run_shows_marker(tmp_path):
    brief = _make_brief(is_late=True)
    html = render_html(brief, tmp_path / "assets", "light", tmp_path)
    assert "LATE RUN" in html


def test_text_render_contains_all_sections():
    brief = _make_brief()
    txt = render_text(brief)
    assert "TOP LINE" in txt
    assert "PRIORITY DEVELOPMENTS" in txt
    assert "WATCHPOINTS" in txt
    assert "viji.john@quantrim.com" in txt
    assert "Errors & Omissions Expected" in txt


def test_text_render_late_marker():
    brief = _make_brief(is_late=True)
    txt = render_text(brief)
    assert "LATE RUN" in txt


def test_confidence_marker_visible():
    brief = _make_brief()
    # Give the item low confidence
    brief.priority_items[0].scored.confidence = "low"
    html = render_html(brief, Path("/nonexistent"), "light", Path("/nonexistent"))
    assert "LOW CONFIDENCE" in html.upper() or "low confidence" in html.lower()
