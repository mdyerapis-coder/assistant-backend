# O1 Google OAuth relay — operator guide

**Host:** `https://assistant.llmclouds.au` (VPS, Caddy → `localhost:8090`)  
**Audience:** whoever is operating this box as the Google OAuth relay for Declan’s Option C hybrid path (on-device chat on the phone, Google Calendar/Gmail still backend-anchored).  
**Decisions:** [ADR-007](adr/007-google-oauth-backend-anchored.md) (confidential client, not phone PKCE), [ADR-012](adr/012-embedded-backend-in-apk.md) (embed shapes), [ADR-013](adr/013-embed-oauth-and-push.md) (O1 relay lock). Android wire notes: [CONTRACT.md](CONTRACT.md) § OAuth relay.

This host is the **O1 thin Google OAuth relay**. Chat on the phone may be local (MediaPipe / Option C). Google consent, token storage, refresh, and Calendar/Gmail tool execution stay here. Do **not** put `client_secret`, the Fernet key, or Google refresh tokens in the APK.

**This is not a production cutover.** The running service stays the full `assistant-backend` (chat included). Do not disable `/v1/chat` until a dedicated Google proxy exists — Option C currently POSTs `/v1/chat` here for calendar/Gmail turns.

---

## 1. What MUST stay on this host

These surfaces are load-bearing for O1. If they move off this box, Google tools stop for the hybrid phone.

| Surface | Auth | Why it cannot leave |
|---|---|---|
| `GET /oauth/google/start` | none (Custom Tab) | Builds the Google auth URL with `client_id`; mints CSRF `state` |
| `GET /oauth/google/callback` | none (Google redirect) | Exchanges `code` using **`client_secret`**; Fernet-encrypts tokens into SQLite |
| Token refresh inside `get_google_credentials()` | internal | Refresh also needs `client_secret` — must not run in-process on the phone |
| Encrypted token store | SQLite `google_oauth_tokens` | Refresh tokens never leave this host (ADR-003, ADR-007) |
| Calendar / Gmail tool execution | bearer, today via `POST /v1/chat` | Tools call `get_google_credentials()`. Option C’s `LocalGoogleGateway` POSTs `/v1/chat` to this host with the device bearer. A future narrow `/v1/google/...` proxy is allowed; shipping refresh tokens to the phone is not. |
| Bearer auth (`ASSISTANT_BEARER_TOKEN`) | `Authorization: Bearer` | Phone uses the same Keystore token for `/oauth/google/status`, `DELETE /oauth/google`, and Google chat turns. Loopback on a future embed does not change this. |
| `GET /oauth/google/status` | bearer | “Connected to Google” row on the phone |
| `DELETE /oauth/google` | bearer | Disconnect: drop stored encrypted tokens |

**Registered Google redirect URI (must match GCP):**

```
https://assistant.llmclouds.au/oauth/google/callback
```

Derived from `ASSISTANT_PUBLIC_URL` (default `https://assistant.llmclouds.au`) unless `GOOGLE_OAUTH_REDIRECT_URI` is set. Source: `app/config.py`, `app/routers/oauth_google.py`.

---

## 2. What the phone uses

Option C is **two base URLs**. They are independent. Chat being on-device does not move OAuth.

| Setting | Default | Role |
|---|---|---|
| `oauthRelayUrl` | `https://assistant.llmclouds.au` | Google host. Always this VPS for O1. |
| `chatBaseUrl` | cloud FastAPI, or unused | On-device LLM path does not send ordinary turns here. |

### Custom Tab (connect)

1. Phone opens a Chrome Custom Tab (never a WebView) at:

   `{oauthRelayUrl}/oauth/google/start`  
   → `https://assistant.llmclouds.au/oauth/google/start`

2. Google redirects to this host’s callback (the GCP-registered URI above).
3. Backend stores encrypted tokens, then redirects the tab to the **deep link below**.
4. App resumes; it GETs `{oauthRelayUrl}/oauth/google/status` with the bearer.

### Deep link the backend actually emits

