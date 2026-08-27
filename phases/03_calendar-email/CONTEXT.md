# Phase 03 — calendar + Gmail (gated on a manual GCP step)

**Reads:** `docs/plan.md` §1 (Google OAuth design), `docs/adr/007-google-oauth-backend-anchored.md`. Phase `01`'s `REPORT.md` (this phase does not strictly need `02`/`02.5` done first — it can start in parallel once the GCP prerequisite below is handled).

**Manual prerequisite, not code — start this early, it's the longest pole:** in GCP project `182773386348`'s console, extend the OAuth consent screen for Calendar (`calendar.events` or narrower) and Gmail (read-only + send, not full mailbox) scopes, and add the real `/oauth/google/callback` URL (matching whatever domain phase `00` actually chose) as an authorized redirect URI. This is Mason's step, not something to automate around.

**Does:** `GET /oauth/google/start` / `GET /oauth/google/callback` (backend-anchored auth-code flow using the existing confidential client), encrypted token storage (`google_oauth_tokens`, per `docs/adr/003-encrypt-tokens-at-rest.md`), then `calendar.py`/`gmail.py` tools. Android side adds a Custom Tab launch + deep-link return + a "Connected to Google" row — coordinate with whoever owns that repo.

**Writes:** `app/routers/oauth_google.py`, `app/tools/calendar.py`, `app/tools/gmail.py`, `google_oauth_tokens` table.

**Human check:** connect Google in-app, then "what's on my calendar today" and "any new emails" return real data. Confirm token refresh works by testing again after the access token's TTL would have expired (don't just test immediately after connecting).

**When done:** write `REPORT.md`.
