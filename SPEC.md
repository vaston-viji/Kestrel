# Kestrel — Build Specification (v1)

> "We scan fast, see early and surface what matters."
> A twice-daily, partner-ready brief on Australian Defence and adjacent national-interest developments.

This document is the build contract for Claude Code. Build to this spec. Where the spec
and inline code comments disagree, the spec wins. Do not silently expand scope; if a
requirement is ambiguous, implement the smallest reasonable version and leave a `# TODO(spec)`
note.

---

## 0. What this is, in one paragraph

Kestrel is a **local, scheduled Python application** that runs twice each working day
(07:00 and 11:30 Australia/Sydney), collects Australian Defence news from a maintained
source registry, ranks and de-duplicates items, uses a language model to write the
judgement layer (executive summary, "why it matters", KPMG angle, watchpoints), and
renders a **self-contained HTML email plus a plain-text version** into a dated output
folder for a **human to review and send**. v1 does not send email itself. It is designed
so a later v2 can move to a server with automated sending and an API-driven model.

---

## 1. Operating posture (v1 scope and non-scope)

**In scope for v1**
- Runs as a Windows **Task Scheduler** job on a local machine.
- Collects from sources defined in `australian_defence_source_universe.xlsx`.
- Collection via RSS/APIs where available, and **resilient web scraping** for sources without feeds.
- Ranks, categorises, tags, de-duplicates and validates items.
- Synthesises the brief through a **model-agnostic interface** (see §7), Anthropic API as default.
- Produces a reviewable **self-contained `.html`** (images embedded as base64), a **`.txt`**, and archives both in a dated folder.
- Logs every selected item and its source to a **SQLite archive** built to last well past 12 months.
- All human-editable configuration lives in a single **`kestrel_config.xlsx`** workbook.

**Explicitly NOT in v1 (design for, do not build)**
- No automated email sending (no SMTP / Graph / SendGrid). Human sends manually.
- No hosted server or cloud function.
- No LinkedIn scraping (prohibited; treated as a manual weak-signal source only — see §5.4).
- No paywalled-article full-text extraction. Headlines/metadata only for paywalled outlets.

**Known v1 failure mode to handle gracefully**
- The machine may be asleep/off at 07:00 or 11:30. Configure the task to wake the machine,
  and on startup the app must detect a **missed run** (no output for the expected slot today)
  and generate it late, flagging the brief header as `LATE RUN — generated HH:MM`.

---

## 2. Repository layout

```
kestrel/
  SPEC.md                       # this file
  README.md                     # quickstart + operator runbook
  pyproject.toml                # deps + entry point
  .env.example                  # secrets template (never commit real .env)
  config/
    kestrel.yaml                # machine-level config (paths, schedule, run modes)
    writing_style.md            # GENERATED from kestrel_config.xlsx at runtime; consumed by synthesiser
    prompts/
      top_line.md               # prompt template: executive summary
      priority_item.md          # prompt template: per priority-development item
      watchpoints.md            # prompt template: watchpoints
      classify.md               # prompt template: category + domain tagging + rating
  assets/                       # brand pack (copied from kestrel_brand_pack_v1.zip) + KPMG_logo.png
  data/
    kestrel_config.xlsx         # MASTER human-editable config (categories, quotes, filters, style, escalation)
    australian_defence_source_universe.xlsx   # MASTER source registry (provided)
    subscribers.xlsx            # MASTER subscriber list (Name, Email, Subscription Preference)
    kestrel.db                  # SQLite archive (generated)
  output/
    YYYY-MM-DD/
      kestrel_morning_YYYY-MM-DD.html
      kestrel_morning_YYYY-MM-DD.txt
      kestrel_morning_YYYY-MM-DD.run.json     # machine record of the run
  src/kestrel/
    __main__.py                 # CLI entry: `python -m kestrel run --slot morning`
    config.py                   # load + validate all config; generate writing_style.md
    pipeline.py                 # orchestrates a full run
    models.py                   # dataclasses: Source, RawItem, ScoredItem, BriefItem, Brief
    collectors/                 # one module per collector strategy (see §5)
    synthesis/                  # model interface + Anthropic + fallback (see §7)
    render/                     # HTML + text rendering (see §8)
    store/                      # SQLite archive + Excel readers (see §6)
  scripts/
    install_task.ps1            # registers the Windows scheduled tasks
    run_once.ps1                # manual trigger for testing
  tests/
  docs/
    OPERATOR_RUNBOOK.md
    SOURCE_MAINTENANCE.md
```

