# START HERE — Version Control & Working Rules (read before v2 work)

This file sets up version control correctly for the shift from Kestrel v1 (local pipeline) to v2
(hosted web app). It has two parts:

- **Part A — Operator steps (you, by hand).** Commands only you should run, because they touch your
  GitHub account and decide what goes live. Do these once, now, before any v2 work.
- **Part B — Rules for Claude Code.** How the assistant must behave while working in this repo.
  Claude Code should read this section and follow it for the whole v2 build.

> Plain principle: **one repo, v2 is additive, `main` stays deployable.** v2 reuses the v1 pipeline
> unchanged and adds the website, subscriber API, database and automated send around it. We never
> fork into a second repo.

---

## Part A — Operator steps (do these yourself, by hand)

Run these in PowerShell from the repo root. **Claude Code must NOT run these for you** (see Part B).

### A1. Tag the current working v1 first (cheapest insurance you'll ever buy)
A tag is a permanent bookmark of today's known-good v1. If v2 ever breaks, you can return to this
exact state.
```powershell
git add -A
git commit -m "v1.0: local pipeline, human-sent brief (pre-v2 baseline)"
git tag -a v1.0 -m "Kestrel v1: local pipeline, human-sent brief"
git push origin main --tags
```
If you ever need v1 back: `git checkout v1.0` (read-only look) or branch from it to restore.

### A2. Create the v2 working branch
All v2 work happens here, so `main` keeps holding a working v1 while you build.
```powershell
git checkout -b v2-webapp
git push -u origin v2-webapp
```
You are now on `v2-webapp`. Confirm with `git branch` (the `*` marks your current branch).

### A3. Point deployments at the safe branch (do this when you set them up)
- **Cloudflare Pages** and **GitHub Actions** should deploy/run from **`main`**, not `v2-webapp`.
  This means nothing half-built ever goes live or sends email while you're still building on the
  branch. You only see v2 in production after you merge to `main` (step A5).
- While building, you test v2 using the workflow's **manual trigger** (`workflow_dispatch`) and
  `wrangler dev`, not the scheduled send. See the deployment runbook, Part 8.

### A4. Confirm no secret was ever committed
```powershell
git log --all --oneline -- ".env"
git log --all -p -S "ANTHROPIC_API_KEY" | findstr /C:"sk-"
```
If either shows a real key, **rotate that key** (issue a new one, revoke the old) — git history is
permanent. Secrets must live only in GitHub Actions secrets and Cloudflare Worker secrets, never in
files. The `.gitignore` already excludes `.env`, `output/` and the local SQLite files.

### A5. Go live: merge v2 to main — ONLY after the runbook Part 8 tests all pass
Do not do this until subscribe, confirm, unsubscribe, a manual test send, and inbox placement have
all been verified.
```powershell
git checkout main
git merge v2-webapp
git tag -a v2.0 -m "Kestrel v2: hosted web app, automated 7am send"
git push origin main --tags
```
After this, `main` is production. From now on, follow the "shipping changes once live" rule in
Part B7.

---

## Part B — Rules for Claude Code (follow these for all v2 work)

Claude Code: read this whole section and apply it throughout. These rules exist because this repo
becomes a live service that sends real email to real subscribers.

### B1. Stay on the `v2-webapp` branch
All your commits go to `v2-webapp`. Before starting work, run `git branch` and confirm you are on
`v2-webapp`. If you are on `main`, stop and tell the operator; do not commit to `main`.

### B2. Never run these — they are the operator's decisions
Do **not** run, and do not offer to run, any of the following on the operator's behalf:
- `git tag …`, `git push --tags`, or any push to `main`
- `git merge` into `main`
- `git checkout main` followed by changes
- deleting branches, force-pushing (`git push --force`), or `git reset --hard` on shared history
- `wrangler deploy`, `wrangler secret put`, or anything that changes live Cloudflare/Resend/DNS state
- triggering the scheduled send

If a task seems to need one of these, **pause and instruct the operator to do it by hand**, pointing
to the relevant Part A step or the deployment runbook. You may *draft* the commands for them to run.

### B3. v2 is additive — reuse v1, don't rebuild it
The v1 pipeline (collection, dedupe, rating, MECE, render) is reused unchanged. The only edits to
v1 code are the four enumerated in `docs/SPEC_v2.md` §9. Do not refactor or rewrite v1 modules
unless a §9 change requires it. If you think a broader change is needed, raise it with the operator
first.

### B4. Commit in small, labelled steps
- Commit after each working unit (e.g. the D1 schema, then the subscribe endpoint, then the confirm
  flow), not in one giant commit at the end.
- Message format: `v2: <area> — <what changed>`. Examples:
  - `v2: worker — add POST /api/subscribe with Turnstile check`
  - `v2: db — add subscribers schema and indexes`
  - `v2: render — replace mailto unsubscribe with HTTPS token link`
- One concern per commit. Don't mix the website and the workflow in a single commit.

### B5. Never commit secrets or generated state
- No API keys, tokens, or `.env` contents in any committed file. Ever.
- Secrets are referenced by name only (e.g. `RESEND_API_KEY`) and read from the environment.
- Do not commit `output/`, local SQLite files, `node_modules/`, or build artifacts. If `.gitignore`
  is missing an entry you need, add it in its own commit.

### B6. Build in the order set by the spec
Follow `docs/SPEC_v2.md` §12 build order. Before writing code, give the operator a short build plan
and flag anything ambiguous, then wait for approval (same as the v1 build).

### B7. After v2 is live (post-merge), shipping changes safely
Once `main` is production, never commit changes straight to `main`. For any change:
1. Branch off main: `git checkout -b fix-<short-name>` (operator may do this; you work on it).
2. Make and commit the change on that branch.
3. Tell the operator to test via `workflow_dispatch` (manual run) and/or `wrangler dev` before
   merging — never test by waiting for the 7am scheduled send.
4. The operator merges to `main` and tags if significant. You do not merge to `main` (see B2).

### B8. When in doubt, surface it
If a request is ambiguous, risky to subscribers/deliverability, or would touch live infrastructure,
stop and ask rather than guessing. A wrong move here sends bad email to real people or taints the
sending domain.

---

## Quick reference: who does what

| Action | Operator (by hand) | Claude Code |
|---|---|---|
| Tag v1.0, create v2-webapp branch | ✅ | ❌ |
| Write website / Worker / workflow code | review | ✅ (on v2-webapp) |
| Commit feature work | — | ✅ (small, labelled) |
| Set Cloudflare/GitHub/Resend secrets | ✅ | ❌ |
| `wrangler deploy`, DNS records | ✅ | draft commands only |
| Merge v2 to main, tag v2.0, go live | ✅ | ❌ |
| Run the runbook Part 8 tests | ✅ | help interpret results |

---

## The mental model in one line
v1 is tagged and safe on `main`. You build v2 on `v2-webapp`. Nothing reaches subscribers until you
test it and merge to `main` yourself. Claude Code writes the code; you hold the levers that go live.
