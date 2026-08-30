# Phase 04 — hardening (close the loop)

**Reads:** `phases/03_calendar-email/REPORT.md` §Not done yet (token-refresh TTL, 7-day calendar), `docs/plan.md` §1.6 (Bitwarden sync) and §3 (phased order), `phases/02_reminders/CONTEXT.md` (template).

**Does:** closes every tracked backend loose end from phases 00–03. No new product surface.
- live-verify `get_google_credentials()` refresh after real access-token expiry (wait past TTL, then drive calendar/Gmail via chat — no code stub, no expiry mock);
- live-verify `list_upcoming_calendar_events(days=7)` driven from chat;
- SQLite backup to off-box storage (litestream to S3/R2 **or** cron + restic — either satisfies, document which and where);
- basic uptime/error alerting for the systemd service on the VPS (health-check ping + restart/failure notification);
- CI: GitHub Actions (or equivalent) running `pytest` on every push.

**Writes:** `app/db.py` or backup config only if needed for (3); `assistant.service` / timer / Caddy snippet only if needed for (3)–(4); `.github/workflows/ci.yml` for (5). Companion Android polish tracked separately: `assistant-android` `phases/07_hardening`.

**Human check:**
1. Let Google access token expire, then "what's on my calendar today" via chat returns real data (proves refresh).
2. "what's on my calendar in the next 7 days" via chat returns `list_upcoming_calendar_events` data.
3. `systemctl --user status assistant` active; kill/restart triggers alert; backup artifact exists off-box and restores to a fresh DB.
4. Push to `main` shows green CI with `pytest` log.

**When done:** write `REPORT.md` with live outputs and links (CI run, backup location, alert proof).