---

## 3. End-to-end run sequence

A single run (`morning` or `afternoon`) executes these stages in order. Each stage is a pure,
testable function. The pipeline records timing and item counts per stage into `*.run.json`.

1. **Load config** — read `kestrel.yaml`, `kestrel_config.xlsx`, source registry, subscribers.
   Regenerate `config/writing_style.md` from the config workbook. Fail fast with a clear
   message if a master file is missing or malformed.
2. **Select sources** — filter `Active = Yes`; filter by slot (`Include in Morning Digest` /
   `Include in Afternoon Digest`); order by `Priority Tier`, then `Signal Score`, then `Trust Score`.
3. **Collect** — for each selected source, run its collector (§5). Collect raw items with
   title, URL, published timestamp, source name, raw snippet. Respect per-source rate limits,
   timeouts and a global time budget (default 10 min). Failures are logged, never fatal.
4. **Normalise + window** — keep items within the lookback window (default: morning = last 18h,
   afternoon = last 6h; configurable). Normalise whitespace, resolve redirects to canonical URLs.
5. **De-duplicate** — apply the dedupe hierarchy (§9.2). Collapse the same story across sources,
   keeping the highest-trust canonical link and recording the others as corroborating sources.
6. **Validate** — run the source-validation framework (§10) on any item whose lead source is
   not `Official`. Attach a confidence level.
7. **Classify + rate** — assign KPMG-capability tags and Defence-domain tags (§11), and compute
   the rating (§12). This stage may call the model (classify prompt) or use rules; default is
   model-assisted with a deterministic fallback.
8. **Select + allocate** — choose items per email section against the section caps (§8.4),
   enforcing MECE across sections. Apply escalation thresholds (§9.3).
9. **Synthesise** — generate Top Line, per-item "why it matters" + KPMG angle, and Watchpoints
   via the synthesiser (§7). Pick the Quote of the Day (§8.3).
10. **Render** — build the self-contained HTML and the plain-text version (§8).
11. **Persist** — write outputs to `output/YYYY-MM-DD/`, append all selected items to the SQLite
    archive (§6.2), write `*.run.json`.
12. **Notify operator** — print a console summary and the absolute path to the HTML for review.

---

## 4. Configuration model

### 4.1 `config/kestrel.yaml` (machine-level, edited by the operator/developer)
Holds only environment and behavioural settings, not editorial content:
```yaml
timezone: Australia/Sydney
schedule:
  morning: "07:00"
  afternoon: "11:30"
paths:
  data_dir: "./data"
  output_dir: "./output"
  assets_dir: "./assets"
run:
  global_time_budget_seconds: 600
  per_source_timeout_seconds: 20
  lookback_hours:
    morning: 18
    afternoon: 6
synthesis:
  provider: "anthropic"        # "anthropic" | "fallback"
  model: "claude-sonnet-4-6"   # operator-overridable
  max_retries: 3
brief:
  theme: "light"               # "light" | "dark" (selects brand header variant)
```

### 4.2 `data/kestrel_config.xlsx` (MASTER editorial config — edited in Excel, per user choice)
One workbook, one concern per sheet. The app reads this every run and treats it as
authoritative. Required sheets and columns:

- **Categories_KPMG** — `Tag`, `Description`, `Active`. KPMG capability tags
  (e.g. Workforce, Estate, Operating Model, Customer & Operations, Cyber, Strategy, Deals, Assurance).
- **Categories_Domain** — `Tag`, `Description`, `Active`. Defence domains
  (e.g. Maritime, Land, Air, Space, Cyber, GWEO, Counter-drone, AUKUS, Critical Minerals).
- **Quotes** — `Quote`, `Author`, `Active`. Pool for Quote of the Day.
- **Filters** — `Key`, `Value`, `Notes`. Tunable thresholds, e.g. `min_rating_to_include`,
  `max_priority_items`, `section_caps`, `lookback override`.
- **Escalation** — `Trigger`, `Keywords`, `Action`, `Active`. The escalation themes
  (AUKUS, GWEO, counter-drone, force posture, northern basing, Indo-Pacific). See §9.3.
- **Writing_Style** — `Rule_Group`, `Rule`, `Active`. Source of truth for tone rules;
  the app concatenates active rows into `config/writing_style.md` at runtime.
- **Audience** — `Key`, `Value`. e.g. `audience = KPMG Partners`, `top_line_max_words = 150`.

> The app must **fail with a precise message** (sheet + column) if the workbook is missing a
> required sheet/column, rather than guessing.

### 4.3 `data/subscribers.xlsx`
Columns: `Name`, `Email`, `Subscription Preference` (`Both` | `Morning` | `Afternoon` | `Paused`).
v1 uses this only to render the recipient-count and (optionally) a "To:" suggestion list in the
run summary. No sending. Unsubscribe is a `mailto:` link (§8.6).

---

## 5. Collection (`src/kestrel/collectors/`)

Each source row in the registry maps to **one** collector strategy, chosen by the `Type` field
and the presence of feed/URL columns. Implement a `Collector` protocol:

```python
class Collector(Protocol):
    def collect(self, source: Source, window: Window) -> list[RawItem]: ...
```

### 5.1 Strategy selection
- `Type == "ASX"` → **ASX collector** (§5.2). Highest priority; market-moving.
- `Type == "Government"` / `Type == "Industry"` / `Type == "Media"` / `Type == "Think Tank"` /
  `Type == "Academia"` / `Type == "Company"`:
  - If the source exposes an RSS/Atom feed (discover via `<link rel=alternate>` or a known
    `/feed`, `/rss`, `/news.xml` path) → **RSS collector**.
  - Else → **HTML scrape collector** (§5.3) against the `URL`.
- `Type == "LinkedIn"` → **not collected** in v1. Skip and log as `skipped_linkedin`. (§5.4)

### 5.2 ASX collector
- Use the ASX announcements feed/endpoint for the ticker in `ASX Ticker`.
- Capture: title, announcement type, price-sensitive flag, timestamp, PDF/detail URL.
- Treat **price-sensitive** announcements as escalation candidates (§9.3).
- Never infer dollar values; only report figures explicitly stated in the announcement.

### 5.3 HTML scrape collector (resilient by design)
Scraping arbitrary sites is fragile. Build it to degrade, not crash:
- Use `httpx` + `selectolax`/`beautifulsoup4`. A realistic User-Agent. Per-source timeout.
- A small **per-source extraction hint** may be stored in the registry `Notes` column
  (e.g. `selector: article h3 a`). If absent, fall back to generic heuristics:
  scan for `<article>`, headline tags (`h1..h3`) with anchors, and `<time>`/meta dates.
- Respect `robots.txt`. Honour a global polite delay between requests to the same host.
- If a source yields zero items two runs in a row, flag it in the run summary as
  `needs_attention` so the operator can fix the selector. Do not fail the run.

### 5.4 LinkedIn (manual, weak-signal only)
Per `claude_source_instructions.md`, LinkedIn is a weak-signal source and must never be the
sole basis for a material claim. v1 does **not** automate it. The run summary includes a short
"manual check suggested" list of the active LinkedIn rows so the operator can eyeball them if
they wish. Nothing is scraped.

