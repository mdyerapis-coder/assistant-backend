# Phase 00 — backend skeleton on the VPS

**Reads:** `docs/plan.md` §1 (backend stack/layout), §1.6 (Bitwarden sync design). `docs/adr/011-bitwarden-secret-sync.md`.

**Does:**
1. Rename the SSH alias for the VPS (103.108.228.3) to something neutral — it currently carries a name tied to the earlier project this one shares no branding with.
2. Scaffold `app/main.py`, `app/config.py`, `app/auth.py` (bearer-token FastAPI dependency), `app/routers/health.py` — no chat logic yet, just enough to boot and answer `/v1/health`.
3. Ship it to the VPS: `assistant.service` (systemd `--user`, `Restart=on-failure`, `EnvironmentFile=%h/assistant.env`), a standalone Caddy site block for the chosen domain, TLS via Caddy's automatic HTTPS.
4. Build and wire `scripts/sync_secrets_from_bitwarden.sh` + `assistant-secrets-sync.service`/`.timer` so `assistant.env` is populated from Bitwarden from day one, not hand-typed once and forgotten.

**Writes:** `app/main.py`, `app/config.py`, `app/auth.py`, `app/routers/health.py`, `assistant.service`, `Caddyfile.snippet` (applied to the VPS's real Caddyfile), `scripts/sync_secrets_from_bitwarden.sh`, `assistant-secrets-sync.service`, `assistant-secrets-sync.timer`.

**Human check:** `curl -H "Authorization: Bearer <token>" https://<domain>/v1/health` returns 200 from both the laptop and the phone's mobile data (confirms genuine internet reachability, not just LAN). Confirm the Bitwarden sync timer actually ran once (`systemctl --user status assistant-secrets-sync.timer`) and `assistant.env` got populated, not left as a placeholder.

**When done:** write `REPORT.md` in this folder recording the date, the actual domain chosen, and the health-check result.
