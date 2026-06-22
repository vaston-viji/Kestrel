"""Plain-text rendering of a Brief."""
from __future__ import annotations
from kestrel.models import Brief, BriefItem

_SEP = "=" * 72
_DIV = "-" * 72


def _item_block(bi: BriefItem) -> str:
    lines = [
        f"  {bi.scored.title}",
        f"  Source: {bi.scored.source_name}",
        f"  URL: {bi.scored.canonical_url}",
    ]
    if bi.scored.confidence in ("low", "medium"):
        lines.append(f"  Confidence: {bi.scored.confidence.upper()}")
    return "\n".join(lines)


def render_text(brief: Brief) -> str:
    parts = []
    parts.append(_SEP)
    parts.append(f"{brief.subject}")
    if brief.is_late:
        parts.append(f"LATE RUN — generated {brief.generated_at.strftime('%H:%M')}")
    parts.append(
        "The developments that matter for Australian Defence, "
        "sovereign industry and national resilience."
    )
    parts.append(_SEP)

    # Top Line
    parts.append("\nTOP LINE\n" + _DIV)
    for bullet in brief.top_line:
        parts.append(bullet)

    # Quote
    if brief.quote and brief.quote[0]:
        parts.append(f'\n"{brief.quote[0]}"\n  — {brief.quote[1]}')

    # Priority developments
    if brief.priority_items:
        parts.append(f"\nPRIORITY DEVELOPMENTS ({len(brief.priority_items)})\n" + _DIV)
        for bi in brief.priority_items:
            parts.append(f"\n{bi.scored.title}")
            parts.append(f"  Source: {bi.scored.source_name}  |  {bi.scored.canonical_url}")
            if bi.scored.confidence in ("low", "medium"):
                parts.append(f"  [{bi.scored.confidence.upper()} CONFIDENCE]")
            parts.append(f"  What happened: {bi.narrative.what_happened}")
            parts.append(f"  Why it matters: {bi.narrative.why_it_matters}")
            parts.append(f"  Kestrel Angle: {bi.narrative.kestrel_angle}")

    # Body sections
    _body_section(parts, "POLICY, POSTURE AND GEOPOLITICS", brief.policy_items)
    _body_section(parts, "MARKET AND INDUSTRY MOVES", brief.market_items)
    _body_section(parts, "EMERGING TECHNOLOGY AND DUAL-USE", brief.tech_items)

    # Watchpoints
    if brief.watchpoints:
        parts.append(f"\nWATCHPOINTS\n" + _DIV)
        for wp in brief.watchpoints:
            parts.append(wp)

    # Footnote
    parts.append(f"\n{_SEP}")
    parts.append("This email was created by AI. Errors & Omissions Expected.")
    parts.append("For feedback to this email please email Viji John <vjohn1@kpmg.com.au>")
    parts.append(
        "Unsubscribe: mailto:vjohn1@kpmg.com.au"
        "?subject=Kestrel%20Unsubscribe"
        "&body=Please%20remove%20me%20from%20the%20Kestrel%20distribution%20list."
    )
    parts.append(_SEP)

    return "\n".join(parts)


def _body_section(parts: list, heading: str, items: list[BriefItem]) -> None:
    if not items:
        return
    parts.append(f"\n{heading}\n" + _DIV)
    for bi in items:
        line = f"- {bi.scored.title} ({bi.scored.source_name})"
        if bi.scored.confidence == "low":
            line += " [LOW CONFIDENCE]"
        line += f"\n  {bi.scored.canonical_url}"
        parts.append(line)
