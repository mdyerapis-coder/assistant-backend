# Phase 07 — ship v1.0

**Reads:** `docs/plan.md` intro (placeholder naming note — repos `assistant-backend`/`assistant-android`, package `com.mdyerapis.assistant`, domain `assistant.llmclouds.au`), `CLAUDE.md` banner, `CONTEXT.md` (delegation boundary), `phases/*/REPORT.md` (what actually shipped), `docs/CONTRACT.md`, `assistant.service` + `Caddyfile.snippet`. Companion: `assistant-android` `phases/11_ship-v1` — keep tags and human check in sync.

**Does:**
1. **Mason decision gate — placeholder rename (cannot start without).** Real project name TBD by Mason. Replace everywhere: repo names, Android package, `assistant.llmclouds.au` / Caddy block, `assistant.service` + `assistant.env`, `docs/` + `CONTEXT.md` + `CLAUDE.md`, Bitwarden item ids, GCP OAuth redirect URI. No code before name is chosen.
2. Release engineering — signed/tagged releases (`git tag -s v1.0.x`), scripted or CI deploy to VPS `103.108.228.3` (`assistant.service` restart, `systemctl status` + `/v1/health` post-deploy).
3. Crash/error reporting + privacy-policy review — backend holds encrypted Google OAuth tokens (calendar/gmail). Add error reporting with PII/token scrubbing; review/publish privacy policy covering scopes, storage, encryption, retention, deletion.
4. Final polish — version string, changelog, `docs/CONTRACT.md` freeze for v1.

**Writes:** renamed repos/files/docs, release script or CI workflow (`.github/workflows/deploy.yml` or `scripts/deploy.sh`), `docs/PRIVACY.md` (or site), error-reporting wiring in `app/main.py`.

**Human check (fresh Android install, no prior state):** factory-reset or new profile → onboarding (paste bearer → `GET /v1/health` 200) → chat streams via SSE → create reminder due +2m → push arrives via FCM → calendar/gmail query returns live Google data → voice input round-trips. All five pass on public mobile data, not LAN.

**When done:** write `REPORT.md` with tag, deploy commit, privacy-policy URL, and human-check result.
