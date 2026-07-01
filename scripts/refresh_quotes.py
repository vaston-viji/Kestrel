"""
Quarterly military quotes refresh.

Reads existing quotes from data/kestrel_config.xlsx (Quotes sheet),
calls Claude to identify notable military/strategic quotes not already
present, and appends new candidates to output/quotes_candidates_<date>.csv
for human review before adding to the sheet.

Run: python scripts/refresh_quotes.py
Schedule: every 90 days via Windows Task Scheduler (see setup below).
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

import anthropic
import openpyxl

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "data" / "kestrel_config.xlsx"
OUTPUT_DIR = ROOT / "output"


def _load_existing(wb_path: Path) -> set[str]:
    wb = openpyxl.load_workbook(wb_path, read_only=True)
    ws = wb["Quotes"]
    existing: set[str] = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        quote = (row[0] or "").strip().lower()
        if quote:
            existing.add(quote)
    return existing


def _fetch_new_quotes(existing: set[str], n: int = 30) -> list[dict]:
    client = anthropic.Anthropic()

    existing_sample = "\n".join(f'- "{q}"' for q in sorted(existing)[:40])

    prompt = f"""You are building a curated database of military, strategic and leadership quotes
for a defence intelligence newsletter called Kestrel.

The database already contains {len(existing)} quotes. A sample of existing entries:
{existing_sample}

Task: identify {n} notable military, strategic or national-security quotes from well-known
historical and contemporary figures that are NOT already in the list above. Focus on:
- Military commanders, strategists and heads of state (historical and modern)
- Defence and national-security scholars
- Quotes that are thematically relevant to defence, strategy, sovereignty, deterrence,
  leadership under pressure, intelligence, and industrial capacity

Return ONLY a JSON array of objects with these fields:
  quote  — the exact quote text (no curly quotes, use straight double quotes inside the JSON)
  author — full name and brief identifier (e.g. "Sun Tzu, The Art of War")
  theme  — one of: general | leadership | strategy | deterrence | technology | sovereignty

No preamble, no markdown fences, just the raw JSON array."""

    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    import json
    raw = message.content[0].text.strip()
    # Strip any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    candidates: list[dict] = json.loads(raw)

    # Filter out any that already exist (double-check)
    new = [
        c for c in candidates
        if c.get("quote", "").strip().lower() not in existing
    ]
    return new


def main() -> None:
    print(f"Loading existing quotes from {CONFIG} ...")
    existing = _load_existing(CONFIG)
    print(f"  {len(existing)} existing quotes found.")

    print("Fetching new quote candidates from Claude ...")
    candidates = _fetch_new_quotes(existing)
    print(f"  {len(candidates)} new candidates returned.")

    if not candidates:
        print("No new quotes found — database may already be comprehensive.")
        return

    today = date.today().isoformat()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"quotes_candidates_{today}.csv"

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["quote", "author", "theme", "active"])
        writer.writeheader()
        for c in candidates:
            writer.writerow({
                "quote": c.get("quote", ""),
                "author": c.get("author", ""),
                "theme": c.get("theme", "general"),
                "active": "Yes",
            })

    print(f"\nCandidates written to: {out_path}")
    print("Review the CSV, then paste approved rows into the Quotes sheet in data/kestrel_config.xlsx.")


if __name__ == "__main__":
    main()
