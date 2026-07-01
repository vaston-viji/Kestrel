# Kestrel v2 — Build Specification (Hosted Web App + Automated Send)

> Layers on top of Kestrel v1 (`SPEC.md`). v1 built the collection → dedupe → rate → synthesise
> → render pipeline that produces the brief. v2 hosts a public website, captures and manages
> subscribers, and **sends the brief automatically every morning at 07:00 Australia/Sydney from
> `kestrel@quantrim.com`**. The v1 pipeline is reused unchanged; v2 adds the web, subscriber and
> email-delivery layers around it.

This document is the build contract for Claude Code. Where it and inline comments disagree, this
document wins. Build to v2 scope only. Do not silently expand scope.

---

## 0. One-paragraph summary

A public website at `kestrel.quantrim.com` (Cloudflare Pages) lets anyone subscribe. Subscribers
confirm via a double opt-in email before they are added. A Cloudflare Worker backed by a
Cloudflare D1 database handles subscribe / confirm / unsubscribe and exposes a protected endpoint
that returns the confirmed recipient list. A scheduled GitHub Actions workflow runs the v1 Python
pipeline at 07:00 Australia/Sydney, builds the brief, fetches confirmed recipients from the Worker,
and sends the email via Resend from `kestrel@quantrim.com`. Domain authentication (SPF, DKIM,
DMARC) is configured on quantrim.com so mail reaches corporate inboxes. There is one send per day.

---

## 1. Architecture

```
                          ┌─────────────────────────────────────────────┐
                          │ Cloudflare (quantrim.com already on CF)       │
   Subscriber's browser   │                                               │
   ───────────────────►   │  Pages:  kestrel.quantrim.com                 │
                          │    - existing website (C:/Claude/kestrel/website)
                          │    - /subscribe page  (form)                  │
                          │    - /confirm page    (lands from email link) │
                          │    - /unsubscribe page                        │
                          │                                               │
                          │  Worker (API):                                │
                          │    POST /api/subscribe                        │
                          │    GET  /api/confirm?token=…                  │
                          │    GET  /api/unsubscribe?token=…              │
                          │    GET  /api/recipients   (auth: shared secret)│
                          │                                               │
                          │  D1 database: subscribers                     │
                          └───────────────▲───────────────────────────────┘
                                          │ HTTPS + shared secret
                                          │ (fetch confirmed recipients)
   ┌──────────────────────────────────────┴───────────────────────────────┐
   │ GitHub Actions (scheduled 07:00 Australia/Sydney)                      │
   │   1. checkout repo (contains the v1 Python pipeline)                   │
   │   2. run `python -m kestrel run --slot morning` → brief HTML + text    │
   │   3. GET /api/recipients → list of confirmed emails                    │
   │   4. send via Resend API from kestrel@quantrim.com                     │
   │   5. log result; write a run record artifact                           │
   └────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                                 Resend (email delivery)
                                          │
                                          ▼
                                 Subscriber inboxes
```

**Why this split:** Cloudflare Workers have short CPU-time limits unsuited to scraping ~150
sources and making multiple model calls. So the lightweight, always-on web/data layer lives on
Cloudflare (free tier), and the heavy daily pipeline runs in GitHub Actions (free minutes for a
private repo). They communicate over one authenticated endpoint.

---

## 2. Scope

**In scope for v2**
- Cloudflare Pages hosting of the existing site + three new pages (subscribe, confirm, unsubscribe).
- Cloudflare Worker API + Cloudflare D1 subscriber database.
- Double opt-in (confirmation email), ON by default, controlled by a config flag.
- One automated daily send at 07:00 Australia/Sydney via Resend from `kestrel@quantrim.com`.
- Reuse of the v1 pipeline to generate the brief (no rewrite).
- Real HTTPS unsubscribe replacing the v1 `mailto:` link.
- DNS authentication (SPF, DKIM, DMARC) + Resend domain verification.
- A separate operator deployment & test runbook (see companion doc).

**Out of scope for v2 (note, do not build)**
- The 11:30 afternoon send (v1 supported two slots; v2 sends once, at 07:00). Keep the pipeline's
  slot parameter intact so afternoon can be switched on later by adding a second cron.
- Subscriber self-service preference management beyond subscribe/unsubscribe.
- Any paid tier, analytics dashboards, or admin UI. (Subscriber list is inspected via D1/SQL.)
- KPMG infrastructure or approvals (this runs entirely on Quantrim-owned infrastructure).

