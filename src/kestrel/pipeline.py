"""Orchestrates a full Kestrel run across all 12 stages."""
from __future__ import annotations
import hashlib
import json
import logging
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import zoneinfo
from collections import Counter
from rapidfuzz import fuzz

from kestrel.config import AppConfig, FilterConfig, select_sources
from kestrel.collectors.router import collect_all
from kestrel.models import (
    Brief, BriefItem, Classification, ItemNarrative,
    RawItem, ScoredItem, Source, Taxonomy, Window,
)
from kestrel.render.html import render_html
from kestrel.render.text import render_text
from kestrel.render.subject import make_subject
from kestrel.store.db import KestrelDB
from kestrel.synthesis.anthropic_synth import make_synthesizer

log = logging.getLogger(__name__)

SECTION_LABEL = {
    "policy": "policy",
    "market": "market",
    "tech": "tech",
}

# Named titles, monetary figures, percentages, or 4-digit years indicate a specific, verifiable claim.
# Items without these markers are likely vague commentary and are downgraded to low confidence.
_SPECIFICITY_RE = re.compile(
    r'\b(?:minister|secretary|general|admiral|senator|prime\s+minister|'
    r'CEO|chief\s+executive|director|commissioner|deputy|lieutenant)\b'
    r'|\$[\d,]+(?:\.\d+)?\s*[bBmM]?(?:illion)?\b'
    r'|\b\d[\d,]*\s*(?:million|billion|per\s+cent|percent)\b'
    r'|\b20[2-9]\d\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_sydney(cfg: AppConfig) -> datetime:
    tz = zoneinfo.ZoneInfo(cfg.timezone)
    return datetime.now(tz=tz)


def _slot_scheduled_time(slot: str, cfg: AppConfig) -> datetime:
    tz = zoneinfo.ZoneInfo(cfg.timezone)
    now = datetime.now(tz=tz)
    sched = cfg.schedule.morning if slot == "morning" else cfg.schedule.afternoon
    h, m = map(int, sched.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def _is_late(slot: str, cfg: AppConfig, db: KestrelDB, run_date: str,
             grace_minutes: int = 5) -> bool:
    if db.has_completed_run(slot, run_date):
        return False
    scheduled = _slot_scheduled_time(slot, cfg)
    now = _now_sydney(cfg)
    return now > scheduled + timedelta(minutes=grace_minutes)


def _window(slot: str, cfg: AppConfig, db: KestrelDB) -> Window:
    now = datetime.now(tz=timezone.utc)
    last = db.last_finished_at(slot)
    if last is not None:
        # Anchor to when the previous run completed; ensure it is UTC-aware
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        start = last
    else:
        # First-ever run for this slot — fall back to configured lookback
        hours = cfg.run.lookback_hours.get(slot, 18)
        start = now - timedelta(hours=hours)
    return Window(start=start, end=now)


def _normalise_url(url: str) -> str:
    """Strip tracking params and lowercase scheme/host."""
    url = url.strip()
    # Remove UTM and common tracking params
    url = re.sub(r"[?&](utm_[^&]*|fbclid=[^&]*|gclid=[^&]*)", "", url)
    url = re.sub(r"[?&]$", "", url)
    return url


def _dedupe(items: list[RawItem], threshold: float,
            sources_by_name: dict[str, Source]) -> list[ScoredItem]:
    """Collapse same story across sources, keeping the best canonical."""

    def _canonical_score(src_name: str) -> tuple[int, float, float]:
        src = sources_by_name.get(src_name)
        if src is None:
            return (2, 0.0, 0.0)
        official_rank = 0 if src.official_status.lower() == "official" else 1
        primary_rank = 0 if src.primary_or_secondary.lower() == "primary" else 1
        return (official_rank + primary_rank, -src.trust_score, -src.signal_score)

    groups: list[list[RawItem]] = []

    for item in items:
        url_norm = _normalise_url(item.url)
        placed = False
        for group in groups:
            rep = group[0]
            rep_url = _normalise_url(rep.url)
            if url_norm == rep_url:
                group.append(item)
                placed = True
                break
            ratio = fuzz.token_set_ratio(item.title.lower(), rep.title.lower())
            if ratio >= threshold * 100:
                group.append(item)
                placed = True
                break
        if not placed:
            groups.append([item])

    deduped: list[ScoredItem] = []
    for group in groups:
        # Pick canonical by: official+primary > trust > signal > earliest timestamp
        best = sorted(group, key=lambda i: _canonical_score(i.source_name))[0]
        others = [i for i in group if i is not best]
        corroborating = [(o.source_name, _normalise_url(o.url)) for o in others]

        # Stub item_id — will be enriched later
        deduped.append(ScoredItem(
            item_id=str(uuid.uuid4()),
            title=best.title,
            canonical_url=_normalise_url(best.url),
            source_name=best.source_name,
            published_at=best.published_at,
            snippet=best.snippet,
            classification=Classification([], [], 2.0, 0.0, "policy"),
            rating_total=0.0,
            rating_impact=0.0,
            rating_sentiment=0.0,
            trust_score=sources_by_name.get(best.source_name, Source(
                name="", type="", sector="", adjacent_domain="", active=True,
                url="", linkedin_url="", asx_ticker="", primary_or_secondary="",
                official_status="", trust_score=3.0, signal_score=3.0,
                noise_score=3.0, priority_tier=3, include_morning=True,
                include_afternoon=True, notes="",
            )).trust_score,
            signal_score=sources_by_name.get(best.source_name, Source(
                name="", type="", sector="", adjacent_domain="", active=True,
                url="", linkedin_url="", asx_ticker="", primary_or_secondary="",
                official_status="", trust_score=3.0, signal_score=3.0,
                noise_score=3.0, priority_tier=3, include_morning=True,
                include_afternoon=True, notes="",
            )).signal_score,
            escalated=False,
            confidence="medium",
            corroborating_sources=corroborating,
            raw_meta=best.raw_meta,
        ))

    return deduped


def _check_escalation(item: ScoredItem, rules: list, title_snippet: str) -> bool:
    for rule in rules:
        for kw in rule["keywords"]:
            if kw.lower() in title_snippet.lower():
                return True
    # ASX price-sensitive
    if item.raw_meta.get("price_sensitive"):
        return True
    return False


def _compute_confidence(item: ScoredItem, sources_by_name: dict[str, Source]) -> str:
    src = sources_by_name.get(item.source_name)
    if src and src.official_status.lower() == "official":
        return "high"
    # Corroboration by a high-trust source lifts to high
    for csrc_name, _ in item.corroborating_sources:
        csrc = sources_by_name.get(csrc_name)
        if csrc and csrc.trust_score >= 4:
            return "high"

    base = "medium" if (src and src.trust_score >= 3) else "low"
    if base == "low":
        return "low"

    # Downgrade stale items: published > 36 h ago adds little editorial value
    if item.published_at:
        age_hours = (datetime.now(timezone.utc) - item.published_at).total_seconds() / 3600
        if age_hours > 36:
            return "low"

    # Downgrade vague items: no named person, figure, or year → likely unverifiable commentary
    combined = f"{item.title} {item.snippet or ''}"
    if not _SPECIFICITY_RE.search(combined):
        return "low"

    return "medium"


def _rate(item: ScoredItem, f: FilterConfig) -> ScoredItem:
    boost = f.escalation_boost if item.escalated else 0.0
    total = (
        f.w_impact * item.classification.impact_score
        + f.w_signal * item.signal_score
        + f.w_trust * item.trust_score
        + boost
        + f.w_sentiment * abs(item.classification.kestrel_sentiment)
    )
    item.rating_total = round(total, 3)
    item.rating_impact = round(f.w_impact * item.classification.impact_score, 3)
    item.rating_sentiment = round(f.w_sentiment * item.classification.kestrel_sentiment, 3)
    return item


def _allocate(
    scored: list[ScoredItem],
    f: FilterConfig,
    escalation_rules: list,
) -> tuple[list[ScoredItem], list[ScoredItem], list[ScoredItem], list[ScoredItem]]:
    """Split into priority, policy, market, tech respecting caps and MECE.

    If the rating threshold would produce zero items, falls back to the top-rated
    available items so the brief is never entirely empty.
    """
    above_min = [i for i in scored if i.rating_total >= f.min_rating_to_include]
    if not above_min and scored:
        # Threshold too strict for available content — use top-rated items as fallback
        above_min = sorted(scored, key=lambda i: i.rating_total, reverse=True)[:10]
    ranked = sorted(above_min, key=lambda i: i.rating_total, reverse=True)

    # Priority: escalated first, then highest rated, cap max_priority_items
    priority_candidates = sorted(ranked, key=lambda i: (-int(i.escalated), -i.rating_total))
    priority_items = priority_candidates[:f.max_priority_items]

    # Remaining items for body (not already in priority)
    priority_ids = {i.item_id for i in priority_items}
    body_pool = [i for i in ranked if i.item_id not in priority_ids]

    policy, market, tech = [], [], []
    body_total = 0
    for item in body_pool:
        if body_total >= f.max_body_headlines_total:
            break
        sec = item.classification.primary_section
        if sec == "policy" and len(policy) < f.max_per_body_subsection:
            policy.append(item)
            body_total += 1
        elif sec == "market" and len(market) < f.max_per_body_subsection:
            market.append(item)
            body_total += 1
        elif sec == "tech" and len(tech) < f.max_per_body_subsection:
            tech.append(item)
            body_total += 1
        # else: section cap reached — drop item to preserve MECE integrity

    return priority_items, policy, market, tech


def _make_digest_md(
    slot: str, run_date: str, scored: list[ScoredItem], linkedin: list[str],
    all_classified: list[ScoredItem] | None = None,
) -> str:
    display = all_classified if all_classified else scored
    lines = [
        f"# Kestrel {slot.title()} Brief — {run_date}",
        f"_Generated in fallback mode. Paste the KPMG angle and Top Line into the HTML._\n",
        f"## Collected and classified items ({len(display)} total, ranked by rating)\n",
    ]
    for i, item in enumerate(display, 1):
        lines.append(f"### {i}. {item.title}")
        lines.append(f"- **Source:** {item.source_name}  |  **Rating:** {item.rating_total:.2f}")
        lines.append(f"- **URL:** {item.canonical_url}")
        lines.append(f"- **Confidence:** {item.confidence}  |  **Escalated:** {item.escalated}")
        lines.append(f"- **Kestrel tags:** {', '.join(item.classification.kestrel_tags) or '—'}")
        lines.append(f"- **Domain tags:** {', '.join(item.classification.domain_tags) or '—'}")
        if item.snippet:
            lines.append(f"- **Snippet:** {item.snippet[:200]}")
        if item.corroborating_sources:
            corr = ", ".join(f"{n} ({u})" for n, u in item.corroborating_sources)
            lines.append(f"- **Also covered by:** {corr}")
        lines.append("")
    if linkedin:
        lines.append("## LinkedIn sources (manual check suggested)")
        for name in linkedin:
            lines.append(f"- {name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quote selection
# ---------------------------------------------------------------------------

# Maps domain/section labels → quote theme bucket
_DOMAIN_TO_THEME = {
    "maritime": "maritime",
    "naval": "maritime",
    "submarine": "maritime",
    "space": "technology",
    "cyber": "technology",
    "emerging technology": "technology",
    "land": "general",
    "air": "general",
    "intelligence": "intelligence",
    "isr": "intelligence",
    "signals": "intelligence",
    "aukus": "alliances",
    "alliance": "alliances",
    "coalition": "alliances",
    "five eyes": "alliances",
    "industry": "industry",
    "procurement": "industry",
    "acquisition": "industry",
    "supply chain": "logistics",
    "logistics": "logistics",
    "sustainment": "logistics",
    "deterrence": "deterrence",
    "nuclear": "deterrence",
    "policy": "strategy",
    "strategy": "strategy",
    "market": "industry",
    "tech": "technology",
}


def _dominant_quote_theme(items: list[ScoredItem]) -> str:
    """Return the quote theme that best matches the dominant content of a set of items."""
    counts: Counter = Counter()
    for item in items:
        for tag in item.classification.domain_tags:
            theme = _DOMAIN_TO_THEME.get(tag.lower())
            if theme:
                counts[theme] += 2          # domain tags weighted higher
        section_theme = _DOMAIN_TO_THEME.get(item.classification.primary_section)
        if section_theme:
            counts[section_theme] += 1
    if not counts:
        return "general"
    return counts.most_common(1)[0][0]


def _pick_quote(quotes: list[dict], items: list[ScoredItem]) -> tuple[str, str]:
    """Choose a random quote whose theme matches the dominant content, with fallback."""
    if not quotes:
        return ("", "")
    theme = _dominant_quote_theme(items)
    themed = [q for q in quotes if q.get("theme", "general") == theme]
    pool = themed if len(themed) >= 3 else quotes   # fall back to full pool if thin
    q = random.choice(pool)
    return (q["quote"], q["author"])


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(slot: str, cfg: AppConfig, db: KestrelDB) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    tz = zoneinfo.ZoneInfo(cfg.timezone)
    started_at = datetime.now(tz=tz)
    run_date = started_at.strftime("%Y-%m-%d")
    timings: dict[str, float] = {}

    late = _is_late(slot, cfg, db, run_date)
    db.start_run(run_id, slot, run_date, started_at, late)

    synth = make_synthesizer(
        cfg.synthesis.provider, cfg.synthesis.model,
        cfg.synthesis.max_retries, cfg.project_root,
    )
    style = _load_style(cfg)
    taxonomy = cfg.taxonomy

    # ── Stage 1 + 2: load config + select sources ──────────────────────────
    t0 = time.time()
    selected_sources = select_sources(cfg, slot)
    log.info("Stage 2: %d sources selected for slot=%s", len(selected_sources), slot)
    timings["select_sources"] = time.time() - t0

    sources_by_name: dict[str, Source] = {s.name: s for s in cfg.sources}

    # ── Stage 3: collect ────────────────────────────────────────────────────
    t0 = time.time()
    from kestrel.collectors.page_cache import init_cache
    init_cache(cfg.paths.data_dir / "page_cache.db")

    window = _window(slot, cfg, db)
    global_deadline = datetime.now(tz=timezone.utc) + timedelta(
        seconds=cfg.run.global_time_budget_seconds
    )
    raw_items, zero_yield, linkedin = collect_all(
        selected_sources, window, cfg.run.per_source_timeout_seconds, global_deadline
    )
    log.info("Stage 3: collected %d raw items", len(raw_items))
    timings["collect"] = time.time() - t0

    # ── Stage 4: normalise + window filter ──────────────────────────────────
    t0 = time.time()
    windowed: list[RawItem] = []
    for item in raw_items:
        item.url = _normalise_url(item.url)
        item.title = re.sub(r"\s+", " ", item.title).strip()
        if item.published_at and item.published_at < window.start:
            continue
        windowed.append(item)
    log.info("Stage 4: %d items after window filter", len(windowed))
    timings["normalise"] = time.time() - t0

    # ── Stage 5: dedupe ─────────────────────────────────────────────────────
    t0 = time.time()
    threshold = cfg.filters.title_similarity_threshold
    deduped = _dedupe(windowed, threshold, sources_by_name)
    log.info("Stage 5: %d items after dedupe", len(deduped))
    timings["dedupe"] = time.time() - t0

    # ── Stage 6: URL suppression + confidence ───────────────────────────────
    t0 = time.time()
    suppressed = []
    for item in deduped:
        if db.is_url_seen(item.canonical_url, cfg.run.shipped_suppression_days):
            log.debug("Suppressed (already shipped): %s", item.title[:60])
            continue
        item.confidence = _compute_confidence(item, sources_by_name)
        suppressed.append(item)
    log.info("Stage 6: %d items after URL suppression", len(suppressed))
    timings["suppress"] = time.time() - t0

    # ── Stage 7: classify + escalation + rate ───────────────────────────────
    t0 = time.time()
    escalation_dicts = [
        {"keywords": r.keywords} for r in cfg.escalation_rules
    ]
    classified: list[ScoredItem] = []
    for item in suppressed:
        raw = RawItem(
            title=item.title, url=item.canonical_url,
            source_name=item.source_name, published_at=item.published_at,
            snippet=item.snippet, raw_meta=item.raw_meta,
        )
        item.classification = synth.classify(raw, taxonomy)
        combined = f"{item.title} {item.snippet}"
        item.escalated = _check_escalation(item, escalation_dicts, combined)
        item = _rate(item, cfg.filters)
        classified.append(item)
    log.info("Stage 7: classified %d items", len(classified))
    timings["classify"] = time.time() - t0

    # Enforce: low-confidence non-official item cannot lead
    classified = _enforce_confidence_order(classified, sources_by_name)

    # ── Stage 8: allocate ────────────────────────────────────────────────────
    t0 = time.time()
    priority_scored, policy_scored, market_scored, tech_scored = _allocate(
        classified, cfg.filters, escalation_dicts
    )
    log.info("Stage 8: priority=%d policy=%d market=%d tech=%d",
             len(priority_scored), len(policy_scored), len(market_scored), len(tech_scored))
    timings["allocate"] = time.time() - t0

    all_selected = priority_scored + policy_scored + market_scored + tech_scored

    # ── Stage 9: synthesise ──────────────────────────────────────────────────
    t0 = time.time()
    top_line = synth.top_line(priority_scored + policy_scored, style,
                               cfg.audience.top_line_max_words)
    watchpoints_bullets = synth.watchpoints(all_selected, style)

    quote = _pick_quote(cfg.quotes, priority_scored + policy_scored)

    def _enrich_priority(items: list[ScoredItem]) -> list[BriefItem]:
        return [BriefItem(scored=i, narrative=synth.enrich_item(i, style), section="")
                for i in items]

    def _body_items(items: list[ScoredItem]) -> list[BriefItem]:
        return [BriefItem(
            scored=i,
            narrative=ItemNarrative(
                what_happened=i.snippet or i.title,
                why_it_matters="",
                kestrel_angle="",
            ),
            section="",
        ) for i in items]

    priority_items = _enrich_priority(priority_scored)
    policy_items = _body_items(policy_scored)
    market_items = _body_items(market_scored)
    tech_items = _body_items(tech_scored)

    for bi in priority_items:
        bi.section = "priority"
    for bi in policy_items:
        bi.section = "policy"
    for bi in market_items:
        bi.section = "market"
    for bi in tech_items:
        bi.section = "tech"

    digest_md = _make_digest_md(slot, run_date, all_selected, linkedin,
                               all_classified=classified)
    log.info("Stage 9: synthesis complete")
    timings["synthesise"] = time.time() - t0

    # ── Stage 10: render ─────────────────────────────────────────────────────
    t0 = time.time()
    subject = make_subject(slot, started_at, cfg.timezone)
    brief = Brief(
        slot=slot,
        run_date=run_date,
        is_late=late,
        generated_at=started_at,
        top_line=top_line,
        quote=quote,
        priority_items=priority_items,
        policy_items=policy_items,
        market_items=market_items,
        tech_items=tech_items,
        watchpoints=watchpoints_bullets,
        digest_md=digest_md,
        subject=subject,
    )
    html_content = render_html(brief, cfg.paths.assets_dir, cfg.brief.theme, cfg.project_root)
    txt_content = render_text(brief)
    log.info("Stage 10: render complete")
    timings["render"] = time.time() - t0

    # ── Stage 11: persist ────────────────────────────────────────────────────
    t0 = time.time()
    out_dir = cfg.paths.output_dir / run_date
    out_dir.mkdir(parents=True, exist_ok=True)

    base = f"kestrel_{slot}_{run_date}"
    html_path = out_dir / f"{base}.html"
    txt_path = out_dir / f"{base}.txt"
    digest_path = out_dir / f"{base}.digest.md"
    subject_path = out_dir / f"{base}.subject.txt"

    html_path.write_text(html_content, encoding="utf-8")
    txt_path.write_text(txt_content, encoding="utf-8")
    digest_path.write_text(digest_md, encoding="utf-8")
    subject_path.write_text(subject, encoding="utf-8")

    # Needs-attention sources (zero yield)
    needs_attention = _check_zero_yield(zero_yield, slot, db, run_id)

    run_json: dict[str, Any] = {
        "run_id": run_id,
        "slot": slot,
        "run_date": run_date,
        "late": late,
        "started_at": started_at.isoformat(),
        "timings": timings,
        "counts": {
            "raw": len(raw_items),
            "windowed": len(windowed),
            "deduped": len(deduped),
            "classified": len(classified),
            "priority": len(priority_items),
            "policy": len(policy_items),
            "market": len(market_items),
            "tech": len(tech_items),
        },
        "zero_yield_sources": zero_yield,
        "needs_attention": needs_attention,
        "linkedin_manual_check": linkedin,
        "html_path": str(html_path.resolve()),
        "txt_path": str(txt_path.resolve()),
        "digest_path": str(digest_path.resolve()),
    }
    run_json_path = out_dir / f"{base}.run.json"
    run_json_path.write_text(json.dumps(run_json, indent=2), encoding="utf-8")

    db.mark_urls_seen_bulk(all_selected)
    db.persist_brief(brief, run_id)

    finished_at = datetime.now(tz=tz)
    item_count = len(all_selected)
    db.finish_run(run_id, finished_at, item_count, "ok")
    timings["persist"] = time.time() - t0

    # ── Stage 12: notify operator ─────────────────────────────────────────────
    _print_summary(run_json, html_path, linkedin, needs_attention)
    return run_json


# ---------------------------------------------------------------------------
# Supporting functions
# ---------------------------------------------------------------------------

def _load_style(cfg: AppConfig) -> str:
    p = cfg.project_root / "config" / "writing_style.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _enforce_confidence_order(items: list[ScoredItem],
                               sources_by_name: dict[str, Source]) -> list[ScoredItem]:
    """Push low-confidence non-official items below the fold."""
    def _sort_key(i: ScoredItem) -> tuple:
        is_official = sources_by_name.get(i.source_name, Source(
            name="", type="", sector="", adjacent_domain="", active=True,
            url="", linkedin_url="", asx_ticker="", primary_or_secondary="",
            official_status="independent", trust_score=3.0, signal_score=3.0,
            noise_score=3.0, priority_tier=3, include_morning=True,
            include_afternoon=True, notes="",
        )).official_status.lower() == "official"
        conf_rank = {"high": 0, "medium": 1, "low": 2}.get(i.confidence, 1)
        return (conf_rank if not is_official else 0, -i.rating_total)

    return sorted(items, key=_sort_key)


def _check_zero_yield(zero_yield: list[str], slot: str, db: KestrelDB,
                      current_run_id: str) -> list[str]:
    prev_runs = db.recent_run_ids(slot, limit=2)
    needs = []
    for src_name in zero_yield:
        streak = db.source_zero_yield_streak(src_name, current_run_id, prev_runs)
        if streak >= 2:
            needs.append(src_name)
    return needs


def _print_summary(run_json: dict, html_path: Path,
                   linkedin: list[str], needs_attention: list[str]) -> None:
    counts = run_json["counts"]
    print("\n" + "=" * 60)
    print(f"  KESTREL {run_json['slot'].upper()} BRIEF — {run_json['run_date']}")
    if run_json.get("late"):
        print("  *** LATE RUN ***")
    print(f"  Items: {counts['raw']} collected → {counts['deduped']} deduped "
          f"→ {counts['priority']+counts['policy']+counts['market']+counts['tech']} selected")
    print(f"  Priority: {counts['priority']}  |  "
          f"Policy: {counts['policy']}  Market: {counts['market']}  Tech: {counts['tech']}")
    print(f"\n  HTML: {html_path}")
    if needs_attention:
        print(f"\n  SOURCES NEEDING ATTENTION (zero yield x2):")
        for s in needs_attention:
            print(f"    ⚠  {s}")
    if linkedin:
        print(f"\n  LINKEDIN (manual check suggested):")
        for s in linkedin:
            print(f"    •  {s}")
    print("=" * 60 + "\n")
