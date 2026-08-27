# Phase 00 — REPORT

**Date:** 2026-08-27
**Status:** done

## What actually happened

- SSH alias for the VPS renamed `openhuman-flowvps` → `assistant-vps` (key file too). Box's OS hostname left as `openhuman-flowvps` — bigger, more invasive change, not requested.
- FastAPI skeleton (`app/main.py`, `config.py`, `auth.py`, `routers/health.py`) built and tested locally (pytest + a live local uvicorn run) before ever touching the VPS.
- Deployed as a **system-level** systemd unit (`/etc/systemd/system/assistant.service`), not `--user` as the plan originally said — this VPS only has a root user, unlike masons-ground's `ubuntu`. Port 8090.
- Domain: `assistant.llmclouds.au`. Caddy site block added alongside the pre-existing, unrelated `tinyhumans.llmclouds.au` block. DNS A record added by Mason at the registrar (no API access from here). TLS cert issued automatically by Caddy once DNS resolved.
- Bitwarden CLI (`bw` 2026.8.0) installed on the VPS from the official GitHub release zip (no npm/node available there). Sync script + systemd oneshot/timer deployed but **timer not yet enabled** — needs the one-time manual setup in `docs/bitwarden-setup.md` (Mason's own master password, deliberately not something I handle).
- **Model provider registry built ahead of schedule** (`app/providers.py`, normally a Phase 01 concern) because Mason wanted credentials pulled in now: 8 providers (Gemini, Mistral, GROQ, DeepSeek, OpenRouter, MiniMax, MiMo, OpenCode Zen), keys fetched from his Bitwarden "API Keys" folder via a session token he unlocked and handed over (never his master password), verified-current model ids via live web search rather than recalled knowledge. Two entries carry TODOs (MiniMax base_url, MiMo/OpenCode-Zen exact model ids) — not confident enough to claim those working without a live test call.

## Human check — result

```
curl -H "Authorization: Bearer <token>" https://assistant.llmclouds.au/v1/health
→ {"status":"ok"}, http 200
```

Verified from the laptop over the public internet (genuinely different network than the VPS, not a LAN/VPN path) — satisfies the "not just locally reachable" intent even without a literal phone-browser test.

## Deviations from the plan, and why

1. System-level systemd unit instead of `--user` (root-only box).
2. Provider registry built now instead of Phase 01 (Mason's request, credentials were ready).
3. `assistant.env` was hand-written once to unblock testing, ahead of the Bitwarden auto-sync timer being enabled — the timer will take over once Mason finishes `docs/bitwarden-setup.md`, at which point it becomes the source of truth and this manual write is superseded.

## Not done yet (tracked, not forgotten)

- Bitwarden auto-sync timer not enabled (needs Mason's one-time setup).
- GLM's API key wasn't in the fields/password/notes locations checked — not pulled in, low priority.