---

## 3. The website (Cloudflare Pages)

Build on the **existing site at `C:/Claude/kestrel/website/`**. Inspect it first and preserve its
look, brand and structure. Add three pages/flows, styled to match the Kestrel brand
(`docs/kestrel_brand_design_note.md`: Graphite text, Violet hero, Electric Blue signal/links,
Lavender soft fills, Light Grey separators; briefing identity, not a news masthead).

### 3.1 Subscribe page/flow
- A simple form: **Name** (optional), **Email** (required), submit button.
- A one-line privacy note: *"We store your name and email only to send the Kestrel brief. You can
  unsubscribe any time."* with a link to a short privacy statement.
- On submit, the page calls `POST /api/subscribe`. On success, show: *"Almost there. Check your
  inbox and click the confirmation link to start receiving Kestrel."* (double opt-in messaging).
- Client-side validation for email format; the Worker re-validates server-side.
- Basic anti-abuse: a honeypot field and Cloudflare Turnstile (free) on the form to stop bots.

### 3.2 Confirm page/flow
- Subscribers arrive here from the confirmation email link:
  `https://kestrel.quantrim.com/confirm?token=…`
- The page calls `GET /api/confirm?token=…`, then shows either *"You're confirmed. The next Kestrel
  brief will arrive at 7am."* or a clear error (expired/invalid token) with a link to re-subscribe.

### 3.3 Unsubscribe page/flow (replaces the v1 mailto:)
- Subscribers arrive from the unsubscribe link in every brief:
  `https://kestrel.quantrim.com/unsubscribe?token=…`
- The page shows the email being unsubscribed (resolved from the token) and a confirm button.
  This satisfies requirement (d): the webpage confirms the address, then the user unsubscribes.
- On confirm, calls `GET /api/unsubscribe?token=…` and shows *"You've been unsubscribed. Sorry to
  see you go."*
- One-click compliance: also honour the unsubscribe on a direct GET so it works even if scripting
  is blocked in the mail client; the page still shows confirmation.

---

## 4. The API (Cloudflare Worker)

A single Worker exposes the endpoints below. JSON in/out. CORS limited to `kestrel.quantrim.com`.

