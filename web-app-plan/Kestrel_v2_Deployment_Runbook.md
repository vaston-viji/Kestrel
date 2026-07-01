# Kestrel v2 — Deployment & Test Runbook

This is your hands-on guide to standing up Kestrel as a live web service that sends the brief
automatically at 7am. It is written for you, the operator, not for Claude Code. Work through it in
order. Claude Code builds the software; this runbook is the accounts, settings, DNS and tests that
only you can do because they need your logins.

Set aside about half a day for first-time setup, most of it waiting for DNS and email verification
to propagate. Budget: **$0/month** at your scale if you stay on free tiers (Cloudflare Pages,
Workers, D1; Resend free; GitHub Actions free for private repos within the monthly minutes).

---

## Before you start — accounts you need
- **Cloudflare account** with `quantrim.com` already added (you have this).
- **GitHub account** and a (private) repository to hold the Kestrel code.
- **Resend account** (free) at resend.com — sign up with an email you control.
- **Anthropic API key** — from console.anthropic.com. This is the one cost that scales with use;
  at one brief a day it is small, but it is real. Set a spend limit on the key.

Keep a password manager note open. You will generate several secrets and paste them in multiple
places. Label each one.

---

## Part 1 — Get the code into GitHub

1. Put the full `kestrel/` project (the v1 scaffold plus what Claude Code builds for v2) into a new
   **private** GitHub repository. Private matters: it keeps your source registry and config out of
   public view, and gives you the larger free Actions allowance.
2. Do **not** commit any real secrets. The `.gitignore` already excludes `.env`. Secrets go into
   GitHub's encrypted secrets store (Part 5), never into files.

---

## Part 2 — Host the website on Cloudflare Pages

1. In the Cloudflare dashboard, go to **Workers & Pages → Create → Pages**.
2. Connect it to your GitHub repo and point it at the `website/` folder (Claude Code will have
   prepared this). Deploy.
3. Go to **Custom domains** for the Pages project and add `kestrel.quantrim.com`. Because
   quantrim.com is already on Cloudflare, this is a couple of clicks and HTTPS is automatic.
4. Visit `https://kestrel.quantrim.com`. You should see the site. If you see a Cloudflare error,
   wait a few minutes for the certificate to issue, then retry.

**Test:** the homepage loads over HTTPS with a valid padlock.

---

## Part 3 — Create the subscriber database (Cloudflare D1)

1. In the dashboard: **Workers & Pages → D1 → Create database**. Name it `kestrel`.
2. Claude Code provides the schema (a `.sql` file). Apply it with the Wrangler CLI:
   ```
   npx wrangler d1 execute kestrel --file=./schema.sql
   ```
   (Claude Code will give you the exact command and file path.)
3. Confirm the table exists:
   ```
   npx wrangler d1 execute kestrel --command="SELECT name FROM sqlite_master WHERE type='table';"
   ```

**Test:** the `subscribers` table is listed.

---

## Part 4 — Deploy the Worker (the API)

1. The Worker code and its `wrangler.toml` come from Claude Code. The toml binds the D1 database
   and declares the environment variables.
2. Set the Worker's secrets (these are NOT in the toml; they are set via CLI so they stay
   encrypted). You will be prompted to paste each value:
   ```
   npx wrangler secret put RESEND_API_KEY
   npx wrangler secret put PIPELINE_SHARED_SECRET
   npx wrangler secret put TURNSTILE_SECRET
   ```
   - `RESEND_API_KEY`: from Part 6.
   - `PIPELINE_SHARED_SECRET`: invent a long random string now (e.g. 40+ random characters). You
     will paste the SAME value into GitHub in Part 5. This is how the daily job proves it is
     allowed to read the recipient list.
   - `TURNSTILE_SECRET`: from the Turnstile widget you create in **Cloudflare → Turnstile** (free;
     protects the signup form from bots). You also get a site key for the form's front end.
3. Non-secret env vars (`DOUBLE_OPT_IN="true"`, `CONFIRM_TOKEN_TTL_DAYS="7"`,
   `SITE_ORIGIN="https://kestrel.quantrim.com"`) live in `wrangler.toml`.
4. Deploy: `npx wrangler deploy`.

**Test:** call the health/recipients endpoint without the secret and confirm it is rejected:
```
curl https://kestrel.quantrim.com/api/recipients
# expect 401/403
```

---

## Part 5 — GitHub Actions secrets (the daily brain)

In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**. Add:
- `ANTHROPIC_API_KEY` — your Anthropic key.
- `RESEND_API_KEY` — the same Resend key as the Worker.
- `PIPELINE_SHARED_SECRET` — the **exact same** random string you set on the Worker in Part 4.
- `RECIPIENTS_URL` — `https://kestrel.quantrim.com/api/recipients`.

**Test:** none yet; verified in Part 8.

---

## Part 6 — Set up Resend (email sending)

1. In Resend: **Add Domain → quantrim.com**. Resend shows you a set of DNS records (a DKIM record,
   an SPF include, and a return-path/MX record).
2. Add those records in **Cloudflare → quantrim.com → DNS**. Set them to **DNS only** (grey cloud),
   not proxied. Save.
