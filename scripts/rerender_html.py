"""Re-render the HTML for the most recent completed run without re-collecting or re-classifying."""
from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kestrel.config import load_config
from kestrel.models import (
    Brief, BriefItem, Classification, ItemNarrative, ScoredItem,
)
from kestrel.render.html import render_html
from kestrel.render.subject import make_subject
from kestrel.store.db import KestrelDB


def _parse_txt(txt_path: Path) -> tuple[list[str], tuple[str, str], list[str]]:
    """Extract top_line bullets, quote, and watchpoints from the plain-text output."""
    if not txt_path.exists():
        return [], ("", ""), []

    text = txt_path.read_text(encoding="utf-8")
    top_line: list[str] = []
    quote: tuple[str, str] = ("", "")
    watchpoints: list[str] = []

    # Top Line section: lines starting with "- " between TOP LINE header and next section
    tl_match = re.search(r"TOP LINE\n-+\n(.*?)(?:\n[A-Z]|\Z)", text, re.DOTALL)
    if tl_match:
        for line in tl_match.group(1).splitlines():
            if line.startswith("- "):
                top_line.append(line)

    # Quote: "..." followed by  — author on next line
    q_match = re.search(r'"([^"]+)"\n\s+—\s+(.+)', text)
    if q_match:
        quote = (q_match.group(1).strip(), q_match.group(2).strip())

    # Watchpoints section
    wp_match = re.search(r"WATCHPOINTS\n-+\n(.*?)(?:\n={3,}|\Z)", text, re.DOTALL)
    if wp_match:
        for line in wp_match.group(1).splitlines():
            if line.startswith("- "):
                watchpoints.append(line)

    return top_line, quote, watchpoints


def _load_brief_from_db(db: KestrelDB, slot: str, output_dir: Path) -> tuple[Brief, str] | None:
    conn = db._conn
    row = conn.execute(
        "SELECT run_id, run_date, late, started_at FROM runs "
        "WHERE slot=? AND status IN ('ok','partial') ORDER BY started_at DESC LIMIT 1",
        (slot,),
    ).fetchone()
    if not row:
        return None
    run_id, run_date, late, started_at_str = row

    items_rows = conn.execute(
        "SELECT item_id, headline, canonical_url, source_name, published_at, section, "
        "summary, why_it_matters, kpmg_angle, confidence, rating_total, rating_impact, "
        "rating_sentiment, kpmg_tags, domain_tags, escalated "
        "FROM items WHERE run_id=?",
        (run_id,),
    ).fetchall()

    corr_map: dict[str, list[tuple[str, str]]] = {}
    for item_id, src_name, src_url in conn.execute(
        "SELECT item_id, source_name, url FROM item_sources "
        "WHERE item_id IN (SELECT item_id FROM items WHERE run_id=?)", (run_id,)
    ).fetchall():
        corr_map.setdefault(item_id, []).append((src_name, src_url))

    priority, policy, market, tech = [], [], [], []
    for r in items_rows:
        (item_id, headline, url, source, pub_str, section,
         what_happened, why_matters, kestrel_angle, confidence,
         rating_total, rating_impact, rating_sentiment,
         kestrel_tags_json, domain_tags_json, escalated) = r

        pub = datetime.fromisoformat(pub_str).replace(tzinfo=timezone.utc) if pub_str else None
        kestrel_tags = json.loads(kestrel_tags_json) if kestrel_tags_json else []
        domain_tags = json.loads(domain_tags_json) if domain_tags_json else []

        si = ScoredItem(
            item_id=item_id,
            title=headline,
            canonical_url=url,
            source_name=source,
            published_at=pub,
            snippet="",
            classification=Classification(
                kestrel_tags=kestrel_tags,
                domain_tags=domain_tags,
                impact_score=rating_impact / 0.4 if rating_impact else 2.0,
                kestrel_sentiment=rating_sentiment / 0.2 if rating_sentiment else 0.0,
                primary_section=section or "policy",
            ),
            rating_total=rating_total or 0.0,
            rating_impact=rating_impact or 0.0,
            rating_sentiment=rating_sentiment or 0.0,
            trust_score=3.0,
            signal_score=3.0,
            escalated=bool(escalated),
            confidence=confidence or "medium",
            corroborating_sources=corr_map.get(item_id, []),
        )
        bi = BriefItem(
            scored=si,
            narrative=ItemNarrative(
                what_happened=what_happened or "",
                why_it_matters=why_matters or "",
                kestrel_angle=kestrel_angle or "",
            ),
            section=section or "",
        )
        if section == "priority":
            priority.append(bi)
        elif section == "market":
            market.append(bi)
        elif section == "tech":
            tech.append(bi)
        else:
            policy.append(bi)

    started_at = datetime.fromisoformat(started_at_str)
    subject = make_subject(slot, started_at, "Australia/Sydney")

    txt_path = output_dir / run_date / f"kestrel_{slot}_{run_date}.txt"
    top_line, quote, watchpoints = _parse_txt(txt_path)

    brief = Brief(
        slot=slot,
        run_date=run_date,
        is_late=bool(late),
        generated_at=started_at,
        top_line=top_line,
        quote=quote,
        priority_items=priority,
        policy_items=policy,
        market_items=market,
        tech_items=tech,
        watchpoints=watchpoints,
        digest_md="",
        subject=subject,
    )
    return brief, run_date


if __name__ == "__main__":
    import argparse
    import zoneinfo

    p = argparse.ArgumentParser(description="Re-render HTML from last DB run")
    p.add_argument("--slot", choices=["morning", "afternoon"], default="afternoon")
    p.add_argument("--project-root", default=None)
    args = p.parse_args()

    root = Path(args.project_root).resolve() if args.project_root else Path(__file__).parent.parent
    cfg = load_config(root)
    db = KestrelDB(cfg.paths.data_dir / "kestrel.db")

    result = _load_brief_from_db(db, args.slot, cfg.paths.output_dir)
    if not result:
        print(f"No completed {args.slot} run found in DB.")
        sys.exit(1)

    brief, run_date = result
    html = render_html(brief, cfg.paths.assets_dir, cfg.brief.theme, root)

    out_dir = cfg.paths.output_dir / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"kestrel_{args.slot}_{run_date}.html"
    out_path.write_text(html, encoding="utf-8")
    db.close()

    print(f"Re-rendered: {out_path}")
