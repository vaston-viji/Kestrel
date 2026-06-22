# Australian Defence Daily Digest Source Universe and Usage Guide

## Purpose

This source universe is designed for a twice-daily scheduled task that produces a partner-ready email on Australian Defence and adjacent national-interest developments.

The brief is not broad news monitoring for its own sake. It is selective monitoring for decision value.

The output should help partners answer four questions fast:

1. What changed?
2. Why does it matter now?
3. Does it affect Australian Defence, sovereign industry, clients or deals?
4. What should we watch next?

## Scope

Include developments that affect Australian Defence and its national interests, especially where they intersect with:

- AUKUS
- Indo-Pacific security
- force posture and basing
- Foreign Military Sales or coalition partner activity that affects Australia
- sovereign industrial capability
- shipbuilding, submarines, guided weapons and munitions
- drones, counter-drone and autonomous systems
- cyber, critical infrastructure and resilience
- space and defence-space convergence
- AI, quantum, semiconductors and other dual-use technologies
- critical minerals and strategic supply chains
- advanced manufacturing and defence workforce

Exclude generic defence content that does not change a decision, a market, a posture setting or an industry implication.

## What the table is

The Excel workbook is the master source registry.

Each row is a source entity. In most cases, channels are consolidated into one row. That means a company row can carry:

- the company website or newsroom
- its LinkedIn page
- its ASX ticker, if listed

This is deliberate. It reduces fragmenting the registry and makes maintenance easier.

## How to read the key fields

### Type
The delivery channel or source class.
Examples:

- Government
- LinkedIn
- ASX
- Media
- Industry
- Think Tank
- Academia
- Company

### Sector
The primary domain.
Examples:

- Defence
- Defence Industry
- Adjacent Domain

### Adjacent Domain
Use this to separate true defence content from adjacent but material themes such as:

- Cyber
- Space
- Critical Infrastructure
- Foreign Affairs
- Critical Technologies
- AUKUS
- GWEO
- Capital Markets

### Active
If `No`, the scheduled task should ignore the source.

### Primary or Secondary
- **Primary** means the source originates the fact. Official releases, company disclosures and ASX announcements belong here.
- **Secondary** means the source interprets, critiques or aggregates the fact. Media and think tanks usually sit here.

### Official Status
Use this to distinguish:

- Official
- Independent
- Trade Media
- Industry Body
- Company-Owned

### Trust Score
A measure of reliability.

- **5**: official or highly trusted primary source
- **4**: credible specialist source
- **3**: useful but requires corroboration
- **1-2**: low confidence or low control

### Signal Score
A measure of likely value for the partner audience.

- **5**: high chance of producing material worth surfacing
- **3**: useful intermittently
- **1-2**: long tail or niche

### Noise Score
A measure of irrelevance or clutter.

- **1**: very low noise
- **3**: manageable noise
- **5**: high noise, scan only with filters

### Priority Tier
Execution priority for the app.

- **Tier 1**: always scan in both runs
- **Tier 2**: scan in both runs unless throttled
- **Tier 3**: scan at least once daily or only when triggered by topic
- **Tier 4**: weak-signal layer, run conditionally
- **Tier 5**: long-tail, maintenance or periodic expansion only

## Recommended scanning order

1. **Tier 1 official and market sources first**
   These create the factual spine of the digest.

2. **Tier 2 specialist and state sources second**
   These add commercial, regional and program context.

3. **Tier 3 to 5 sources last**
   These are for weak signals, corroboration and edge cases.

## Source handling rules

### 1. Official beats interpretive
If media conflicts with official disclosure, treat the official source as the factual anchor.
Use media for colour, critique, leaks, stakeholder reaction and second-order implications.

### 2. ASX matters disproportionately
Any ASX release from a defence or dual-use name can be market-moving, board-relevant or a lead indicator of program momentum.
Prioritise ASX announcements even when the commercial value is modest.

### 3. LinkedIn is a weak-signal source, not a truth source
Use LinkedIn to catch:

- executive moves
- facility openings
- hiring signals
- partnership teasers
- event appearances
- community sentiment

Do not rely on LinkedIn alone for material claims if a higher-trust source should exist.

### 4. Trade media is often early but uneven
Trade media often catches deals, demos, partnerships and commentary before mainstream outlets.
Use trust and tier to separate high-value trade outlets from noisy aggregators.

### 5. Academia and think tanks are for implication, not just facts
These sources are useful when they shift:

- strategic narrative
- policy debate
- technology confidence
- alliance framing
- partner or government talking points

## What should make the email

An item should usually make the email if it changes one or more of these:

- Australian strategic posture
- Defence investment priorities
- sovereign industrial capability
- alliance or partner alignment
- supply chain resilience
- regulatory or export settings
- capture opportunities or client risk
- market valuation or sentiment around defence-exposed firms
- adoption pace of dual-use technologies

## What should not make the email

Avoid cluttering the digest with:

- ceremonial updates without strategic or commercial consequence
- generic recruiting content
- routine event promotion with no real signal
- opinion pieces that add no new fact or implication
- duplicate coverage of the same development

## Minimum item structure for the app

For each selected item, capture:

- headline
- source
- date and time
- category
- summary in one or two sentences
- why it matters to Australian Defence or national interest
- commercial or client implication
- confidence level
- canonical link

## Suggested twice-daily operating model

### Morning run
Optimise for:

- overnight developments
- official releases
- ASX announcements
- geopolitical and Indo-Pacific developments
- cyber incidents or advisories

### Afternoon run
Optimise for:

- company and LinkedIn updates
- state agency releases
- trade media and think tank content
- event-day signals
- late-breaking ministerial or company announcements

## Recommended output style for partner audience

Write in Australian English.
Use sharp, direct language.
Lead with the answer.
Do not bury the implication.
Do not sound like a media summary.

Each item should answer:

- what happened
- why it matters
- why KPMG should care
- what to watch next

## Recommended next build step

Use this workbook as the maintained source registry and build the app so it can:

1. filter by `Active = Yes`
2. prioritise by `Priority Tier`, `Trust Score` and `Signal Score`
3. weight `Primary` and `Official` sources first
4. deduplicate entities and stories
5. generate an email against a fixed template
6. log which sources produced selected items, to improve scoring over time

## Maintenance guidance

- Re-verify URLs quarterly
- Downgrade or deactivate sources after 12 months of inactivity
- Add newly relevant companies after major contracts, listings or funding rounds
- Review tiers after each major event cycle such as Avalon, Land Forces, Indo Pacific and budget season

## Files in this delivery

- `australian_defence_source_universe.xlsx` — master source registry and build sheets
- `claude_source_instructions.md` — this guide

Generated on 2026-06-16.