3. Back in Resend, click **Verify**. It may take a few minutes to hours for DNS to propagate.
4. Create a Resend **API key** (read/send). Use this value for `RESEND_API_KEY` in Parts 4 and 5.

**Test:** Resend shows quantrim.com as **Verified**.

---

## Part 7 — Email authentication DNS (gets you past corporate spam filters)

This is the most important part for deliverability. In **Cloudflare → quantrim.com → DNS**, confirm
or add these (Resend's records cover much of SPF/DKIM; you are completing the set):

- **SPF** (TXT on root `quantrim.com`): a single record that includes Resend's send servers, e.g.
  `v=spf1 include:resend.com ~all`. If you already have an SPF record, merge the include into the
  existing one. Never create two SPF records.
- **DKIM**: the CNAME/TXT record(s) Resend gave you in Part 6. These let receivers verify the mail
  is really from you.
- **DMARC** (TXT on `_dmarc.quantrim.com`): start permissive for monitoring:
  `v=DMARC1; p=none; rua=mailto:dmarc@quantrim.com;`
  After a week of clean reports, tighten to `p=quarantine`.

**Test:** use a free checker (e.g. send a message to a Gmail account and view "Show original";
SPF, DKIM and DMARC should all say **PASS**). Claude Code can also script a check.

---

## Part 8 — Test the whole flow before going live

Do these in order. Do not schedule the daily send until all pass.

1. **Signup → confirm.** Open `kestrel.quantrim.com`, subscribe with your own address. You should
   get a confirmation email within a minute. Click it. The confirm page should say you're
   confirmed. Check D1: that row's status is `confirmed`.
   ```
   npx wrangler d1 execute kestrel --command="SELECT email,status FROM subscribers;"
   ```
2. **Bot protection.** Try submitting the form with scripting disabled or via a quick curl POST;
   Turnstile should block it.
3. **Recipients endpoint with secret.**
   ```
   curl -H "Authorization: Bearer <PIPELINE_SHARED_SECRET>" https://kestrel.quantrim.com/api/recipients
   # expect your confirmed address in the JSON
   ```
4. **Manual brief send.** In GitHub: **Actions → Daily Brief → Run workflow** (the
   `workflow_dispatch` trigger). Watch the run. It should generate the brief, fetch recipients, and
   send. Check your inbox: the brief arrives from `kestrel@quantrim.com`, looks right, and the
   unsubscribe link points to `kestrel.quantrim.com/unsubscribe?token=…`.
5. **Inbox placement.** Confirm it landed in the inbox, not spam, in both a Gmail and an Outlook
   account if you can. If it's in spam, check the SPF/DKIM/DMARC PASS from Part 7 first.
6. **Unsubscribe.** Click the unsubscribe link in the received brief. The page should show your
   address and, on confirm, unsubscribe you. Check D1: status `unsubscribed`. Re-run the workflow;
   you should NOT receive the brief.
7. **One-click unsubscribe.** In Gmail/Outlook, the native "unsubscribe" button (from the
   `List-Unsubscribe` header) should also work.

---

## Part 9 — Go live

1. Confirm the `DOUBLE_OPT_IN` flag is `"true"` (default).
2. **Warm the domain.** Do not import 200 addresses and blast them. For the first week, keep volume
   low: your own confirmed test addresses plus a handful of friendly early subscribers. Ask one or
   two contacts inside KPMG to confirm the brief is arriving and, if needed, to mark it "not junk"
   or ask their IT to allowlist `kestrel@quantrim.com`. This builds sender reputation.
3. Turn on the schedule: the workflow's cron is already set for 07:00 Australia/Sydney (via two UTC
   crons and a Sydney-time guard so it fires once year-round across daylight saving). Confirm the
   next scheduled run time in the Actions tab.
4. After a week of clean DMARC reports, tighten DMARC to `p=quarantine`.

---

## Ongoing operation

- **Daily:** GitHub emails you if a run fails. If you get one, open the failed run's log. The
  common causes are an expired Anthropic key, a Resend limit, or a source-collection error that
  shouldn't be fatal (the pipeline is built to continue past dead sources).
- **Weekly:** glance at the D1 subscriber count and the DMARC reports.
- **Source upkeep:** unchanged from v1 — maintain `australian_defence_source_universe.xlsx`.
- **Cost watch:** the only metered cost is the Anthropic API. Keep a spend cap on the key.

---

## Honest risks to keep in mind
- **Corporate filters can still quarantine a new external sender** regardless of perfect
  authentication. The warming step and an insider allowlist are your best mitigations. Give it two
  weeks before judging deliverability.
- **A fully public form invites bots and bad addresses.** Turnstile + double opt-in handle most of
  it, but watch for sudden signup spikes and prune unconfirmed rows periodically.
- **You are now a data custodian.** It is only name + email, but treat the list with care: don't
  export it casually, honour every unsubscribe, and keep the privacy note accurate.
- **GitHub cron is best-effort**, occasionally delayed by a few minutes under load. For a 7am brief
  that is fine; if exact timing ever becomes critical, a paid scheduler is the upgrade path.