### 5.5 Collector output
All collectors return `RawItem(title, url, source_name, published_at, snippet, raw_meta)`.
Network and parse errors are caught per source and recorded; one bad source never aborts a run.

---

## 6. Storage (`src/kestrel/store/`)

### 6.1 Excel readers
Thin, validated readers for the three master workbooks. Read-only. Never write back to the
masters. Surface precise errors on schema drift.

### 6.2 SQLite archive (`data/kestrel.db`)
The durable record. Must remain performant past 12 months (tens of thousands of rows).
Use WAL mode and the indexes below. Suggested schema:

```sql
CREATE TABLE runs (
  run_id        TEXT PRIMARY KEY,        -- uuid
  slot          TEXT NOT NULL,           -- 'morning' | 'afternoon'
  run_date      TEXT NOT NULL,           -- ISO date (local)
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  late          INTEGER NOT NULL DEFAULT 0,
  item_count    INTEGER,
  status        TEXT NOT NULL            -- 'ok' | 'partial' | 'failed'
);

CREATE TABLE items (
  item_id          TEXT PRIMARY KEY,     -- uuid
  run_id           TEXT NOT NULL REFERENCES runs(run_id),
  headline         TEXT NOT NULL,
  canonical_url    TEXT NOT NULL,
  source_name      TEXT NOT NULL,
  published_at     TEXT,
  section          TEXT,                 -- which email section it landed in
  summary          TEXT,
  why_it_matters   TEXT,
  kpmg_angle       TEXT,
  confidence       TEXT,                 -- 'high' | 'medium' | 'low'
  rating_total     REAL,
  rating_impact    REAL,
  rating_sentiment REAL,                 -- KPMG sentiment, signed
  kpmg_tags        TEXT,                 -- json array
  domain_tags      TEXT,                 -- json array
  escalated        INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT NOT NULL
);

CREATE TABLE item_sources (        -- corroborating sources for a deduped story
  item_id     TEXT NOT NULL REFERENCES items(item_id),
  source_name TEXT NOT NULL,
  url         TEXT NOT NULL
);

CREATE TABLE url_seen (            -- dedupe + "have we shipped this before" memory
  url_hash    TEXT PRIMARY KEY,    -- sha256 of canonical url
  first_seen  TEXT NOT NULL,
  headline    TEXT
);

CREATE INDEX idx_items_run        ON items(run_id);
CREATE INDEX idx_items_date       ON items(created_at);
CREATE INDEX idx_runs_date_slot   ON runs(run_date, slot);
```
`url_seen` lets the app suppress stories already shipped in a prior brief (configurable
suppression window, default 5 days) so partners do not see repeats.

---

## 7. Synthesis (`src/kestrel/synthesis/`)

The judgement layer is what makes Kestrel a brief and not an RSS reader. It is generated
behind one interface so the backing model can change without touching the pipeline.

### 7.1 Interface
```python
class Synthesizer(Protocol):
    def top_line(self, items: list[ScoredItem], style: str, max_words: int) -> list[str]: ...
    def enrich_item(self, item: ScoredItem, style: str) -> ItemNarrative: ...   # why_it_matters + kpmg_angle
    def watchpoints(self, items: list[ScoredItem], style: str) -> list[str]: ...
    def classify(self, item: RawItem, taxonomy: Taxonomy) -> Classification: ... # tags + rating inputs
```

### 7.2 Implementations
- **AnthropicSynthesizer** (default). Reads `ANTHROPIC_API_KEY` from environment. Uses the
  model named in `kestrel.yaml`. Prompts live in `config/prompts/*.md` and inject
  `config/writing_style.md`. Retries with backoff. Strict output contracts: prompts must
  instruct the model to return only the requested structure (plain bullets or JSON as
  specified per prompt), and the code must parse defensively.
