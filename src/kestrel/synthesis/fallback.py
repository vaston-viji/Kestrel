"""FallbackSynthesizer — no model calls; keyword-based classify; digest.md output."""
from __future__ import annotations
import re

from kestrel.models import Classification, ItemNarrative, RawItem, ScoredItem, Taxonomy

# ---------------------------------------------------------------------------
# Domain → section mapping
# ---------------------------------------------------------------------------
_SECTION_KEYWORDS: dict[str, list[str]] = {
    "tech": [
        "cyber", "AI", "artificial intelligence", "quantum", "space", "satellite",
        "software", "algorithm", "autonomous", "drone", "UAS", "UAV", "sensor",
        "semiconductor", "dual-use", "technology", "digital", "radar", "electronic",
    ],
    "market": [
        "contract", "deal", "acquisition", "tender", "awarded", "ASX", "market",
        "listing", "shares", "revenue", "billion", "million", "procurement",
        "supplier", "industry", "company", "firm", "enterprise", "partnership",
    ],
}

_KPMG_KEYWORDS: dict[str, list[str]] = {
    "Cyber": ["cyber", "security", "breach", "vulnerability", "hack", "incident"],
    "Workforce": ["workforce", "hiring", "recruitment", "training", "personnel", "staff"],
    "Deals": ["contract", "deal", "acquisition", "merger", "awarded", "tender", "procurement"],
    "Estate": ["base", "facility", "precinct", "property", "construction", "infrastructure"],
    "Strategy": ["strategy", "strategic", "posture", "policy", "doctrine", "plan"],
    "Operating Model": ["transformation", "reform", "restructure", "model", "operating"],
    "Assurance": ["audit", "review", "compliance", "assurance", "risk"],
    "Customer & Operations": ["operations", "logistics", "supply chain", "maintenance"],
}

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "AUKUS": ["AUKUS", "SSN", "Virginia", "submarine", "Pillar I", "Pillar II"],
    "Maritime": ["maritime", "naval", "navy", "ship", "frigate", "destroyer", "submarine", "patrol"],
    "Land": ["land", "army", "vehicle", "armoured", "soldier", "protected mobility"],
    "Air": ["air force", "RAAF", "aircraft", "F-35", "aviation", "UAV", "drone", "helicopter"],
    "Space": ["space", "satellite", "orbit", "launch", "space domain"],
    "Cyber": ["cyber", "hack", "breach", "malware", "vulnerability", "threat actor"],
    "GWEO": ["GWEO", "guided weapons", "munitions", "missile", "rocket", "Enterprise"],
    "Counter-drone": ["counter-drone", "counter-UAS", "c-UAS", "drone defeat", "anti-drone"],
    "Critical Minerals": ["critical minerals", "lithium", "rare earth", "cobalt", "titanium"],
}


def _match_keywords(text: str, keyword_map: dict[str, list[str]]) -> list[str]:
    text_lower = text.lower()
    return [tag for tag, kws in keyword_map.items()
            if any(kw.lower() in text_lower for kw in kws)]


def _classify_section(text: str) -> str:
    for section in ("tech", "market"):
        kws = _SECTION_KEYWORDS[section]
        if any(k.lower() in text.lower() for k in kws):
            return section
    return "policy"


def _estimate_impact(text: str, escalated: bool) -> float:
    score = 2.0
    if escalated:
        score += 1.5
    high_kws = ["AUKUS", "billion", "submarine", "GWEO", "force posture",
                 "Indo-Pacific", "Taiwan", "northern basing", "price sensitive"]
    mid_kws = ["contract", "partnership", "acquisition", "minister", "announced"]
    for kw in high_kws:
        if kw.lower() in text.lower():
            score += 0.5
    for kw in mid_kws:
        if kw.lower() in text.lower():
            score += 0.25
    return min(score, 5.0)


def _estimate_sentiment(text: str) -> float:
    pos = ["awarded", "partnership", "investment", "opportunity", "capability", "expansion"]
    neg = ["risk", "threat", "breach", "delay", "concern", "vulnerability", "cancelled"]
    s = sum(0.5 for p in pos if p in text.lower())
    s -= sum(0.5 for n in neg if n in text.lower())
    return max(-2.0, min(2.0, s))


class FallbackSynthesizer:
    """Deterministic synthesizer — works with no API key."""

    def classify(self, item: RawItem, taxonomy: Taxonomy) -> Classification:
        combined = f"{item.title} {item.snippet}"
        kpmg_tags = _match_keywords(combined, _KPMG_KEYWORDS)
        domain_tags = _match_keywords(combined, _DOMAIN_KEYWORDS)
        # Filter to only configured tags
        kpmg_tags = [t for t in kpmg_tags if t in taxonomy.kpmg_tags]
        domain_tags = [t for t in domain_tags if t in taxonomy.domain_tags]
        section = _classify_section(combined)
        # rough escalation for impact estimation
        escalation_kws = ["AUKUS", "GWEO", "counter-drone", "force posture",
                          "northern basing", "Indo-Pacific", "price sensitive"]
        escalated = any(k.lower() in combined.lower() for k in escalation_kws)
        impact = _estimate_impact(combined, escalated)
        sentiment = _estimate_sentiment(combined)
        return Classification(
            kpmg_tags=kpmg_tags or ["Strategy"],
            domain_tags=domain_tags,
            impact_score=round(impact, 1),
            kpmg_sentiment=round(sentiment, 1),
            primary_section=section,
        )

    def top_line(self, items: list[ScoredItem], style: str, max_words: int) -> list[str]:
        bullets = []
        for item in items[:5]:
            entity = re.split(r"\s+(?:says|announces|confirms|reports|launches)", item.title)[0]
            bullet = f"<b>{entity.strip()}</b> — {item.title}"
            bullets.append(f"- {bullet}")
        return bullets

    def enrich_item(self, item: ScoredItem, style: str) -> ItemNarrative:
        return ItemNarrative(
            what_happened=item.snippet or item.title,
            why_it_matters="[[PASTE FROM CLAUDE — why does this matter for Australian Defence?]]",
            kpmg_angle="[[PASTE FROM CLAUDE — what is the KPMG client conversation here?]]",
        )

    def watchpoints(self, items: list[ScoredItem], style: str) -> list[str]:
        bullets = []
        domains_seen: set[str] = set()
        for item in items:
            for tag in item.classification.domain_tags:
                if tag not in domains_seen:
                    domains_seen.add(tag)
                    bullets.append(f"- Watch for developments in {tag} capability as today's signals mature.")
                    if len(bullets) >= 5:
                        return bullets
        if len(bullets) < 3:
            bullets.append("- Monitor official releases from Defence and the Minister's office for follow-on announcements.")
        return bullets[:5]
