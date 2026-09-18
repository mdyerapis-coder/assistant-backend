# assistant-backend (placeholder name — rename before this ships)

Backend for a personal-assistant app: OpenAI-backed chat with tool-calling for reminders, calendar, and email, talked to by a native Android app over a bearer-authed SSE API. Built on ICM: folders carry sequencing, `CONTEXT.md` files carry the contract for each piece, status is derivable by what exists on disk — not by asking.

## Where things live

| Folder | What it holds |
|---|---|
| `docs/plan.md` | The full approved design — read this first for anything not answered below |
| `docs/adr/` | One decision per file, the *why* behind a structural choice — read before undoing one |
| `docs/CONTRACT.md` | The SSE frame shape plus the O1 OAuth relay URLs/deep link. **This is the only file the Android repo should ever need to read from this one.** |
| `docs/oauth-relay.md` | Operator guide for `assistant.llmclouds.au` as the O1 Google OAuth relay (what must stay on this host, phone URLs, secrets, curl checks) |
| `phases/` | The build order, in execution order (`00_...` → `03_...`). Each phase folder is a contract: what it reads, builds, and how a human verifies it's done |
| `app/` | The actual FastAPI application (created starting at phase `00_backend-skeleton`) |
| `skills/` | SKILL.md files for anything beyond the core tools — empty until phase `03` is well past |
| `scripts/` | One-off and scheduled scripts (bearer token generation, Bitwarden secret sync) |

## Route by what just happened

| If | Go to |
|---|---|
| Starting the next phase of work | The lowest-numbered `phases/*/CONTEXT.md` that has no `REPORT.md` sibling yet |
| Asked "what's actually done" | Scan `phases/*/` for a `REPORT.md` — its presence *is* the done signal, no report means not done |
| Building the Android app and need the API contract | `docs/CONTRACT.md` only — do not read `app/` |
| Operating `assistant.llmclouds.au` as the O1 Google OAuth relay | `docs/oauth-relay.md` |
| Need to understand *why* something is structured a certain way | `docs/adr/` |
| Need the full design (schemas, ADR rationale in context, verification steps) | `docs/plan.md` |

## The one rule

A phase isn't done until its `CONTEXT.md`'s human-check has actually been run and a `REPORT.md` written recording it. Don't start the next phase on the assumption the last one "should" work.

## Phase 02.5 — Reminder Delivery

**Status:** Scaffolded. Firebase project `api-intergrations-501314` is configured. Service account `assistant-backend-fcm@api-intergrations-501314.iam.gserviceaccount.com` created with `Firebase Admin` role. Service account key saved at `service-account.json` (gitignored).

**What was added:**
- `app/scheduler.py` — background polling loop (30s interval) that fires due reminders via FCM
- `app/fcm.py` — Firebase Cloud Messaging integration using firebase-admin SDK
- `app/routers/device_tokens.py` — POST `/v1/device-tokens` endpoint for Android FCM token registration
- `device_tokens` table in `app/db.py`
- Scheduler wired into FastAPI lifespan in `app/main.py`
- 3 new tests in `tests/test_scheduler.py`

**Still needed for full end-to-end:**
- Android app must call POST `/v1/device-tokens` with its FCM token on startup
- Human check: create a reminder due 2 minutes out, confirm push notification lands on phone
- Write `REPORT.md` in `phases/02.5_reminder-delivery/`

## Agent skills

This repo uses [mattpocock/skills](https://github.com/mattpocock/skills). See:

- **Issue tracker**: `docs/agents/issue-tracker.md`
- **Triage labels**: `docs/agents/triage-labels.md`
- **Domain docs**: `docs/agents/domain.md`