- **FallbackSynthesizer**. No model calls. Produces a **structured digest** (`output/.../
  kestrel_<slot>_<date>.digest.md`) containing all selected, deduped, rated items with their
  metadata, and writes the HTML with placeholder Top Line/KPMG-angle blocks clearly marked
  `[[PASTE FROM CLAUDE]]`. This guarantees a working pipeline before the API key is approved.

> **Blocking prerequisite for full automation:** a working `ANTHROPIC_API_KEY` (or an approved
> KPMG-hosted model endpoint). Until then the app runs in `provider: fallback` mode. Document
> this prominently in README and the runbook.

### 7.3 Editorial constraints the prompts must enforce
- Australian English. Sharp, direct. Lead with the answer.
- No em dashes. No "not X, but Y" contrast pivots. No stacked synonyms. No consulting fluff.
- Top Line ≤ 150 words, 3–5 bullets, **bold** company / Service / capability names.
- Every priority item must answer: what happened, why it matters, **KPMG angle**, what to watch.
- The model must not invent figures, contract values, dates or attributions. If a fact is not
  in the source snippet, it must not appear. Unverified non-official items carry their
  confidence level through to render.

---

## 8. Email output (`src/kestrel/render/`)

### 8.1 Format
- **Self-contained HTML**: all images embedded as base64 data URIs (works offline and survives
  forwarding). Inline CSS only (Outlook-safe). No external fonts; use a websafe geometric/neo-
  grotesque stack with sensible fallbacks per the brand note.
- A matching **plain-text** rendering for accessibility and quick reading.
- Both saved to `output/YYYY-MM-DD/` with the naming in §2.

### 8.2 Subject line (emit into run summary and as a `subject.txt`)
- Morning: `D&DI Morning Brief <DDD DD-MMM-YY> [Kestrel]`
- Afternoon: `D&DI Afternoon Brief <DDD DD-MMM-YY> [Kestrel]`
- Date formatted in `Australia/Sydney`, e.g. `Tue 16-Jun-26`.

### 8.3 Sections, in order
1. **Header / masthead** — use the brand header asset matching `brief.theme`
   (`assets/.../headers/<theme>/kestrel_email_header_1200x300_<theme>.png`, Outlook variant for
   narrow clients). Subheading text, verbatim:
   *"The developments that matter for Australian Defence, sovereign industry and national resilience."*
2. **Top Line** — 3–5 synthesised bullets, ≤150 words, bolded key entities. The single most
   important block.
3. **Quote of the Day** — random active row from `Quotes`, centred and italicised, with author.
4. **Priority developments** — 4–7 items. Each: Headline / What happened / Why it matters /
   KPMG angle. This is the core section.
5. **Main body** — three MECE subsections, each a ranked bullet list (bold key entity + outcome,
   trailing `(Source)` link). Cap **10 per subsection**, hard cap **15 headlines total** across
   the body, ordered by rating. Fewer is better; do not pad.
   - **Policy, posture and geopolitics**
   - **Market and industry moves**
   - **Emerging technology and dual-use**
6. **Watchpoints** — 3–5 synthesised, forward-looking judgement bullets.
7. **Footnote** — verbatim:
   *"This email was created by AI. Errors & Omissions Expected."* then
   *"For feedback to this email please email Viji John <vjohn1@kpmg.com.au>"* then the
   unsubscribe link (§8.6). Small, centred **KPMG logo** below the footnote.

### 8.4 Section caps (read from `Filters`, with these defaults)
- `max_priority_items = 7` (min 4)
- `max_per_body_subsection = 10`
- `max_body_headlines_total = 15`
- `watchpoints = 3..5`

### 8.5 MECE enforcement
An item appears in exactly one body subsection. The classifier assigns a primary subsection;
ties broken by domain tag. The Priority developments section may re-feature a body item only if
its significance clearly warrants top billing; if so, it is not double-counted in the body cap.

