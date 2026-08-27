# Personal Assistant App — Implementation Plan

## Context

Mason wants a personal-assistant experience that lives on his phone and handles calendar, appointments, reminders, and email now, with SMS and finances as later goals. He explored an existing self-hosted agent product earlier and decided its mobile story wasn't a fit — he'd rather build his own: OpenAI-backed, a real native Android app (not a Telegram bot or PWA), chat loop proven first, then reminders + calendar + email landed together as v1's real scope. This is a clean-slate project with its own name (TBD) and no shared branding, code, or naming with anything explored earlier tonight. He also wants the project organized as an ICM workspace (folder structure as agent architecture) and built via delegation across his existing CLI agent tools (Codex, Crush, OpenCode, Cline, MiniMax-backed variants) rather than one tool doing everything — the ICM structure is exactly what makes that delegation tractable, since it gives each tool a walkable, self-contained slice of the project instead of requiring full shared context.

Two decisions were confirmed with Mason during planning:
- **Backend host: the VPS at 103.108.228.3** (currently reachable via an SSH alias tied to the earlier project — rename that alias to something neutral as a Phase 0 cleanup step), not masons-ground or the laptop. It already has Caddy configured with working TLS on the `llmclouds.au` domain (Mason's own domain), is always-on (required for reminders to fire reliably), and is meaningfully cleaner than masons-ground, which tonight's Fleet Ledger audit found cluttered (dead domains, a plaintext key, an exposed Postgres container, drifted config). This is a fresh start on that box for this project specifically — a new, separate service alongside whatever else runs there, sharing no code, config, or naming with it.
- **Delegation split: by repo.** Claude Code (this session/future sessions) builds the backend repo — the architecturally load-bearing piece (the SSE contract, the tool-execution loop, OAuth). The Android app repo gets delegated to Codex or Cline, following the module plan below; Mason will assign the specific tool when that work starts.

Working names (placeholders only — replace everywhere once Mason picks a real name): repos `assistant-backend` and `assistant-android`, Android package `com.mdyerapis.assistant`, backend domain `assistant.llmclouds.au` (a new, standalone Caddy site block on the VPS).

---

## 0. ICM workspace scaffolding (do this first, before any code)

Before Phase 0 below, run the `icm-architect` skill to scaffold both repos (or a parent workspace containing both) as ICM workspaces — folder structure organized so an agent with zero prior context (Codex, Cline, a fresh Claude session) can walk in, find the piece it owns, and edit it without needing the whole project's history. This is the enabling structure for the "by repo" delegation split: `assistant-backend/` and `assistant-android/` should each be self-describing enough that whichever tool builds the Android app never needs to read the backend's Python source, and vice versa — only the shared SSE-frame-shape contract (see Phase 1) needs to be visible to both.

---

## 1. Backend service (`assistant-backend`, built by Claude Code)

**Stack:** Python + FastAPI + `uvicorn`, SQLite via `aiosqlite` (no ORM at this size). Matches Mason's existing Python/SQLite/systemd pattern (hermes-gateway, fcc-server, hermes-threat-crawler), adapted to run on the VPS (103.108.228.3) instead of masons-ground.

```
assistant-backend/
  pyproject.toml
  app/
    main.py                 # FastAPI() app, mounts routers, startup opens sqlite conn
    config.py                # loads OPENAI_API_KEY, ASSISTANT_BEARER_TOKEN,
                              # GOOGLE_CLIENT_SECRET_JSON path from env
    auth.py                  # FastAPI dependency: Authorization: Bearer <token>,
                              # secrets.compare_digest against ASSISTANT_BEARER_TOKEN
    db.py                    # schema + migrations, plain SQL
    memory.py                 # phase 1: user_facts table + remember()/forget() +
                               # search_past_conversations() — tier 1/tier 2 memory (see
                               # section 1.5)
    routers/
      chat.py                 # POST /v1/chat -> SSE stream (the entire chat loop lives here:
                               # OpenAI call, tool-execution loop, SSE encoding, injects
                               # tier-1 memory facts into the system prompt every request)
      health.py                # GET /v1/health, bearer-gated cheap ping
      oauth_google.py          # phase 3: GET /oauth/google/start, GET /oauth/google/callback
    openai_client.py          # thin wrapper: chat.completions.create(stream=True, tools=[...])
    tools/
      registry.py              # phase 1: plain list of {name, json_schema, fn, always_visible} —
                                # Goose-style, append-only; list_skills()/use_skill() live here too
      memory_tools.py           # phase 1: remember/forget/search_past_conversations wired to memory.py
      reminders.py              # phase 2: create_reminder/list_reminders/cancel_reminder
      calendar.py                # phase 3
      gmail.py                    # phase 3
    sse.py                      # encodes ChatEvent-shaped dicts as `data: {...}\n\n` frames —
                                 # MUST match assistant-android's SseFrameCodec.kt exactly
  skills/                    # phase 4+: SKILL.md files for anything beyond the core
                              # always_visible tools — see section 1.5
  scripts/
    gen_bearer_token.py        # one-off: prints secrets.token_urlsafe(32) for pasting into app
  assistant.service            # systemd --user unit on the VPS, Restart=on-failure,
                                # EnvironmentFile=%h/assistant.env (0600, never committed)
  Caddyfile.snippet            # standalone site block to append to the VPS's /etc/caddy/Caddyfile:
                                # assistant.llmclouds.au { reverse_proxy localhost:<port> }
```

**API shape — single chat endpoint, backend-mediated, phone never talks to OpenAI or Google directly.** Tool execution needs server-held state (SQLite rows, OAuth refresh tokens, the OpenAI key) that must never live on the phone. `POST /v1/chat` takes `{conversation_id?: string, message: string}`, calls OpenAI with `stream=True` and the registered `tools=[...]`, executes any requested tool call server-side, feeds results back into the same turn, and streams `ChatEvent`-shaped SSE frames to the phone throughout: `delta`, `tool_call_started`, `tool_call_progress`, `tool_call_finished`, `message_completed`, `error`.

**Auth (phone ↔ backend):** one static bearer token (`scripts/gen_bearer_token.py`), stored in `assistant.env` on the server and pasted once into the Android app's onboarding screen. No refresh/expiry — rotate manually if it ever leaks.

**Reminders schema:**
```sql
CREATE TABLE conversations (id TEXT PRIMARY KEY, created_at TEXT);
CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT,
                        content TEXT, tool_calls_json TEXT, created_at TEXT);
CREATE TABLE reminders (id INTEGER PRIMARY KEY, text TEXT, due_at TEXT,
                         created_at TEXT, fired_at TEXT, status TEXT); -- pending|fired|cancelled
CREATE TABLE google_oauth_tokens (provider TEXT PRIMARY KEY, access_token_enc BLOB,
                                    refresh_token_enc BLOB, expiry TEXT, scope TEXT);
CREATE TABLE user_facts (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT); -- tier-1 memory,
                                                                              -- see section 1.5
```
Google tokens encrypted at the application layer (`cryptography.fernet`, keyed off an env secret) even though the DB lives on a server Mason controls — defense in depth against DB-file/backup leakage.

**Google OAuth — backend-anchored, not phone-side PKCE.** Because tools execute backend-side and the backend already holds a confidential OAuth client (existing `client_secret_*.apps.googleusercontent.com.json`, GCP project `182773386348`), use a standard authorization-code flow with the client secret: phone launches a Custom Tab (never WebView) at `GET /oauth/google/start`, Google redirects to `/oauth/google/callback` (registered against `assistant.llmclouds.au`), backend exchanges the code, stores encrypted tokens, redirects the Custom Tab to `assistantapp://oauth-complete`. Reuse only the *shape* of encrypted/TTL'd/constant-time-compared CSRF `state` tracking for the redirect — not phone-side PKCE mechanics, which don't apply to a confidential-client flow.

**Manual prerequisite Mason does himself, start in parallel tonight:** in GCP project `182773386348`'s console, extend the OAuth consent screen for Calendar (`calendar.events` or narrower) and Gmail (read-only + send, not full mailbox) scopes, and add `https://assistant.llmclouds.au/oauth/google/callback` as an authorized redirect URI.

---

## 1.5 Memory & skills design (synthesized from Hermes Agent, OpenHuman, Khoj, Goose)

Researched all four's actual mechanisms (not marketing copy) before designing this. Verdict per project: **Hermes Agent** (`NousResearch/hermes-agent` — confirmed to be the actual software behind Mason's self-hosted `hermes-gateway` on masons-ground) has the cheapest, most directly transferable memory design. **OpenHuman** has the most mature skills/progressive-disclosure pattern. **Goose**'s extension-as-config-list is the cleanest *registration* ergonomics. **Khoj**'s RAG-over-documents architecture doesn't transfer (this assistant's data is structured — reminders/events/emails — not a document corpus to embed), but its "one backend, many thin surface clients" shape validates the architecture already chosen here.