### 4.1 `POST /api/subscribe`
- Body: `{ "name": string|null, "email": string }`.
- Validate email; reject disposable/obviously invalid forms with a clear message.
- Verify Turnstile token.
- Upsert into `subscribers`: if new, status `pending`, generate a `confirm_token`; if already
  `confirmed`, respond success idempotently (do not leak that they're already subscribed); if
  `unsubscribed`, allow re-subscribe by resetting to `pending` with a fresh token.
- If double opt-in is **on** (default): send the confirmation email via Resend (see §6.3) and
  respond `{ "status": "pending_confirmation" }`.
- If double opt-in is **off** (flag): set status `confirmed` immediately and respond
  `{ "status": "subscribed" }`. (The flag lives in the Worker's environment; see §8.)

### 4.2 `GET /api/confirm?token=…`
- Look up by `confirm_token`. If valid and not expired (token TTL configurable, default 7 days):
  set status `confirmed`, clear the token, stamp `confirmed_at`. Respond success.
- If invalid/expired: respond error (the page renders a friendly message).

### 4.3 `GET /api/unsubscribe?token=…`
- Look up by `unsubscribe_token` (a stable per-subscriber token, set at confirfrom time and
  embedded in every brief's unsubscribe link). Set status `unsubscribed`, stamp `unsubscribed_at`.
- Idempotent: unsubscribing an already-unsubscribed address still returns success.

### 4.4 `GET /api/recipients` (protected)
- Requires header `Authorization: Bearer <PIPELINE_SHARED_SECRET>`.
- Returns confirmed subscribers only: `[{ "name": ..., "email": ... }, …]`.
- Rate-limited; the secret is stored in both the Worker env and the GitHub Actions secrets.

---

## 5. The database (Cloudflare D1)

```sql
CREATE TABLE subscribers (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  email             TEXT NOT NULL UNIQUE,        -- stored lowercase, trimmed
  name              TEXT,
  status            TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'confirmed' | 'unsubscribed'
  confirm_token     TEXT,                        -- null once confirmed
  unsubscribe_token TEXT NOT NULL,               -- stable, used in every brief
  created_at        TEXT NOT NULL,
  confirmed_at      TEXT,
  unsubscribed_at   TEXT,
  source            TEXT DEFAULT 'website'       -- where the signup came from
);
CREATE INDEX idx_sub_status ON subscribers(status);
CREATE INDEX idx_sub_confirm ON subscribers(confirm_token);
CREATE INDEX idx_sub_unsub  ON subscribers(unsubscribe_token);
```

- Tokens are cryptographically random (>=128 bits), URL-safe.
- Email is the natural unique key; always normalise to lowercase before insert/lookup.
- No passwords, no sensitive data beyond name + email. (APP / Australian Privacy Principles: this
  is the minimum needed for the stated purpose.)

---

## 6. Email delivery (Resend)

### 6.1 Sender identity
- From: `Kestrel <kestrel@quantrim.com>`.
- Reply-To: `vjohn1@kpmg.com.au` (so replies reach Viji, as in v1).
- Resend domain `quantrim.com` must be verified (DNS records in the runbook).

### 6.2 The daily brief send (from GitHub Actions)
- After the pipeline renders the brief, the workflow fetches confirmed recipients and sends.
- **Send individually or via batch with per-recipient unsubscribe links** — do NOT put all
  recipients in one To: field (privacy + deliverability). Use Resend's batch API, one message per
  recipient, each with that subscriber's unique `unsubscribe_token` in the link.
- Set the `List-Unsubscribe` and `List-Unsubscribe-Post` headers to the unsubscribe URL so Gmail/
  Outlook show a native one-click unsubscribe (a strong deliverability and compliance signal).
- Subject: `D&DI Morning Brief <DDD DD-MMM-YY> [Kestrel]` (Australia/Sydney date).
- Body: the v1 self-contained HTML, with the v1 `mailto:` unsubscribe replaced by the per-recipient
  HTTPS unsubscribe URL (§3.3). Plain-text alternative included.

### 6.3 The confirmation email (from the Worker)
- Sent on subscribe when double opt-in is on. Short, branded, single clear button:
  *"Confirm your subscription"* → `https://kestrel.quantrim.com/confirm?token=…`.
- Plain-text alternative. From/Reply-To as §6.1.

### 6.4 Deliverability rules (non-negotiable for "must get through corporate filters")
- SPF, DKIM, DMARC configured on quantrim.com (records in the runbook). DMARC starts at
  `p=none` for monitoring, tightened to `p=quarantine` after a week of clean reports.
- Double opt-in on at launch (protects sender reputation while the domain is new).
- Warm gradually: do not blast 200 cold addresses on day one. The runbook documents a warming ramp.
- `List-Unsubscribe` headers present on every send.
- Bounce/complaint handling: if Resend reports a hard bounce or complaint for an address, mark it
  `unsubscribed` (add a small webhook or a daily reconciliation step; webhook preferred).

---

## 7. The daily pipeline (GitHub Actions)

### 7.1 Trigger
- `.github/workflows/daily-brief.yml`, scheduled via cron. GitHub cron is **UTC**; 07:00
  Australia/Sydney is **21:00 UTC** (AEDT, UTC+11) or **22:00 UTC** (AEST, UTC+10). Australia
  observes daylight saving, so the workflow must run a small guard that checks the current Sydney
  local time and **only proceeds if it is the 07:00 Sydney hour**, scheduling two UTC crons
  (21:00 and 22:00 UTC) with the guard so exactly one fires year-round. Document this clearly.
- Also support `workflow_dispatch` (manual trigger) for testing.

### 7.2 Steps
1. Checkout the repo (contains the full v1 `kestrel/` project).
2. Set up Python 3.11, install the project (`pip install -e .`).
3. Run `python -m kestrel run --slot morning` with `synthesis.provider: anthropic` and the API key
   from GitHub secrets. Produces the brief HTML + text.
4. Sydney-time guard: exit cleanly (success, no send) if it is not the 07:00 Sydney hour.
5. `GET https://kestrel.quantrim.com/api/recipients` with the shared-secret bearer token.
6. For each recipient, render the unsubscribe URL with their token and send via Resend (§6.2).
7. Upload the rendered brief and a JSON run-record as workflow artifacts (audit trail).
8. On failure at any step, the workflow fails loudly (GitHub emails the repo owner). No silent
   misses.

### 7.3 Secrets (GitHub Actions repository secrets)
- `ANTHROPIC_API_KEY` — runtime synthesis.
- `RESEND_API_KEY` — sending.
- `PIPELINE_SHARED_SECRET` — to call `/api/recipients`.
- `RECIPIENTS_URL` — `https://kestrel.quantrim.com/api/recipients`.

---

## 8. Configuration & flags

- **Worker env vars (Cloudflare):** `DOUBLE_OPT_IN` (default `"true"`), `RESEND_API_KEY`,
  `PIPELINE_SHARED_SECRET`, `TURNSTILE_SECRET`, `CONFIRM_TOKEN_TTL_DAYS` (default `7`),
  `SITE_ORIGIN` (`https://kestrel.quantrim.com`).
- **GitHub secrets:** as §7.3.
- **Pipeline config:** unchanged from v1 (`config/kestrel.yaml`, `data/kestrel_config.xlsx`). The
  only v1 change: the unsubscribe link in the rendered brief becomes a templated HTTPS URL with a
  `{{unsubscribe_token}}` placeholder the sender fills per recipient.

---

## 9. Changes to the v1 pipeline (minimal, enumerated)

1. **Unsubscribe link**: the renderer emits `https://kestrel.quantrim.com/unsubscribe?token={{UNSUB_TOKEN}}`
   as a placeholder, replaced per-recipient at send time. The v1 `mailto:` is removed.
2. **Send target**: v1 produced a file for a human to forward; v2's GitHub Actions step performs
   the send. The v1 file output is retained as the audit artifact.
3. **Provider**: v2 runs `synthesis.provider: anthropic` (the key now lives in GitHub secrets), so
   there is no `[[PASTE FROM CLAUDE]]` fallback in normal operation. Fallback mode remains available
   for local testing.
4. Everything else in v1 (collection, dedupe, rating, MECE, brand, sections) is unchanged.

---

## 10. Privacy & compliance (light-touch, required)
- Collect only name + email + status. State the purpose on the form.
- Working one-click unsubscribe on every send (`List-Unsubscribe` + the page).
- A short privacy statement page on the site.
- Honour bounces/complaints as unsubscribes.
- Do not share or sell the list. Do not add addresses the user did not submit.

---

## 11. Acceptance criteria (definition of done for v2)
1. `kestrel.quantrim.com` serves the existing site plus working subscribe, confirm and unsubscribe
   pages, all brand-consistent and HTTPS.
2. Submitting the form creates a `pending` subscriber and sends a confirmation email; clicking the
   link flips them to `confirmed`. An unconfirmed address never receives the brief.
3. The unsubscribe link in a brief opens a page that shows the address and, on confirm, sets the
   subscriber to `unsubscribed`; they receive no further briefs. The native client one-click
   unsubscribe also works.
4. `GET /api/recipients` returns only confirmed subscribers and rejects requests without the secret.
5. A manual `workflow_dispatch` run generates the brief, fetches recipients, and sends via Resend
   from `kestrel@quantrim.com` with per-recipient unsubscribe links and `List-Unsubscribe` headers.
6. The scheduled workflow fires once per day at 07:00 Australia/Sydney across daylight-saving
   changes (the UTC-cron + Sydney-guard behaves correctly).
7. SPF, DKIM and DMARC pass for quantrim.com; a test send to Gmail and Outlook lands in the inbox
   (or at worst is diagnosably filtered, not silently rejected).
8. Turnstile + honeypot block automated form submissions.
9. The `DOUBLE_OPT_IN` flag, set to `false`, makes subscription immediate (no confirm email); set
   to `true` (default) restores double opt-in. No code change needed to flip it.
10. A failed pipeline run fails the workflow loudly; no silent missed send.

---

## 12. Build order (recommended for Claude Code)
1. Inspect the existing website; set up the Cloudflare Pages project and custom domain.
2. D1 schema + Worker with the four endpoints; test locally with `wrangler dev`.
3. Wire the three website pages to the Worker.
4. Resend domain verification + confirmation-email send from the Worker.
5. Modify the v1 renderer for the HTTPS unsubscribe placeholder.
6. GitHub Actions workflow: pipeline run → recipients fetch → Resend send, behind `workflow_dispatch`.
7. Add the scheduled cron + Sydney-time guard.
8. DNS authentication records; deliverability test to Gmail/Outlook.
9. Run the full acceptance-criteria checklist.