### 8.6 Unsubscribe
A `mailto:` link: `mailto:vjohn1@kpmg.com.au?subject=Kestrel%20Unsubscribe&body=...`
prefilled with the recipient line for Viji to action manually. No backend needed in v1.

### 8.7 Brand
Follow `kestrel_brand_design_note.md`: Graphite `#4E4E51` text/structure, Violet `#7766EC`
hero accent, Electric Blue `#2272FF` signal/links, Lavender `#BCA3EE` soft fills, Light Grey
`#D9D9D9` separators. Briefing identity, not a news masthead. No military clichés.

---

## 9. Selection, dedupe and escalation

### 9.1 Selection rules (priority order)
1. Official over interpretive (official source is the factual anchor).
2. ASX over commentary when the item is market-moving.
3. Primary over secondary; higher Trust/Signal over lower.
4. Suppress stories already shipped within the suppression window (`url_seen`).

### 9.2 Dedupe hierarchy
When multiple sources cover one story:
1. Prefer the **Official/Primary** source as canonical.
2. Else prefer **highest Trust Score**, then **Signal Score**, then earliest timestamp.
3. Record the losers as corroborating `item_sources`. Merge does not lose links.
Story-equivalence is determined by URL match, then by title/entity similarity above a
configurable threshold (use token-set ratio; default 0.82).

### 9.3 Escalation thresholds
Items matching any active `Escalation` trigger (AUKUS, GWEO, counter-drone, force posture,
northern basing, Indo-Pacific), or any **price-sensitive ASX** announcement, are flagged
`escalated = 1`, get a rating boost, and are eligible for Top Line and Priority developments
even if their raw rating is modest. Keyword lists live in the `Escalation` sheet.

---

## 10. Source validation framework (§ "Validation")

For any item whose lead source is **not Official**, compute a confidence level before it can
appear high in the brief:

- **Corroboration**: is the same fact carried by an independent source of Trust ≥ 4, or by an
  Official/Primary source? (+ strong)
- **Source standing**: lead source Trust Score and Official Status.
- **Specificity**: does the item cite named entities, dated events, dollar figures or program
  names (verifiable), versus vague claims?
- **Recency/consistency**: timestamp within window and not contradicted by an Official source.

Map to `confidence ∈ {high, medium, low}`. Rules:
- An **unverified, low-confidence, non-official** claim may not lead the Top Line or be the sole
  basis of a Priority development. It can appear lower with a visible confidence marker.
- If a non-official item conflicts with an Official source, the Official source anchors the fact
  and the discrepancy may be noted as colour.

---

## 11. Categorisation (§ "Categorisation")

Two independent tag sets, both drawn from `kestrel_config.xlsx`:
- **KPMG capability tags** (Categories_KPMG): Workforce, Estate, Operating Model,
  Customer & Operations, Cyber, Strategy, Deals, Assurance, etc.
- **Defence domain tags** (Categories_Domain): Maritime, Land, Air, Space, Cyber, GWEO,
  Counter-drone, AUKUS, Critical Minerals, etc.

The classifier (model-assisted, deterministic fallback by keyword) assigns 0..n of each to every
item. Tags drive MECE subsection allocation, the KPMG angle, and future scoring analytics. Tags
are stored on the item in SQLite as JSON arrays.

---

## 12. Rating (§ "Rating")

Each item gets a numeric rating used for ordering and selection:

```
rating_total = w_impact * impact_score
             + w_signal * source_signal_score      (from registry, 1-5)
             + w_trust  * source_trust_score        (from registry, 1-5)
             + escalation_boost                     (if escalated)
             + w_sentiment * kpmg_sentiment         (signed: positive opportunity vs negative risk)
```

- `impact_score` (1–5): impact on the sector / Australian operating environment, from the
  classifier.
