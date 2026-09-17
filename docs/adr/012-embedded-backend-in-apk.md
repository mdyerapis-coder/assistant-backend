# ADR-012: embedding this backend inside the Android APK — what it would take

**Status:** proposed, analysis only. No code committed to this path.

The question: can the FastAPI backend stop being a server the phone talks to
(`sable.llmclouds.au`) and instead ship *inside* the APK, so the app is
self-contained? This records the honest requirements list and what silently
dies, so the decision is made with eyes open.

## The three realistic shapes

**A. Chaquopy — run the existing Python app in-process.**
CPython embedded via the Chaquopy Gradle plugin, uvicorn bound to
`127.0.0.1` on a foreground-service thread, the app's OkHttp base URL pointed
at loopback. Days-to-weeks, keeps this codebase.

**B. Kotlin rewrite — an in-process Ktor (or no-HTTP) port.**
The client's `ChatApiClient` is already a transport seam; an in-process
implementation could skip HTTP entirely. Weeks, divergent-behavior risk, but
no Python runtime, smallest APK, best battery behavior. The right endgame if
the embed ever becomes the primary distribution.

**C. Status quo + on-device mode.** The app already has an on-device LLM path
(feature/localmodel). If the goal is "works without the server", deepening
that path is cheaper than both A and B — but it is not "the backend in the
APK"; it is a reduced assistant.

## Option A requirement list (the actual ask)

**Dependency wheels (the hard gate).** Chaquopy ships prebuilt Android wheels
for pydantic-core, cryptography, orjson, aiohttp's C deps, and PyYAML's
optional C ext is skippable. Known substitutions needed in
`pyproject.toml` for an Android flavor:

- `uvicorn[standard]` → plain `uvicorn` (drop uvloop, httptools, watchfiles —
  all unavailable or pointless on Android; the pure-asyncio loop is fine at
  one-client scale)
- `firebase-admin` → **drop** (see FCM below)
- `mcp` → HTTP-transport servers only; stdio subprocess MCP servers cannot
  spawn on Android
- everything else (`fastapi`, `openai`, `httpx`, `aiosqlite`, `croniter`,
  `google-auth`) is pure Python and rides along

**Lifecycle.** Android kills idle background processes. The server needs a
foreground service with a persistent notification, a partial wake lock while
an SSE stream is open, and a "backend starting…" state in the UI (interpreter
init is seconds, not milliseconds). The existing onboarding connection-check
already has the retry shape for this.

**Loopback is not private.** Every app on the phone shares `127.0.0.1`. The
bearer-token check stays mandatory even with no network involved — generate a
per-install token, store it in the Keystore-backed encrypted storage the app
already has (ADR-003), never log it.

**Keys move on-device.** ADR-011's Bitwarden-to-server-env sync does not exist
on a phone. Provider API keys would live in `EncryptedSharedPreferences`, and
every provider call originates from the phone's IP. New threat model: a rooted
device extracts the keys. Accepted for a personal build; not acceptable if the
APK is ever distributed.

**Google OAuth conflicts with ADR-007.** The confidential client secret cannot
ship in an APK. Either the Google flow moves to phone-side PKCE (the thing
ADR-007 deliberately avoided) or a thin cloud relay keeps only the OAuth
exchange server-side. This is the single sharpest edge of the embed.

**Push and scheduling change owners.** FCM is server-initiated by design; a
backend on the phone pushing to itself is circular. Reminders and the phase-06
recurring automations move to WorkManager + local notifications. The systemd
health-alert/backup units obviously do not exist; their job (is it alive, is
the DB backed up) needs an Android answer or is silently dropped.

**Size and start cost.** APK is ~125 MB today; add roughly 40–80 MB for the
interpreter and wheels. Cold-start interpreter init of a few seconds on
mid-range hardware.

## What silently dies if you just do it

| Feature | Fate under Option A |
|---|---|
| Chat against cloud providers | works, from phone IP |
| SSE streaming | works over loopback |
| SQLite memory/threads | works, app-private dir |
| Google Calendar/Gmail tools | **blocked on the OAuth question** |
| FCM reminder delivery | **replaced by WorkManager/local notifications** |
| Recurring automations (croniter) | port to WorkManager |
| MCP stdio tool servers | **dropped**; HTTP MCP only |
| Bitwarden secret sync | **dropped**; manual key entry on-device |
| health-alert / backup timers | **dropped** or re-implemented |
| Device-control SMS relay | unaffected (already phone-side) |

## Recommended path

1. Wheel-availability spike: build an Android-flavored venv via Chaquopy's
   pip and prove `fastapi`, `pydantic`, `cryptography`, `orjson`, `aiohttp`,
   `aiosqlite` all import on-device. Half a day, kills or green-lights A.
2. Hello-world spike: `/v1/health` and `/v1/models` served from loopback,
   consumed by the unmodified `ChatApiClient`. A day.
3. Decide the OAuth and push questions *on paper* before writing any more
   code — they are the two places where "embed" stops being a packaging
   exercise and becomes a redesign. OAuth+push paper decisions are accepted
   in ADR-013 (O1 thin OAuth relay, P1 WorkManager+local notifications,
   P2 in-process SMS).
4. Only then: feature-parity port of scheduler/notifications, key storage,
   and a per-install token.

If step 1 or 3 fails, Option C (deepen on-device mode) is the fallback, and
Option B stays the endgame if the embed ever needs to be the primary product.
