from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Source:
    name: str
    type: str
    sector: str
    adjacent_domain: str
    active: bool
    url: str
    linkedin_url: str
    asx_ticker: str
    primary_or_secondary: str
    official_status: str
    trust_score: float
    signal_score: float
    noise_score: float
    priority_tier: int
    include_morning: bool
    include_afternoon: bool
    notes: str
    country: str = ""
    hq_state: str = ""


@dataclass
class Window:
    start: datetime
    end: datetime


@dataclass
class RawItem:
    title: str
    url: str
    source_name: str
    published_at: Optional[datetime]
    snippet: str
    raw_meta: dict = field(default_factory=dict)


@dataclass
class Classification:
    kpmg_tags: list[str]
    domain_tags: list[str]
    impact_score: float          # 1–5
    kpmg_sentiment: float        # -2..+2
    primary_section: str         # 'policy' | 'market' | 'tech'


@dataclass
class Taxonomy:
    kpmg_tags: list[str]
    domain_tags: list[str]


@dataclass
class ItemNarrative:
    what_happened: str
    why_it_matters: str
    kpmg_angle: str


@dataclass
class ScoredItem:
    item_id: str
    title: str
    canonical_url: str
    source_name: str
    published_at: Optional[datetime]
    snippet: str
    classification: Classification
    rating_total: float
    rating_impact: float
    rating_sentiment: float
    trust_score: float
    signal_score: float
    escalated: bool
    confidence: str              # 'high' | 'medium' | 'low'
    corroborating_sources: list[tuple[str, str]] = field(default_factory=list)
    raw_meta: dict = field(default_factory=dict)


@dataclass
class BriefItem:
    scored: ScoredItem
    narrative: ItemNarrative
    section: str                 # email section this item lands in


@dataclass
class Brief:
    slot: str                    # 'morning' | 'afternoon'
    run_date: str                # ISO date string
    is_late: bool
    generated_at: datetime
    top_line: list[str]          # bullet strings
    quote: tuple[str, str]       # (text, author)
    priority_items: list[BriefItem]
    policy_items: list[BriefItem]
    market_items: list[BriefItem]
    tech_items: list[BriefItem]
    watchpoints: list[str]       # bullet strings
    digest_md: str               # structured digest for fallback / paste-in
    subject: str