- `kpmg_sentiment` (signed, e.g. -2..+2): is this good or bad for KPMG / its clients
  (opportunity vs risk). Both magnitudes matter; a large negative is still highly newsworthy.
- Weights live in the `Filters` sheet so they are tunable without code changes. Provide sensible
  defaults (e.g. impact 0.4, signal 0.2, trust 0.2, sentiment 0.2, escalation_boost +1.0).
- Ordering within every section is by `rating_total` descending.

---

## 13. Scheduling (Windows, v1)

- `scripts/install_task.ps1` registers two Task Scheduler jobs (07:00 and 11:30,
  Australia/Sydney) that run `python -m kestrel run --slot morning|afternoon` in the project
  venv, with **wake-the-computer** enabled and **run-on-next-logon-if-missed** behaviour.
- On startup the app checks the archive for a completed run in today's slot; if missing and the
  slot time has passed, it generates the brief and marks it `late = 1`, and the rendered header
  shows `LATE RUN — generated HH:MM`.
- `scripts/run_once.ps1` triggers a manual run for testing.

---

## 14. Dependencies and conventions

- Python 3.11+. Manage with `pyproject.toml`.
- Libraries: `httpx`, `selectolax` (or `beautifulsoup4`+`lxml`), `feedparser`, `openpyxl`,
  `pydantic` (config validation), `jinja2` (HTML templating), `anthropic` (default synthesiser),
  `python-dateutil`, `tenacity` (retries), `rapidfuzz` (title similarity), `tzdata`.
- Secrets only via environment / `.env` (see `.env.example`). Never commit a real key. Never log
  the key.
- Logging: structured, per-run log file under `output/YYYY-MM-DD/`. Console summary at the end.
- Every pipeline stage independently unit-testable with fixture data in `tests/`.

---

## 15. Acceptance criteria (definition of done for v1)

1. `python -m kestrel run --slot morning` in **fallback mode** produces, with no API key:
   a dated folder containing a self-contained `.html`, a `.txt`, a `.digest.md`, a `subject.txt`,
   and a `*.run.json`; and appends rows to `kestrel.db`.
2. With a valid `ANTHROPIC_API_KEY` and `provider: anthropic`, the same command produces a brief
   with a real Top Line (≤150 words, 3–5 bullets, bolded entities), 4–7 priority items each with a
   KPMG angle, three MECE body subsections respecting caps, a quote, and 3–5 watchpoints.
3. Editing `kestrel_config.xlsx` (e.g. adding a quote, changing `max_priority_items`, adding a
   KPMG tag, editing a writing-style rule) changes the next run with **no code edits**.
4. Setting a source to `Active = No` removes it from collection; slot flags route sources to the
   right run.
5. The same story from two sources appears once, with the higher-trust canonical link and the
   other recorded as corroborating.
6. A non-official, uncorroborated claim never leads the Top Line and renders with a visible
   confidence marker.
7. A deliberately broken source (bad URL/selector) is logged as `needs_attention` and the run
   still completes.
8. Brand: correct palette, header asset for the configured theme, verbatim subheading and
   footnote, centred KPMG logo, unsubscribe `mailto:` to Viji.
9. A simulated missed slot generates late and the header shows the late marker.
10. `tests/` pass, including dedupe, rating order, MECE allocation, config validation and
    fallback rendering.

---

## 16. v2 design hooks (build seams, do not implement)

- Swap `FallbackSynthesizer`/`AnthropicSynthesizer` for a KPMG-hosted endpoint behind the same
  interface.
- Replace the human-send step with a `Sender` interface (Graph API / SMTP) reading
  `subscribers.xlsx` and `Subscription Preference`.
- Move the scheduler from Task Scheduler to a server/cron or cloud function; the pipeline is
  already environment-agnostic.
- Use the `items`/`item_sources` history to auto-tune source Signal Scores (the registry's
  stated "improve scoring over time" goal).