**Memory — two-tier, Hermes Agent's design, not a knowledge graph:**
- **Tier 1 — always-loaded facts** (`app/memory.py`, new `user_facts` table: `key TEXT PRIMARY KEY, value TEXT, updated_at TEXT`). Small, size-capped (mirror Hermes's ~800-token budget), injected into *every* chat request's system prompt so the model always has timezone, standing preferences, recurring commitments, etc. — never fetched mid-conversation, so it doesn't disturb prompt caching. A `remember(key, value)` / `forget(key)` tool is how the model writes to it — add/replace/remove semantics, no auto-summarization. If a write would exceed the cap, the tool call fails with a message telling the model to consolidate/replace an existing key first, exactly like Hermes's forced-consolidation behavior — don't build silent auto-compaction, it's the wrong failure mode to hide.
- **Tier 2 — searchable history** (already-planned `messages` table is tier 2 as-is for v1): a `search_past_conversations(query)` tool doing plain SQLite `LIKE`/FTS5 full-text search over `messages.content`. **No vector DB / embeddings in v1** — Khoj's pgvector approach is the natural upgrade path *if* semantic (not keyword) recall over months of history ever becomes a real problem, not a day-one requirement.
- **"Learning" is not a separate subsystem** — both Hermes and OpenHuman converge on this: it's the model itself deciding, mid-conversation, to call `remember(...)` when it notices something worth keeping (a stated preference, a correction). No standalone ML/stability-detector service for v1 (OpenHuman's is real but is solving a scale problem — thousands of candidate facts across a multi-agent system — this project doesn't have yet).

**Skills/tools — Goose's registration ergonomics + Hermes/OpenHuman's retrieval shape:**
- **Registration** (Goose's pattern): tools live as **plain entries in a list**, `app/tools/registry.py` — `{name, json_schema, fn, always_visible: bool}`. Adding a fifth tool later means appending an entry, never touching `chat.py`'s routing logic. No custom marketplace/registry server to build.
- **Retrieval** (Hermes + OpenHuman's progressive-disclosure pattern, worth adopting from day one even though v1 only has a handful of tools — cheap to build now, expensive to retrofit once the tool count grows past reminders+calendar+email into whatever comes after): tools marked `always_visible` (the core v1 set: reminders, calendar, email, `remember`/`forget`) go straight into every OpenAI `tools=[...]` call. Anything added later that *isn't* core (a one-off skill) is reached via `list_skills()` (names + one-line descriptions only, cheap) → the model calls `use_skill(name)` to get that skill's full schema/instructions injected for the rest of the turn. This is the seam that lets the project grow (SMS, finances, arbitrary future skills) without every request paying for every tool's full schema.
- **Skill authoring format** (OpenHuman's SKILL.md convention, deferred past v1): once skills beyond the core four exist, author them as markdown files with YAML frontmatter (name/description/when-to-use) under a `skills/` directory the backend loads at startup — not a database table — so adding a skill is "write a markdown file," matching how Mason already thinks about this from OpenHuman/Hermes. Not needed until Phase 4+; the core v1 tools are plain Python functions in the registry, not markdown-authored.

---

## 1.6 Credential sync from Bitwarden (personal vault, not Secrets Manager)

Mason wants his API keys (OpenAI, Google client secret) to live in Bitwarden and flow into the backend automatically when rotated, rather than manually re-pasting an env file after every rotation. He's on the regular personal vault, not Bitwarden Secrets Manager — worth being direct about the one real tradeoff this implies before designing around it: **unlocking the personal vault non-interactively requires the master password to exist somewhere on the server.** There's no way around this with the personal vault — it's how Bitwarden's client-side encryption works, the CLI can't derive the vault key without it. This is different from (and less clean than) Secrets Manager's machine-token model, which needs no master password at all. Note this as a real, if manageable, security tradeoff — not a solved problem — and revisit if it ever feels uncomfortable (Secrets Manager has a free tier for a small number of secrets, worth reconsidering later).

**Design — scheduled pull-and-diff, not live push (rotation isn't latency-sensitive; checking every ~20 min is plenty):**

```
assistant-backend/
  scripts/
    sync_secrets_from_bitwarden.sh   # bw unlock --passwordenv BW_MASTER_PASSWORD --raw
                                       # -> bw sync -> bw get item <id> --session <token> for
                                       # each configured item -> diff against current
                                       # assistant.env -> if changed: rewrite assistant.env,
                                       # `systemctl --user restart assistant`
  assistant-secrets-sync.service      # oneshot systemd --user unit running the script above
  assistant-secrets-sync.timer        # systemd --user timer, ~20 min interval
```

- **Two separate, differently-scoped env files** — don't let the sync script's own credentials live next to the secrets it manages:
  - `~/.bw-sync.env` (0600, read only by the sync service): `BW_CLIENTID`/`BW_CLIENTSECRET` (a Bitwarden **personal API key**, from the web vault's Account Settings — this pair alone can log the CLI in but cannot decrypt anything without also unlocking) and `BW_MASTER_PASSWORD`. This file is the single most sensitive thing on the box now — protect it like the master password it contains, because it is one.
  - `assistant.env` (0600, read by the actual assistant service): the plain resolved secrets (`OPENAI_API_KEY`, `GOOGLE_CLIENT_SECRET_JSON`, `ASSISTANT_BEARER_TOKEN`) — written *by* the sync script, never edited by hand once this is live.
- **Restart-on-change, not live in-process reload** — simpler and avoids partial-reload bugs (half the process running with an old key, half with a new one). A 20-minute-interval restart of a stateless-per-request FastAPI service is unnoticeable to a single-user phone app.
- Mason creates one Bitwarden item per secret (or one item with multiple custom fields) and records its item ID in the sync script's config — a one-time manual step per credential, not per rotation.

---

## 2. Android app (`assistant-android`, delegated to Codex/Cline)

**Toolchain (reuse as-is — already installed on this laptop from tonight's Android tooling setup):** JDK 17, Gradle 8.14, Kotlin 2.0.21, AGP 8.7.3, KSP 2.0.21-1.0.28, Hilt 2.52, Compose BOM 2024.11.00, OkHttp 4.12.0, kotlinx.serialization 1.7.3, kotlinx.coroutines 1.9.0, Room 2.7.2, compileSdk 35 (needs `sdkmanager "platforms;android-35"` — only android-34 is installed right now), minSdk 26. No `jvmToolchain` pinning beyond the root JDK 17 declaration (ADR-004 below).

**Module layout**, modeled on Mason's own prior app `hermes-android` (verified pattern: `core:*`/`backend-client` as pure-JVM modules with zero Android imports, compiler-enforced testability on bare JDK with MockWebServer):

```
assistant-android/
  settings.gradle.kts
  gradle/libs.versions.toml

  app/
    .../App.kt                          # @HiltAndroidApp
    .../MainActivity.kt
    .../nav/AppNavHost.kt                # onboarding -> chat
    AndroidManifest.xml                   # intent-filter assistantapp://oauth-complete
                                           # (unused in v1, reserved for phase 3)

  core/
    model/                                # pure JVM
      .../ChatMessage.kt
      .../ChatEvent.kt                     # sealed: Delta, MessageStarted, MessageCompleted,
                                            # ToolCallStarted/Progress/Finished, Error, Unknown
      .../ChatState.kt
      .../ToolCall.kt                       # name, argsJson, status

    network/                              # pure JVM
      .../OkHttpClientFactory.kt
      .../BearerAuthInterceptor.kt
      .../BackoffPolicy.kt                  # full-jitter backoff
      .../AppError.kt                        # sealed: Retryable, AuthExpired, Fatal,
                                              # ToolExecutionFailed — error carries intent

    security/                             # Android, reused near-verbatim from hermes-android
      .../KeystoreSecretStore.kt             # AES-GCM via Android Keystore
      .../BearerTokenRepository.kt            # write/read/delete backend token

    database/                             # Android/Room, thin in v1 (chat history only)
      .../AppDatabase.kt
      .../ChatMessageDao.kt
      .../ChatMessageEntity.kt

    designsystem/                         # Android
      .../theme/Theme.kt
      .../components/MessageBubble.kt
      .../components/MessageContent.kt
      .../components/StateComponents.kt
      .../components/ToolCallChip.kt        # NEW: renders a collapsed "Calling X…" / "✓ done"
                                              # pill — the seam tool events render into before
                                              # any real reminder/calendar/email tool exists

  backend-client/                        # pure JVM, equivalent of hermes-android's backend:<name>
    .../ChatApiClient.kt                    # POST /v1/chat, reads OkHttp SSE response
    .../SseFrameCodec.kt                     # parses `data: {...}` -> ChatEvent; `[DONE]` ->
                                              # MessageCompleted; never throws on unknown frame —
                                              # MUST match assistant-backend's sse.py exactly
    .../ChatReducer.kt                        # PURE fn (ChatState, ChatEvent) -> ChatState;
                                               # no coroutines/IO; handles delta-before-started
    src/test/.../SseFrameCodecTest.kt
    src/test/.../ChatReducerTest.kt

  feature/
    onboarding/
      .../OnboardingViewModel.kt            # paste bearer token -> GET /v1/health -> store
      .../OnboardingScreen.kt
    chat/
      .../ChatViewModel.kt                   # StateFlow<ChatState>, feeds ChatReducer
      .../ChatUiState.kt
      .../ChatScreen.kt                       # collectAsStateWithLifecycle(), renders
                                               # MessageBubble list + ToolCallChip inline
```

Feature modules depend only on `core:*`/`backend-client`, never on each other.

**Streamed chat pattern:** OkHttp reads the SSE response body from `/v1/chat`; `SseFrameCodec` parses `data: {...}` lines into `ChatEvent`s (lenient — unrecognized frames become `Unknown`, never throws); `ChatReducer.reduce(state, event): state` is a pure fold (no IO, unit-testable, handles a `Delta` arriving before `MessageStarted` by synthesizing the message); `ChatViewModel` owns a `StateFlow<ChatState>` fed by the reducer; `ChatScreen` collects it and renders bubbles + `ToolCallChip`s.

**Auth:** no OAuth/PKCE needed for talking to the backend — just the bearer token via `BearerTokenRepository`/`KeystoreSecretStore`, following the shape of hermes-android's `verifyBearerKey()` (write key → cheap verifying call → delete on rejection) minus all OAuth complexity.

---

## 3. Phased build order

| Phase | What | Depends on |
|---|---|---|
| **0** | Backend skeleton on the VPS: rename the SSH alias to something neutral, empty FastAPI app, `/v1/health`, bearer auth, systemd unit, standalone Caddy site block + TLS, plus the Bitwarden sync script/timer (section 1.6) so `assistant.env` is populated by the vault from day one rather than hand-typed once and forgotten. Verify `curl -H "Authorization: Bearer <token>" https://assistant.llmclouds.au/v1/health` works. | Nothing — do this first |
| **1** | **Chat loop end-to-end — the proof milestone.** Backend: `POST /v1/chat`, `tools/registry.py` + tier-1 memory (`user_facts`, `remember`/`forget`, injected into every system prompt) wired in from the start since it's cheap now and expensive to retrofit, streams OpenAI SSE straight through, persists to SQLite. Android: `app`, all `core:*`, `backend-client`, `feature:onboarding`, `feature:chat`. Sideload debug APK, paste token, send a message, watch it stream. | Phase 0 |
| **1.5** | Tool-calling plumbing proof: register one trivial fake tool (`get_current_time`, no I/O) plus `remember`/`forget`, wire the execute-and-continue loop, confirm `ToolCallChip` renders on-device. Validates the whole tool-calling seam *and* tier-1 memory before real tools exist. | Phase 1 |
| **2** | Reminders (pure backend logic, zero external dependency): `reminders` table + `create_reminder`/`list_reminders`/`cancel_reminder` tools. Fully testable via chat alone. | Phase 1.5 |
| **2.5** | Reminder *delivery* (scheduler fires at `due_at`, pushes to phone) — **separately shippable**, needs Firebase/FCM (new external dependency: Firebase project, service account, FCM token registration). Don't gate Phase 2's demo on this. | Phase 2 |
| **3** | Calendar + Gmail — gated on Mason's manual GCP consent-screen step. `oauth_google.py` + `calendar.py`/`gmail.py` tools; Android adds Custom Tab launch + deep-link return + "Connected to Google" row. **Start the GCP console prerequisite in parallel, as early as tonight** — it's the longest pole. | Phase 1 (parallel-startable) |

---

## 4. ADR-equivalent notes (carry into both repos' own docs once scaffolded)

- **ADR-001:** `core:model`, `core:network`, `backend-client` (Android) and the backend's own pure-logic modules stay free of framework imports where possible — compiler-enforced testability.
- **ADR-002:** error mapping carries intent (`AppError` sealed type: `Retryable`/`AuthExpired`/`Fatal`/`ToolExecutionFailed`), not raw status codes.
- **ADR-003:** secrets in Android Keystore via `core:security`, never `EncryptedSharedPreferences`. Backend-side: Google OAuth tokens (and ideally the OpenAI key) encrypted at the application layer in SQLite even on a controlled server.
- **ADR-004:** no per-module `jvmToolchain` pinning beyond the root JDK 17 declaration (avoids failing on a machine with only a newer JDK and no toolchain resolver).
- **ADR-005:** backend-mediated tool execution is mandatory — the phone never holds the OpenAI key or a Google token, and never calls either API directly.
- **ADR-006:** reminder creation and reminder delivery are separately shippable milestones (delivery needs Firebase, creation doesn't).
- **ADR-007:** Google OAuth is backend-anchored (confidential client), not phone-side PKCE, because the backend — not the phone — executes calendar/email tools and already holds a client secret.
- **ADR-008** (from Hermes Agent's memory design): tier-1 memory (`user_facts`) is small, size-capped, and loaded once per request into the system prompt — never fetched mid-conversation. A write past the cap fails loudly and asks the model to consolidate, rather than silently auto-summarizing. This preserves prompt-cache stability and keeps "what does the assistant know about me" auditable as a short, readable table, not an opaque blob.
- **ADR-009** (from Goose's extension config + Hermes/OpenHuman's progressive disclosure): tools are a flat, append-only list (`tools/registry.py`), never routing-logic branches in `chat.py`. Tools flagged `always_visible` go into every request's `tools=[...]`; anything else is reached via `list_skills()`/`use_skill()` so the per-request tool-schema cost doesn't grow with every future capability added.
- **ADR-010** (from Khoj, as a deliberately deferred non-decision): no vector DB / embeddings in v1. `search_past_conversations` is plain SQLite text search. Revisit only if keyword search over months of history proves insufficient — don't pre-build RAG infrastructure this project doesn't yet need.
- **ADR-011** (credential rotation): secrets sync from Bitwarden on a schedule (~20 min) via a separate, more-tightly-scoped systemd unit than the app itself, writing a plain env file the app restarts to pick up — not live in-process reload, and not read directly by the app process. Explicitly accepted tradeoff: this requires the Bitwarden master password to exist on the server (personal-vault limitation, not a Secrets-Manager setup) — flagged, not hidden; revisit if Bitwarden Secrets Manager becomes available.

---

## Verification

- **Phase 0:** `curl -H "Authorization: Bearer <token>" https://assistant.llmclouds.au/v1/health` returns 200 from both the laptop and the phone's mobile data (confirms it's genuinely internet-reachable, not just LAN).
- **Phase 1:** send a real chat message from the sideloaded Android app, confirm tokens stream into the UI in real time (not just as one final blob), confirm the conversation persists in the backend's SQLite (`sqlite3 app.db "select * from messages;"`) and in the app's Room DB.
- **Phase 1.5:** ask the assistant "what time is it," confirm `ToolCallChip` shows "Calling get_current_time…" then "✓ done," and the model's final answer reflects the tool result. Separately: tell it "remember that I go by [name]," start a fresh conversation, and confirm it still knows without being told again — proves tier-1 memory injection is actually wired into the system prompt, not just the tool call succeeding in isolation.
- **Phase 2:** "remind me to call the dentist tomorrow at 9am" → confirm a `reminders` row is created with the right `due_at`, and "what are my reminders" lists it back correctly.
- **Phase 3:** after connecting Google in-app, "what's on my calendar today" and "any new emails" return real data; confirm token refresh works by testing again after the access token's TTL would have expired.