| Who | Scheme | Notes |
|---|---|---|
| **This backend (now)** | `sableapp://oauth-complete` | Matches live `assistant-android` (`AndroidManifest` intent-filter + `GoogleAccountManager.OAUTH_COMPLETE_URI`). Set in `app/routers/oauth_google.py`; override with `GOOGLE_OAUTH_DEEPLINK`. |
| **Live APK** | `sableapp://oauth-complete` | Package `com.mdyerapis.sable`. This is the only OAuth-complete filter on the phone. |
| **Historical alias** | `assistantapp://oauth-complete` | What this backend emitted before the Sable rename. **Not** registered on the current APK. Only set `GOOGLE_OAUTH_DEEPLINK=assistantapp://oauth-complete` if you are sideloading a pre-rename build. |

If the Custom Tab finishes Google consent but the app never flips to “Google connected”, the deep-link scheme is the first thing to check.

### Google tools from on-device chat

Matching calendar/Gmail turns POST `POST /v1/chat` to `oauthRelayUrl` with the Keystore bearer. The relay runs existing tools via `get_google_credentials()`. The phone:

- does **not** send on-device `local:` conversation ids or MediaPipe model ids
- does **not** download refresh tokens or `client_secret`
- greys out Connect Google / fails honestly if there is no bearer or the relay is unreachable — it must not invent events

Unrelated chat stays on-device. Reminders (P1) and SMS (P2) are phone-local on that path; they are not this host’s O1 job.

Same bearer as `/v1/health`. Paste via onboarding or Settings → Connect cloud assistant even if chat stays On-Device.

---

## 3. What can eventually be stripped (relay-only vs full chat backend)

**Do not strip anything in this change.** Chat is not feature-flagged off. Option C still needs `/v1/chat` on this host for Google turns.

| Keep forever on the O1 host | Keep until a Google HTTP proxy exists | Safe to drop only when embed is primary *and* Google no longer uses `/v1/chat` |
|---|---|---|
| `/oauth/google/*` | `POST /v1/chat` (Google tool loop) | Chat as the phone’s primary LLM (`/v1/models`, ordinary SSE turns) |
| `google_oauth_tokens` + Fernet key | LLM provider keys used by that Google turn | Scheduler / FCM reminder *delivery* (P1 is WorkManager on the phone) |
| `get_google_credentials()` refresh | `app/tools/calendar.py`, `app/tools/gmail.py` | SMS FCM hop (`action: send_sms` → `POST /v1/sms/results`) — P2 is in-process on the phone |
| Bearer check | | Threads / memory APIs if the phone never pulls them |
| Caddy TLS on `assistant.llmclouds.au` | | Bitwarden sync of *model* API keys (Gemini, MiniMax, …) if chat is fully on-device **and** Google turns no longer need an LLM here |

Later strip shape (not this PR): a small process that only serves `/oauth/google/*`, the encrypted token store, refresh, and either (a) the existing Google tool handlers behind `/v1/chat` or (b) a narrow authenticated `/v1/google/...` proxy. Drop chat/scheduler/FCM from *this* host only after the phone has stopped depending on them.

When the relay is down: chat/reminders/SMS still work on-device; Calendar/Gmail must grey out / reconnect — never fake events.

---

## 4. Env and secrets — server only, never the APK

Bitwarden sync ([ADR-011](adr/011-bitwarden-secret-sync.md), [docs/bitwarden-setup.md](bitwarden-setup.md)) writes `assistant.env` on this VPS. The app process never talks to Bitwarden. **None of this belongs in the APK** (ADR-012: on-device keys, if any, are EncryptedSharedPreferences for *LLM* providers — not Google OAuth).

