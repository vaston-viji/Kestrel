# Kestrel

**"We scan fast, see early and surface what matters."**

A local, twice-daily brief on Australian Defence and adjacent national-interest developments,
written for Australian Defence, sovereign industry and national security professionals. Kestrel collects from a maintained source registry, ranks
and de-duplicates, uses a language model to write the judgement layer, and renders a
self-contained HTML email for a human to review and send.

> Read **`SPEC.md`** first. It is the build contract.

## Status: v1
- Runs locally on Windows via Task Scheduler at 07:00 and 11:30 (Australia/Sydney).
- Generates a reviewable brief; **a human sends it**. No automated sending in v1.
- Works **today** without an API key in `fallback` mode (produces a structured digest plus an
  HTML brief with `[[PASTE FROM CLAUDE]]` placeholders for the judgement layer).

## Blocking prerequisite for full automation
A working `ANTHROPIC_API_KEY` (or a self-hosted model endpoint). Until that is in
place, run in `fallback` mode. See `SPEC.md` §7.

## Quickstart
```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e .
cp .env.example .env                                # add your key when approved
# fallback mode works with no key:
python -m kestrel run --slot morning
# open the HTML printed at the end of the run for review
```

## Master files you edit (no code changes needed)
- `data/kestrel_config.xlsx` — categories, quotes, filters, escalation, writing style, audience.
- `data/australian_defence_source_universe.xlsx` — the source registry.
- `data/subscribers.xlsx` — Name, Email, Subscription Preference.

## Layout
See `SPEC.md` §2.

## Runbooks
- `docs/OPERATOR_RUNBOOK.md` — daily operation, reviewing and sending, handling missed runs.
- `docs/SOURCE_MAINTENANCE.md` — keeping the registry healthy (quarterly URL re-verification, etc.).