| Secret / env | Where it lives | Notes |
|---|---|---|
| `GOOGLE_CLIENT_SECRET_JSON` | `assistant.env` (0600) | Confidential web client. GCP project number `182773386348`. Sync script currently **passthrough** — not always a Bitwarden item. |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | env **or** `/opt/assistant-backend/.google-token-key` | Fernet key for `google_oauth_tokens`. Prefer the file: Bitwarden rewrite used to drop unknown keys. Rotating this key makes stored tokens unreadable. |
| `ASSISTANT_BEARER_TOKEN` | `assistant.env` + phone Keystore | Phone ↔ relay auth. Not a Google secret. |
| `ASSISTANT_PUBLIC_URL` | optional; default is this host | Must stay `https://assistant.llmclouds.au` in prod or Google `redirect_uri` breaks. |
| `GOOGLE_OAUTH_REDIRECT_URI` | optional override | Default `{PUBLIC_BASE_URL}/oauth/google/callback`. |
| `GOOGLE_OAUTH_DEEPLINK` | optional override | Default `sableapp://oauth-complete`. |
| `~/.bw-sync.env` + systemd-creds master password | VPS only | Unlock the personal vault. Most sensitive files on the box. |

Provider LLM keys (`OPENAI_API_KEY`, `GOOGLE_GEMINI_API_KEY`, …) are for **this process’s** chat completions. They are still required today because O1 Google turns use `/v1/chat` on this host. They are not Google OAuth material and still must not be baked into the APK.

Generate a Fernet key (once, on the VPS):

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
# install as the file the sync script does not touch:
sudo install -m 600 /dev/stdin /opt/assistant-backend/.google-token-key <<<'<key>'
```

---

## 5. Health / verify

Substitute the live bearer (from `assistant.env`). Do not paste it into chat logs.

```bash
RELAY=https://assistant.llmclouds.au
# source /opt/assistant-backend/assistant.env   # on the VPS

# 1. Process is up (bearer-gated)
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $ASSISTANT_BEARER_TOKEN" \
  "$RELAY/v1/health"
# expect 200  body: {"status":"ok"}

# 2. OAuth status (bearer-gated) — connected true/false is both success
curl -sS -H "Authorization: Bearer $ASSISTANT_BEARER_TOKEN" \
  "$RELAY/oauth/google/status"
# expect 200  {"connected": false}  or  {"connected": true, "expiry", "scope", "updated_at"}

# 3. Status without bearer must fail
curl -sS -o /dev/null -w '%{http_code}\n' "$RELAY/oauth/google/status"
# expect 401

# 4. Custom Tab start URL must redirect (302) to accounts.google.com
#    (503 = GOOGLE_CLIENT_SECRET_JSON missing on this host)
curl -sS -o /dev/null -w '%{http_code}\n' "$RELAY/oauth/google/start"
# expect 302
```

Or: `ASSISTANT_BEARER_TOKEN=... ./scripts/verify_oauth_relay.sh`

**GCP console (human, not automatable here):** project `182773386348` → OAuth client (web) → Authorized redirect URIs **must** include:

```
https://assistant.llmclouds.au/oauth/google/callback
```

A mismatch returns `redirect_uri_mismatch` in the Custom Tab. Confirm after any domain or `ASSISTANT_PUBLIC_URL` change. Scopes this backend requests: Calendar readonly, Gmail readonly, Gmail send (see `GOOGLE_SCOPES` in `oauth_google.py`).

End-to-end on a phone: Settings → `oauthRelayUrl` = `https://assistant.llmclouds.au` → paste bearer → Connect Google → Custom Tab → return on `sableapp://oauth-complete` → status green → “what’s on my calendar today?” hits this host’s `/v1/chat`.

---

## Related

| Doc | What it answers |
|---|---|
| [ADR-007](adr/007-google-oauth-backend-anchored.md) | Why the secret stays on the server |
| [ADR-011](adr/011-bitwarden-secret-sync.md) | How `assistant.env` is rewritten |
| [ADR-012](adr/012-embedded-backend-in-apk.md) | Why embed cannot ship `client_secret` |
| [ADR-013](adr/013-embed-oauth-and-push.md) | O1 / P1 / P2 lock; this file is follow-up 1 |
| [CONTRACT.md](CONTRACT.md) | Android-facing URLs, deep link, OAuth endpoints |
| [plan.md](plan.md) | Original confidential-client flow + GCP prerequisite |
| `assistant-android` `docs/spikes/option-c-on-device.md` | Phone-side Option C / O1 behaviour |
